"""Atomic operation contract against a disposable, fully migrated PostgreSQL."""
import asyncio
import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.config import get_settings
from app.database import AsyncSessionLocal, AppSessionLocal
from app.models.generation_operation import GenerationOperationCreate
from app.services import generation_operation_service as service
from tests.auth_helpers import make_access_token

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_operations_enabled', True)


def quick_body(event, count=2):
    return {'event_id': str(event), 'mode': 'quick', 'source': 'count',
            'count': {'normal_count': count}, 'output_formats': []}


@pytest.mark.asyncio
async def test_contract_replay_and_conflict(db_session, org_world, client_factory):
    event, tenant = org_world['event_id'], org_world['requester_tenant']
    key = str(uuid4())
    async with client_factory(org_world['requester_user']) as client:
        headers = {'X-Tenant-ID': str(tenant), 'Idempotency-Key': key}
        first = await client.post('/api/v1/generation-operations', json=quick_body(event), headers=headers)
        assert first.status_code == 202, first.text
        replay = await client.post('/api/v1/generation-operations', json=quick_body(event), headers=headers)
        conflict = await client.post('/api/v1/generation-operations', json=quick_body(event, 3), headers=headers)
        status = await client.get(first.json()['status_url'], headers=headers)
    assert replay.status_code == 202, replay.text
    assert replay.json()['id'] == first.json()['id']
    assert replay.json()['replayed'] is True
    assert conflict.status_code == 409
    assert status.status_code == 200
    assert 'settings_snapshot' not in status.json()
    assert 'idempotency_key' not in status.json()
    for table in ['generation_operations','generation_imports','generation_outbox']:
        count = (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'), {'tid': str(tenant)})).scalar()
        assert count == 1
    assert (await db_session.execute(text('SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key=\'invitations_per_month\''), {'tid':str(tenant)})).scalar()==2


@pytest.mark.asyncio
async def test_queue_full_does_not_create_or_charge(db_session, org_world, client_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_queue_max_cards', 1)
    tenant = org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        response = await client.post('/api/v1/generation-operations', json=quick_body(org_world['event_id']),
            headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code == 429, response.text
    assert response.headers['retry-after']=='30'
    for table in ['generation_operations','generation_imports','generation_outbox','invitations','usage_counters']:
        assert (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'), {'tid':str(tenant)})).scalar()==0


@pytest_asyncio.fixture
async def committed_world(monkeypatch):
    # This test deliberately commits to an isolated DB so 100 independent HTTP
    # requests exercise the real application role, RLS and transaction boundary.
    import os
    from urllib.parse import urlparse
    name = urlparse(get_settings().database_url).path.lower()
    assert any(word in name for word in ('test','scratch','iso')), 'Never seed concurrency tests in production'
    tenant, user, event = uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as db:
        await db.execute(text("INSERT INTO auth.users(id,email,aud,role,email_confirmed_at,instance_id) VALUES(:id,:email,'authenticated','authenticated',now(),'00000000-0000-0000-0000-000000000000')"),
                         {'id':str(user),'email':f'{user}@example.test'})
        await db.execute(text("INSERT INTO profiles(id,full_name) VALUES(:id,'P1 concurrency actor') ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name"),{'id':str(user)})
        await db.execute(text("INSERT INTO tenants(id,name,slug,status) VALUES(:id,'P1 isolated',:slug,'active')"),{'id':str(tenant),'slug':f'p1-{tenant}'})
        await db.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'owner','active')"),{'tid':str(tenant),'uid':str(user)})
        await db.execute(text("INSERT INTO events(id,tenant_id,title,start_date,status) VALUES(:id,:tid,'P1 isolated event',now()+interval '7 days','draft')"),{'id':str(event),'tid':str(tenant)})
        await db.commit()
    from app import middleware as middleware_module
    monkeypatch.setattr(middleware_module.rate_limiter, 'hit', AsyncMock(return_value=True))
    # No dependency override: the API opens independent qentry_app connections.
    app.dependency_overrides.clear()
    return tenant,user,event


@pytest.mark.asyncio
async def test_100_concurrent_http_replays_create_one_operation_and_one_usage(committed_world):
    tenant, user, event = committed_world
    headers = {'Authorization':f'Bearer {make_access_token(user)}','X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',timeout=60) as client:
        async def request():
            return await client.post('/api/v1/generation-operations',json=quick_body(event,3),headers=headers)
        responses = await asyncio.gather(*[request() for _ in range(100)])
        # Admission deliberately applies backpressure before parsing. Drain the
        # burst before retrying rejected intents, rather than synchronizing a
        # second burst on every Retry-After interval.
        assert all(r.status_code in (202,429) for r in responses)
        rejected=[i for i,r in enumerate(responses) if r.status_code==429]
        if rejected:
            await asyncio.sleep(max(float(responses[i].headers['Retry-After']) for i in rejected))
        for i in rejected:
            responses[i]=await request()
    assert all(response.status_code==202 for response in responses), [(r.status_code,r.text[:150]) for r in responses if r.status_code!=202]
    assert len({response.json()['id'] for response in responses})==1
    async with AsyncSessionLocal() as db:
        for table,expected in [('generation_operations',1),('generation_imports',1),('generation_import_rows',3),('invitations',3),('batch_items',3),('generation_batches',1),('generation_outbox',1)]:
            count = (await db.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()
            assert count==expected, table
        usage = (await db.execute(text("SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':str(tenant)})).scalar()
        assert usage==3
        audits = (await db.execute(text("SELECT count(*) FROM audit_logs WHERE tenant_id=:tid AND action='generation.operation.accepted'"),{'tid':str(tenant)})).scalar()
        assert audits==1


@pytest.mark.asyncio
async def test_two_distinct_requests_cannot_take_last_event_place(committed_world):
    tenant,user,event=committed_world
    async with AsyncSessionLocal() as db:
        await db.execute(text('UPDATE events SET normal_quota=1 WHERE id=:id'),{'id':str(event)})
        await db.commit()
    headers={'Authorization':f'Bearer {make_access_token(user)}','X-Tenant-ID':str(tenant)}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        responses=await asyncio.gather(*[client.post('/api/v1/generation-operations',json=quick_body(event,1),headers={**headers,'Idempotency-Key':str(uuid4())}) for _ in range(2)])
    assert sorted(response.status_code for response in responses)==[202,400]
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text('SELECT count(*) FROM invitations WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==1
        assert (await db.execute(text("SELECT sum(value) FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':str(tenant)})).scalar()==1


@pytest.mark.asyncio
async def test_failure_after_usage_rolls_back_every_admission_row(db_session, org_world, client_factory, monkeypatch):
    async def fail_audit(*args, **kwargs):
        raise RuntimeError('isolated simulated final audit failure')
    monkeypatch.setattr(service, 'log_audit', fail_audit)
    tenant = org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        response = await client.post('/api/v1/generation-operations', json=quick_body(org_world['event_id']),
            headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code == 500
    for table in ['generation_operations','generation_imports','generation_import_rows','generation_batches','batch_items','generation_outbox','invitations','usage_counters']:
        assert (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==0, table


@pytest.mark.asyncio
async def test_creator_with_only_create_permission_needs_no_batch_or_export_permission(db_session, org_world, client_factory):
    user, role = uuid4(), uuid4()
    tenant = org_world['requester_tenant']
    await db_session.execute(text("INSERT INTO auth.users(id,email,aud,role,email_confirmed_at,instance_id) VALUES(:id,:email,'authenticated','authenticated',now(),'00000000-0000-0000-0000-000000000000')"),
        {'id':str(user),'email':f'{user}@example.test'})
    await db_session.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'member','active')"), {'tid':str(tenant),'uid':str(user)})
    await db_session.execute(text("INSERT INTO roles(id,tenant_id,name) VALUES(:id,:tid,'P1-create-only')"), {'id':str(role),'tid':str(tenant)})
    await db_session.execute(text("INSERT INTO role_permissions(role_id,permission_key) VALUES(:id,'invitations.create')"),{'id':str(role)})
    await db_session.execute(text('INSERT INTO membership_roles(tenant_id,user_id,role_id) VALUES(:tid,:uid,:rid)'),{'tid':str(tenant),'uid':str(user),'rid':str(role)})
    async with client_factory(user) as client:
        headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())}
        response=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id']),headers=headers)
        assert response.status_code==202, response.text
        status=await client.get(response.json()['status_url'],headers=headers)
        rows=await client.get(response.json()['status_url']+'/rows',headers=headers)
        exported=await client.post('/api/v1/generation-operations',json={**quick_body(org_world['event_id']),'output_formats':['pdf']},headers={**headers,'Idempotency-Key':str(uuid4())})
    assert status.status_code==200
    assert rows.status_code==403
    assert exported.status_code==403
    assert 'invitations.export' in exported.text


@pytest.mark.asyncio
async def test_designed_snapshot_keeps_original_elements_background_and_font(db_session, org_world, client_factory):
    import io,base64,json
    from PIL import Image
    template=uuid4();tenant=org_world['requester_tenant'];event=org_world['event_id']
    content=io.BytesIO();Image.new('RGB',(100,100),'white').save(content,format='PNG')
    reference='data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()
    await db_session.execute(text("INSERT INTO invite_templates(id,tenant_id,event_id,name,template_type,ticket_class,background_url) VALUES(:id,:tid,:eid,'Original','designed','normal',:bg)"),{'id':str(template),'tid':str(tenant),'eid':str(event),'bg':reference})
    await db_session.execute(text("INSERT INTO template_elements(template_id,element_type,data_key,static_content,font_family) VALUES(:id,'qr_code','invite.barcode_payload',NULL,'Amiri'),(:id,'custom_text',NULL,'Original text','Amiri')"),{'id':str(template)})
    request={'event_id':str(event),'mode':'designed','source':'names','templates':{'normal':str(template)},
             'rows':[{'guest_name':'Snapshot guest'}],'output_formats':[]}
    async with client_factory(org_world['requester_user']) as client:
        headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())}
        response=await client.post('/api/v1/generation-operations',json=request,headers=headers)
        assert response.status_code==202, response.text
        operation=response.json()['id']
        await db_session.execute(text("UPDATE invite_templates SET name='Changed',background_url=NULL WHERE id=:id"),{'id':str(template)})
        await db_session.execute(text("UPDATE template_elements SET static_content='Changed text' WHERE template_id=:id AND element_type='custom_text'"),{'id':str(template)})
        replay=await client.post('/api/v1/generation-operations',json=request,headers=headers)
        assert replay.json()['id']==operation
    row=(await db_session.execute(text('SELECT templates_snapshot FROM generation_operations WHERE id=:id'),{'id':operation})).mappings().one()
    snap=row['templates_snapshot']['normal']
    assert snap['template']['name']=='Original'
    assert snap['template']['background_url'].startswith('snapshot:')
    assert any(element['static_content']=='Original text' for element in snap['elements'])
    assert snap['fonts']['Amiri:normal']
    stored=(await db_session.execute(text('SELECT content FROM generation_snapshot_assets WHERE tenant_id=:tid AND sha256=:sha'),{'tid':str(tenant),'sha':snap['background_sha256']})).scalar()
    assert bytes(stored)==content.getvalue()
    assert hashlib.sha256(bytes(stored)).hexdigest()==snap['background_sha256']
    size=(await db_session.execute(text('SELECT SUM(octet_length(content)) FROM generation_snapshot_assets WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()
    tracked=(await db_session.execute(text("SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key='storage_bytes'"),{'tid':str(tenant)})).scalar()
    assert tracked==size

    # A frozen operation cannot be altered even by a privileged test session.
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("UPDATE generation_operations SET templates_snapshot='{}' WHERE id=:id"),{'id':operation})


@pytest.mark.asyncio
async def test_real_application_rls_hides_other_tenant_operation_and_assets(committed_world):
    tenant,user,event=committed_world
    body=GenerationOperationCreate(**quick_body(event))
    snapshot={'event':{'title':'P1 frozen'},'templates':{},'assets':{},'renderer_sha256':'0'*64}
    async with AppSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"),{'tid':str(tenant)})
        operation,_=await service.admit_operation(db,tenant,user,str(uuid4()),body,snapshot)
        await db.commit()
    async with AppSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"),{'tid':str(uuid4())})
        for table in ['generation_operations','generation_imports','generation_import_rows','generation_outbox','generation_operation_assets']:
            assert (await db.execute(text(f'SELECT count(*) FROM {table}'))).scalar()==0, table
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError) as denied:
            async with db.begin_nested():
                await db.execute(text("INSERT INTO generation_operation_assets(tenant_id,operation_id,asset_id,asset_key) VALUES(:tid,:oid,:aid,'foreign')"),{'tid':str(tenant),'oid':str(operation['id']),'aid':str(uuid4())})
        assert denied.value.orig.sqlstate=='42501'


@pytest.mark.asyncio
async def test_bulk_rows_keep_people_counts_and_original_excel_numbers(db_session,org_world,client_factory):
    tenant=org_world['requester_tenant']
    body={'event_id':str(org_world['event_id']),'source':'excel','mode':'quick','output_formats':[],
          'rows':[{'guest_name':'Arabic count','guest_count':'٣'},{'guest_name':'Second','guest_count':2,'ticket_class':'vip'}],
          'source_row_numbers':[2,9]}
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=body,headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
        assert response.status_code==202,response.text
        data=response.json()
        rows=await client.get(data['status_url']+'/rows?limit=1',headers={'X-Tenant-ID':str(tenant)})
    assert (data['cards_count'],data['people_count'],data['vip_people'],data['normal_people'])==(2,5,2,3)
    assert rows.json()['items'][0]['source_row_number']==2
    assert rows.json()['next_row']==2
    counts=(await db_session.execute(text('SELECT COUNT(*),SUM(guest_count) FROM invitations WHERE tenant_id=:tid'),{'tid':str(tenant)})).first()
    assert tuple(counts)==(2,5)


@pytest.mark.asyncio
async def test_tenant_keys_are_independent_and_foreign_parent_links_fail(db_session,org_world,client_factory):
    tenant_a=org_world['requester_tenant'];tenant_b=org_world['provider_tenant'];event_b=uuid4();key=str(uuid4())
    await db_session.execute(text("INSERT INTO events(id,tenant_id,title,start_date,status) VALUES(:id,:tid,'Second workspace',now(),'draft')"),{'id':str(event_b),'tid':str(tenant_b)})
    async with client_factory(org_world['requester_user']) as client:
        first=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],1),headers={'X-Tenant-ID':str(tenant_a),'Idempotency-Key':key})
    async with client_factory(org_world['provider_user']) as client:
        second=await client.post('/api/v1/generation-operations',json=quick_body(event_b,1),headers={'X-Tenant-ID':str(tenant_b),'Idempotency-Key':key})
    assert first.status_code==second.status_code==202
    assert first.json()['id']!=second.json()['id']
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError) as mismatch:
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO generation_batches(tenant_id,event_id,operation_id,part_index,count_total) VALUES(:tid,:eid,:oid,0,1)"),{'tid':str(tenant_a),'eid':str(org_world['event_id']),'oid':second.json()['id']})
    assert mismatch.value.orig.sqlstate=='23503'
    with pytest.raises(IntegrityError) as duplicate:
        async with db_session.begin_nested():
            await db_session.execute(text("INSERT INTO generation_batches(tenant_id,event_id,operation_id,part_index,count_total) VALUES(:tid,:eid,:oid,0,1)"),{'tid':str(tenant_a),'eid':str(org_world['event_id']),'oid':first.json()['id']})
    assert duplicate.value.orig.sqlstate=='23505'


@pytest.mark.asyncio
async def test_rsvp_contact_is_canonical_without_printing_and_feature_is_required(db_session,org_world,client_factory):
    tenant=org_world['requester_tenant'];event=org_world['event_id']
    await db_session.execute(text("INSERT INTO feature_flags(tenant_id,flag_key,enabled) VALUES(:tid,'rsvp',true) ON CONFLICT(tenant_id,flag_key) DO UPDATE SET enabled=true"),{'tid':str(tenant)})
    body={'event_id':str(event),'source':'names','mode':'quick','require_rsvp':True,'output_formats':[],
          'rows':[{'guest_name':'Contact test','metadata':{'custom_fields':{'guest.phone':'+967700000000'}}}]}
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=body,headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
        assert response.status_code==202,response.text
        await db_session.execute(text("UPDATE feature_flags SET enabled=false WHERE tenant_id=:tid AND flag_key='rsvp'"),{'tid':str(tenant)})
        denied=await client.post('/api/v1/generation-operations',json=body,headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert denied.status_code==403,denied.text
    row=(await db_session.execute(text('SELECT guest_phone,rsvp_status,status FROM invitations WHERE tenant_id=:tid'),{'tid':str(tenant)})).first()
    assert tuple(row)==('967700000000','pending','created')


@pytest.mark.asyncio
async def test_new_contract_is_off_until_durable_worker_is_ready(db_session,org_world,client_factory,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_operations_enabled',False)
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id']),headers={'X-Tenant-ID':str(org_world['requester_tenant']),'Idempotency-Key':str(uuid4())})
    assert response.status_code==503
    assert response.headers['retry-after']=='60'


@pytest.mark.asyncio
async def test_split_batches_are_all_durable_and_legacy_worker_cannot_render_snapshot(db_session,org_world,client_factory,monkeypatch):
    from app.services import batch_pipeline
    monkeypatch.setattr(get_settings(),'generation_batch_cards',1)
    tenant=org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],3),headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code==202,response.text
    operation=response.json()['id']
    result=await db_session.execute(text('SELECT id,part_index FROM generation_batches WHERE tenant_id=:tid AND operation_id=:oid ORDER BY part_index'),{'tid':str(tenant),'oid':operation})
    batches=result.fetchall()
    assert [row.part_index for row in batches]==[0,1,2]
    assert (await db_session.execute(text('SELECT count(*) FROM generation_outbox WHERE tenant_id=:tid AND operation_id=:oid'),{'tid':str(tenant),'oid':operation})).scalar()==3
    outcome=await batch_pipeline.run_batch_pipeline(db_session,batches[0].id)
    assert outcome=={'status':'queued','code':'DURABLE_WORKER_REQUIRED'}


@pytest.mark.asyncio
async def test_per_tenant_queue_limit_is_checked_before_usage(db_session,org_world,client_factory,monkeypatch):
    tenant=org_world['requester_tenant'];event=org_world['event_id']
    monkeypatch.setattr(get_settings(),'generation_tenant_max_operations',1)
    async with client_factory(org_world['requester_user']) as client:
        headers={'X-Tenant-ID':str(tenant)}
        first=await client.post('/api/v1/generation-operations',json=quick_body(event,1),headers={**headers,'Idempotency-Key':str(uuid4())})
        blocked=await client.post('/api/v1/generation-operations',json=quick_body(event,1),headers={**headers,'Idempotency-Key':str(uuid4())})
    assert first.status_code==202
    assert blocked.status_code==429 and blocked.headers['retry-after']=='30'
    assert (await db_session.execute(text("SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':str(tenant)})).scalar()==1


@pytest.mark.asyncio
async def test_global_operation_cap_is_atomic_and_does_not_double_count_child_batches(db_session,org_world,client_factory,monkeypatch):
    active=(await db_session.execute(text("SELECT (SELECT count(*) FROM generation_operations WHERE status IN ('queued','running','cancel_requested'))+(SELECT count(*) FROM generation_batches WHERE operation_id IS NULL AND status IN ('queued','generating_barcodes','rendering_images','generating_pdf','generating_zip'))"))).scalar()
    monkeypatch.setattr(get_settings(),'generation_queue_max_operations',int(active)+1)
    monkeypatch.setattr(get_settings(),'generation_batch_cards',1)
    tenant=org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        first=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],3),headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
        second=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],1),headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert first.status_code==202,first.text
    assert second.status_code==429 and second.headers['retry-after']=='30'
    assert (await db_session.execute(text("SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':str(tenant)})).scalar()==3


def test_database_logs_hide_admission_parameters():
    from app.database import engine,app_engine
    assert engine.sync_engine.hide_parameters is True
    assert app_engine.sync_engine.hide_parameters is True


@pytest.mark.asyncio
async def test_oversized_template_is_rejected_before_copying_assets_or_charging(db_session,org_world,client_factory,monkeypatch):
    from app.services import generation_snapshot_service as snapshots
    from unittest.mock import MagicMock
    tenant=org_world['requester_tenant'];template=uuid4()
    await db_session.execute(text("INSERT INTO invite_templates(id,tenant_id,event_id,name,template_type,ticket_class,background_url) VALUES(:id,:tid,:eid,'Too many elements','designed','normal','data:image/png;base64,unused')"),{'id':str(template),'tid':str(tenant),'eid':str(org_world['event_id'])})
    await db_session.execute(text("INSERT INTO template_elements(template_id,element_type) SELECT :id,'custom_text'::element_type FROM generate_series(1,201)"),{'id':str(template)})
    download=MagicMock()
    monkeypatch.setattr(snapshots.storage_service,'download_file',download)
    body={'event_id':str(org_world['event_id']),'mode':'designed','source':'names','rows':[{'guest_name':'Test'}],
          'templates':{'normal':str(template)},'output_formats':[]}
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=body,headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code==422,response.text
    assert '200' in response.text
    download.assert_not_called()
    assert (await db_session.execute(text('SELECT count(*) FROM usage_counters WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==0


@pytest.mark.asyncio
async def test_expired_asset_references_are_pinned_once_without_signed_url_http(db_session,org_world,client_factory,monkeypatch):
    import io
    from PIL import Image
    from unittest.mock import MagicMock
    from app.services import generation_snapshot_service as snapshots
    tenant=org_world['requester_tenant'];template=uuid4();event=org_world['event_id']
    image=io.BytesIO();Image.new('RGB',(10,10),'white').save(image,format='PNG')
    monkeypatch.setattr(snapshots.storage_service.settings,'supabase_url','https://storage.example')
    path=f'{tenant}/{event}/template.png'
    reference='https://storage.example/storage/v1/object/sign/invitations/'+path
    download=MagicMock(return_value=image.getvalue())
    monkeypatch.setattr(snapshots.storage_service,'download_file',download)
    await db_session.execute(text("INSERT INTO invite_templates(id,tenant_id,event_id,name,template_type,ticket_class,background_url) VALUES(:id,:tid,:eid,'Pinned','designed','normal',:bg)"),{'id':str(template),'tid':str(tenant),'eid':str(event),'bg':reference+'?token=expired-background'})
    await db_session.execute(text("INSERT INTO template_elements(template_id,element_type,static_content) VALUES(:id,'qr_code',NULL),(:id,'image',:ref),(:id,'image',:ref)"),{'id':str(template),'ref':reference+'?token=expired-image'})
    body={'event_id':str(event),'mode':'designed','source':'names','rows':[{'guest_name':'Test'}],
          'templates':{'normal':str(template)},'output_formats':[]}
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=body,headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code==202,response.text
    download.assert_called_once_with(path)
    assert (await db_session.execute(text('SELECT count(*) FROM generation_snapshot_assets WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==1
    assert (await db_session.execute(text("SELECT SUM(value) FROM usage_counters WHERE tenant_id=:tid AND key='storage_bytes'"),{'tid':str(tenant)})).scalar()==len(image.getvalue())


@pytest.mark.asyncio
async def test_outbox_concurrent_publishers_and_rollback_redelivery(committed_world):
    """Real row locks: broker ack plus lost DB commit is safely redeliverable."""
    from app.services.generation_dispatch_service import dispatch_one
    tenant, user, event = committed_world
    body = GenerationOperationCreate(**quick_body(event, 1))
    snapshot = {'event': {'title': 'Outbox isolated'}, 'templates': {},
                'assets': {}, 'renderer_sha256': '0'*64}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"), {'tid':str(tenant)})
        operation, _ = await service.admit_operation(db, tenant, user, str(uuid4()), body, snapshot)
        await db.commit()
    # Other committed admission tests deliberately leave work queued. Isolate
    # this global publisher test in the disposable database, without deleting it.
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_operations SET status='cancelled' WHERE id<>:id AND status IN ('queued','running')"), {'id':operation['id']})
        await db.commit()
    published = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_broker(payload):
        published.append(payload)
        entered.set()
        await release.wait()

    async with AsyncSessionLocal() as first:
        pending = asyncio.create_task(dispatch_one(first, slow_broker))
        await asyncio.wait_for(entered.wait(), 3)
        try:
            async with AsyncSessionLocal() as second:
                broker = AsyncMock()
                assert await dispatch_one(second, broker) == 'idle'
                broker.assert_not_awaited()
                await second.commit()
        finally:
            release.set()
        assert await pending == 'published'
        # Simulates death after Redis ack and before DB commit.
        await first.rollback()
    async with AsyncSessionLocal() as recovered:
        broker = AsyncMock()
        assert await dispatch_one(recovered, broker) == 'published'
        broker.assert_awaited_once_with(published[0])
        assert broker.call_args.args[0]['operation_id'] == str(operation['id'])
        await recovered.commit()
    async with AsyncSessionLocal() as last:
        broker = AsyncMock()
        assert await dispatch_one(last, broker) == 'idle'
        broker.assert_not_awaited()
    from app.services.generation_lease_service import claim_batch
    async def claim_independently():
        async with AsyncSessionLocal() as db:
            lease = await claim_batch(db, tenant, operation['id'], UUID(published[0]['batch_id']))
            await db.commit()
            return lease
    from uuid import UUID
    claims = await asyncio.gather(claim_independently(), claim_independently())
    assert sum(lease is not None for lease in claims) == 1
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_batches SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE operation_id=:id"), {'id':operation['id']})
        await db.commit()


@pytest.mark.asyncio
async def test_outbox_database_backoff_and_cancel_filter(db_session, org_world):
    from app.services.generation_dispatch_service import dispatch_one
    tenant, user, event = (org_world['requester_tenant'], org_world['requester_user'], org_world['event_id'])
    body = GenerationOperationCreate(**quick_body(event, 1))
    snapshot = {'event': {}, 'templates': {}, 'assets': {}, 'renderer_sha256': '0'*64}
    await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"), {'tid':str(tenant)})
    operation, _ = await service.admit_operation(db_session, tenant, user, str(uuid4()), body, snapshot)
    await db_session.execute(text("UPDATE generation_operations SET status='cancelled' WHERE id<>:id AND status IN ('queued','running')"), {'id':operation['id']})
    broker = AsyncMock(side_effect=ConnectionError('redis://private:secret@localhost'))
    assert await dispatch_one(db_session, broker) == 'deferred'
    row = (await db_session.execute(text('''SELECT attempts,last_error_code,published_at,
        available_at>now() AS deferred FROM generation_outbox WHERE operation_id=:id'''),
        {'id': operation['id']})).mappings().one()
    assert row['attempts'] == 1 and row['last_error_code'] == 'BROKER_UNAVAILABLE'
    assert row['published_at'] is None and row['deferred']
    await db_session.execute(text("UPDATE generation_outbox SET available_at=now() WHERE operation_id=:id"), {'id':operation['id']})
    await db_session.execute(text("UPDATE generation_operations SET status='cancel_requested' WHERE id=:id"), {'id':operation['id']})
    broker = AsyncMock()
    assert await dispatch_one(db_session, broker) == 'idle'
    broker.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_lease_fences_duplicate_expired_and_cancelled_worker(db_session, org_world):
    from app.services.generation_lease_service import claim_batch, lock_owned_batch, heartbeat
    tenant, user, event = org_world['requester_tenant'], org_world['requester_user'], org_world['event_id']
    await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"), {'tid':str(tenant)})
    operation, _ = await service.admit_operation(db_session, tenant, user, str(uuid4()),
        GenerationOperationCreate(**quick_body(event, 1)),
        {'event': {}, 'templates': {}, 'assets': {}, 'renderer_sha256':'0'*64})
    batch = (await db_session.execute(text('SELECT id FROM generation_batches WHERE operation_id=:id'), {'id':operation['id']})).scalar_one()
    lease = await claim_batch(db_session, tenant, operation['id'], batch)
    assert lease is not None and lease.attempt == 1
    assert await claim_batch(db_session, tenant, operation['id'], batch) is None
    assert await heartbeat(db_session, lease)
    await db_session.execute(text("UPDATE generation_batches SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"), {'id':batch})
    assert not await heartbeat(db_session, lease)
    replacement = await claim_batch(db_session, tenant, operation['id'], batch)
    assert replacement.attempt == 2 and replacement.owner != lease.owner
    assert not await lock_owned_batch(db_session, lease)
    assert await lock_owned_batch(db_session, replacement)
    await db_session.execute(text("UPDATE generation_operations SET status='cancel_requested' WHERE id=:id"), {'id':operation['id']})
    assert not await lock_owned_batch(db_session, replacement)
    assert not await heartbeat(db_session, replacement)


@pytest.mark.asyncio
async def test_operation_cancel_and_retry_http_contract(db_session,org_world,client_factory):
    tenant,event,user=org_world['requester_tenant'],org_world['event_id'],org_world['requester_user']
    headers={'X-Tenant-ID':str(tenant)}
    async with client_factory(user) as client:
        created=await client.post('/api/v1/generation-operations',json=quick_body(event,1),headers={**headers,'Idempotency-Key':str(uuid4())})
        assert created.status_code==202,created.text
        url=created.json()['status_url']
        cancelled=await client.post(url+'/cancel',headers=headers)
        assert cancelled.status_code==200,cancelled.text
        assert cancelled.json()['status']=='cancelled'
        assert (await client.post(url+'/cancel',headers=headers)).status_code==200
        assert (await client.post(url+'/retry',headers=headers)).status_code==409
        next_op=await client.post('/api/v1/generation-operations',json=quick_body(event,1),headers={**headers,'Idempotency-Key':str(uuid4())})
        oid=next_op.json()['id']
        await db_session.execute(text("UPDATE generation_batches SET status='failed' WHERE operation_id=:id"),{'id':oid})
        await db_session.execute(text("UPDATE batch_items SET render_status='failed' WHERE operation_id=:id"),{'id':oid})
        await db_session.execute(text("UPDATE generation_operations SET status='failed',cards_failed=1 WHERE id=:id"),{'id':oid})
        retried=await client.post(next_op.json()['status_url']+'/retry',headers=headers)
        assert retried.status_code==202,retried.text
        assert retried.json()['status']=='queued' and retried.json()['cards_failed']==0
        assert retried.json()['files_done']==0
    assert (await db_session.execute(text('SELECT count(*) FROM invitations WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==2
    assert (await db_session.execute(text("SELECT sum(value) FROM usage_counters WHERE tenant_id=:tid AND key='invitations_per_month'"),{'tid':str(tenant)})).scalar()==2


@pytest.mark.asyncio
@pytest.mark.parametrize('path,extra',[
    ('/api/v1/fast-invitations/generate',{'invitations':[{'guest_name':'cutover'}],'generate_pdf':False,'generate_zip':False}),
    ('/api/v1/fast-invitations/generate-by-count',{'count':1,'generate_pdf':False,'generate_zip':False}),
    ('/api/v1/batches/generate-designed-fast',{'template_id':str(uuid4()),'invitations':[{'guest_name':'cutover'}],'output_formats':[]}),
])
async def test_legacy_creation_cutover_rejects_before_creating_or_charging(db_session,org_world,client_factory,path,extra):
    tenant=org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post(path,json={'event_id':str(org_world['event_id']),**extra},headers={'X-Tenant-ID':str(tenant)})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='GENERATION_CONTRACT_UPGRADE'
    for table in ('invitations','generation_batches','usage_counters'):
        assert (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'),{'tid':str(tenant)})).scalar()==0


@pytest.mark.asyncio
async def test_hidden_qr_template_is_rejected_before_admission(db_session,org_world,client_factory):
    tenant,event=org_world['requester_tenant'],org_world['event_id']
    template=uuid4()
    await db_session.execute(text("INSERT INTO invite_templates(id,tenant_id,event_id,name,template_type,ticket_class,background_url) VALUES(:id,:tid,:eid,'Hidden QR','designed','normal','data:image/png;base64,')"),{'id':template,'tid':tenant,'eid':event})
    await db_session.execute(text("INSERT INTO template_elements(template_id,element_type,is_visible) VALUES(:id,'qr_code',false)"),{'id':template})
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json={
            'event_id':str(event),'mode':'designed','source':'count','count':{'normal_count':1},
            'templates':{'normal':str(template)},'output_formats':[]},
            headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())})
    assert response.status_code==422,response.text
    assert 'القالب غير مكتمل' in response.json()['detail']
    for table in ('generation_operations','invitations','usage_counters'):
        assert (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'),{'tid':tenant})).scalar()==0


@pytest.mark.asyncio
async def test_capabilities_report_enabled_only_when_worker_is_ready(db_session,org_world,client_factory,monkeypatch):
    settings=get_settings()
    headers={'X-Tenant-ID':str(org_world['requester_tenant'])}
    async with client_factory(org_world['requester_user']) as client:
        monkeypatch.setattr(settings,'generation_worker_enabled',False)
        off=await client.get('/api/v1/generation-operations/capabilities',headers=headers)
        monkeypatch.setattr(settings,'generation_worker_enabled',True)
        on=await client.get('/api/v1/generation-operations/capabilities',headers=headers)
    assert off.status_code==200 and off.json()['enabled'] is False
    assert on.json()['enabled'] is True
    assert on.json()['max_cards']==settings.generation_operation_max_cards
    assert set(on.json())=={'contract_version','enabled','max_cards','max_people_per_card','output_formats','drafts_enabled'}


@pytest.mark.asyncio
async def test_status_reports_expected_files_for_read_and_list(db_session,org_world,client_factory):
    headers={'X-Tenant-ID':str(org_world['requester_tenant']),'Idempotency-Key':str(uuid4())}
    async with client_factory(org_world['requester_user']) as client:
        created=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],2),headers=headers)
        read=await client.get(created.json()['status_url'],headers=headers)
        listing=await client.get('/api/v1/generation-operations',params={'event_id':str(org_world['event_id'])},headers=headers)
    assert created.json()['files_expected']==0 and read.json()['files_expected']==0
    assert listing.json()['items'][0]['files_expected']==0


def test_files_expected_is_derived_from_the_frozen_snapshot_on_admission_rows():
    row={'id':uuid4(),'settings_snapshot':{'output_formats':['pdf','zip']}}
    assert service.compact_operation(row)['files_expected']==2
    assert service.compact_operation({'id':uuid4(),'files_expected':1})['files_expected']==1


@pytest.mark.asyncio
async def test_list_filters_by_status_on_the_server_and_pages_by_cursor(db_session,org_world,client_factory):
    tenant,event=org_world['requester_tenant'],org_world['event_id']
    async with client_factory(org_world['requester_user']) as client:
        ids=[]
        for _ in range(3):
            headers={'X-Tenant-ID':str(tenant),'Idempotency-Key':str(uuid4())}
            created=await client.post('/api/v1/generation-operations',json=quick_body(event,1),headers=headers)
            assert created.status_code==202,created.text
            ids.append(created.json()['id'])
        await db_session.execute(text("UPDATE generation_operations SET status='failed' WHERE id=:id"),{'id':ids[0]})
        headers={'X-Tenant-ID':str(tenant)}
        failed=await client.get('/api/v1/generation-operations',params={'event_id':str(event),'status':'failed'},headers=headers)
        active=await client.get('/api/v1/generation-operations',params=[('event_id',str(event)),('status','queued'),('status','running')],headers=headers)
        page=await client.get('/api/v1/generation-operations',params={'event_id':str(event),'limit':2},headers=headers)
        invalid=await client.get('/api/v1/generation-operations',params={'status':'nonsense'},headers=headers)
    assert [o['id'] for o in failed.json()['items']]==[ids[0]]
    assert {o['id'] for o in active.json()['items']}=={ids[1],ids[2]}
    assert len(page.json()['items'])==2 and page.json()['next_cursor']
    assert invalid.status_code==422


@pytest.mark.asyncio
async def test_card_ceiling_error_has_one_stable_shape(db_session,org_world,client_factory,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_operation_max_cards',3)
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-operations',json=quick_body(org_world['event_id'],4),
            headers={'X-Tenant-ID':str(org_world['requester_tenant']),'Idempotency-Key':str(uuid4())})
    assert response.status_code==413
    detail=response.json()['detail']
    assert detail['code']=='MAX_CARDS_EXCEEDED' and detail['max_cards']==3 and '3' in detail['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('snapshot,expected',[
    ('{"output_formats":["pdf","zip"]}',2),
    ('{"output_formats":[]}',0),
    ('{}',0),                          # P1-era row without the key
    ('{"output_formats":null}',0),     # JSON null is not SQL NULL; must not raise
    ('{"output_formats":"pdf"}',0),    # malformed scalar must not break the whole listing
])
async def test_files_expected_tolerates_legacy_or_malformed_snapshots(db_session,snapshot,expected):
    column=service.SUMMARY_COLUMNS.split(',')[-1].strip().strip('"')
    assert column.endswith('AS files_expected')
    got=(await db_session.execute(text(f"SELECT {column} FROM (SELECT CAST(:s AS jsonb) AS settings_snapshot) t"),{'s':snapshot})).scalar()
    assert got==expected
