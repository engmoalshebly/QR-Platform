from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.routes import auth, invites

pytestmark = pytest.mark.unit


def setup_activation(monkeypatch, *, status='pending', expired=False, existing=False, role='member', tenant_status='active'):
    uid, tid = uuid4(), uuid4()
    invite = {'id': uuid4(), 'tenant_id': tid, 'email': 'invited@example.test', 'role': role,
              'status': status, 'tenant_status': tenant_status,
              'expires_at': datetime.now(timezone.utc) + timedelta(days=-1 if expired else 1)}
    lookup, account = MagicMock(), MagicMock()
    lookup.mappings.return_value.first.return_value = invite
    account.first.return_value = (uid,) if existing else None
    db = SimpleNamespace(execute=AsyncMock(side_effect=[lookup, MagicMock(), account, MagicMock()]), rollback=AsyncMock())
    provider = SimpleNamespace(create_user=MagicMock(), delete_user=MagicMock())
    delivery = AsyncMock(return_value=SimpleNamespace(user=SimpleNamespace(id=str(uid))))
    joined = AsyncMock(return_value={'tenant_id': str(tid), 'role': role})
    monkeypatch.setattr(invites, 'get_supabase_admin', lambda: SimpleNamespace(auth=SimpleNamespace(admin=provider)))
    monkeypatch.setattr(invites, 'run_in_threadpool', delivery)
    monkeypatch.setattr(invites, 'accept_invite', joined)
    monkeypatch.setattr(auth, '_enforce_public_rate_limit', AsyncMock())
    request = Request({'type': 'http', 'headers': [], 'client': ('127.0.0.1', 1234)})
    return request, Response(), db, delivery, joined, provider, uid


@pytest.mark.asyncio
async def test_activation_creates_unique_password_and_joins_without_workspace(monkeypatch):
    req, response, db, delivery, joined, provider, uid = setup_activation(monkeypatch)
    result = await invites.activate_invited_account('test-token', req, response, db)
    assert result['email'] == 'invited@example.test'
    password = result['initial_password']
    assert len(password) >= 24 and any(c.isupper() for c in password) and any(c.islower() for c in password) and any(c.isdigit() for c in password)
    assert delivery.call_args.args[0] is provider.create_user
    payload = delivery.call_args.args[1]
    assert payload['password'] == password and payload['email_confirm'] is True
    assert 'password' not in payload['user_metadata']
    assert joined.call_args.args[1].id == uid
    assert joined.call_args.args[1].email == result['email']
    assert joined.call_args.args[2] is db
    assert all('INSERT INTO tenants' not in str(call.args[0]) for call in db.execute.call_args_list)
    assert response.headers['Cache-Control'] == 'no-store'
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_does_not_reset_existing_account(monkeypatch):
    req, response, db, delivery, joined, *_ = setup_activation(monkeypatch, existing=True)
    with pytest.raises(HTTPException) as error:
        await invites.activate_invited_account('test-token', req, response, db)
    assert error.value.detail['code'] == 'INVITE_ACCOUNT_EXISTS'
    delivery.assert_not_awaited()
    joined.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs,status_code', [
    ({'status': 'revoked'}, 410), ({'expired': True}, 410),
    ({'role': 'owner'}, 409), ({'tenant_status': 'suspended'}, 403),
])
async def test_activation_requires_valid_invite(monkeypatch, kwargs, status_code):
    req, response, db, delivery, joined, *_ = setup_activation(monkeypatch, **kwargs)
    with pytest.raises(HTTPException) as error:
        await invites.activate_invited_account('test-token', req, response, db)
    assert error.value.status_code == status_code
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_retry_never_discloses_password(monkeypatch):
    req, response, db, delivery, joined, *_ = setup_activation(monkeypatch, status='accepted')
    with pytest.raises(HTTPException) as error:
        await invites.activate_invited_account('test-token', req, response, db)
    assert error.value.detail['code'] == 'INVITE_ALREADY_ACCEPTED'
    assert 'initial_password' not in error.value.detail
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_cleans_up_identity_when_join_fails(monkeypatch):
    req, response, db, delivery, joined, provider, uid = setup_activation(monkeypatch)
    joined.side_effect = RuntimeError('membership write failed')
    with pytest.raises(HTTPException) as error:
        await invites.activate_invited_account('test-token', req, response, db)
    assert error.value.status_code == 503
    db.rollback.assert_awaited_once()
    assert delivery.call_args.args == (provider.delete_user, str(uid))


@pytest.mark.asyncio
async def test_activation_missing_token_creates_nothing(monkeypatch):
    req, response, db, delivery, joined, *_ = setup_activation(monkeypatch)
    lookup = MagicMock()
    lookup.mappings.return_value.first.return_value = None
    db.execute.side_effect = [lookup]
    with pytest.raises(HTTPException) as error:
        await invites.activate_invited_account('test-token', req, response, db)
    assert error.value.status_code == 404
    delivery.assert_not_awaited()
