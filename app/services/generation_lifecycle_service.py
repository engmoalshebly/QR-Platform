"""Operation state changes. All writers lock the parent before its children."""
from sqlalchemy import text
from fastapi import HTTPException
from app.services.generation_lease_service import lock_owned_batch


async def reconcile(db, tenant_id, operation_id):
    p = {'tid':str(tenant_id), 'oid':str(operation_id)}
    status = (await db.execute(text('SELECT status FROM generation_operations WHERE tenant_id=:tid AND id=:oid FOR UPDATE'), p)).scalar()
    if status is None:
        return
    await db.execute(text("""UPDATE generation_batches b SET count_done=c.done,count_failed=c.failed,
        progress=LEAST(95,(c.done*80)/GREATEST(b.count_total,1))
        FROM (SELECT batch_id,count(*) FILTER(WHERE render_status='done') AS done,
              count(*) FILTER(WHERE render_status='failed') AS failed FROM batch_items
              WHERE tenant_id=:tid AND operation_id=:oid GROUP BY batch_id) c
        WHERE b.id=c.batch_id AND b.tenant_id=:tid AND b.operation_id=:oid AND b.status NOT IN ('ready','cancelled')"""),p)
    counts = (await db.execute(text('''SELECT count(*) FILTER(WHERE render_status='done') AS done,
        count(*) FILTER(WHERE render_status='failed') AS failed FROM batch_items
        WHERE tenant_id=:tid AND operation_id=:oid'''), p)).mappings().one()
    batches = (await db.execute(text('''SELECT count(*) AS total,count(*) FILTER(WHERE status='ready') AS done,
        count(*) FILTER(WHERE status='failed') AS failed,
        count(*) FILTER(WHERE status NOT IN ('ready','failed','cancelled')) AS active,
        COALESCE(sum((SELECT sum(COALESCE(jsonb_array_length(b.output_manifest->f),1)) FROM unnest(b.output_formats) f WHERE f IN ('pdf','zip')))
        FILTER(WHERE b.status='failed'),0) AS failed_formats
        FROM generation_batches b WHERE b.tenant_id=:tid AND b.operation_id=:oid'''), p)).mappings().one()
    files = (await db.execute(text("SELECT count(*) FROM generation_artifacts WHERE tenant_id=:tid AND operation_id=:oid AND status='verified' AND kind IN ('pdf','zip')"),p)).scalar()
    verified_failed = (await db.execute(text("""SELECT count(*) FROM generation_artifacts a JOIN generation_batches b ON b.id=a.batch_id
        WHERE a.tenant_id=:tid AND a.operation_id=:oid AND a.status='verified' AND a.kind IN ('pdf','zip') AND b.status='failed'"""),p)).scalar()
    if status not in ('cancel_requested','cancelled'):
        if batches['active']:
            status = 'running'
        elif batches['done']==batches['total']:
            status = 'completed'
        else:
            status = 'partial' if counts['done'] or files else 'failed'
    terminal = status in ('completed','partial','failed','cancelled')
    await db.execute(text('''UPDATE generation_operations SET status=:status,cards_done=:done,cards_failed=:failed,
        files_done=:files,files_failed=:files_failed,updated_at=clock_timestamp(),
        completed_at=CASE WHEN :terminal THEN COALESCE(completed_at,clock_timestamp()) ELSE NULL END,
        error_code=CASE WHEN :status='completed' THEN NULL ELSE error_code END,
        error_message=CASE WHEN :status='completed' THEN NULL ELSE error_message END
        WHERE tenant_id=:tid AND id=:oid'''), {**p,'status':status,'done':counts['done'],'failed':counts['failed'],
        'files':files,'files_failed':max(0,int(batches['failed_formats'])-verified_failed),'terminal':terminal})


