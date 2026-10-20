"""Owned-object upload intents: a failed upload cannot become an untracked orphan."""
import asyncio
from sqlalchemy import text
from app.services.entitlement_service import resolve_billing_tenant
from app.services import storage_service


async def register(db,lease,event_id,path,size):
    from app.services.feature_service import require_storage_for_upload
    await require_storage_for_upload(db,lease.tenant_id,size)
    billing=await resolve_billing_tenant(db,lease.tenant_id)
    await db.execute(text("""INSERT INTO usage_counters(tenant_id,period_start,period_end,key,value)
        VALUES(:billing,'1970-01-01','2099-12-31','storage_bytes',:size)
        ON CONFLICT(tenant_id,period_start,key) DO UPDATE SET value=usage_counters.value+EXCLUDED.value,updated_at=clock_timestamp()"""),
        {'billing':billing,'size':size})
    await db.execute(text("""INSERT INTO generation_storage_objects(path,tenant_id,event_id,operation_id,batch_id,lease_owner,byte_size,accounted,billing_tenant_id)
        VALUES(:path,:tenant_id,:eid,:operation_id,:batch_id,:owner,:size,true,:billing)"""),
        {**lease.params(),'path':path,'eid':event_id,'size':size,'billing':billing})


async def accounted(db,tenant,path):
    # Space was reserved before IO. Publishing must not charge it a second time.
    exists=(await db.execute(text('SELECT accounted FROM generation_storage_objects WHERE tenant_id=:tid AND path=:path'),
        {'tid':str(tenant),'path':path})).scalar()
    if not exists:
        raise RuntimeError('Missing storage reservation')
    await db.execute(text('UPDATE generation_storage_objects SET published=true WHERE tenant_id=:tid AND path=:path'),{'tid':str(tenant),'path':path})


async def cleanup_orphans(db,limit=10):
    rows=(await db.execute(text('''SELECT o.path,o.tenant_id,o.byte_size,o.accounted,o.billing_tenant_id
        FROM generation_storage_objects o JOIN generation_batches b
          ON b.id=o.batch_id AND b.tenant_id=o.tenant_id AND b.operation_id=o.operation_id
        WHERE NOT o.published AND o.created_at<clock_timestamp()-interval '24 hours'
          AND (b.lease_owner IS NULL OR b.lease_owner<>o.lease_owner OR b.lease_expires_at<=clock_timestamp())
          AND NOT EXISTS(SELECT 1 FROM batch_items i WHERE i.tenant_id=o.tenant_id AND i.operation_id=o.operation_id
              AND (i.stage_results->'barcode'->>'path'=o.path OR i.stage_results->'design'->>'path'=o.path))
          AND NOT EXISTS(SELECT 1 FROM generation_artifacts a WHERE a.tenant_id=o.tenant_id AND a.operation_id=o.operation_id AND a.storage_path=o.path)
        ORDER BY o.created_at,o.path LIMIT :limit FOR UPDATE OF o SKIP LOCKED'''),{'limit':max(1,min(10,limit))})).mappings().all()
    removed=0
    for row in rows:
        if not await asyncio.to_thread(storage_service.delete_file,row['path']):
            continue
        if row['accounted']:
            await db.execute(text("""UPDATE usage_counters SET value=GREATEST(0,value-:size),updated_at=clock_timestamp()
                WHERE tenant_id=:billing AND key='storage_bytes' AND period_start='1970-01-01'::date"""),
                {'billing':row['billing_tenant_id'],'size':row['byte_size']})
        await db.execute(text('DELETE FROM generation_storage_objects WHERE path=:path AND tenant_id=:tid'),{'path':row['path'],'tid':row['tenant_id']})
        removed+=1
    return removed
