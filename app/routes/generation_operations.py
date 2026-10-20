"""New 202 API. Admission remains gated until P2 worker activation."""
import re
import asyncio
from typing import Literal
import weakref
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.config import get_settings
from app.database import get_db
from app.models.generation_operation import GenerationOperationCreate, GenerationOperationRead
from app.services.permission_service import require_permission
from app.services import generation_operation_service as service
from app.services.generation_snapshot_service import prepare_snapshot

router = APIRouter(prefix='/generation-operations', tags=['Generation Operations'])

# Bound snapshot copies per API event loop; waiting requests own no quota locks.
_preparation_slots = weakref.WeakKeyDictionary()


def preparation_slots():
    loop = asyncio.get_running_loop()
    if loop not in _preparation_slots:
        _preparation_slots[loop] = asyncio.Semaphore(2)
    return _preparation_slots[loop]



@router.post('', status_code=202, response_model=GenerationOperationRead)
async def create_operation(body: GenerationOperationCreate, request: Request,
                           idempotency_key: str = Header(..., alias='Idempotency-Key', min_length=8, max_length=128),
                           user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}', idempotency_key):
        raise HTTPException(422, 'مفتاح الطلب يجب أن يكون معرّفًا ثابتًا من 8 إلى 128 حرفًا')
    settings = get_settings()
    if not settings.generation_operations_enabled:
        raise HTTPException(503, 'مسار العمليات الجديد قيد التجهيز. استخدم مسار الإنشاء الحالي', headers={'Retry-After': '60'})
    tenant_id = get_tenant_id_from_header(request)
    slots = preparation_slots()
    try:
        await asyncio.wait_for(slots.acquire(), timeout=5)
    except TimeoutError:
        raise HTTPException(429, 'تجهيز عمليات أخرى جارٍ. أعد المحاولة بالمفتاح نفسه', headers={'Retry-After':'2'})
    try:
        await require_permission(db, tenant_id, user.id, 'invitations.create')
        existing = await service.find_replay(db, tenant_id, user.id, idempotency_key, service.request_fingerprint(body))
        if existing:
            return service.compact_operation(existing, replayed=True)
        if len(body.normalized_rows()) > settings.generation_operation_max_cards:
            raise service.max_cards_error(settings.generation_operation_max_cards)
        await service.authorize_admission(db, tenant_id, user.id, body)
        snapshot = await prepare_snapshot(db, tenant_id, body)
        # End read-only preflight: no admission or quota locks are held during asset IO. Start a
        # fresh scoped transaction for atomic admission and reinstall RLS context.
        await db.commit()
        await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"), {'tid': str(tenant_id)})
        operation, replayed = await service.admit_operation(db, tenant_id, user.id, idempotency_key, body, snapshot)
        await db.commit()
        return service.compact_operation(operation, replayed)
    except DBAPIError as error:
        await db.rollback()
        if getattr(error.orig, 'sqlstate', None) in ('55P03','40P01','40001'):
            raise HTTPException(429, 'طلب الإنشاء قيد المعالجة. أعد المحاولة بالمفتاح نفسه', headers={'Retry-After':'2'})
        raise
    except BaseException:
        await db.rollback()
        raise
    finally:
        slots.release()


@router.get('')
async def list_operations(request: Request, event_id: UUID | None = None,
                          status: list[Literal['queued','running','completed','partial','failed','cancel_requested','cancelled']] | None = Query(None),
                          before: UUID | None = None, limit: int = Query(50, ge=1, le=100),
                          user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, 'batches.view')
    params = {'tid': str(tenant_id), 'limit': limit+1}
    query = f'SELECT {service.SUMMARY_COLUMNS} FROM generation_operations WHERE tenant_id=:tid'
    if event_id:
        query += ' AND event_id=:eid'
        params['eid'] = str(event_id)
    if status:
        query += ' AND status=ANY(CAST(:statuses AS text[]))'
        params['statuses'] = sorted(set(status))
    if before:
        query += ' AND (created_at,id)<(SELECT created_at,id FROM generation_operations WHERE tenant_id=:tid AND id=:before)'
        params['before'] = str(before)
    result = await db.execute(text(query+' ORDER BY created_at DESC,id DESC LIMIT :limit'), params)
    rows = [dict(row) for row in result.mappings().all()]
    return {'items':[service.compact_operation(row) for row in rows[:limit]],
            'next_cursor': str(rows[limit-1]['id']) if len(rows)>limit else None}


