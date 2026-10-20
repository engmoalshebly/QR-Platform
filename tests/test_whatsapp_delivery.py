"""OpenWA integration regressions; the provider is always mocked (no messages)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.services import whatsapp_service as svc
from app.routes.whatsapp import apply_ack


@pytest.mark.parametrize('raw,expected', [('+967 775-451-608','967775451608'), ('00966775123456','966775123456'), ('967775451608','967775451608')])
def test_international_phone(raw, expected):
    assert svc.normalize_phone(raw) == expected


@pytest.mark.parametrize('raw', ['', '0775451608','+123', '+1234567890123456','abc','+12345678@c.us'])
def test_invalid_phone(raw):
    with pytest.raises(ValueError): svc.normalize_phone(raw)


def test_signature_covers_exact_bytes():
    import hmac, hashlib
    raw = b'{"event":"message.ack"}'
    sig = 'sha256=' + hmac.new(b'secret', raw, hashlib.sha256).hexdigest()
    assert svc.verify_signature(raw, 'secret', sig)
    assert not svc.verify_signature(raw + b' ', 'secret', sig)
    assert not svc.verify_signature(raw, 'other-secret', sig)


def test_rsvp_and_admission_policy():
    inv = {'metadata': {'require_rsvp': True}, 'rsvp_status': 'pending'}
    assert svc.eligibility(inv) == ('rsvp', None)
    assert svc.eligibility({**inv, 'rsvp_status': 'accepted'}) == ('ticket', None)
    for patch in ({'status':'revoked'}, {'rsvp_status':'declined'}, {'is_registration':True},
                  {'event_status':'cancelled'}, {'expires_at':datetime.now(timezone.utc)-timedelta(seconds=1)}):
        assert svc.eligibility({**inv, **patch})[0] is None


@pytest.fixture
async def wa_world(db_session, org_world, monkeypatch):
    tid, uid, eid = org_world['requester_tenant'], org_world['requester_user'], org_world['event_id']
    iid, sid = uuid4(), uuid4()
    monkeypatch.setattr(svc, 'configured', lambda: True)
    monkeypatch.setattr(svc, 'require_feature', AsyncMock())
    monkeypatch.setattr(svc, 'check_feature_flag', AsyncMock(return_value=True))
    monkeypatch.setattr(svc, 'has_permission', AsyncMock(return_value=True))
    monkeypatch.setattr(svc, 'enforce_monthly_limit', AsyncMock())
    monkeypatch.setattr(svc, 'crypt', lambda value, **kw: value)
    await db_session.execute(text('''INSERT INTO whatsapp_connections(tenant_id,session_id,api_key_ciphertext,enabled,status)
        VALUES(:tid,:sid,'test-key',true,'ready')'''), {'tid':str(tid),'sid':str(sid)})
    await db_session.execute(text('''INSERT INTO invitations(id,tenant_id,event_id,token,guest_name,guest_phone,status,rsvp_status,metadata)
        VALUES(:id,:tid,:eid,:token,'ضيف اختبار','+967775451608','accepted','accepted',CAST(:meta AS jsonb))'''),
        {'id':str(iid),'tid':str(tid),'eid':str(eid),'token':uuid4().hex,'meta':'{"require_rsvp":false}'})
    return tid,uid,iid,eid


@pytest.mark.asyncio
async def test_queue_idempotency_and_payload_conflict(db_session, wa_world):
    tid,uid,iid,_ = wa_world
    request = uuid4()
    first = await svc.queue_deliveries(db_session,tid,uid,[iid],request)
    assert first['queued'] == 1
    assert await svc.queue_deliveries(db_session,tid,uid,[iid],request) == first
    with pytest.raises(HTTPException) as error:
        await svc.queue_deliveries(db_session,tid,uid,[iid,uuid4()],request)
    assert error.value.status_code == 409
    second = await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    assert second['queued'] == 0 and second['items'][0]['reason'] == 'already_pending'


@pytest.mark.asyncio
async def test_foreign_tenant_invitation_is_not_queued(db_session, wa_world):
    tid,uid,iid,_ = wa_world
    foreign = uuid4()
    result = await svc.queue_deliveries(db_session,tid,uid,[foreign],uuid4())
    assert result['queued'] == 0 and result['items'][0]['reason'] == 'not_found'


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_never_retried(db_session, wa_world, monkeypatch):
    tid,uid,iid,_ = wa_world
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    calls = []
    async def provider(method, path, **kwargs):
        if method == 'GET': return {'status':'ready'}
        calls.append(path)
        raise svc.ProviderError()
    monkeypatch.setattr(svc, 'provider', provider)
    assert await svc.dispatch_one(db_session)
    state = (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar()
    assert state == 'unknown'
    await svc.dispatch_one(db_session)
    assert len(calls) == 1
    result = await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4(),allow_resend=True)
    assert result['queued'] == 0 and result['items'][0]['reason'] == 'requires_review'


@pytest.mark.asyncio
async def test_revoke_before_dispatch_prevents_provider_call(db_session, wa_world, monkeypatch):
    tid,uid,iid,_ = wa_world
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    await db_session.execute(text("UPDATE invitations SET status='revoked' WHERE id=:id"),{'id':str(iid)})
    provider = AsyncMock()
    monkeypatch.setattr(svc,'provider',provider)
    await svc.dispatch_one(db_session)
    provider.assert_not_awaited()
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar() == 'cancelled'


@pytest.mark.asyncio
async def test_success_and_early_ack_keep_read_state(db_session, wa_world, monkeypatch):
    tid,uid,iid,_ = wa_world
    result = await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    await db_session.execute(text("INSERT INTO whatsapp_webhook_receipts(tenant_id,event_id,wa_message_id,ack) VALUES(:tid,'early','test-message',3)"),{'tid':str(tid)})
    async def provider(method, path, **kwargs):
        return {'status':'ready'} if method == 'GET' else {'messageId':'test-message'}
    monkeypatch.setattr(svc,'provider',provider)
    await svc.dispatch_one(db_session)
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE id=:id'),{'id':result['items'][0]['delivery_id']})).scalar() == 'read'
    await apply_ack(db_session,tid,'test-message')
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE id=:id'),{'id':result['items'][0]['delivery_id']})).scalar() == 'read'


@pytest.mark.asyncio
async def test_permission_removed_cancels_queued(db_session, wa_world, monkeypatch):
    tid,uid,iid,_ = wa_world
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    monkeypatch.setattr(svc,'has_permission',AsyncMock(return_value=False))
    provider=AsyncMock();monkeypatch.setattr(svc,'provider',provider)
    await svc.dispatch_one(db_session)
    provider.assert_not_awaited()

@pytest.mark.asyncio
async def test_connection_rows_are_isolated_by_rls(db_session, wa_world, org_world):
    tid,_,_,_ = wa_world
    foreign = org_world['provider_tenant']
    await db_session.execute(text("INSERT INTO whatsapp_connections(tenant_id,enabled) VALUES(:tid,false)"), {'tid':str(foreign)})
    await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,true)"), {'tid':str(tid)})
    await db_session.execute(text('SET LOCAL ROLE qentry_app'))
    try:
        rows=(await db_session.execute(text('SELECT tenant_id FROM whatsapp_connections'))).scalars().all()
        assert rows == [tid]
        assert not (await db_session.execute(text('SELECT tenant_id FROM whatsapp_connections WHERE tenant_id=:tid'),{'tid':str(foreign)})).first()
    finally:
        await db_session.execute(text('RESET ROLE'))


@pytest.mark.asyncio
async def test_webhook_signature_and_duplicate_ack(db_session, wa_world, monkeypatch):
    import hashlib, hmac, json
    from starlette.requests import Request
    from app.routes.whatsapp import webhook
    tid,uid,iid,_=wa_world
    result=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    did=result['items'][0]['delivery_id']
    await db_session.execute(text("UPDATE whatsapp_connections SET webhook_secret_ciphertext='test-secret' WHERE tenant_id=:tid"),{'tid':str(tid)})
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='sent',wa_message_id='ack-test' WHERE id=:id"),{'id':did})
    sid=(await db_session.execute(text('SELECT session_id FROM whatsapp_connections WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar()
    raw=json.dumps({'sessionId':str(sid),'event':'message.ack','data':{'messageId':'ack-test','ack':2}}).encode()
    signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
    def request(sig):
        async def receive(): return {'type':'http.request','body':raw,'more_body':False}
        return Request({'type':'http','headers':[(b'x-openwa-signature',sig.encode())]},receive)
    with pytest.raises(HTTPException) as denied: await webhook(request('invalid'),db_session)
    assert denied.value.status_code==401
    await webhook(request(signature),db_session)
    await webhook(request(signature),db_session)
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE id=:id'),{'id':did})).scalar()=='delivered'
    assert (await db_session.execute(text('SELECT count(*) FROM whatsapp_webhook_receipts WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar()==1


@pytest.mark.asyncio
async def test_route_denies_send_without_whatsapp_permission(monkeypatch):
    from app.routes import whatsapp
    async def deny(*args): raise HTTPException(403,'denied')
    monkeypatch.setattr(whatsapp,'require_permission',deny)
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:uuid4())
    queue=AsyncMock();monkeypatch.setattr(svc,'queue_deliveries',queue)
    body=whatsapp.SendRequest(invitation_ids=[uuid4()],client_request_id=uuid4())
    with pytest.raises(HTTPException) as error: await whatsapp.send(body,object(),SimpleNamespace(id=uuid4()),object())
    assert error.value.status_code==403
    queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnected_session_waits_without_posting(db_session, wa_world, monkeypatch):
    tid,uid,iid,_=wa_world
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    provider=AsyncMock(return_value={'status':'disconnected'});monkeypatch.setattr(svc,'provider',provider)
    await svc.dispatch_one(db_session)
    assert provider.await_count==1 and provider.call_args.args[0]=='GET'
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar()=='waiting_connection'

@pytest.mark.asyncio
async def test_link_provisions_scoped_credentials_without_enabling_or_exposing_them(db_session, wa_world, monkeypatch):
    from app.routes import whatsapp
    tid,uid,_,_=wa_world
    await db_session.execute(text('DELETE FROM whatsapp_connections WHERE tenant_id=:tid'), {'tid':str(tid)})
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:tid)
    monkeypatch.setattr(whatsapp,'require_permission',AsyncMock())
    monkeypatch.setattr(whatsapp,'require_feature',AsyncMock())
    monkeypatch.setattr(whatsapp,'audit',AsyncMock())
    sid=uuid4()
    async def provider(method,path,**kwargs):
        payload=kwargs.get('payload') or {}
        if path=='sessions': return [] if method=='GET' else {'id':str(sid),'status':'created'}
        if path=='auth/api-keys':
            assert payload['role']=='operator' and payload['allowedSessions']==[str(sid)]
            return {'apiKey':'test-scoped-key'}
        if path.endswith('/webhooks'):
            if method=='GET':return []
            assert 'active' not in payload
            return {'id':str(uuid4())}
        if path.endswith('/start'):return {'id':str(sid),'status':'qr_ready'}
        return {'id':str(sid),'status':'created'}
    monkeypatch.setattr(svc,'provider',provider)
    result=await whatsapp.link_connection(object(),SimpleNamespace(id=uid),db_session)
    assert result=={'linked':True,'status':'qr_ready'}
    conn=await svc.connection(db_session,tid)
    assert not conn['enabled'] and conn['session_id']==sid
    assert conn['api_key_ciphertext']=='test-scoped-key'
    assert 'api_key_ciphertext' not in whatsapp.present(conn)


@pytest.mark.asyncio
async def test_receipt_committed_after_response_is_reconciled_on_next_tick(db_session, wa_world):
    tid,uid,iid,_=wa_world
    result=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    did=result['items'][0]['delivery_id']
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='sent',wa_message_id='late-commit' WHERE id=:id"),{'id':did})
    await db_session.execute(text("INSERT INTO whatsapp_webhook_receipts(tenant_id,event_id,wa_message_id,ack) VALUES(:tid,'late-event','late-commit',3)"),{'tid':str(tid)})
    await svc.dispatch_one(db_session)
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE id=:id'),{'id':did})).scalar()=='read'


def test_secrets_use_a_separate_stable_key(monkeypatch):
    monkeypatch.setattr(svc,'get_settings',lambda:SimpleNamespace(whatsapp_encryption_key='a'*32))
    ciphertext=svc.crypt('provider-credential')
    assert 'provider-credential' not in ciphertext
    assert svc.crypt(ciphertext,decrypt=True)=='provider-credential'
    monkeypatch.setattr(svc,'get_settings',lambda:SimpleNamespace(whatsapp_encryption_key='b'*32))
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):svc.crypt(ciphertext,decrypt=True)

@pytest.mark.parametrize('url', ['http://:secret@openwa-api:2785', 'https://user@host.test', 'http://openwa-api:2785?token=x', 'file:///tmp/openwa'])
def test_provider_endpoint_rejects_url_credentials_and_non_http_schemes(monkeypatch, url):
    monkeypatch.setattr(svc,'get_settings',lambda:SimpleNamespace(openwa_enabled=True,openwa_base_url=url,openwa_master_key='a'*32,whatsapp_encryption_key='b'*32))
    assert not svc.configured()

@pytest.mark.asyncio
async def test_table_summary_returns_latest_per_purpose_beyond_history_page(db_session, wa_world, monkeypatch):
    from app.routes import whatsapp
    tid,uid,iid,eid=wa_world
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:tid)
    monkeypatch.setattr(whatsapp,'require_permission',AsyncMock())
    first=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    did=first['items'][0]['delivery_id']
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='sent',created_at=now()-interval '1 hour' WHERE id=:id"),{'id':did})
    latest=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4(),allow_resend=True)
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='read' WHERE id=:id"),{'id':latest['items'][0]['delivery_id']})
    await db_session.execute(text('''INSERT INTO whatsapp_deliveries(id,tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,state,created_at)
        SELECT gen_random_uuid(),tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,'sent',now()-interval '2 days'
        FROM whatsapp_deliveries CROSS JOIN generate_series(1,60) WHERE id=:id'''),{'id':did})
    await db_session.execute(text('''UPDATE invitations SET metadata=CAST(:meta AS jsonb),rsvp_status='pending' WHERE id=:id'''),{'id':str(iid),'meta':'{"require_rsvp":true}'})
    rsvp=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='delivered' WHERE id=:id"),{'id':rsvp['items'][0]['delivery_id']})
    result=await whatsapp.delivery_summary(object(),eid,str(iid),SimpleNamespace(id=uid),db_session)
    by_purpose={row['purpose']:row for row in result}
    assert len(result)==2
    assert by_purpose['ticket']['state']=='read'
    assert by_purpose['ticket']['attempt_count']==62
    assert by_purpose['rsvp']['state']=='delivered'
    assert 'api_key_ciphertext' not in by_purpose['ticket']
    assert await whatsapp.delivery_summary(object(),uuid4(),str(iid),SimpleNamespace(id=uid),db_session)==[]
    assert await whatsapp.delivery_summary(object(),eid,str(uuid4()),SimpleNamespace(id=uid),db_session)==[]
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:uuid4())
    assert await whatsapp.delivery_summary(object(),eid,str(iid),SimpleNamespace(id=uid),db_session)==[]


@pytest.mark.asyncio
async def test_table_history_scopes_to_one_invitation(db_session, wa_world, monkeypatch):
    from app.routes import whatsapp
    tid,uid,iid,eid=wa_world
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:tid)
    monkeypatch.setattr(whatsapp,'require_permission',AsyncMock())
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    other=uuid4()
    await db_session.execute(text('''INSERT INTO invitations(id,tenant_id,event_id,token,guest_name,guest_phone,status,rsvp_status,metadata)
        VALUES(:id,:tid,:eid,:token,'ضيف آخر','+967700000001','accepted','accepted','{}')'''),{'id':str(other),'tid':str(tid),'eid':str(eid),'token':uuid4().hex})
    await svc.queue_deliveries(db_session,tid,uid,[other],uuid4())
    rows=await whatsapp.history(object(),eid,50,0,iid,SimpleNamespace(id=uid),db_session)
    assert len(rows)==1 and rows[0]['invitation_id']==iid
    assert await whatsapp.history(object(),eid,50,0,uuid4(),SimpleNamespace(id=uid),db_session)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['not-a-uuid', ','.join(str(uuid4()) for _ in range(101))])
async def test_table_summary_rejects_bad_or_excessive_ids(invalid, monkeypatch):
    from app.routes import whatsapp
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:uuid4())
    monkeypatch.setattr(whatsapp,'require_permission',AsyncMock())
    db=SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await whatsapp.delivery_summary(object(),uuid4(),invalid,SimpleNamespace(id=uuid4()),db)
    assert error.value.status_code==422
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('denied_permission',['whatsapp.view','invitations.view'])
async def test_table_summary_requires_both_read_permissions(denied_permission,monkeypatch):
    from app.routes import whatsapp
    async def permission(db,tid,uid,key):
        if key==denied_permission: raise HTTPException(403,'denied')
    monkeypatch.setattr(whatsapp,'get_tenant_id_from_header',lambda _:uuid4())
    monkeypatch.setattr(whatsapp,'require_permission',permission)
    db=SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await whatsapp.delivery_summary(object(),uuid4(),str(uuid4()),SimpleNamespace(id=uuid4()),db)
    assert error.value.status_code==403
    db.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_signed_negative_ack_reports_failure_and_late_read_wins(db_session,wa_world):
    import hashlib,hmac,json
    from starlette.requests import Request
    from app.routes.whatsapp import webhook
    tid,uid,iid,_=wa_world
    result=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    did=result['items'][0]['delivery_id']
    await db_session.execute(text("UPDATE whatsapp_connections SET webhook_secret_ciphertext='test-secret' WHERE tenant_id=:tid"),{'tid':str(tid)})
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='sent',wa_message_id='negative-test' WHERE id=:id AND tenant_id=:tid"),{'id':did,'tid':str(tid)})
    sid=(await db_session.execute(text('SELECT session_id FROM whatsapp_connections WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()
    async def post(ack):
        raw=json.dumps({'sessionId':str(sid),'event':'message.ack','data':{'messageId':'negative-test','ack':ack}}).encode()
        signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
        async def receive():return {'type':'http.request','body':raw,'more_body':False}
        return await webhook(Request({'type':'http','headers':[(b'x-openwa-signature',signature.encode())]},receive),db_session)
    await post(1);await post(-1)
    row=(await db_session.execute(text('SELECT state,error_code FROM whatsapp_deliveries WHERE id=:id AND tenant_id=:tid'),{'id':did,'tid':str(tid)})).mappings().one()
    assert row['state']=='failed' and row['error_code']=='whatsapp_rejected'
    await post(3);await post(-1)
    row=(await db_session.execute(text('SELECT state,error_code FROM whatsapp_deliveries WHERE id=:id AND tenant_id=:tid'),{'id':did,'tid':str(tid)})).mappings().one()
    assert row['state']=='read' and row['error_code'] is None


@pytest.mark.asyncio
async def test_dispatcher_reconciles_error_ack_commit_race(db_session,wa_world):
    tid,uid,iid,_=wa_world
    result=await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    did=result['items'][0]['delivery_id']
    await db_session.execute(text("UPDATE whatsapp_deliveries SET state='sent',wa_message_id='late-negative' WHERE id=:id AND tenant_id=:tid"),{'id':did,'tid':str(tid)})
    await db_session.execute(text("INSERT INTO whatsapp_webhook_receipts(tenant_id,event_id,wa_message_id,ack) VALUES(:tid,'late-negative','late-negative',-1)"),{'tid':str(tid)})
    await svc.dispatch_one(db_session)
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE id=:id AND tenant_id=:tid'),{'id':did,'tid':str(tid)})).scalar_one()=='failed'
