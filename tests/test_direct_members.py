from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request
from app.auth import CurrentUser
from app.routes import tenants
from app.services import feature_service

pytestmark = pytest.mark.unit


def setup_direct(monkeypatch, *, new=False, pending=True):
    tid, uid, actor, iid = uuid4(), uuid4(), uuid4(), uuid4()
    account = None if new else {'id': uid, 'email': 'member@example.com', 'email_confirmed_at': datetime.now(timezone.utc),
                               'full_name': 'Test member', 'avatar_url': None}
    queries = []
    async def execute(query, parameters=None):
        sql = str(query); queries.append((sql, parameters))
        result = MagicMock()
        if 'FROM auth.users' in sql: result.mappings.return_value.first.return_value = account
        elif "UPDATE invites SET status='revoked'" in sql:
            result.mappings.return_value.all.return_value = [{'id': iid, 'expires_at': datetime.now(timezone.utc)+timedelta(days=1)}] if pending else []
        elif 'SELECT 1 FROM memberships' in sql: result.first.return_value = None
        elif 'INSERT INTO memberships' in sql:
            result.mappings.return_value.first.return_value = {'tenant_id':tid,'user_id':uid,'role':'viewer','status':'active','created_at':datetime.now(timezone.utc)}
        elif 'SELECT name FROM tenants' in sql: result.scalar_one.return_value = 'Test workspace'
        return result
    db = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock(), rollback=AsyncMock())
    permission, owner, quota, audit, sync_roles = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    provider = SimpleNamespace(create_user=MagicMock(), delete_user=MagicMock())
    thread = AsyncMock(return_value=SimpleNamespace(user=SimpleNamespace(id=str(uid))))
    monkeypatch.setattr(tenants,'get_tenant_id_from_header',lambda _:tid)
    monkeypatch.setattr(tenants,'require_permission',permission)
    monkeypatch.setattr(tenants,'require_owner',owner)
    monkeypatch.setattr(tenants,'log_audit',audit)
    monkeypatch.setattr(tenants,'_sync_base_membership_roles',sync_roles)
    monkeypatch.setattr(tenants,'get_supabase_admin',lambda:SimpleNamespace(auth=SimpleNamespace(admin=provider)))
    monkeypatch.setattr(tenants.asyncio,'to_thread',thread)
    monkeypatch.setattr(feature_service,'check_seats_limit',quota)
    body=tenants.DirectMemberCreateRequest(email='member@example.com',full_name='Test member',temporary_password='Test-password-123',role='viewer')
    req=Request({'type':'http','headers':[],'client':('127.0.0.1',1234)})
    return body,req,BackgroundTasks(),CurrentUser(id=actor,email='owner@example.com'),db,quota,permission,thread,provider,queries,tid


@pytest.mark.asyncio
async def test_direct_existing_member_consumes_pending_seat_without_changing_password(monkeypatch):
    body,req,tasks,user,db,quota,permission,thread,provider,queries,tid=setup_direct(monkeypatch)
    async def check_quota(*args,**kwargs):
        assert any("UPDATE invites SET status='revoked'" in sql for sql,_ in queries)
    quota.side_effect=check_quota
    result=await tenants.add_existing_member_directly(body,req,tasks,user,db)
    assert result.tenant_id==tid
    permission.assert_awaited_once()
    thread.assert_not_awaited()
    assert not tasks.tasks
    assert any("status='accepted'" in sql and params['tid']==str(tid) for sql,params in queries)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_new_member_schedules_credentials_after_commit(monkeypatch):
    body,req,tasks,user,db,quota,permission,thread,provider,queries,tid=setup_direct(monkeypatch,new=True)
    await tenants.add_existing_member_directly(body,req,tasks,user,db)
    assert thread.call_args.args[0] is provider.create_user
    assert thread.call_args.args[1]['password']==body.temporary_password
    db.commit.assert_awaited_once()
    assert len(tasks.tasks)==1
    assert tasks.tasks[0].func is tenants.send_temporary_access_email


@pytest.mark.asyncio
async def test_direct_authorization_precedes_auth_catalog_access(monkeypatch):
    body,req,tasks,user,db,quota,permission,thread,*_=setup_direct(monkeypatch)
    permission.side_effect=HTTPException(403,'Forbidden')
    with pytest.raises(HTTPException): await tenants.add_existing_member_directly(body,req,tasks,user,db)
    db.execute.assert_not_awaited()
    thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_quota_failure_cannot_commit_invite_conversion(monkeypatch):
    body,req,tasks,user,db,quota,permission,thread,*_=setup_direct(monkeypatch,new=True)
    quota.side_effect=HTTPException(429,'Seats full')
    with pytest.raises(HTTPException): await tenants.add_existing_member_directly(body,req,tasks,user,db)
    db.commit.assert_not_awaited()
    thread.assert_not_awaited()
    assert not tasks.tasks


@pytest.mark.asyncio
async def test_direct_failed_profile_write_cleans_up_created_account(monkeypatch):
    body,req,tasks,user,db,quota,permission,thread,provider,*_=setup_direct(monkeypatch,new=True)
    execute=db.execute.side_effect
    async def fail_profile(query,parameters=None):
        if 'INSERT INTO profiles' in str(query): raise RuntimeError('write failed')
        return await execute(query,parameters)
    db.execute.side_effect=fail_profile
    with pytest.raises(HTTPException) as error: await tenants.add_existing_member_directly(body,req,tasks,user,db)
    assert error.value.status_code==502
    db.rollback.assert_awaited_once()
    assert thread.call_args.args[0] is provider.delete_user
    assert not tasks.tasks
