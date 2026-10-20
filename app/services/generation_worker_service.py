"""Durable generation consumer. Own each result transaction; never call legacy pipeline."""
import asyncio
import hashlib
import json
from contextlib import suppress
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.database import AsyncSessionLocal
from app.config import get_settings
from app.services.generation_lease_service import claim_batch, lock_owned_batch, heartbeat
from app.services.generation_lifecycle_service import fail_attempt, reconcile
from app.services.generation_workspace_service import WorkspaceFull
from app.services.generation_snapshot_service import renderer_fingerprint
from app.services import generation_render_service as render, storage_service as storage
from app.services import generation_object_service as objects
from app.services.permission_service import require_permission
from app.services.feature_service import require_feature


class OwnershipLost(Exception):
    pass


class GenerationFailure(Exception):
    def __init__(self, code, transient=False):
        self.code,self.transient=code,transient
        super().__init__(code)


async def _allowed(db, operation):
    tid,uid=operation['tenant_id'],operation['created_by']
    await require_permission(db,tid,uid,'invitations.create')
    settings=operation['settings_snapshot']
    if settings['output_formats']:
        await require_permission(db,tid,uid,'invitations.export')
        await require_feature(db,tid,'pdf_export')
    if settings['require_rsvp']:
        await require_feature(db,tid,'rsvp')
    event=(await db.execute(text('SELECT status,deleted_at FROM events WHERE id=:id AND tenant_id=:tid'),
        {'id':operation['event_id'],'tid':tid})).mappings().first()
    if not event or event['deleted_at'] or event['status']=='cancelled':
        raise GenerationFailure('EVENT_UNAVAILABLE')


async def _guard(db,lease,operation):
    if not await lock_owned_batch(db,lease):
        raise OwnershipLost()
    await _allowed(db,operation)


from app.services.generation_monitoring_service import event as monitoring_event, sample_worker


def _sample_worker():
    try:
        sample_worker()
    except Exception:
        # Observability must not invalidate a completed business transaction.
        pass


async def _beat(lease, lost):
    try:
        while True:
            await asyncio.sleep(15)
            await asyncio.to_thread(_sample_worker)
            async with AsyncSessionLocal() as db:
                if not await heartbeat(db,lease):
                    lost.set()
                    return
                await db.commit()
    except asyncio.CancelledError:
        raise
    except Exception:
        # Loss of database contact is loss of authority, never permission to proceed.
        lost.set()


async def _check(lease,operation,lost):
    if lost.is_set():
        raise OwnershipLost()
    async with AsyncSessionLocal() as db:
        await _guard(db,lease,operation)
        await db.commit()


async def _io(function,*args):
    try:
        return await asyncio.wait_for(asyncio.to_thread(function,*args),timeout=30)
    except Exception as exc:
        raise GenerationFailure('STORAGE_UNAVAILABLE',transient=True) from exc


async def _save_blob(lease,operation,lost,label,content,mime):
    await _check(lease,operation,lost)
    if not content:
        raise GenerationFailure('EMPTY_OUTPUT')
    path=f"{lease.tenant_id}/{operation['event_id']}/operations/{lease.operation_id}/{lease.batch_id}/{lease.owner}/{label}-{uuid4()}"
    async with AsyncSessionLocal() as db:
        await _guard(db,lease,operation)
        await objects.register(db,lease,operation['event_id'],path,len(content))
        await db.commit()
    await _io(storage.upload_file,path,content,mime)
    # Verify the private object, not its temporary signed URL or upload return.
    fetched=await _io(storage.download_file,path)
    digest=hashlib.sha256(content).hexdigest()
    if len(fetched)!=len(content) or hashlib.sha256(fetched).hexdigest()!=digest:
        raise GenerationFailure('STORAGE_INTEGRITY',transient=True)
    return {'path':path,'sha256':digest,'byte_size':len(content)}