@router.get('/capabilities')
async def operation_capabilities(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_db)):
    """Lets the client choose the 202 contract or the legacy one; limits mirror server enforcement."""
    get_tenant_id_from_header(request)
    settings = get_settings()
    drafts = bool((await db.execute(text("SELECT to_regclass('public.generation_drafts') IS NOT NULL"))).scalar())
    return {'contract_version': 1,
            'drafts_enabled': drafts,
            'enabled': bool(settings.generation_operations_enabled and settings.generation_worker_enabled),
            'max_cards': settings.generation_operation_max_cards,
            'max_people_per_card': 100,
            'output_formats': ['pdf', 'zip']}


@router.get('/{operation_id}', response_model=GenerationOperationRead)
async def get_operation(operation_id: UUID, request: Request,
                         user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    return service.compact_operation(await service.read_operation(db, tenant_id, user.id, operation_id))


@router.get('/{operation_id}/rows')
async def operation_rows(operation_id: UUID, request: Request, after_row: int = Query(0, ge=0, le=2147483647),
                         limit: int = Query(50, ge=1, le=100),
                         user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, 'invitations.view')
    await service.read_operation(db, tenant_id, user.id, operation_id)
    result = await db.execute(text('''SELECT id,source_row_number,normalized_data,validation_errors,selected FROM generation_import_rows
        WHERE tenant_id=:tid AND operation_id=:oid AND source_row_number>:after ORDER BY source_row_number LIMIT :limit'''),
        {'tid':str(tenant_id),'oid':str(operation_id),'after':after_row,'limit':limit+1})
    rows = [dict(row) for row in result.mappings().all()]
    return {'items':rows[:limit],'next_row':rows[limit-1]['source_row_number'] if len(rows)>limit else None}


@router.get('/{operation_id}/artifacts')
async def operation_artifacts(operation_id: UUID, request: Request, before: UUID | None = None,
                              limit: int = Query(50, ge=1, le=100),
                              user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await service.read_operation(db, tenant_id, user.id, operation_id)
    from app.services.feature_service import require_feature
    await require_permission(db, tenant_id, user.id, 'invitations.export')
    await require_feature(db, tenant_id, 'pdf_export')
    params = {'tid':str(tenant_id),'oid':str(operation_id),'limit':limit+1}
    query = "SELECT id,batch_id,kind,part_index,file_part,byte_size,sha256,verified_at,(SELECT count(*) FROM generation_artifact_items ai WHERE ai.tenant_id=generation_artifacts.tenant_id AND ai.artifact_id=generation_artifacts.id) AS cards_count FROM generation_artifacts WHERE tenant_id=:tid AND operation_id=:oid AND status='verified'"
    if before:
        query += ' AND (kind,part_index,id)>(SELECT kind,part_index,id FROM generation_artifacts WHERE tenant_id=:tid AND operation_id=:oid AND id=:before)'
        params['before'] = str(before)
    result = await db.execute(text(query+' ORDER BY kind,part_index,id LIMIT :limit'),params)
    rows = [dict(row) for row in result.mappings().all()]
    return {'items':rows[:limit],'next_cursor':str(rows[limit-1]['id']) if len(rows)>limit else None}


@router.post('/{operation_id}/cancel',response_model=GenerationOperationRead)
async def cancel_generation_operation(operation_id: UUID,request: Request,
        user: CurrentUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    from app.services.generation_lifecycle_service import cancel_operation
    from app.services.audit_service import log_audit
    tenant_id=get_tenant_id_from_header(request)
    await require_permission(db,tenant_id,user.id,'batches.manage')
    await service.read_operation(db,tenant_id,user.id,operation_id)
    await cancel_operation(db,tenant_id,operation_id)
    await log_audit(db,tenant_id=tenant_id,actor_user_id=user.id,action='generation.operation.cancelled',
        resource_type='generation_operation',resource_id=str(operation_id),metadata={})
    result=service.compact_operation(await service.read_operation(db,tenant_id,user.id,operation_id))
    await db.commit()
    return result


@router.post('/{operation_id}/retry',status_code=202,response_model=GenerationOperationRead)
async def retry_generation_operation(operation_id: UUID,request: Request,
        user: CurrentUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    from app.services.generation_lifecycle_service import retry_operation
    from app.services.feature_service import require_feature
    from app.services.audit_service import log_audit
    tenant_id=get_tenant_id_from_header(request)
    await require_permission(db,tenant_id,user.id,'batches.manage')
    await require_permission(db,tenant_id,user.id,'invitations.create')
    await service.read_operation(db,tenant_id,user.id,operation_id)
    row=(await db.execute(text('SELECT settings_snapshot FROM generation_operations WHERE tenant_id=:tid AND id=:id'),
        {'tid':str(tenant_id),'id':str(operation_id)})).scalar_one()
    if row['output_formats']:
        await require_permission(db,tenant_id,user.id,'invitations.export')
        await require_feature(db,tenant_id,'pdf_export')
    if row['require_rsvp']:
        await require_feature(db,tenant_id,'rsvp')
    await retry_operation(db,tenant_id,operation_id)
    await log_audit(db,tenant_id=tenant_id,actor_user_id=user.id,action='generation.operation.retried',
        resource_type='generation_operation',resource_id=str(operation_id),metadata={})
    result=service.compact_operation(await service.read_operation(db,tenant_id,user.id,operation_id))
    await db.commit()
    return result


@router.get('/{operation_id}/artifacts/{artifact_id}/download')
async def download_operation_artifact(operation_id:UUID,artifact_id:UUID,request:Request,
        user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    """Authenticated direct download. Keep the final chunk until integrity passes."""
    import hashlib
    import httpx
    from urllib.parse import quote
    from fastapi.responses import StreamingResponse
    from app.services import storage_service
    from app.services.feature_service import require_feature
    tenant=get_tenant_id_from_header(request)
    await service.read_operation(db,tenant,user.id,operation_id)
    await require_permission(db,tenant,user.id,'invitations.export')
    await require_feature(db,tenant,'pdf_export')
    artifact=(await db.execute(text("""SELECT kind,file_part,part_index,storage_path,byte_size,sha256 FROM generation_artifacts
        WHERE tenant_id=:tid AND operation_id=:oid AND id=:id AND status='verified' AND kind IN ('pdf','zip')"""),
        {'tid':str(tenant),'oid':str(operation_id),'id':str(artifact_id)})).mappings().first()
    if artifact is None:
        raise HTTPException(404,'الملف غير متاح')
    settings=get_settings()
    endpoint=settings.supabase_url.rstrip('/')+'/storage/v1/object/invitations/'+quote(artifact['storage_path'],safe='/')
    client=httpx.AsyncClient(timeout=60,follow_redirects=False,trust_env=False,verify=storage_service.storage_ssl_context())
    try:
        upstream=await client.send(client.build_request('GET',endpoint,headers={
            'Authorization':'Bearer '+settings.supabase_service_role_key,'apikey':settings.supabase_service_role_key}),stream=True)
        upstream.raise_for_status()
    except Exception:
        await client.aclose()
        raise HTTPException(503,'تعذر فتح الملف؛ أعد المحاولة')
    async def content():
        count=0
        digest=hashlib.sha256()
        pending=b''
        try:
            async for block in upstream.aiter_bytes(65536):
                count+=len(block)
                if count>artifact['byte_size']:
                    raise RuntimeError('Artifact exceeds verified size')
                digest.update(block)
                if pending:
                    yield pending
                pending=block
            if count!=artifact['byte_size'] or digest.hexdigest()!=artifact['sha256']:
                raise RuntimeError('Artifact integrity mismatch')
            if pending:
                yield pending
        finally:
            await upstream.aclose()
            await client.aclose()
    extension=artifact['kind']
    filename=f"invitations-{str(operation_id)[:8]}-{str(artifact_id)[:8]}.{extension}"
    return StreamingResponse(content(),media_type='application/pdf' if extension=='pdf' else 'application/zip',headers={
        'Content-Disposition':f'attachment; filename="{filename}"','Content-Length':str(artifact['byte_size']),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
