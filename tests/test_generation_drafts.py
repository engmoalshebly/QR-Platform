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
        rows = [{'guest_name': 'ضيف', 'custom_fields': {'email': 'guest@example.com'}}]
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