async def _read_blob(result):
    try:
        content=await _io(storage.download_file,result['path'])
    except GenerationFailure as error:
        if isinstance(error.__cause__,KeyError) or str(getattr(error.__cause__,'status',''))=='404':
            raise GenerationFailure('CHECKPOINT_MISSING',True) from error
        raise
    if len(content)!=result['byte_size'] or hashlib.sha256(content).hexdigest()!=result['sha256']:
        raise GenerationFailure('CHECKPOINT_INTEGRITY',True)
    return content


async def _invalidate_checkpoint(lease,operation,items,stage,path):
    # A missing/corrupt image must not permanently poison every export retry.
    # Invalidate only rows represented by that object; keep other stages/files.
    async with AsyncSessionLocal() as db:
        await _guard(db,lease,operation)
        for item in items:
            if item['stage_results'].get(stage,{}).get('path')!=path:
                continue
            await db.execute(text("""UPDATE batch_items SET stage_results=stage_results-CAST(:stage AS text),
                render_status='pending',completed_at=NULL,
                barcode_status=CASE WHEN :stage='barcode' THEN 'pending' ELSE barcode_status END,
                design_status=CASE WHEN :stage='design' THEN 'pending' ELSE design_status END
                WHERE id=:id AND tenant_id=:tenant_id AND batch_id=:batch_id AND operation_id=:operation_id"""),
                {**lease.params(),'id':item['id'],'stage':stage})
        await db.execute(text('UPDATE generation_storage_objects SET published=false WHERE tenant_id=:tid AND operation_id=:oid AND path=:path'),
            {'tid':str(lease.tenant_id),'oid':str(lease.operation_id),'path':path})
        await reconcile(db,lease.tenant_id,lease.operation_id)
        await db.commit()


async def _stage(lease,operation,lost,status):
    await _check(lease,operation,lost)
    async with AsyncSessionLocal() as db:
        await _guard(db,lease,operation)
        await db.execute(text('UPDATE generation_batches SET status=CAST(:status AS batch_status),updated_at=clock_timestamp() WHERE id=:batch_id AND tenant_id=:tenant_id'),{**lease.params(),'status':status})
        await db.commit()


async def _save_item(lease,operation,lost,items,stage,result):
    # Signed links are compatibility metadata only. Checkpoints use private paths.
    url=await _io(storage.get_signed_url,result['path'],86400*7)
    if not url:
        raise GenerationFailure('STORAGE_UNAVAILABLE',True)
    async with AsyncSessionLocal() as db:
        await _guard(db,lease,operation)
        for item in items:
            checkpoint={**item['stage_results'],stage:result}
            done=stage=='design' or operation['mode']=='quick'
            await db.execute(text('''UPDATE batch_items SET stage_results=CAST(:data AS jsonb),
                barcode_status=CASE WHEN :stage='barcode' THEN 'done' ELSE barcode_status END,
                design_status=CASE WHEN :stage='design' THEN 'done' ELSE design_status END,
                render_status=CASE WHEN :done THEN 'done' ELSE 'pending' END,
                barcode_url=CASE WHEN :stage='barcode' THEN :url ELSE barcode_url END,
                render_url=CASE WHEN :stage='design' THEN :url ELSE render_url END,
                error_message=NULL,completed_at=CASE WHEN :done THEN clock_timestamp() ELSE NULL END
                WHERE id=:id AND tenant_id=:tenant_id AND batch_id=:batch_id AND operation_id=:operation_id'''),
                {**lease.params(),'id':item['id'],'data':json.dumps(checkpoint),'stage':stage,'done':done,'url':url})
            if stage=='barcode':
                info=result['info']
                await db.execute(text('''UPDATE invitations SET barcode_png_url=:url,barcode_payload=:payload,
                    barcode_signature=:sig,qr_data=:public,updated_at=clock_timestamp()
                    WHERE id=:id AND tenant_id=:tenant_id AND generation_operation_id=:operation_id'''),
                    {**lease.params(),'id':item['invitation_id'],'url':url,'payload':info['barcode_payload'],'sig':info['signature'],'public':info['payload']})
            else:
                await db.execute(text('''UPDATE invitations SET render_image_url=:url,card_image_url=:url,updated_at=clock_timestamp()
                    WHERE id=:id AND tenant_id=:tenant_id AND generation_operation_id=:operation_id'''),
                    {**lease.params(),'id':item['invitation_id'],'url':url})
            item['stage_results']=checkpoint
        await objects.accounted(db,lease.tenant_id,result['path'])
        await reconcile(db,lease.tenant_id,lease.operation_id)
        await db.commit()