async def cancel_operation(db, tenant_id, operation_id):
    p={'tid':str(tenant_id),'oid':str(operation_id)}
    status=(await db.execute(text('SELECT status FROM generation_operations WHERE tenant_id=:tid AND id=:oid FOR UPDATE'),p)).scalar()
    if status is None:
        raise HTTPException(404,'العملية غير موجودة')
    if status in ('completed','partial','failed'):
        raise HTTPException(409,'انتهت العملية؛ لا يمكن إلغاء نتائجها المكتملة')
    if status=='cancelled':
        return
    await db.execute(text("UPDATE generation_operations SET status='cancel_requested' WHERE tenant_id=:tid AND id=:oid"),p)
    # Invalidate ownership under the same parent lock as result commits. Work in
    # progress may finish CPU/IO, but can no longer attach or publish its output.
    await db.execute(text("""UPDATE generation_batches SET status='cancelled',lease_owner=NULL,lease_expires_at=NULL,
        updated_at=clock_timestamp() WHERE tenant_id=:tid AND operation_id=:oid AND status NOT IN ('ready','failed','cancelled')"""),p)
    await db.execute(text("UPDATE generation_operations SET status='cancelled',updated_at=clock_timestamp(),completed_at=clock_timestamp() WHERE tenant_id=:tid AND id=:oid"),p)
    await reconcile(db,tenant_id,operation_id)


async def retry_operation(db, tenant_id, operation_id):
    p={'tid':str(tenant_id),'oid':str(operation_id)}
    status=(await db.execute(text('SELECT status FROM generation_operations WHERE tenant_id=:tid AND id=:oid FOR UPDATE'),p)).scalar()
    if status not in ('partial','failed'):
        raise HTTPException(409,'إعادة المحاولة متاحة للعمليات التي تحتوي مراحل فاشلة فقط')
    from app.config import get_settings
    settings=get_settings()
    cards=(await db.execute(text('SELECT cards_count FROM generation_operations WHERE tenant_id=:tid AND id=:oid'),p)).scalar()
    capacity=(await db.execute(text('SELECT generation_check_capacity(:tid,:cards,:operations,:queued_cards,:tenant_ops)'),
        {**p,'cards':cards,'operations':settings.generation_queue_max_operations,
         'queued_cards':settings.generation_queue_max_cards,'tenant_ops':settings.generation_tenant_max_operations})).scalar()
    if not capacity:
        raise HTTPException(429,'قائمة التوليد ممتلئة؛ أعد المحاولة لاحقًا',headers={'Retry-After':'5'})
    await db.execute(text("""UPDATE batch_items SET render_status=CASE WHEN render_status='failed' THEN 'pending' ELSE render_status END,
        barcode_status=CASE WHEN barcode_status='failed' THEN 'pending' ELSE barcode_status END,
        design_status=CASE WHEN design_status='failed' THEN 'pending' ELSE design_status END,error_message=NULL
        WHERE tenant_id=:tid AND operation_id=:oid AND batch_id IN
        (SELECT id FROM generation_batches WHERE tenant_id=:tid AND operation_id=:oid AND status='failed')"""),p)
    await db.execute(text("""UPDATE generation_outbox SET published_at=NULL,attempts=0,available_at=clock_timestamp(),last_error_code=NULL
        WHERE tenant_id=:tid AND operation_id=:oid AND batch_id IN
        (SELECT id FROM generation_batches WHERE tenant_id=:tid AND operation_id=:oid AND status='failed')"""),p)
    await db.execute(text("""UPDATE generation_batches SET status='queued',recovery_count=0,last_error_code=NULL,error_message=NULL,
        lease_owner=NULL,lease_expires_at=NULL,completed_at=NULL,updated_at=clock_timestamp()
        WHERE tenant_id=:tid AND operation_id=:oid AND status='failed'"""),p)
    await db.execute(text("""UPDATE generation_operations SET status='queued',cards_failed=0,files_failed=0,
        error_code=NULL,error_message=NULL,completed_at=NULL,updated_at=clock_timestamp() WHERE tenant_id=:tid AND id=:oid"""),p)


async def fail_attempt(db, lease, code, *, transient=False):
    if not await lock_owned_batch(db,lease):
        return False
    p=lease.params()
    count=(await db.execute(text('SELECT recovery_count FROM generation_batches WHERE id=:batch_id AND tenant_id=:tenant_id AND operation_id=:operation_id'),p)).scalar()+1
    retry = transient and count<3
    await db.execute(text('''UPDATE generation_batches SET status=CAST(:status AS batch_status),recovery_count=:count,
        last_error_code=:code,error_message=:code,lease_owner=NULL,lease_expires_at=NULL,updated_at=clock_timestamp()
        WHERE id=:batch_id AND tenant_id=:tenant_id'''),{**p,'status':'queued' if retry else 'failed','code':code,'count':count})
    if retry:
        await db.execute(text('''UPDATE generation_outbox SET published_at=NULL,last_error_code=:code,
            available_at=clock_timestamp()+make_interval(secs=>:delay)
            WHERE tenant_id=:tenant_id AND operation_id=:operation_id AND batch_id=:batch_id'''),{**p,'code':code,'delay':min(300,2**count)})
    else:
        await db.execute(text("""UPDATE batch_items SET render_status='failed',error_message=:code
            WHERE tenant_id=:tenant_id AND batch_id=:batch_id AND operation_id=:operation_id AND render_status<>'done'"""),{**p,'code':code})
        await db.execute(text("UPDATE generation_operations SET error_code=:code,error_message='تعذّر إكمال إحدى مراحل التوليد؛ راجع حالة العملية وأعد المرحلة الفاشلة' WHERE id=:operation_id AND tenant_id=:tenant_id"),{**p,'code':code})
    await reconcile(db,lease.tenant_id,lease.operation_id)
    return True


