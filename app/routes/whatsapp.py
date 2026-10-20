"""Tenant-authorized WhatsApp settings, requests, history and signed provider events."""
import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Literal, Annotated
from uuid import UUID
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db, get_privileged_db
from app.config import get_settings
from app.services import whatsapp_service as svc
from app.services import whatsapp_message_service as messages
from app.services.permission_service import require_permission, require_any_permission, has_permission
from app.services.feature_service import require_feature, check_feature_flag
from app.services.audit_service import log_audit
from app.security import get_client_ip

router = APIRouter(prefix='/whatsapp', tags=['WhatsApp'])


class SendRequest(BaseModel):
    invitation_ids: list[UUID] = Field(min_length=1, max_length=100)
    client_request_id: UUID
    allow_resend: bool = False
    message_versions: dict[UUID,Annotated[int,Field(ge=0)]] | None = Field(default=None,max_length=100)


class ConnectionUpdate(BaseModel):
    enabled: bool


async def authorize(request, user, db, permission):
    tid = get_tenant_id_from_header(request)
    await require_permission(db, tid, user.id, permission)
    return tid


async def audit(db, request, user, tid, action, metadata=None):
    await log_audit(db, tenant_id=tid, actor_user_id=user.id, action=action,
                    resource_type='whatsapp', metadata=metadata or {}, ip_address=get_client_ip(request))


def present(conn):
    return {'linked': bool(conn and conn['session_id'] and conn['api_key_ciphertext']),
            'enabled': bool(conn and conn['enabled']), 'status': conn['status'] if conn else 'not_connected',
            'phone': conn['phone'] if conn else None, 'last_checked_at': conn['last_checked_at'] if conn else None}


