import csv
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request
from app.services import invitation_table_service as tables
from app.routes import digital_invitations as routes
from app.routes import whatsapp

@pytest.fixture
async def large_world(db_session,org_world):
    tid,uid,eid=org_world['requester_tenant'],org_world['requester_user'],org_world['event_id']
    await db_session.execute(text('''INSERT INTO invitations(id,tenant_id,event_id,token,guest_name,guest_phone,ticket_class,status,rsvp_status,
        metadata,guest_count,checkin_count,created_at)
        SELECT gen_random_uuid(),:tid,:eid,gen_random_uuid()::text,'ضيف_'||n,'+967700000001',
        (CASE WHEN n%3=0 THEN 'vip' ELSE 'normal' END)::ticket_class,
        (CASE WHEN n%2=0 THEN 'accepted' ELSE 'created' END)::invitation_status,
        (CASE WHEN n%2=0 THEN 'accepted' ELSE 'pending' END)::rsvp_status,
        jsonb_build_object('require_rsvp',true),1,CASE WHEN n%10=0 THEN 1 ELSE 0 END,now()-n*interval '1 second'
        FROM generate_series(1,3000) n'''),{'tid':str(tid),'eid':str(eid)})
    return tid,uid,eid

@pytest.mark.asyncio
async def test_global_totals_search_and_pages_beyond_500(db_session,large_world):
    tid,uid,eid=large_world;filters=tables.TableFilters(eid)
    first=await tables.page(db_session,tid,filters,50,0)
    second=await tables.page(db_session,tid,filters,50,50)
    assert first['total']==3000 and len(first['items'])==50
    assert first['stats']['accepted']==1500 and first['stats']['pending']==1500
    assert set(i.id for i in first['items']).isdisjoint(i.id for i in second['items'])
    found=await tables.page(db_session,tid,replace(filters,search='ضيف_2999'),50,0)
    assert found['total']==1 and found['items'][0].guest_name=='ضيف_2999'
    assert found['stats']['total']==3000
    filtered=await tables.page(db_session,tid,replace(filters,rsvp_status='accepted',ticket_class='vip'),50,0)
    assert filtered['total']==500
    final=await tables.page(db_session,tid,tables.TableFilters(eid,tab='final',checkin='checked_in'),50,0)
    assert final['total']==300 and final['stats']['total']==1500
    end=await tables.page(db_session,tid,filters,100,999999)
    assert end['offset']==2900 and len(end['items'])==100
    assert (await tables.page(db_session,uuid4(),filters))['total']==0
    assert (await tables.page(db_session,tid,replace(filters,event_id=uuid4())))['total']==0

@pytest.mark.asyncio
async def test_whatsapp_filter_uses_current_purpose_and_complete_scope(db_session,large_world):
    tid,uid,eid=large_world
    invs=(await db_session.execute(text("SELECT id,guest_name FROM invitations WHERE tenant_id=:tid AND guest_name IN ('ضيف_1','ضيف_2','ضيف_2999')"),{'tid':str(tid)})).mappings().all()
    ids={r['guest_name']:r['id'] for r in invs};rid=uuid4()
    await db_session.execute(text("INSERT INTO whatsapp_delivery_requests(id,tenant_id,client_request_id,payload_hash,response) VALUES(:id,:tid,:cid,'test','{}')"),{'id':str(rid),'tid':str(tid),'cid':str(uuid4())})
    for name,purpose,state in [('ضيف_1','rsvp','read'),('ضيف_2','rsvp','sent'),('ضيف_2999','rsvp','unknown')]:
        await db_session.execute(text('''INSERT INTO whatsapp_deliveries(tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,state)
        VALUES(:tid,:eid,:iid,:rid,:uid,:purpose,'967700000001',:state)'''),{'tid':str(tid),'eid':str(eid),'iid':str(ids[name]),'rid':str(rid),'uid':str(uid),'purpose':purpose,'state':state})
    f=tables.TableFilters(eid,whatsapp_state='not_sent')
    page=await tables.page(db_session,tid,f,50,0,True)
    assert page['total']==2998 # accepted guest 2 still needs a ticket.
    sent=await tables.page(db_session,tid,replace(f,whatsapp_state='sent'),50,0,True)
    assert sent['total']==1 and sent['items'][0].id==ids['ضيف_1']
    review=await tables.page(db_session,tid,replace(f,whatsapp_state='unknown'),50,0,True)
    assert review['total']==1 and review['items'][0].id==ids['ضيف_2999']
    assert review['whatsapp'][0]['state']=='unknown'

