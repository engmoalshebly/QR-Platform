from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import CurrentUser
from app.routes import invites

pytestmark = pytest.mark.unit


def setup_resend(monkeypatch, *, status="pending", expired=False, recent=False, sent=True, role="member"):
    tenant_id, invite_id = uuid4(), uuid4()
    row = {"id": invite_id, "email": "member@example.test", "token": "test-token",
           "role": role, "status": status, "tenant_name": "Test workspace",
           "expires_at": datetime.now(timezone.utc) + timedelta(days=-1 if expired else 1)}
    result, cooldown = MagicMock(), MagicMock()
    result.mappings.return_value.first.return_value = row
    cooldown.first.return_value = (1,) if recent else None
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result, cooldown]), commit=AsyncMock())
    permission, owner, audit = AsyncMock(), AsyncMock(), AsyncMock()
    delivery = AsyncMock(return_value=sent)
    monkeypatch.setattr(invites, "get_tenant_id_from_header", lambda _: tenant_id)
    monkeypatch.setattr(invites, "require_permission", permission)
    monkeypatch.setattr(invites, "require_owner", owner)
    monkeypatch.setattr(invites, "log_audit", audit)
    monkeypatch.setattr(invites, "run_in_threadpool", delivery)
    user = CurrentUser(id=uuid4(), email="owner@example.test")
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    return invite_id, request, user, db, delivery, permission, owner, audit


@pytest.mark.asyncio
async def test_resend_reuses_invite_without_new_seat(monkeypatch):
    iid, req, user, db, delivery, permission, owner, audit = setup_resend(monkeypatch)
    await invites.resend_invite(iid, req, user, db)
    permission.assert_awaited_once()
    assert delivery.call_args.args[2].endswith("/invites/accept/test-token")
    assert all("INSERT INTO invites" not in str(call.args[0]) for call in db.execute.call_args_list)
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expired", [("accepted", False), ("revoked", False), ("pending", True)])
async def test_resend_rejects_nonvalid_invites(monkeypatch, status, expired):
    iid, req, user, db, delivery, *_ = setup_resend(monkeypatch, status=status, expired=expired)
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 409
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_cooldown(monkeypatch):
    iid, req, user, db, delivery, *_ = setup_resend(monkeypatch, recent=True)
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_delivery_failure_is_not_success(monkeypatch):
    iid, req, user, db, delivery, permission, owner, audit = setup_resend(monkeypatch, sent=False)
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 503
    db.commit.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_resend_requires_owner(monkeypatch):
    iid, req, user, db, delivery, permission, owner, audit = setup_resend(monkeypatch, role="admin")
    owner.side_effect = HTTPException(status_code=403)
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 403
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_missing_or_other_tenant_invite(monkeypatch):
    iid, req, user, db, delivery, *_ = setup_resend(monkeypatch)
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    db.execute.side_effect = [result]
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 404
    assert "i.tenant_id = :tid" in str(db.execute.call_args.args[0])
    delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_requires_manage_permission(monkeypatch):
    iid, req, user, db, delivery, permission, *_ = setup_resend(monkeypatch)
    permission.side_effect = HTTPException(status_code=403)
    with pytest.raises(HTTPException) as error:
        await invites.resend_invite(iid, req, user, db)
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    delivery.assert_not_awaited()
