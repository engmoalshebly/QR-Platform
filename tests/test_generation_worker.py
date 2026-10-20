"""P2 consumer with real PostgreSQL and real image/PDF/ZIP, isolated object store."""
import asyncio
import hashlib
import io
import zipfile
from unittest.mock import AsyncMock
from uuid import UUID,uuid4
import pytest
import pytest_asyncio
from sqlalchemy import text
from PIL import Image
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.generation_operation import GenerationOperationCreate
from app.services import generation_operation_service as admission, generation_worker_service as worker
from app.services.generation_snapshot_service import prepare_snapshot
from app.services.generation_lifecycle_service import retry_operation,cancel_operation,recover_operations
from tests.test_generation_operations import committed_world  # reusable isolated committed tenant fixture

pytestmark=pytest.mark.integration


@pytest_asyncio.fixture
async def world(committed_world,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_worker_enabled',True)
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO feature_flags(tenant_id,flag_key,enabled) VALUES(:tid,'pdf_export',true) ON CONFLICT(tenant_id,flag_key) DO UPDATE SET enabled=true"),{'tid':committed_world[0]})
        await db.commit()
    import tempfile,os
    scratch=tempfile.TemporaryDirectory(prefix='.p3-work-',dir=os.getcwd())
    monkeypatch.setattr(get_settings(),'generation_workspace_dir',scratch.name)
    blobs={}
    def upload(path,content,mime):
        blobs[path]=bytes(content)
        return path
    monkeypatch.setattr(worker.storage,'upload_file',upload)
    monkeypatch.setattr(worker.storage,'download_file',lambda path:blobs[path])
    monkeypatch.setattr(worker.storage,'upload_disk_file',lambda path,file,mime:upload(path,file.read_bytes(),mime))
    def verify(path,size,digest):
        assert len(blobs[path])==size and hashlib.sha256(blobs[path]).hexdigest()==digest
    monkeypatch.setattr(worker.storage,'verify_disk_object',verify)
    monkeypatch.setattr(worker.storage,'get_signed_url',lambda path,expires:'https://storage.invalid/'+path)
    yield (*committed_world,blobs)
    scratch.cleanup()
    # The disposable DB is shared between tests; terminalize this test's work.
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_operations SET status='cancelled' WHERE tenant_id=:tid"),{'tid':committed_world[0]})
        await db.execute(text('UPDATE generation_batches SET lease_owner=NULL,lease_expires_at=NULL WHERE tenant_id=:tid'),{'tid':committed_world[0]})
        await db.commit()


async def admit(world,formats=('pdf','zip'),count=2,designed=False):
    tenant,user,event,_=world
    data={'event_id':str(event),'mode':'quick','source':'count','count':{'normal_count':count},'output_formats':list(formats)}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_tenant_id',:id,false)"),{'id':str(tenant)})
        if designed:
            import base64
            image=io.BytesIO();Image.new('RGB',(300,400),'white').save(image,'PNG')
            template=uuid4()
            await db.execute(text('''INSERT INTO invite_templates(id,tenant_id,event_id,name,template_type,ticket_class,width_px,height_px,background_url)
                VALUES(:id,:tid,:eid,'Frozen P2','designed','normal',300,400,:url)'''),
                {'id':template,'tid':tenant,'eid':event,'url':'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()})
            await db.execute(text("""INSERT INTO template_elements(template_id,element_type,x,y,width,height,z_index,data_key)
                VALUES(:id,'qr_code',0.1,0.1,0.5,0.4,0,'invite.barcode_payload')"""),{'id':template})
            await db.execute(text("""INSERT INTO template_elements(template_id,element_type,x,y,width,height,z_index,static_content,font_family,font_size,font_weight)
                VALUES(:id,'custom_text',0.1,0.7,0.8,0.15,1,'مرحبا','Amiri',16,'normal')"""),{'id':template})
            data.update(mode='designed',templates={'normal':str(template)})
        body=GenerationOperationCreate(**data)
        snapshot=await prepare_snapshot(db,tenant,body)
        operation,_=await admission.admit_operation(db,tenant,user,str(uuid4()),body,snapshot)
        batch=(await db.execute(text('SELECT id FROM generation_batches WHERE operation_id=:id ORDER BY part_index LIMIT 1'),{'id':operation['id']})).scalar_one()
        await db.commit()
    return operation['id'],batch


async def state(oid):
    async with AsyncSessionLocal() as db:
        return dict((await db.execute(text('SELECT * FROM generation_operations WHERE id=:id'),{'id':oid})).mappings().one())


@pytest.mark.asyncio
@pytest.mark.parametrize('designed',[False,True])
async def test_complete_real_outputs_and_duplicate_delivery(world,designed):
    oid,bid=await admit(world,designed=designed)
    if designed:
        # The worker must not load the mutable template again.
        async with AsyncSessionLocal() as db:
            await db.execute(text('UPDATE invite_templates SET background_url=NULL WHERE tenant_id=:tid'),{'tid':world[0]})
            await db.execute(text('DELETE FROM template_elements WHERE template_id IN (SELECT id FROM invite_templates WHERE tenant_id=:tid)'),{'tid':world[0]})
            await db.commit()
    result=await worker.execute_batch(world[0],oid,bid)
    assert result=={'status':'ready'},result
    data=await state(oid)
    assert (data['status'],data['cards_done'],data['cards_failed'],data['files_done'],data['files_failed'])==('completed',2,0,2,0)
    before=dict(world[3])
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'not_claimed'}
    assert world[3]==before
    async with AsyncSessionLocal() as db:
        artifacts=(await db.execute(text("SELECT * FROM generation_artifacts WHERE operation_id=:id ORDER BY kind"),{'id':oid})).mappings().all()
        coverage=(await db.execute(text('SELECT count(*) FROM generation_artifact_items WHERE operation_id=:id'),{'id':oid})).scalar()
        assert coverage==4
        assert (await db.execute(text('SELECT count(*) FROM invitations WHERE generation_operation_id=:id'),{'id':oid})).scalar()==2
    assert len(artifacts)==2
    for artifact in artifacts:
        content=world[3][artifact['storage_path']]
        assert hashlib.sha256(content).hexdigest()==artifact['sha256']
        if artifact['kind']=='pdf':
            assert content.startswith(b'%PDF')
        else:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                assert len(archive.namelist())==2
                for name in archive.namelist():
                    Image.open(io.BytesIO(archive.read(name))).verify()


@pytest.mark.asyncio
async def test_retry_pdf_only_reuses_cards_and_preserves_invitation_usage(world,monkeypatch):
    oid,bid=await admit(world)
    original=worker.render.pdf
    monkeypatch.setattr(worker.render,'pdf',lambda *args: (_ for _ in ()).throw(ValueError('test PDF failure')))
    failed=await worker.execute_batch(world[0],oid,bid)
    assert failed['code']=='PDF_FAILED'
    data=await state(oid)
    assert data['status']=='partial' and data['cards_done']==2 and data['files_failed']==2
    async with AsyncSessionLocal() as db:
        before=(await db.execute(text("SELECT value FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':world[0]})).scalar()
        paths=(await db.execute(text('SELECT stage_results FROM batch_items WHERE operation_id=:id ORDER BY id'),{'id':oid})).scalars().all()
        await db.execute(text("SELECT set_config('app.current_tenant_id',:id,false)"),{'id':str(world[0])})
        await retry_operation(db,world[0],oid)
        await db.commit()
    monkeypatch.setattr(worker.render,'pdf',original)
    monkeypatch.setattr(worker.render,'barcode',lambda *args: (_ for _ in ()).throw(AssertionError('barcode must not repeat')))
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    data=await state(oid)
    assert data['status']=='completed' and data['files_done']==2 and data['files_failed']==0
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT value FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':world[0]})).scalar()==before
        assert (await db.execute(text('SELECT stage_results FROM batch_items WHERE operation_id=:id ORDER BY id'),{'id':oid})).scalars().all()==paths
        assert (await db.execute(text('SELECT execution_attempt FROM generation_batches WHERE id=:id'),{'id':bid})).scalar()==2


@pytest.mark.asyncio
async def test_cancel_during_upload_cannot_publish_result(world,monkeypatch):
    oid,bid=await admit(world,formats=())
    original=worker._save_blob
    async def upload_and_cancel(*args):
        result=await original(*args)
        async with AsyncSessionLocal() as db:
            await cancel_operation(db,world[0],oid)
            await db.commit()
        return result
    monkeypatch.setattr(worker,'_save_blob',upload_and_cancel)
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ownership_lost'}
    data=await state(oid)
    assert data['status']=='cancelled' and data['cards_done']==0
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text('SELECT count(*) FROM generation_artifacts WHERE operation_id=:id'),{'id':oid})).scalar()==0
        assert (await db.execute(text("SELECT count(*) FROM batch_items WHERE operation_id=:id AND stage_results<>'{}'::jsonb"),{'id':oid})).scalar()==0


@pytest.mark.asyncio
async def test_storage_transient_failure_is_bounded_and_recoverable(world,monkeypatch):
    oid,bid=await admit(world,formats=())
    monkeypatch.setattr(worker.storage,'upload_file',lambda *args: (_ for _ in ()).throw(ConnectionError('private credentials')))
    for _ in range(3):
        result=await worker.execute_batch(world[0],oid,bid)
        assert result['code']=='STORAGE_UNAVAILABLE'
    data=await state(oid)
    assert data['status']=='failed' and data['cards_failed']==2
    assert 'credentials' not in data['error_message']
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'not_claimed'}


@pytest.mark.asyncio
async def test_crashed_worker_recovery_invalidates_owner_and_requeues_outbox(world):
    from app.services.generation_lease_service import claim_batch,lock_owned_batch
    oid,bid=await admit(world,formats=())
    async with AsyncSessionLocal() as db:
        lease=await claim_batch(db,world[0],oid,bid)
        await db.execute(text("UPDATE generation_batches SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"),{'id':bid})
        await db.execute(text('UPDATE generation_outbox SET published_at=now() WHERE operation_id=:id'),{'id':oid})
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await recover_operations(db)>=1
        assert not await lock_owned_batch(db,lease)
        assert (await db.execute(text('SELECT published_at FROM generation_outbox WHERE operation_id=:id'),{'id':oid})).scalar() is None
        await db.commit()
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}


@pytest.mark.asyncio
async def test_never_claimed_batch_stops_republishing_and_can_be_retried(world,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_republish_max',3)
    oid,bid=await admit(world,formats=())
    async def stale(attempts):
        async with AsyncSessionLocal() as db:
            # The updated_at trigger would reset the age; replica mode skips it for this fixture only.
            await db.execute(text("SET LOCAL session_replication_role=replica"))
            await db.execute(text("UPDATE generation_batches SET updated_at=clock_timestamp()-interval '2 minutes' WHERE id=:id"),{'id':bid})
            await db.execute(text('UPDATE generation_outbox SET published_at=now(),attempts=:n WHERE operation_id=:id'),{'id':oid,'n':attempts})
            await db.commit()
    await stale(2)
    async with AsyncSessionLocal() as db:
        assert await recover_operations(db)>=1
        await db.commit()
    assert (await state(oid))['status']!='failed'  # below the cap: republished, still queued
    await stale(3)
    async with AsyncSessionLocal() as db:
        assert await recover_operations(db)>=1
        await db.commit()
    data=await state(oid)
    assert data['status']=='failed' and data['error_code']=='DISPATCH_STALLED'
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_tenant_id',:id,false)"),{'id':str(world[0])})
        await retry_operation(db,world[0],oid)
        assert (await db.execute(text('SELECT attempts FROM generation_outbox WHERE operation_id=:id'),{'id':oid})).scalar()==0
        await db.commit()
    assert (await state(oid))['status']=='queued'


@pytest.mark.asyncio
async def test_permission_revocation_prevents_render_and_files(world,monkeypatch):
    oid,bid=await admit(world)
    async with AsyncSessionLocal() as db:
        replacement=uuid4()
        await db.execute(text("INSERT INTO auth.users(id,email,aud,role,email_confirmed_at,instance_id) VALUES(:id,:email,'authenticated','authenticated',now(),'00000000-0000-0000-0000-000000000000')"),{'id':replacement,'email':f'{replacement}@example.test'})
        await db.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'owner','active')"),{'tid':world[0],'uid':replacement})
        await db.execute(text("UPDATE memberships SET status='disabled' WHERE tenant_id=:tid AND user_id=:uid"),{'tid':world[0],'uid':world[1]})
        await db.commit()
    render_spy=AsyncMock()
    monkeypatch.setattr(worker,'_save_blob',render_spy)
    result=await worker.execute_batch(world[0],oid,bid)
    assert result['code']=='AUTHORIZATION_CHANGED'
    render_spy.assert_not_awaited()
    assert not world[3]


@pytest.mark.asyncio
async def test_zip_retry_keeps_verified_pdf_and_cards(world,monkeypatch):
    oid,bid=await admit(world)
    from app.services.generation_export_service import PartBuilder
    original=PartBuilder.add_images
    monkeypatch.setattr(PartBuilder,'add_images',lambda *args: (_ for _ in ()).throw(ValueError('ZIP error')))
    result=await worker.execute_batch(world[0],oid,bid)
    assert result['code']=='ZIP_FAILED'
    data=await state(oid)
    assert data['files_done']==1 and data['files_failed']==1 and data['status']=='partial'
    async with AsyncSessionLocal() as db:
        before=(await db.execute(text("SELECT storage_path FROM generation_artifacts WHERE operation_id=:id AND kind='pdf'"),{'id':oid})).scalar_one()
        await db.execute(text("SELECT set_config('app.current_tenant_id',:id,false)"),{'id':str(world[0])})
        await retry_operation(db,world[0],oid)
        await db.commit()
    monkeypatch.setattr(PartBuilder,'add_images',original)
    monkeypatch.setattr(worker.render,'pdf',lambda *args: (_ for _ in ()).throw(AssertionError('PDF must not repeat')))
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT storage_path FROM generation_artifacts WHERE operation_id=:id AND kind='pdf'"),{'id':oid})).scalar_one()==before
    assert (await state(oid))['files_done']==2


@pytest.mark.asyncio
async def test_corrupt_upload_is_not_published(world,monkeypatch):
    oid,bid=await admit(world,formats=())
    monkeypatch.setattr(worker.storage,'download_file',lambda path:b'corrupted object')
    result=await worker.execute_batch(world[0],oid,bid)
    assert result['code']=='STORAGE_INTEGRITY'
    assert (await state(oid))['cards_done']==0
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT count(*) FROM batch_items WHERE operation_id=:id AND barcode_status='done'"),{'id':oid})).scalar()==0


@pytest.mark.asyncio
@pytest.mark.parametrize('missing',[False,True])
async def test_damaged_checkpoint_regenerates_only_affected_card(world,monkeypatch,missing):
    oid,bid=await admit(world)
    original_pdf=worker.render.pdf
    monkeypatch.setattr(worker.render,'pdf',lambda *args: (_ for _ in ()).throw(ValueError('PDF fails once')))
    assert (await worker.execute_batch(world[0],oid,bid))['code']=='PDF_FAILED'
    async with AsyncSessionLocal() as db:
        first=(await db.execute(text("SELECT stage_results->'barcode'->>'path' FROM batch_items WHERE operation_id=:id ORDER BY id LIMIT 1"),{'id':oid})).scalar_one()
        await db.execute(text("SELECT set_config('app.current_tenant_id',:id,false)"),{'id':str(world[0])})
        await retry_operation(db,world[0],oid)
        await db.commit()
    if missing:
        del world[3][first]
    else:
        world[3][first]=b'damaged'
    monkeypatch.setattr(worker.render,'pdf',original_pdf)
    result=await worker.execute_batch(world[0],oid,bid)
    assert result['code']==('CHECKPOINT_MISSING' if missing else 'CHECKPOINT_INTEGRITY')
    assert (await state(oid))['cards_done']==1
    original_barcode=worker.render.barcode
    calls=[]
    def generate_once(*args):
        calls.append(args[0]['id'])
        return original_barcode(*args)
    monkeypatch.setattr(worker.render,'barcode',generate_once)
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    assert len(calls)==1
    assert (await state(oid))['cards_done']==2


@pytest.mark.asyncio
async def test_export_parts_have_exact_coverage_and_separate_file_counters(world,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_export_max_pages',1)
    oid,bid=await admit(world,count=30)
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    data=await state(oid)
    assert (data['cards_done'],data['files_done'],data['files_failed'])==(30,4,0)
    async with AsyncSessionLocal() as db:
        parts=(await db.execute(text('SELECT id,kind,file_part FROM generation_artifacts WHERE operation_id=:id ORDER BY kind,file_part'),{'id':oid})).mappings().all()
        assert [(p['kind'],p['file_part']) for p in parts]==[('pdf',0),('pdf',1),('zip',0),('zip',1)]
        for kind in ('pdf','zip'):
            coverage=(await db.execute(text('''SELECT count(*),count(DISTINCT ai.source_row_id) FROM generation_artifact_items ai
                JOIN generation_artifacts a ON a.id=ai.artifact_id AND a.tenant_id=ai.tenant_id
                WHERE a.operation_id=:id AND a.kind=:kind'''),{'id':oid,'kind':kind})).one()
            assert tuple(coverage)==(30,30)


@pytest.mark.asyncio
async def test_direct_download_streams_verified_private_file(world,monkeypatch):
    import httpx
    from httpx import AsyncClient,ASGITransport
    from unittest.mock import MagicMock
    from app.main import app
    from tests.auth_helpers import make_access_token
    oid,bid=await admit(world,formats=('pdf',))
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    async with AsyncSessionLocal() as db:
        artifact=(await db.execute(text("SELECT id,storage_path FROM generation_artifacts WHERE operation_id=:id"),{'id':oid})).mappings().one()
    payload=world[3][artifact['storage_path']]
    upstream=httpx.Response(200,content=payload,request=httpx.Request('GET','https://storage.invalid/object'))
    remote=MagicMock()
    remote.send=AsyncMock(return_value=upstream)
    remote.aclose=AsyncMock()
    remote.build_request.return_value=httpx.Request('GET','https://storage.invalid/object')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:remote)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get(f'/api/v1/generation-operations/{oid}/artifacts/{artifact["id"]}/download',headers={
            'Authorization':'Bearer '+make_access_token(world[1]),'X-Tenant-ID':str(world[0])})
    assert response.status_code==200,response.text
    assert response.content==payload
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['cache-control']=='no-store'


@pytest.mark.asyncio
async def test_orphan_cleanup_removes_only_unpublished_expired_objects(world,monkeypatch):
    from app.services import generation_object_service as objects
    oid,bid=await admit(world,formats=())
    original=worker._save_blob
    async def cancelled(*args):
        result=await original(*args)
        async with AsyncSessionLocal() as db:
            await cancel_operation(db,world[0],oid)
            await db.commit()
        return result
    monkeypatch.setattr(worker,'_save_blob',cancelled)
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ownership_lost'}
    assert len(world[3])==1
    deleted=[]
    def delete(path):
        deleted.append(path)
        world[3].pop(path,None)
        return True
    monkeypatch.setattr(worker.storage,'delete_file',delete)
    async with AsyncSessionLocal() as db:
        assert await objects.cleanup_orphans(db)==0
        await db.execute(text("UPDATE generation_storage_objects SET created_at=now()-interval '2 days' WHERE operation_id=:id"),{'id':oid})
        assert await objects.cleanup_orphans(db)==1
        await db.commit()
    assert len(deleted)==1 and not world[3]
    # Referenced objects survive the same sweep even after their lease ended.
    monkeypatch.setattr(worker,'_save_blob',original)
    oid,bid=await admit(world,formats=())
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_storage_objects SET created_at=now()-interval '2 days' WHERE operation_id=:id"),{'id':oid})
        assert await objects.cleanup_orphans(db)==0
        await db.commit()
    assert len(world[3])==2


@pytest.mark.asyncio
async def test_storage_is_reserved_before_external_upload(world,monkeypatch):
    from fastapi import HTTPException
    from app.services import feature_service
    oid,bid=await admit(world,formats=())
    monkeypatch.setattr(feature_service,'require_storage_for_upload',AsyncMock(side_effect=HTTPException(429,'storage full')))
    result=await worker.execute_batch(world[0],oid,bid)
    assert result['status']=='failed'
    assert not world[3]
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text('SELECT count(*) FROM generation_storage_objects WHERE operation_id=:id'),{'id':oid})).scalar()==0