@pytest.mark.asyncio
async def test_export_streams_all_matching_rows_and_requires_export_permission(db_session,large_world,monkeypatch):
    tid,uid,eid=large_world
    await db_session.execute(text("UPDATE invitations SET rsvp_message='=HYPERLINK(1)' WHERE tenant_id=:tid AND guest_name='ضيف_2998'"),{'tid':str(tid)})
    permission=AsyncMock();monkeypatch.setattr(routes,'require_permission',permission)
    monkeypatch.setattr(routes,'has_permission',AsyncMock(return_value=False))
    request=Request({'type':'http','headers':[(b'x-tenant-id',str(tid).encode())],'client':('127.0.0.1',1)})
    response=await routes.export_invitation_table(request,tables.TableFilters(eid),SimpleNamespace(id=uid),db_session)
    chunks=[chunk async for chunk in response.body_iterator]
    body=''.join(chunk.decode() if isinstance(chunk,bytes) else chunk for chunk in chunks)
    assert body.startswith('\ufeff')
    rows=list(csv.reader(io.StringIO(body.lstrip('\ufeff'))))
    assert len(rows)==3001 and len(rows[0])==9
    assert any('ضيف_2999' in row for row in rows)
    assert any("'=HYPERLINK(1)" in row for row in rows)
    assert all(row[1].startswith("'+") for row in rows[1:])
    assert permission.call_args.args[-1]=='ui.rsvp.action.export'
    if response.background: await response.background()

@pytest.mark.asyncio
async def test_no_whatsapp_filter_without_view_permission(monkeypatch):
    monkeypatch.setattr(routes,'require_permission',AsyncMock())
    monkeypatch.setattr(routes,'has_permission',AsyncMock(return_value=False))
    tid=uuid4();request=Request({'type':'http','headers':[(b'x-tenant-id',str(tid).encode())]})
    db=SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as err:
        await routes.invitation_table(request,tables.TableFilters(uuid4(),whatsapp_state='not_sent'),50,0,SimpleNamespace(id=uuid4()),db)
    assert err.value.status_code==403
    db.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_history_filters_pagination_and_creation_anchor(db_session,large_world,monkeypatch):
    tid,uid,eid=large_world;rid=uuid4()
    iid=(await db_session.execute(text("SELECT id FROM invitations WHERE tenant_id=:tid AND guest_name='ضيف_2999'"),{'tid':str(tid)})).scalar_one()
    await db_session.execute(text("INSERT INTO whatsapp_delivery_requests(id,tenant_id,client_request_id,payload_hash,response) VALUES(:rid,:tid,:cid,'test','{}')"),{'rid':str(rid),'tid':str(tid),'cid':str(uuid4())})
    await db_session.execute(text('''INSERT INTO whatsapp_deliveries(tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,state,created_at)
        SELECT :tid,:eid,:iid,:rid,:uid,CASE WHEN n%2=0 THEN 'ticket' ELSE 'rsvp' END,'967700000001','sent',now()-n*interval '1 second'
        FROM generate_series(1,120) n'''),{'tid':str(tid),'eid':str(eid),'iid':str(iid),'rid':str(rid),'uid':str(uid)})
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:tid)
    monkeypatch.setattr(whatsapp,'require_permission',AsyncMock())
    args={'request':object(),'event_id':eid,'user':SimpleNamespace(id=uid),'db':db_session,'search':'','state':'all','purpose':'all','limit':50,'offset':0,'as_of':None}
    first=await whatsapp.history_page(**args)
    await db_session.execute(text('''INSERT INTO whatsapp_deliveries(tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,state,created_at)
        VALUES(:tid,:eid,:iid,:rid,:uid,'ticket','967700000001','sent',:time)'''),{'tid':str(tid),'eid':str(eid),'iid':str(iid),'rid':str(rid),'uid':str(uid),'time':first['as_of']+timedelta(seconds=1)})
    second=await whatsapp.history_page(**{**args,'offset':50,'as_of':first['as_of']})
    assert first['total']==second['total']==120
    assert set(r['id'] for r in first['items']).isdisjoint(r['id'] for r in second['items'])
    ticket=await whatsapp.history_page(**{**args,'purpose':'ticket','search':'ضيف_2999','as_of':first['as_of']})
    assert ticket['total']==60
    assert (await whatsapp.history_page(**{**args,'state':'failed'}))['total']==0
    with pytest.raises(HTTPException):
        await whatsapp.history_page(**{**args,'as_of':datetime(2026,10,12)})