async def _export(lease,operation,batch,items,assets,lost):
    from app.services.generation_workspace_service import workspace,file_digest
    from app.services.generation_export_service import PartBuilder
    formats=operation['settings_snapshot']['output_formats']
    if not formats:
        return
    async with AsyncSessionLocal() as db:
        previous=(await db.execute(text('SELECT output_manifest FROM generation_batches WHERE tenant_id=:tenant_id AND id=:batch_id'),lease.params())).scalar() or {}
        verified={(row['kind'],row['file_part']):row for row in (await db.execute(text("SELECT id,kind,file_part FROM generation_artifacts WHERE tenant_id=:tenant_id AND batch_id=:batch_id AND operation_id=:operation_id AND status='verified'"),lease.params())).mappings()}
    frames=[]
    by_path={}
    stage='design' if operation['mode']=='designed' else 'barcode'
    for item in items:
        result=item['stage_results'][stage]
        if result['path'] not in by_path:
            frame={'result':result,'item':item,'rows':[]}
            by_path[result['path']]=frame
            frames.append(frame)
        by_path[result['path']]['rows'].append(str(item['source_row_id']))
    per_page=1 if operation['mode']=='designed' else operation['settings_snapshot']['layout']['rows']*operation['settings_snapshot']['layout']['cols']
    limits=operation['settings_snapshot']
    with workspace() as scratch:
        for kind in formats:
            if kind in previous and all((kind,part['file_part']) in verified for part in previous[kind]):
                continue
            await _stage(lease,operation,lost,'generating_pdf' if kind=='pdf' else 'generating_zip')
            builder=PartBuilder(scratch,kind,limits['export_max_bytes'],limits['export_max_pages'])
            try:
                for start in range(0,len(frames),per_page):
                    await _check(lease,operation,lost)
                    group=frames[start:start+per_page]
                    entries=[]
                    coverage=[]
                    for index,frame in enumerate(group,start+1):
                        result=frame['result']
                        try:
                            content=await _read_blob(result)
                        except GenerationFailure as error:
                            if error.code in ('CHECKPOINT_MISSING','CHECKPOINT_INTEGRITY'):
                                await _invalidate_checkpoint(lease,operation,items,stage,result['path'])
                            raise
                        file=scratch.output('.png')
                        await asyncio.to_thread(scratch.write,file,[content])
                        del content
                        entries.append({'file':file,'name':f'{index:05d}.png','guest_name':frame['item']['normalized_data']['guest_name'],'code':frame['item']['token'][:8]})
                        coverage.extend(frame['rows'])
                    if kind=='pdf':
                        content=await asyncio.to_thread(render.pdf_page,operation['mode'],entries,limits['layout'],assets)
                        await asyncio.to_thread(builder.add_pdf_page,content,coverage)
                        del content
                    else:
                        await asyncio.to_thread(builder.add_images,entries,coverage)
                    for entry in entries:
                        entry['file'].unlink()
                await asyncio.to_thread(builder.finish_part)
            except (GenerationFailure,OwnershipLost):
                raise
            except Exception as error:
                raise GenerationFailure('PDF_FAILED' if kind=='pdf' else 'ZIP_FAILED') from error
            finally:
                builder.close()
            plan=[{key:part[key] for key in ('kind','file_part','rows')} for part in builder.parts]
            if kind in previous and previous[kind]!=plan:
                raise GenerationFailure('EXPORT_PLAN_MISMATCH')
            async with AsyncSessionLocal() as db:
                await _guard(db,lease,operation)
                await db.execute(text("UPDATE generation_batches SET output_manifest=jsonb_set(COALESCE(output_manifest,'{}'::jsonb),ARRAY[CAST(:kind AS text)],CAST(:plan AS jsonb)) WHERE tenant_id=:tenant_id AND id=:batch_id"),{**lease.params(),'kind':kind,'plan':json.dumps(plan)})
                await db.commit()
            for part in builder.parts:
                if (kind,part['file_part']) in verified:
                    part['file'].unlink()
                    continue
                await _check(lease,operation,lost)
                size,digest=await asyncio.to_thread(file_digest,part['file'])
                if (size,digest)!=(part['byte_size'],part['sha256']):
                    raise GenerationFailure('EXPORT_INTEGRITY')
                path=f"{lease.tenant_id}/{operation['event_id']}/operations/{lease.operation_id}/{lease.batch_id}/{lease.owner}/{uuid4()}.{kind}"
                async with AsyncSessionLocal() as db:
                    await _guard(db,lease,operation)
                    await objects.register(db,lease,operation['event_id'],path,size)
                    await db.commit()
                await _io(storage.upload_disk_file,path,part['file'],'application/pdf' if kind=='pdf' else 'application/zip')
                await _io(storage.verify_disk_object,path,size,digest)
                async with AsyncSessionLocal() as db:
                    await _guard(db,lease,operation)
                    aid=uuid4()
                    await db.execute(text("""INSERT INTO generation_artifacts(id,tenant_id,event_id,operation_id,batch_id,
                        kind,part_index,file_part,storage_path,byte_size,sha256,status,verified_at)
                        VALUES(:id,:tenant_id,:event_id,:operation_id,:batch_id,:kind,:part,:file_part,:path,:size,:sha,'verified',clock_timestamp())"""),
                        {**lease.params(),'id':aid,'event_id':operation['event_id'],'kind':kind,'part':batch['part_index']*10000+part['file_part'],
                         'file_part':part['file_part'],'path':path,'size':size,'sha':digest})
                    await db.execute(text("""INSERT INTO generation_artifact_items(tenant_id,operation_id,artifact_id,source_row_id)
                        SELECT tenant_id,operation_id,:aid,source_row_id FROM batch_items
                        WHERE tenant_id=:tenant_id AND operation_id=:operation_id AND batch_id=:batch_id AND render_status='done'
                        AND source_row_id=ANY(CAST(:rows AS uuid[]))"""),{**lease.params(),'aid':aid,'rows':part['rows']})
                    await objects.accounted(db,lease.tenant_id,path)
                    await reconcile(db,lease.tenant_id,lease.operation_id)
                    await db.commit()
                part['file'].unlink()


