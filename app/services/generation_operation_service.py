"""Atomic operation admission. No render, upload, broker call or message send here."""
import hashlib
import json
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from sqlalchemy import text
from app.config import get_settings
from app.services.permission_service import require_permission, has_permission
from app.services.feature_service import require_feature, enforce_monthly_limit, enforce_static_limit, require_storage_for_upload, record_non_asset_storage
from app.services.quota_service import check_quota_mixed
from app.services.audit_service import log_audit

SUMMARY_COLUMNS = ('id,tenant_id,event_id,created_by,request_sha256,mode,source,status,cards_count,people_count,'
                   'vip_cards,normal_cards,vip_people,normal_people,cards_done,cards_failed,'
                   'files_done,files_failed,created_at,updated_at,completed_at,error_code,error_message,'
                   "CASE WHEN jsonb_typeof(settings_snapshot->'output_formats')='array' "
                   "THEN jsonb_array_length(settings_snapshot->'output_formats') ELSE 0 END AS files_expected")


def max_cards_error(limit):
    """One shape for every route that enforces the operational card ceiling."""
    return HTTPException(413, {'code': 'MAX_CARDS_EXCEEDED', 'max_cards': limit,
                               'message': f'الحد الحالي {limit} دعوة للعملية الواحدة؛ قسّم البيانات إلى عمليات أصغر'})