@router.get('/connection')
async def get_connection(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = get_tenant_id_from_header(request)
    await require_any_permission(db, tid, user.id, 'whatsapp.manage', 'whatsapp.send', 'whatsapp.view')
    return {**present(await svc.connection(db, tid)), 'configured': svc.configured(),
            'feature_enabled': await check_feature_flag(db, tid, 'whatsapp_delivery')}


@router.post('/connection/link')
async def link_connection(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.manage')
    await require_feature(db, tid, 'whatsapp_delivery')
    if not svc.configured():
        raise HTTPException(503, 'خدمة WhatsApp غير مهيأة لدى المنصة.')
    await db.execute(text('INSERT INTO whatsapp_connections(tenant_id) VALUES(:tid) ON CONFLICT DO NOTHING'), {'tid': str(tid)})
    conn = await svc.connection(db, tid, lock=True)
    try:
        session_id = conn['session_id']
        if not session_id:
            # Deterministic name recovers an orphan session if a create response was lost.
            name = 'dawaa-' + str(tid)
            sessions = await svc.provider('GET', 'sessions')
            existing = next((s for s in sessions if s.get('name') == name), None)
            session = existing or await svc.provider('POST', 'sessions', payload={'name': name, 'config': {'autoReconnect': True}})
            session_id = UUID(session['id'])
        key = svc.crypt(conn['api_key_ciphertext'], decrypt=True) if conn['api_key_ciphertext'] else None
        if not key:
            created = await svc.provider('POST', 'auth/api-keys', payload={'name': 'dawaa-' + str(tid), 'role': 'operator', 'allowedSessions': [str(session_id)]})
            key = created['apiKey']
        secret = svc.crypt(conn['webhook_secret_ciphertext'], decrypt=True) if conn['webhook_secret_ciphertext'] else secrets.token_urlsafe(32)
        callback = get_settings().app_url.rstrip('/') + '/api/v1/whatsapp/webhook'
        hooks = await svc.provider('GET', f'sessions/{session_id}/webhooks', key=key)
        existing = next((w for w in hooks if w.get('url') == callback), None)
        webhook = await svc.provider('PUT' if existing else 'POST', f"sessions/{session_id}/webhooks" + (f"/{existing['id']}" if existing else ''),
            key=key, payload={'url': callback, 'events': ['message.ack'], 'secret': secret, **({'active': True} if existing else {}), 'retryCount': 5})
        session = await svc.provider('GET', f'sessions/{session_id}', key=key)
        if session['status'] in ('created','disconnected','failed'):
            session = await svc.provider('POST', f'sessions/{session_id}/start', key=key)
        await db.execute(text('''UPDATE whatsapp_connections SET session_id=:sid,api_key_ciphertext=:key,
            webhook_secret_ciphertext=:secret,webhook_id=:wid,status=:status,phone=:phone,last_checked_at=now(),updated_at=now() WHERE tenant_id=:tid'''),
            {'tid': str(tid), 'sid': str(session_id), 'key': svc.crypt(key), 'secret': svc.crypt(secret),
             'wid': webhook['id'], 'status': session['status'], 'phone': session.get('phone')})
    except svc.ProviderError:
        raise HTTPException(503, 'تعذر الاتصال بخدمة WhatsApp. أعد المحاولة؛ لن تُرسل رسائل من عملية الربط.')
    await audit(db, request, user, tid, 'whatsapp.link')
    await db.commit()
    return {'linked': True, 'status': session['status']}


@router.post('/connection/refresh')
async def refresh_connection(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.manage')
    conn = await svc.connection(db, tid, lock=True)
    if not conn or not conn['api_key_ciphertext']:
        raise HTTPException(409, 'اربط الرقم أولاً.')
    try:
        session = await svc.provider('GET', f"sessions/{conn['session_id']}", key=svc.crypt(conn['api_key_ciphertext'], decrypt=True))
    except svc.ProviderError:
        raise HTTPException(503, 'تعذر التحقق من الاتصال.')
    await db.execute(text('UPDATE whatsapp_connections SET status=:status,phone=:phone,last_checked_at=now() WHERE tenant_id=:tid'),
                     {'tid': str(tid), 'status': session['status'], 'phone': session.get('phone')})
    await db.commit()
    return {'status': session['status'], 'phone': session.get('phone')}


@router.get('/connection/qr')
async def qr_connection(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.manage')
    await require_feature(db, tid, 'whatsapp_delivery')
    conn = await svc.connection(db, tid)
    if not conn or not conn['api_key_ciphertext']:
        raise HTTPException(409, 'ابدأ الربط أولاً.')
    try:
        qr = await svc.provider('GET', f"sessions/{conn['session_id']}/qr", key=svc.crypt(conn['api_key_ciphertext'], decrypt=True))
    except svc.ProviderError:
        raise HTTPException(409, 'رمز الربط غير جاهز أو الرقم متصل بالفعل؛ حدّث الحالة.')
    from fastapi.responses import JSONResponse
    return JSONResponse(qr, headers={'Cache-Control': 'no-store'})


@router.put('/connection')
async def set_connection(body: ConnectionUpdate, request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.manage')
    conn = await svc.connection(db, tid, lock=True)
    if not conn:
        raise HTTPException(409, 'اربط الرقم أولاً.')
    if body.enabled:
        await require_feature(db, tid, 'whatsapp_delivery')
        if not svc.configured() or not conn['api_key_ciphertext']:
            raise HTTPException(409, 'الاتصال غير مهيأ.')
    await db.execute(text('UPDATE whatsapp_connections SET enabled=:enabled,updated_at=now() WHERE tenant_id=:tid'), {'tid': str(tid), 'enabled': body.enabled})
    if not body.enabled:
        await db.execute(text("UPDATE whatsapp_deliveries SET state='cancelled',error_code='connection_disabled',updated_at=now() WHERE tenant_id=:tid AND state IN ('queued','waiting_connection')"), {'tid': str(tid)})
    await audit(db, request, user, tid, 'whatsapp.enable' if body.enabled else 'whatsapp.disable')
    await db.commit()
    return {'enabled': body.enabled}


@router.post('/deliveries', status_code=202)
async def send(body: SendRequest, request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.send')
    await require_permission(db, tid, user.id, 'invitations.send')
    response = await svc.queue_deliveries(db, tid, user.id, body.invitation_ids, body.client_request_id, allow_resend=body.allow_resend, message_versions=body.message_versions)
    await audit(db, request, user, tid, 'whatsapp.queue', {'request_id': response['request_id'], 'queued': response['queued']})
    await db.commit()
    return response


@router.get('/deliveries')
async def history(request: Request, event_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), invitation_id: UUID | None = None,
                  user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.view')
    await require_permission(db, tid, user.id, 'invitations.view')
    rows = await db.execute(text('''SELECT d.id,d.invitation_id,d.purpose,d.recipient,d.state,d.error_code,d.created_at,d.updated_at,i.guest_name
        FROM whatsapp_deliveries d JOIN invitations i ON i.id=d.invitation_id
        WHERE d.tenant_id=:tid AND d.event_id=:eid AND i.tenant_id=:tid'''
        + (' AND d.invitation_id=:iid' if invitation_id else '')
        + ' ORDER BY d.created_at DESC,d.id DESC LIMIT :limit OFFSET :offset'),
        {'tid': str(tid), 'eid': str(event_id), 'limit': limit, 'offset': offset, **({'iid': str(invitation_id)} if invitation_id else {})})
    return [dict(r) for r in rows.mappings().all()]


@router.get('/deliveries/summary')
async def delivery_summary(request: Request, event_id: UUID, invitation_ids: str = Query(min_length=1, max_length=3699),
                           user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.view')
    await require_permission(db, tid, user.id, 'invitations.view')
    try:
        ids = list(dict.fromkeys(UUID(value) for value in invitation_ids.split(',')))
    except ValueError:
        raise HTTPException(422, 'معرفات الدعوات غير صالحة.')
    if not 1 <= len(ids) <= 100:
        raise HTTPException(422, 'اختر من دعوة واحدة إلى 100 دعوة في طلب الحالة.')
    return await svc.read_summary(db, tid, event_id, ids)


@router.get('/deliveries/page')
async def history_page(request: Request, event_id: UUID, invitation_id: UUID | None = None,
                       search: str = Query('', max_length=200),
                       state: Literal['all','queued','waiting_connection','sending','sent','delivered','read','failed','unknown','cancelled'] = 'all',
                       purpose: Literal['all','rsvp','ticket'] = 'all',
                       limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), as_of: datetime | None = None,
                       user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.view')
    await require_permission(db, tid, user.id, 'invitations.view')
    if as_of and as_of.tzinfo is None:
        raise HTTPException(422, 'وقت السجل يحتاج منطقة زمنية.')
    anchor = min(as_of or datetime.now(timezone.utc), datetime.now(timezone.utc))
    where = 'd.tenant_id=:tid AND d.event_id=:eid AND i.tenant_id=:tid AND d.created_at<=:anchor'
    params = {'tid':str(tid),'eid':str(event_id),'anchor':anchor}
    if invitation_id:
        where += ' AND d.invitation_id=:iid'; params['iid']=str(invitation_id)
    if state != 'all':
        where += ' AND d.state=:state'; params['state']=state
    if purpose != 'all':
        where += ' AND d.purpose=:purpose'; params['purpose']=purpose
    if search.strip():
        escaped = search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        where += ' AND (i.guest_name ILIKE :search OR i.guest_name_ar ILIKE :search OR d.recipient ILIKE :search)'
        params['search']='%'+escaped+'%'
    source = 'FROM whatsapp_deliveries d JOIN invitations i ON i.id=d.invitation_id'
    total = (await db.execute(text(f'SELECT COUNT(*) {source} WHERE {where}'),params)).scalar_one()
    offset = min(offset, ((max(total,1)-1)//limit)*limit)
    rows = (await db.execute(text(f'''SELECT d.id,d.invitation_id,d.purpose,d.recipient,d.state,d.error_code,d.created_at,d.updated_at,
        COALESCE(i.guest_name_ar,i.guest_name) guest_name {source} WHERE {where}
        ORDER BY d.created_at DESC,d.id DESC LIMIT :limit OFFSET :offset'''),{**params,'limit':limit,'offset':offset})).mappings().all()
    return {'items':[dict(row) for row in rows],'total':total,'limit':limit,'offset':offset,'as_of':anchor}


@router.post('/deliveries/{delivery_id}/cancel')
async def cancel(delivery_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.send')
    await require_permission(db, tid, user.id, 'invitations.send')
    row = (await db.execute(text("UPDATE whatsapp_deliveries SET state='cancelled',error_code='cancelled_by_user',updated_at=now() WHERE id=:id AND tenant_id=:tid AND state IN ('queued','waiting_connection') RETURNING id"), {'id': str(delivery_id), 'tid': str(tid)})).first()
    if not row:
        raise HTTPException(409, 'يمكن إلغاء الرسائل التي لم تبدأ فقط.')
    await audit(db, request, user, tid, 'whatsapp.cancel', {'delivery_id': str(delivery_id)})
    await db.commit()
    return {'state': 'cancelled'}


class ReviewRequest(BaseModel):
    outcome: str = Field(pattern='^(sent|not_sent)$')
    note: str = Field(min_length=20, max_length=500)


@router.post('/deliveries/{delivery_id}/review')
async def review(delivery_id: UUID, body: ReviewRequest, request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    tid = await authorize(request, user, db, 'whatsapp.manage')
    await require_permission(db, tid, user.id, 'whatsapp.view')
    if len(body.note.strip()) < 20:
        raise HTTPException(422, 'اكتب دليل المراجعة بوضوح.')
    row = (await db.execute(text("UPDATE whatsapp_deliveries SET state=:state,error_code='manually_reviewed',updated_at=now() WHERE id=:id AND tenant_id=:tid AND state='unknown' RETURNING id"),
                           {'tid':str(tid),'id':str(delivery_id),'state':'sent' if body.outcome == 'sent' else 'failed'})).first()
    if not row:
        raise HTTPException(409, 'المراجعة متاحة للنتائج غير المحسومة فقط.')
    await audit(db, request, user, tid, 'whatsapp.review', {'delivery_id':str(delivery_id),'outcome':body.outcome,'evidence':body.note.strip()})
    await db.commit()
    return {'reviewed':True}


@router.post('/webhook', include_in_schema=False)
async def webhook(request: Request, db=Depends(get_privileged_db)):
    # Public transport endpoint: authorization is the per-connection signature.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(413, 'Payload too large')
    try:
        payload = json.loads(raw)
        sid = str(UUID(payload['sessionId']))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, 'Invalid event')
    conn = (await db.execute(text('SELECT * FROM whatsapp_connections WHERE session_id=:sid'), {'sid': sid})).mappings().first()
    if not conn or not conn['webhook_secret_ciphertext'] or not svc.verify_signature(bytes(raw), svc.crypt(conn['webhook_secret_ciphertext'], decrypt=True), request.headers.get('X-OpenWA-Signature')):
        raise HTTPException(401, 'Invalid signature')
    if payload.get('event') != 'message.ack':
        return {'accepted': True}
    data = payload.get('data') or {}
    if not isinstance(data, dict):
        raise HTTPException(400, 'Invalid acknowledgement')
    mid, ack = data.get('messageId'), data.get('ack')
    if not isinstance(mid, str) or len(mid) > 512 or type(ack) is not int or ack not in (-1,0,1,2,3,4):
        raise HTTPException(400, 'Invalid acknowledgement')
    eid = hashlib.sha256(f'{sid}:{mid}:{ack}'.encode()).hexdigest()
    await db.execute(text('''INSERT INTO whatsapp_webhook_receipts(tenant_id,event_id,wa_message_id,ack)
        VALUES(:tid,:eid,:mid,:ack) ON CONFLICT DO NOTHING'''), {'tid': str(conn['tenant_id']), 'eid': eid, 'mid': mid, 'ack': ack})
    await apply_ack(db, conn['tenant_id'], mid)
    await db.commit()
    return {'accepted': True}


async def apply_ack(db, tenant_id, mid):
    # A signed error ACK is a real failure. Delivered/read evidence takes
    # precedence over late error events; a missing send receipt stays unknown.
    await db.execute(text("""UPDATE whatsapp_deliveries d SET
        state=CASE WHEN a.ack>=3 THEN 'read' WHEN a.ack>=2 THEN 'delivered' ELSE 'failed' END,
        error_code=CASE WHEN a.ack<2 AND a.failed THEN 'whatsapp_rejected'
                       WHEN d.error_code='whatsapp_rejected' THEN NULL ELSE d.error_code END,updated_at=now()
        FROM (SELECT MAX(ack) ack,BOOL_OR(ack=-1) failed FROM whatsapp_webhook_receipts WHERE tenant_id=:tid AND wa_message_id=:mid) a
        WHERE d.tenant_id=:tid AND d.wa_message_id=:mid
          AND (a.ack>=2 OR a.failed) AND (d.state IN ('sent','delivered') OR (d.state='failed' AND d.error_code='whatsapp_rejected'))"""),
        {'tid':str(tenant_id),'mid':mid})

# Event-specific authoring is separate from managing the institution connection.


class MessageConfigUpdate(BaseModel):
    rsvp_text: str = Field(min_length=1,max_length=700)
    ticket_text: str = Field(min_length=1,max_length=700)
    image_id: UUID | None = None
    version: int = Field(ge=0)


async def message_access(request,user,db,event_id,*,edit=False):
    tid=get_tenant_id_from_header(request)
    await require_permission(db,tid,user.id,'invitations.view')
    if edit:
        await require_permission(db,tid,user.id,'events.edit')
        await require_permission(db,tid,user.id,'whatsapp.send')
        await require_feature(db,tid,'whatsapp_delivery')
    else:
        await require_any_permission(db,tid,user.id,'whatsapp.view','whatsapp.send')
    return tid,await messages.event_owned(db,tid,event_id)


@router.get('/events/{event_id}/message')
async def get_message_config(event_id:UUID,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tid,event=await message_access(request,user,db,event_id)
    cfg=await messages.config(db,tid,event_id)
    link=get_settings().app_url.rstrip('/')+'/i/guest-preview'
    sample={'guest_name':'اسم الضيف'}
    return {**cfg,'defaults':{'rsvp_text':messages.DEFAULT_RSVP,'ticket_text':messages.DEFAULT_TICKET},
            'variables':messages.VARIABLES,'sample_values':{'guest_name':'اسم الضيف','event_name':event['title_ar'] or event['title'],
            'event_date':messages.render('{event_date}',sample,event,'').strip(),'event_location':event['venue_name'] or event['venue_address'] or 'حسب تفاصيل الدعوة'},
            'sample_link':link}


@router.put('/events/{event_id}/message')
async def save_message_config(event_id:UUID,body:MessageConfigUpdate,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tid,event=await message_access(request,user,db,event_id,edit=True)
    rsvp=messages.validate_template(body.rsvp_text);ticket=messages.validate_template(body.ticket_text)
    # Same lock used by enqueue freezes configuration until every row is snapshotted.
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'whatsapp-template:'+str(tid)+':'+str(event_id)})
    cfg=await messages.config(db,tid,event_id)
    if cfg['version']!=body.version:raise HTTPException(409,'تغيرت الرسالة بواسطة مستخدم آخر. أعد تحميلها قبل الحفظ.')
    if body.image_id:await messages.image(db,tid,event_id,body.image_id)
    sample={'guest_name':'اسم الضيف'};link=get_settings().app_url.rstrip('/')+'/i/'+'0'*32
    if any(messages.message_length(messages.render(value,sample,event,link))>(1024 if body.image_id else 4096) for value in (rsvp,ticket)):
        raise HTTPException(422,'المعاينة تتجاوز حد الرسالة. اختصر النص؛ النص المصاحب للصورة حتى 1024 حرفاً بعد استبدال المتغيرات.')
    await db.execute(text('''INSERT INTO whatsapp_message_templates(tenant_id,event_id,rsvp_text,ticket_text,image_id,version)
        VALUES(:tid,:eid,:rsvp,:ticket,:iid,1) ON CONFLICT(tenant_id,event_id) DO UPDATE SET
        rsvp_text=excluded.rsvp_text,ticket_text=excluded.ticket_text,image_id=excluded.image_id,
        version=whatsapp_message_templates.version+1,updated_at=now()'''),
        {'tid':str(tid),'eid':str(event_id),'rsvp':rsvp,'ticket':ticket,'iid':str(body.image_id) if body.image_id else None})
    await audit(db,request,user,tid,'whatsapp.message.update',{'event_id':str(event_id),'version':body.version+1,'with_image':bool(body.image_id)})
    await db.commit()
    return await messages.config(db,tid,event_id)


@router.post('/events/{event_id}/message/image')
async def upload_message_image(event_id:UUID,request:Request,file:UploadFile=File(...),user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tid,_=await message_access(request,user,db,event_id,edit=True)
    content=await file.read(messages.MAX_UPLOAD_BYTES+1)
    normalized=await asyncio.to_thread(messages.normalize_image,content)
    from app.services.feature_service import require_storage_for_upload,record_non_asset_storage
    await require_storage_for_upload(db,tid,len(normalized))
    iid=(await db.execute(text('''INSERT INTO whatsapp_message_images(tenant_id,event_id,content) VALUES(:tid,:eid,:content) RETURNING id'''),
                         {'tid':str(tid),'eid':str(event_id),'content':normalized})).scalar_one()
    await record_non_asset_storage(db,tid,len(normalized))
    await audit(db,request,user,tid,'whatsapp.message.image',{'event_id':str(event_id),'image_id':str(iid),'size':len(normalized)})
    await db.commit()
    return {'image_id':iid,'size':len(normalized)}


@router.get('/events/{event_id}/message/images/{image_id}')
async def get_message_image(event_id:UUID,image_id:UUID,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tid,_=await message_access(request,user,db,event_id)
    row=await messages.image(db,tid,event_id,image_id)
    return Response(bytes(row['content']),media_type=row['mime_type'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


class MessagePreviewRequest(BaseModel):
    invitation_ids:list[UUID]=Field(min_length=1,max_length=100)


@router.post('/events/{event_id}/message/preview')
async def preview_messages(event_id:UUID,body:MessagePreviewRequest,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tid,event=await message_access(request,user,db,event_id)
    cfg=await messages.config(db,tid,event_id)
    # Two representative messages at most, but validate every selected guest's length.
    from sqlalchemy import bindparam
    rows=(await db.execute(text('''SELECT * FROM invitations WHERE tenant_id=:tid AND event_id=:eid AND id IN :ids''').bindparams(bindparam('ids',expanding=True)),
                          {'tid':str(tid),'eid':str(event_id),'ids':list(map(str,body.invitation_ids))})).mappings().all()
    if len(rows)!=len(set(body.invitation_ids)):raise HTTPException(404,'إحدى الدعوات غير متاحة لهذا الحدث.')
    samples={};too_long=0
    for inv in rows:
        purpose,reason=svc.eligibility(inv)
        if reason:continue
        link=get_settings().app_url.rstrip('/')+'/i/'+quote(str(inv['token']),safe='')
        message=messages.render(cfg[purpose+'_text'],inv,event,link)
        if messages.message_length(message)>(1024 if cfg['image_id'] else 4096):too_long+=1
        if purpose not in samples:samples[purpose]={'purpose':purpose,'text':message,'guest_name':inv['guest_name_ar'] or inv['guest_name']}
    return {'version':cfg['version'],'image_id':cfg['image_id'],'samples':list(samples.values()),'too_long':too_long}