async def execute_batch(tenant_id: UUID,operation_id: UUID,batch_id: UUID):
    if not get_settings().generation_worker_enabled:
        return {'status':'disabled'}
    async with AsyncSessionLocal() as db:
        lease=await claim_batch(db,tenant_id,operation_id,batch_id)
        await db.commit()
    if not lease:
        return {'status':'not_claimed'}
    monitoring_event("started",operation_id)
    await asyncio.to_thread(_sample_worker)
    lost=asyncio.Event()
    beat=asyncio.create_task(_beat(lease,lost))
    try:
        async with AsyncSessionLocal() as db:
            operation=dict((await db.execute(text('SELECT * FROM generation_operations WHERE tenant_id=:tenant_id AND id=:operation_id'),lease.params())).mappings().one())
            batch=dict((await db.execute(text('SELECT * FROM generation_batches WHERE tenant_id=:tenant_id AND id=:batch_id AND operation_id=:operation_id'),lease.params())).mappings().one())
            items=[dict(row) for row in (await db.execute(text('''SELECT bi.*,i.token,r.normalized_data FROM batch_items bi
                JOIN invitations i ON i.id=bi.invitation_id AND i.tenant_id=bi.tenant_id AND i.generation_operation_id=bi.operation_id
                JOIN generation_import_rows r ON r.id=bi.source_row_id AND r.tenant_id=bi.tenant_id AND r.operation_id=bi.operation_id
                WHERE bi.tenant_id=:tenant_id AND bi.operation_id=:operation_id AND bi.batch_id=:batch_id ORDER BY r.source_row_number'''),lease.params())).mappings()]
            rows=(await db.execute(text('''SELECT DISTINCT a.sha256,a.content,a.mime_type FROM generation_snapshot_assets a
                JOIN generation_operation_assets m ON m.asset_id=a.id AND m.tenant_id=a.tenant_id
                WHERE m.tenant_id=:tenant_id AND m.operation_id=:operation_id'''),lease.params())).mappings().all()
            assets={row['sha256']:dict(row) for row in rows}
        if len(items)!=batch['count_total'] or not items:
            raise GenerationFailure('INCOMPLETE_INPUT')
        if operation['settings_snapshot']['renderer_sha256']!=renderer_fingerprint():
            raise GenerationFailure('RENDERER_VERSION_MISMATCH')
        if any(hashlib.sha256(asset['content']).hexdigest()!=digest for digest,asset in assets.items()):
            raise GenerationFailure('SNAPSHOT_INTEGRITY')
        await _stage(lease,operation,lost,'generating_barcodes')
        for item in items:
            await _check(lease,operation,lost)
            if item['barcode_status']=='done':
                continue
            inv={**item['normalized_data'],'id':item['invitation_id'],'token':item['token']}
            try:
                content,info=await asyncio.to_thread(render.barcode,inv,operation['settings_snapshot']['layout'])
            except Exception as exc:
                raise GenerationFailure('BARCODE_FAILED') from exc
            result=await _save_blob(lease,operation,lost,'qr',content,'image/png')
            result['info']=info
            await _save_item(lease,operation,lost,[item],'barcode',result)
        if operation['mode']=='designed':
            await _stage(lease,operation,lost,'rendering_images')
            snapshot=operation['templates_snapshot'][str(batch['ticket_class'])]
            size=render.slots(snapshot)
            for start in range(0,len(items),size):
                group=items[start:start+size]
                await _check(lease,operation,lost)
                if all(item['design_status']=='done' for item in group):
                    continue
                try:
                    content=await asyncio.to_thread(render.designed,snapshot,assets,render.contexts(group,batch,operation['event_snapshot']))
                except Exception as exc:
                    raise GenerationFailure('DESIGN_FAILED') from exc
                result=await _save_blob(lease,operation,lost,'card',content,'image/png')
                await _save_item(lease,operation,lost,group,'design',result)
                for item in group:
                    item['design_status']='done'
        await _export(lease,operation,batch,items,assets,lost)
        async with AsyncSessionLocal() as db:
            await _guard(db,lease,operation)
            await db.execute(text("""UPDATE generation_batches SET status='ready',progress=100,completed_at=clock_timestamp(),
                count_done=count_total,count_failed=0,lease_owner=NULL,lease_expires_at=NULL,error_message=NULL,last_error_code=NULL,
                updated_at=clock_timestamp() WHERE tenant_id=:tenant_id AND id=:batch_id AND operation_id=:operation_id"""),lease.params())
            await reconcile(db,tenant_id,operation_id)
            await db.commit()
        await asyncio.to_thread(_sample_worker)
        monitoring_event('completed',operation_id)
        return {'status':'ready'}
    except OwnershipLost:
        monitoring_event("ownership_lost",operation_id)
        return {'status':'ownership_lost'}
    except Exception as error:
        monitoring_event("failed",operation_id)
        code,transient=('AUTHORIZATION_CHANGED',False) if isinstance(error,HTTPException) else (error.code,error.transient) if isinstance(error,GenerationFailure) else ('GENERATION_FAILED',False)
        if isinstance(error,WorkspaceFull):
            code,transient='WORKSPACE_LIMIT',True
        if isinstance(error,DBAPIError) and (error.connection_invalidated or
                getattr(error.orig,'sqlstate',None) in ('40001','40P01','55P03','08000','08003','08006','57P01')):
            code,transient='DATABASE_TRANSIENT',True
        async with AsyncSessionLocal() as db:
            applied=await fail_attempt(db,lease,code,transient=transient)
            await db.commit()
        return {'status':'failed' if applied else 'ownership_lost','code':code}
    finally:
        beat.cancel()
        with suppress(asyncio.CancelledError):
            await beat
