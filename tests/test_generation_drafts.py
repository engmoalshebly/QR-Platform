from uuid import uuid4
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_draft_owner_revision_expiry_and_event_scope(db_session, org_world, client_factory):
    w = org_world
    headers = {'X-Tenant-ID': str(w['requester_tenant'])}
    path = f"/api/v1/generation-drafts/{w['event_id']}/quick"
    async with client_factory(w['requester_user']) as client:
        empty = await client.get(path, headers=headers)
        assert empty.status_code == 200 and empty.json()['revision'] == 0
        rows = [{'guest_name': 'ضيف', 'invitation_count':1, 'ticket_class':'normal', 'custom_fields': {'email': 'guest@example.com'}}]
        saved = await client.put(path, headers=headers, json={'revision': 0, 'rows': rows})
        assert saved.status_code == 200 and saved.json()['revision'] == 1
        assert (await client.get(path, headers=headers)).json()['rows'] == rows
        conflict = await client.put(path, headers=headers, json={'revision': 0, 'rows': []})
        assert conflict.status_code == 409
        saved = await client.put(path, headers=headers, json={'revision': 1, 'rows': []})
        assert saved.status_code == 200 and saved.json()['revision'] == 2
        foreign = await client.get(f'/api/v1/generation-drafts/{uuid4()}/quick', headers=headers)
        assert foreign.status_code == 404
        too_many = await client.put(path, headers=headers, json={'revision': 2, 'rows': [{}] * 1001})
        assert too_many.status_code == 422
        await db_session.execute(text('UPDATE generation_drafts SET expires_at=now()-interval \'1 second\' WHERE event_id=:eid'), {'eid':w['event_id']})
        assert (await client.get(path, headers=headers)).json()['revision'] == 0
        from app.services.generation_upload_service import cleanup_expired_uploads
        await cleanup_expired_uploads(db_session)
        assert (await db_session.execute(text('SELECT count(*) FROM generation_drafts WHERE event_id=:eid'), {'eid':w['event_id']})).scalar() == 0
        assert (await client.put(path, headers=headers, json={'revision':0,'rows':rows})).status_code == 200
    async with client_factory(w['provider_user']) as client:
        denied = await client.get(path, headers={'X-Tenant-ID': str(w['provider_tenant'])})
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_drafts_isolate_owners_in_same_tenant_and_accept_bounded_large_list(db_session, org_world, client_factory):
    w = org_world
    await db_session.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'owner','active')"), {'tid':w['requester_tenant'],'uid':w['provider_user']})
    headers = {'X-Tenant-ID': str(w['requester_tenant'])}
    path = f"/api/v1/generation-drafts/{w['event_id']}/designed"
    rows = [{'guest_name': f'ضيف {i}', 'ticket_class':'normal', 'invitation_count':1, 'custom_fields':{}} for i in range(1000)]
    async with client_factory(w['requester_user']) as client:
        assert (await client.put(path, headers=headers, json={'revision':0,'rows':rows})).status_code == 200
    async with client_factory(w['provider_user']) as client:
        assert (await client.get(path, headers=headers)).json()['rows'] == []
        assert (await client.put(path, headers=headers, json={'revision':0,'rows':[]})).status_code == 200
    async with client_factory(w['requester_user']) as client:
        assert len((await client.get(path, headers=headers)).json()['rows']) == 1000


@pytest.mark.asyncio
async def test_draft_rls_hides_rows_without_matching_tenant(db_session, org_world):
    w = org_world
    await db_session.execute(text("""INSERT INTO generation_drafts(tenant_id,event_id,created_by,kind,payload)
        VALUES(:tid,:eid,:uid,'quick','[]')"""), {'tid':w['requester_tenant'],'eid':w['event_id'],'uid':w['requester_user']})
    await db_session.execute(text('SET LOCAL ROLE qentry_app'))
    await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,true)"), {'tid':str(w['requester_tenant'])})
    assert (await db_session.execute(text('SELECT count(*) FROM generation_drafts'))).scalar() == 1
    for tenant in (str(w['provider_tenant']), ''):
        await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,true)"), {'tid':tenant})
        assert (await db_session.execute(text('SELECT count(*) FROM generation_drafts'))).scalar() == 0
        assert (await db_session.execute(text("UPDATE generation_drafts SET payload='[]'"))).rowcount == 0


@pytest.mark.parametrize('row', [
    {'guest_name':' '}, {'guest_name':None}, {'guest_name':'ضيف','invitation_count':True},
    {'guest_name':'ضيف','invitation_count':1.5}, {'guest_name':'ضيف','invitation_count':0},
    {'guest_name':'ضيف','ticket_class':'other'}, {'guest_name':'ضيف','custom_fields':None},
    {'guest_name':'ضيف','custom_fields':{'company':{'nested':'invalid'}}},
])
def test_draft_rejects_corrupt_row_shapes(row):
    from app.routes.generation_drafts import DraftWrite
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DraftWrite(revision=0,rows=[row])


def test_legacy_draft_rows_receive_safe_defaults_without_losing_custom_fields():
    from app.routes.generation_drafts import DraftWrite
    row=DraftWrite(revision=0,rows=[{'guest_name':' ضيف ', 'custom_fields':{'company':'شركة'}}]).model_dump()['rows'][0]
    assert row=={'guest_name':'ضيف','invitation_count':1,'ticket_class':'normal','custom_fields':{'company':'شركة'}}


@pytest.mark.parametrize('revision', [True, -1, 2147483647])
def test_draft_revision_stays_within_database_integer_bounds(revision):
    from app.routes.generation_drafts import DraftWrite
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DraftWrite(revision=revision,rows=[])