@pytest.mark.asyncio
async def test_export_is_denied_without_export_permission(monkeypatch):
    monkeypatch.setattr(routes,'authorize_table',AsyncMock(return_value=(uuid4(),False)))
    monkeypatch.setattr(routes,'require_permission',AsyncMock(side_effect=HTTPException(403,'denied')))
    db=SimpleNamespace(stream=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await routes.export_invitation_table(object(),tables.TableFilters(uuid4(),tab='final'),SimpleNamespace(id=uuid4()),db)
    assert error.value.status_code==403
    db.stream.assert_not_awaited()

@pytest.mark.asyncio
async def test_table_http_validation_and_permissions(client_factory,large_world,org_world):
    tid,uid,eid=large_world
    headers={'X-Tenant-ID':str(tid)}
    async with client_factory(uid) as client:
        result=await client.get('/api/v1/invitations/table',params={'event_id':str(eid),'offset':2950},headers=headers)
        assert result.status_code==200
        assert result.json()['total']==3000 and len(result.json()['items'])==50
        for params in ({'limit':101},{'offset':-1},{'search':'a'*201},{'whatsapp_state':'unsupported'},{'tab':'unsupported'}):
            response=await client.get('/api/v1/invitations/table',params={'event_id':str(eid),**params},headers=headers)
            assert response.status_code==422
        response=await client.get('/api/v1/whatsapp/deliveries/page',params={'event_id':str(eid),'limit':101},headers=headers)
        assert response.status_code==422
    async with client_factory(org_world['provider_user']) as client:
        response=await client.get('/api/v1/invitations/table',params={'event_id':str(eid)},headers=headers)
        assert response.status_code==403

@pytest.mark.asyncio
async def test_final_export_keeps_entry_status_and_gate_columns(db_session,large_world,monkeypatch):
    tid,uid,eid=large_world
    monkeypatch.setattr(routes,'require_permission',AsyncMock())
    monkeypatch.setattr(routes,'has_permission',AsyncMock(return_value=False))
    request=Request({'type':'http','headers':[(b'x-tenant-id',str(tid).encode())],'client':('127.0.0.1',1)})
    response=await routes.export_invitation_table(request,tables.TableFilters(eid,tab='final'),SimpleNamespace(id=uid),db_session)
    body=''.join([chunk.decode() if isinstance(chunk,bytes) else chunk async for chunk in response.body_iterator])
    rows=list(csv.reader(io.StringIO(body.lstrip('\ufeff'))))
    assert len(rows)==1501
    assert rows[0][3:6]==['حالة الدخول','مرات الدخول','بوابة الدخول']
    assert sum(row[3]=='تم الدخول' for row in rows[1:])==300
    assert all(row[5]=='تلقائي' for row in rows[1:])
    if response.background: await response.background()