async def recover_operations(db, limit=100):
    """Bounded sweep; caller commits. Published-but-lost broker jobs are reissued."""
    operations=(await db.execute(text('''SELECT o.id,o.tenant_id FROM generation_operations o
        WHERE o.status IN ('queued','running') AND EXISTS(SELECT 1 FROM generation_batches b
        WHERE b.operation_id=o.id AND b.tenant_id=o.tenant_id AND b.status NOT IN ('ready','failed','cancelled')
          AND (b.lease_expires_at<=clock_timestamp() OR (b.lease_owner IS NULL AND b.updated_at<clock_timestamp()-interval '60 seconds')))
        ORDER BY o.updated_at,o.id LIMIT :limit FOR UPDATE OF o SKIP LOCKED'''),{'limit':max(1,min(limit,100))})).mappings().all()
    recovered=0
    from app.config import get_settings
    republish_max=get_settings().generation_republish_max
    for op in operations:
        p={'tid':op['tenant_id'],'oid':op['id']}
        batches=(await db.execute(text('''SELECT id,lease_owner,recovery_count FROM generation_batches
            WHERE tenant_id=:tid AND operation_id=:oid AND status NOT IN ('ready','failed','cancelled')
            AND (lease_expires_at<=clock_timestamp() OR (lease_owner IS NULL AND updated_at<clock_timestamp()-interval '60 seconds'))
            FOR UPDATE'''),p)).mappings().all()
        for batch in batches:
            count=batch['recovery_count']+bool(batch['lease_owner'])
            # A published event that nobody ever claims (lost broker, no consumer) used to be
            # re-published forever because it never consumed a recovery chance.
            published=(await db.execute(text('''SELECT COALESCE(max(attempts),0) FROM generation_outbox
                WHERE tenant_id=:tid AND operation_id=:oid AND batch_id=:bid AND published_at IS NOT NULL'''),
                {**p,'bid':batch['id']})).scalar()
            stalled=not batch['lease_owner'] and published>=republish_max
            code='DISPATCH_STALLED' if stalled else 'WORKER_LOST'
            failed=count>=3 or stalled
            q={**p,'bid':batch['id'],'count':count,'status':'failed' if failed else 'queued','code':code}
            await db.execute(text('''UPDATE generation_batches SET status=CAST(:status AS batch_status),
                lease_owner=NULL,lease_expires_at=NULL,recovery_count=:count,last_error_code=:code,updated_at=clock_timestamp()
                WHERE tenant_id=:tid AND id=:bid'''),q)
            if failed:
                message='لم تُستلم المهمة من العامل رغم إعادة النشر؛ راجع الناقل والعامل ثم أعد المحاولة' if stalled else 'توقّف العامل مرارًا؛ أعد المحاولة بعد مراجعة التشغيل'
                await db.execute(text("UPDATE generation_operations SET error_code=:code,error_message=:message WHERE tenant_id=:tid AND id=:oid"),{**p,'code':code,'message':message})
                await db.execute(text("UPDATE batch_items SET render_status='failed',error_message=:code WHERE tenant_id=:tid AND batch_id=:bid AND render_status<>'done'"),q)
            else:
                # Respect a broker or worker backoff already scheduled in future.
                await db.execute(text('''UPDATE generation_outbox SET published_at=NULL,
                    available_at=GREATEST(available_at,clock_timestamp()),last_error_code=:code
                    WHERE tenant_id=:tid AND operation_id=:oid AND batch_id=:bid'''),q)
            recovered+=1
        await reconcile(db,op['tenant_id'],op['id'])
    return recovered