def request_fingerprint(body):
    # Hash normalized intent, never live template state. A replay after a template
    # edit retrieves the original operation rather than creating a new snapshot.
    return hashlib.sha256(json.dumps(body.model_dump(mode='json'), sort_keys=True,
                                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


async def find_replay(db, tenant_id, user_id, key, fingerprint):
    result = await db.execute(text(f'SELECT {SUMMARY_COLUMNS} FROM generation_operations WHERE tenant_id=:tid AND idempotency_key=:key'),
                              {'tid': str(tenant_id), 'key': key})
    row = result.mappings().first()
    if not row:
        return None
    if row['request_sha256'].strip() != fingerprint:
        raise HTTPException(409, 'مفتاح الطلب مستخدم لبيانات مختلفة. استخدم مفتاحًا جديدًا للعملية الجديدة')
    if row['created_by'] != user_id and not await has_permission(db, tenant_id, user_id, 'batches.view'):
        raise HTTPException(403, 'لا يسمح لك بعرض هذه العملية')
    return dict(row)


async def authorize_admission(db, tenant_id, user_id, body):
    await require_permission(db, tenant_id, user_id, 'invitations.create')
    if body.output_formats:
        await require_permission(db, tenant_id, user_id, 'invitations.export')
        await require_feature(db, tenant_id, 'pdf_export')
    if body.require_rsvp:
        await require_feature(db, tenant_id, 'rsvp')


async def admit_operation(db, tenant_id, user_id, key, body, snapshot, staged=None):
    """Caller owns commit/rollback; all durable rows and usage share one transaction."""
    settings = get_settings()
    rows = body.normalized_rows()
    cards = len(rows) if staged is None else staged["cards"]
    if cards > settings.generation_operation_max_cards:
        raise HTTPException(413, f'الحد الحالي {settings.generation_operation_max_cards} دعوة للعملية الواحدة')
    if not 1 <= settings.generation_batch_cards <= 1000:
        raise HTTPException(503, 'إعداد حجم الدفعة غير صالح')
    digest = request_fingerprint(body)
    await db.execute(text("SELECT set_config('lock_timeout','15000',true)"))
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                     {'key': f'generation-request:{tenant_id}:{key}'})
    existing = await find_replay(db, tenant_id, user_id, key, digest)
    if existing:
        return existing, True
    # Authorization is checked again after snapshot IO / waiting for another request.
    await authorize_admission(db, tenant_id, user_id, body)
    capacity = await db.execute(text('SELECT generation_check_capacity(:tid,:cards,:op_limit,:card_limit,:tenant_limit)'),
        {'tid': str(tenant_id), 'cards': cards, 'op_limit': settings.generation_queue_max_operations,
         'card_limit': settings.generation_queue_max_cards, 'tenant_limit': settings.generation_tenant_max_operations})
    if not capacity.scalar():
        raise HTTPException(429, 'طابور الإنشاء ممتلئ أو بلغت المؤسسة حد العمليات المنتظرة. أعد المحاولة لاحقًا',
                            headers={'Retry-After': '30'})
    # Recheck mutable event admission data; rendering itself uses only the snapshot.
    event = await db.execute(text("SELECT id FROM events WHERE id=:eid AND tenant_id=:tid AND deleted_at IS NULL AND status<>'cancelled' FOR SHARE"),
                             {'eid': str(body.event_id), 'tid': str(tenant_id)})
    if not event.first():
        raise HTTPException(409, 'لم يعد المناسبة متاحًا لإنشاء الدعوات')
    await check_quota_mixed(db, str(tenant_id), str(body.event_id), rows)
    people = sum(row['guest_count'] for row in rows)
    await enforce_monthly_limit(db, tenant_id, 'invitations_per_month', 'الدعوات الشهرية', count=people)
    count = await db.execute(text("SELECT count(*) FROM invitations WHERE tenant_id=:tid AND event_id=:eid AND status NOT IN ('revoked','expired')"),
                             {'tid': str(tenant_id), 'eid': str(body.event_id)})
    await enforce_static_limit(db, tenant_id, 'invitations_per_event', count.scalar() or 0, 'الدعوات لكل مناسبة', requested=cards)
    unique_assets = {asset['sha256']: asset for asset in snapshot['assets'].values()}
    new_asset_bytes = 0
    if unique_assets:
        existing_assets = await db.execute(text('SELECT sha256 FROM generation_snapshot_assets WHERE tenant_id=:tid AND sha256=ANY(:hashes)'),
            {'tid':str(tenant_id),'hashes':list(unique_assets)})
        stored_hashes = {value.strip() for value in existing_assets.scalars().all()}
        new_asset_bytes = sum(len(asset['content']) for digest,asset in unique_assets.items() if digest not in stored_hashes)
        if new_asset_bytes:
            await require_storage_for_upload(db,tenant_id,new_asset_bytes)
    operation_id, import_id = uuid4(), uuid4()
    settings_snapshot = {'contract_version': 1, 'layout': body.layout.model_dump(), 'output_formats': body.output_formats,
                         'require_rsvp': body.require_rsvp, 'batch_cards': settings.generation_batch_cards,
                         'renderer_sha256': snapshot['renderer_sha256'],
                         'export_max_bytes': settings.generation_export_max_bytes,
                         'export_max_pages': settings.generation_export_max_pages}
    params = {'id': str(operation_id), 'tid': str(tenant_id), 'eid': str(body.event_id), 'uid': str(user_id),
              'key': key, 'digest': digest, 'mode': body.mode, 'source': body.source,
              'cards': cards, 'people': people,
              'vip_cards': staged['vip_cards'] if staged else sum(r['ticket_class']=='vip' for r in rows),
              'normal_cards': staged['normal_cards'] if staged else sum(r['ticket_class']=='normal' for r in rows),
              'vip_people': sum(r['guest_count'] for r in rows if r['ticket_class']=='vip'),
              'normal_people': sum(r['guest_count'] for r in rows if r['ticket_class']=='normal'),
              'settings': json.dumps(settings_snapshot), 'event': json.dumps(snapshot['event']), 'templates': json.dumps(snapshot['templates'])}
    result = await db.execute(text('''INSERT INTO generation_operations
        (id,tenant_id,event_id,created_by,idempotency_key,request_sha256,mode,source,cards_count,people_count,
         vip_cards,normal_cards,vip_people,normal_people,settings_snapshot,event_snapshot,templates_snapshot)
        VALUES(:id,:tid,:eid,:uid,:key,:digest,:mode,:source,:cards,:people,:vip_cards,:normal_cards,:vip_people,:normal_people,
               CAST(:settings AS jsonb),CAST(:event AS jsonb),CAST(:templates AS jsonb)) RETURNING *'''), params)
    operation = dict(result.mappings().one())
    await db.execute(text('''INSERT INTO generation_imports(id,tenant_id,event_id,operation_id,source,original_filename,source_sha256,rows_count)
        VALUES(:id,:tid,:eid,:oid,:source,:filename,:sha,:cards)'''),
        {'id': str(import_id), 'tid': str(tenant_id), 'eid': str(body.event_id), 'oid': str(operation_id),
         'source': body.source, 'filename': body.original_filename, 'sha': body.source_sha256, 'cards': cards})
    for key_name, asset in snapshot['assets'].items():
        asset_id = uuid5(NAMESPACE_URL, f'generation-asset:{tenant_id}:{asset["sha256"]}')
        await db.execute(text('''INSERT INTO generation_snapshot_assets(id,tenant_id,sha256,kind,mime_type,content)
            VALUES(:id,:tid,:sha,:kind,:mime,:content) ON CONFLICT(tenant_id,sha256) DO NOTHING'''),
            {'id': str(asset_id), 'tid': str(tenant_id), 'sha': asset['sha256'], 'kind': asset['kind'],
             'mime': asset['mime_type'], 'content': asset['content']})
        await db.execute(text('''INSERT INTO generation_operation_assets(tenant_id,operation_id,asset_id,asset_key)
            SELECT :tid,:oid,id,:key FROM generation_snapshot_assets WHERE tenant_id=:tid AND sha256=:sha'''),
            {'tid': str(tenant_id), 'oid': str(operation_id), 'key': key_name, 'sha': asset['sha256']})
    if new_asset_bytes:
        # Track snapshot bytes under the same linked billing account as all other
        # non-asset storage. Deduplicated replays / copies never charge twice.
        await record_non_asset_storage(db,tenant_id,new_asset_bytes)
    if staged is not None:
        await db.execute(text("""INSERT INTO generation_import_rows(tenant_id,operation_id,import_id,source_row_number,normalized_data)
            SELECT tenant_id,:oid,:iid,row_number,normalized_data FROM generation_upload_rows
            WHERE tenant_id=:tid AND upload_id=:upload AND selected ORDER BY row_number"""),
            {'tid':str(tenant_id),'oid':str(operation_id),'iid':str(import_id),'upload':staged['id']})
    else:
        row_records = [{'id': str(uuid4()), 'number': body.source_row_numbers[index] if body.source_row_numbers else index+(2 if body.source=='excel' else 1), 'data': row} for index, row in enumerate(rows)]
        await db.execute(text('''INSERT INTO generation_import_rows(id,tenant_id,operation_id,import_id,source_row_number,normalized_data)
            SELECT r.id,:tid,:oid,:iid,r.number,r.data FROM jsonb_to_recordset(CAST(:rows AS jsonb))
            AS r(id uuid,number integer,data jsonb)'''),
            {'tid': str(tenant_id), 'oid': str(operation_id), 'iid': str(import_id), 'rows': json.dumps(row_records)})
    # One INSERT ... SELECT. No N-per-row database calls or quota reservations.
    result = await db.execute(text('''INSERT INTO invitations
        (tenant_id,event_id,created_by,template_id,token,ticket_class,guest_name,guest_count,guest_name_ar,
         guest_phone,guest_whatsapp,guest_email,seat_number,table_number,hall,zone,notes,metadata,status,rsvp_status,
         generation_operation_id,generation_source_row_id)
        SELECT :tid,:eid,:uid,
          NULLIF(CAST(:templates AS jsonb)->>(r.normalized_data->>'ticket_class'),'')::uuid,
          encode(gen_random_bytes(24),'hex'),(r.normalized_data->>'ticket_class')::ticket_class,
          r.normalized_data->>'guest_name',(r.normalized_data->>'guest_count')::integer,r.normalized_data->>'guest_name_ar',
          r.normalized_data->>'guest_phone',r.normalized_data->>'guest_whatsapp',r.normalized_data->>'guest_email',
          r.normalized_data->>'seat_number',r.normalized_data->>'table_number',r.normalized_data->>'hall',r.normalized_data->>'zone',r.normalized_data->>'notes',
          r.normalized_data->'metadata',
          CASE WHEN :rsvp THEN 'created'::invitation_status ELSE 'accepted'::invitation_status END,
          CASE WHEN :rsvp THEN 'pending'::rsvp_status ELSE 'accepted'::rsvp_status END,:oid,r.id
        FROM generation_import_rows r WHERE r.tenant_id=:tid AND r.operation_id=:oid AND r.selected
        RETURNING id'''),
        {'tid': str(tenant_id), 'eid': str(body.event_id), 'uid': str(user_id), 'oid': str(operation_id),
         'templates': json.dumps({key: str(value) for key,value in body.templates.items()}), 'rsvp': body.require_rsvp})
    if len(result.fetchall()) != cards:
        raise RuntimeError('generation row admission mismatch')
    sizes={}
    for ticket_class in ('vip','normal'):
        batch_size=min(settings.generation_batch_cards,250)
        if body.mode=='designed' and ticket_class in snapshot['templates']:
            from app.services.generation_render_service import slots
            page_slots=slots(snapshot['templates'][ticket_class])
            if page_slots>1000:
                raise HTTPException(422,'عدد خانات الرموز في الصفحة يتجاوز الحد المسموح')
            batch_size=page_slots*max(1,min(10,batch_size//page_slots))
        sizes[ticket_class]=batch_size
    p={'tid':str(tenant_id),'oid':str(operation_id),'sizes':json.dumps(sizes)}
    groups=(await db.execute(text("""WITH ranked AS (SELECT normalized_data->>'ticket_class' AS ticket_class,
        (row_number() OVER(PARTITION BY normalized_data->>'ticket_class' ORDER BY source_row_number)-1) /
        ((CAST(:sizes AS jsonb)->>(normalized_data->>'ticket_class'))::integer) AS group_index
        FROM generation_import_rows WHERE tenant_id=:tid AND operation_id=:oid)
        SELECT ticket_class,group_index,count(*) AS count_total FROM ranked GROUP BY ticket_class,group_index
        ORDER BY CASE ticket_class WHEN 'vip' THEN 0 ELSE 1 END,group_index"""),p)).mappings().all()
    batches=[{'id':str(uuid4()),'part_index':index,'ticket_class':group['ticket_class'],'group_index':group['group_index'],
              'count_total':group['count_total'],'template_id':str(body.templates[group['ticket_class']]) if group['ticket_class'] in body.templates else None}
             for index,group in enumerate(groups)]
    await db.execute(text("""INSERT INTO generation_batches
        (id,tenant_id,event_id,template_id,operation_id,part_index,mode,ticket_class,count_total,layout_json,output_formats,status,created_by,metadata)
        SELECT b.id,:tid,:eid,b.template_id,:oid,b.part_index,CAST(:mode AS template_type),CAST(b.ticket_class AS ticket_class),
        b.count_total,CAST(:layout AS jsonb),:formats,'queued',:uid,jsonb_build_object('admission_contract',1,'group_index',b.group_index)
        FROM jsonb_to_recordset(CAST(:batches AS jsonb)) AS b(id uuid,template_id uuid,part_index integer,ticket_class text,count_total integer,group_index integer)"""),
        {**p,'eid':str(body.event_id),'mode':body.mode,'layout':json.dumps(body.layout.model_dump()),'formats':body.output_formats,'uid':str(user_id),'batches':json.dumps(batches)})
    result=await db.execute(text("""WITH ranked AS (SELECT id,normalized_data->>'ticket_class' AS ticket_class,
        (row_number() OVER(PARTITION BY normalized_data->>'ticket_class' ORDER BY source_row_number)-1) /
        ((CAST(:sizes AS jsonb)->>(normalized_data->>'ticket_class'))::integer) AS group_index
        FROM generation_import_rows WHERE tenant_id=:tid AND operation_id=:oid)
        INSERT INTO batch_items(tenant_id,batch_id,invitation_id,operation_id,source_row_id)
        SELECT :tid,b.id,i.id,:oid,r.id FROM ranked r
        JOIN generation_batches b ON b.tenant_id=:tid AND b.operation_id=:oid AND b.ticket_class::text=r.ticket_class
           AND (b.metadata->>'group_index')::bigint=r.group_index
        JOIN invitations i ON i.tenant_id=:tid AND i.generation_operation_id=:oid AND i.generation_source_row_id=r.id
        RETURNING id"""),p)
    if len(result.fetchall())!=cards:
        raise RuntimeError('generation item admission mismatch')
    if staged is not None:
        await db.execute(text("UPDATE generation_uploads SET status='frozen',operation_id=:oid,content=NULL WHERE tenant_id=:tid AND id=:upload"),
            {**p,'upload':staged['id']})
    await db.execute(text('''INSERT INTO generation_outbox(tenant_id,operation_id,batch_id)
        SELECT tenant_id,operation_id,id FROM generation_batches WHERE tenant_id=:tid AND operation_id=:oid'''),
        {'tid': str(tenant_id), 'oid': str(operation_id)})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user_id, action='generation.operation.accepted',
                    resource_type='generation_operation', resource_id=str(operation_id),
                    metadata={'cards_count': cards, 'people_count': people, 'batch_count': len(batches), 'request_sha256': digest})
    return operation, False


async def read_operation(db, tenant_id, user_id, operation_id):
    result = await db.execute(text(f'SELECT {SUMMARY_COLUMNS} FROM generation_operations WHERE id=:id AND tenant_id=:tid'),
                              {'id': str(operation_id), 'tid': str(tenant_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, 'العملية غير موجودة')
    if row['created_by'] != user_id and not await has_permission(db, tenant_id, user_id, 'batches.view'):
        raise HTTPException(403, 'لا يسمح لك بمتابعة هذه العملية')
    return dict(row)


def compact_operation(row, replayed=False):
    # No PII, source rows, private paths, signed URLs or full snapshots here.
    keys = ('id','event_id','mode','source','status','cards_count','people_count','vip_cards','normal_cards',
            'vip_people','normal_people','cards_done','cards_failed','files_done','files_failed','created_at','updated_at','completed_at','error_code','error_message')
    result = {key: row.get(key) for key in keys}
    expected = row.get('files_expected')
    if expected is None:
        formats = (row.get('settings_snapshot') or {}).get('output_formats')
        expected = len(formats) if isinstance(formats, list) else 0
    result['files_expected'] = expected
    result.update({'contract_version': 1, 'replayed': replayed, 'status_url': f'/api/v1/generation-operations/{row["id"]}'})
    return result


def guard_legacy_generation_creation():
    """Explicit cutover, never silently change a legacy 201 contract to 202."""
    if get_settings().generation_operations_enabled:
        raise HTTPException(409,{'code':'GENERATION_CONTRACT_UPGRADE',
            'operation_endpoint':'/api/v1/generation-operations',
            'message':'تم تفعيل الإنشاء عبر العمليات؛ حدّث الواجهة وأرسل الطلب بمفتاح ثابت للمسار الجديد'})
