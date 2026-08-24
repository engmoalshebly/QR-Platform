"""Regression coverage for team-only gate and attendance authorization."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import permission_service


class _Result:
    def __init__(self, allowed: bool):
        self.allowed = allowed

    def first(self):
        return (1,) if self.allowed else None


class _Db:
    def __init__(self, operation_exists: bool):
        self.operation_exists = operation_exists
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.operation_exists)


@pytest.mark.asyncio
async def test_gate_access_requires_an_active_provider_operation(monkeypatch):
    db = _Db(operation_exists=True)
    tenant_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(permission_service, "has_permission", AsyncMock(return_value=True))

    allowed = await permission_service.check_provider_event_access(
        db, event_id, tenant_id, user_id, "gates.manage",
    )

    assert allowed is True
    statement, params = db.calls[0]
    assert "event_operations" in statement
    assert "provider_tenant_id" in statement
    assert params == {"eid": str(event_id), "tid": str(tenant_id), "uid": str(user_id)}


@pytest.mark.asyncio
async def test_gate_access_stops_before_operation_query_without_permission(monkeypatch):
    db = _Db(operation_exists=True)
    monkeypatch.setattr(permission_service, "has_permission", AsyncMock(return_value=False))

    allowed = await permission_service.check_provider_event_access(
        db, uuid4(), uuid4(), uuid4(), "checkin.scan",
    )

    assert allowed is False
    assert db.calls == []