@pytest.mark.asyncio
async def test_artifact_feed_exposes_parts_and_coverage_counts(world,monkeypatch):
    from httpx import AsyncClient,ASGITransport
    from app.main import app
    from tests.auth_helpers import make_access_token
    monkeypatch.setattr(get_settings(),'generation_export_max_pages',1)
    oid,bid=await admit(world,count=26,formats=('pdf',))
    assert await worker.execute_batch(world[0],oid,bid)=={'status':'ready'}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get(f'/api/v1/generation-operations/{oid}/artifacts',headers={
            'Authorization':'Bearer '+make_access_token(world[1]),'X-Tenant-ID':str(world[0])})
    assert response.status_code==200,response.text
    assert [(item['file_part'],item['cards_count']) for item in response.json()['items']]==[(0,25),(1,1)]
    assert all(item['batch_id']==str(bid) for item in response.json()['items'])
    assert all('storage_path' not in item for item in response.json()['items'])


async def second_world():
    """Another committed tenant in the disposable DB, shaped like ``committed_world``."""
    tenant,user,event=uuid4(),uuid4(),uuid4()
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO auth.users(id,email,aud,role,email_confirmed_at,instance_id) VALUES(:id,:email,'authenticated','authenticated',now(),'00000000-0000-0000-0000-000000000000')"),{'id':str(user),'email':f'{user}@example.test'})
        await db.execute(text("INSERT INTO profiles(id,full_name) VALUES(:id,'fairness actor') ON CONFLICT(id) DO NOTHING"),{'id':str(user)})
        await db.execute(text("INSERT INTO tenants(id,name,slug,status) VALUES(:id,'fairness',:slug,'active')"),{'id':str(tenant),'slug':f'fair-{tenant}'})
        await db.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'owner','active')"),{'tid':str(tenant),'uid':str(user)})
        await db.execute(text("INSERT INTO events(id,tenant_id,title,start_date,status) VALUES(:id,:tid,'fairness event',now()+interval '7 days','draft')"),{'id':str(event),'tid':str(tenant)})
        await db.commit()
    return tenant,user,event,{}


