from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import asyncio
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.routes import tenants
from app.services import feature_service

pytestmark = pytest.mark.unit

@pytest.mark.parametrize('enabled', [False, True])
def test_availability_uses_canonical_feature_check_after_membership(monkeypatch, enabled):
    tid, uid = uuid4(), uuid4()
    membership = AsyncMock()
    check = AsyncMock(return_value=enabled)
    monkeypatch.setattr(tenants, 'get_tenant_id_from_header', lambda request: tid)
    monkeypatch.setattr(tenants, 'verify_membership', membership)
    monkeypatch.setattr(feature_service, 'check_feature_flag', check)
    db = object()
    result = asyncio.run(tenants.get_feature_availability('rsvp', Request({'type':'http','headers':[]}), SimpleNamespace(id=uid), db))
    membership.assert_awaited_once_with(db, tid, uid)
    check.assert_awaited_once_with(db, tid, 'rsvp')
    assert result == {'feature_key':'rsvp', 'enabled':enabled}

def test_nonmember_cannot_read_feature_availability(monkeypatch):
    monkeypatch.setattr(tenants, 'get_tenant_id_from_header', lambda request: uuid4())
    monkeypatch.setattr(tenants, 'verify_membership', AsyncMock(side_effect=HTTPException(403, 'forbidden')))
    check = AsyncMock()
    monkeypatch.setattr(feature_service, 'check_feature_flag', check)
    with pytest.raises(HTTPException):
        asyncio.run(tenants.get_feature_availability('rsvp', Request({'type':'http','headers':[]}), SimpleNamespace(id=uuid4()), object()))
    check.assert_not_called()