@pytest.mark.asyncio
async def test_dispatch_window_interleaves_tenants_instead_of_fifo(world,monkeypatch):
    from app.services.generation_dispatch_service import dispatch_one
    monkeypatch.setattr(get_settings(),'generation_dispatch_window',2)
    other=await second_world()
    noisy=[await admit(world,formats=(),count=1) for _ in range(3)]  # tenant A queues first
    quiet=await admit(other,formats=(),count=1)                       # tenant B arrives last
    mine={oid for oid,_ in noisy}|{quiet[0]}
    async with AsyncSessionLocal() as db:  # isolate from other tests' leftovers in the disposable DB
        await db.execute(text("UPDATE generation_operations SET status='cancelled' WHERE id<>ALL(CAST(:ids AS uuid[]))"),{'ids':[str(i) for i in mine]})
        await db.commit()
    seen=[]
    async def publish(payload):
        seen.append(payload['operation_id'])
    async def tick():
        async with AsyncSessionLocal() as db:
            status=await dispatch_one(db,publish)
            await db.commit()
            return status
    assert await tick()=='published' and seen[0]==str(noisy[0][0])
    assert await tick()=='published' and seen[1]==str(quiet[0])   # B jumps ahead of A's 2nd/3rd
    assert await tick()=='idle'                                    # window of 2 is full: backpressure
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_operations SET status='cancelled' WHERE id=:id"),{'id':quiet[0]})
        await db.commit()
    assert await tick()=='published' and seen[2]==str(noisy[1][0])
