"""Stable, machine-readable errors from the actual enforcement services."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.middleware import RateLimitMiddleware
from app.routes.auth import _enforce_public_rate_limit
from app.services import entitlement_service, feature_service, quota_service, usage_service

pytestmark = pytest.mark.unit


def result(row=None, scalar=None):
    value = MagicMock()
    value.mappings.return_value.first.return_value = row
    value.scalar.return_value = scalar
    value.scalar_one_or_none.return_value = scalar
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["static", "seats", "canonical", "monthly"])
async def test_limit_errors_expose_same_contract_and_http_status(monkeypatch, entry):
    tenant_id = uuid4()
    key = "seats_max" if entry == "seats" else "events_per_month"
    monkeypatch.setattr(feature_service, "get_plan_limit", AsyncMock(return_value=1))
    monkeypatch.setattr(entitlement_service, "get_limits", AsyncMock(return_value=({}, {key: {"value": 1}})))
    monkeypatch.setattr(usage_service, "get_tenant_plan_limits", AsyncMock(return_value=("starter", [{"key": key, "value": 1}])))
    monkeypatch.setattr(entitlement_service, "resolve_billing_tenant", AsyncMock(return_value=tenant_id))
    monkeypatch.setattr(usage_service, "get_current_usage", AsyncMock(return_value={key: 1}))
    monkeypatch.setattr(usage_service, "get_usage_period", AsyncMock(return_value={"resets_at": datetime(2026, 11, 1, tzinfo=timezone.utc), "timezone": "UTC"}))
    db = SimpleNamespace(execute=AsyncMock(return_value=result()))

    app = FastAPI()
    @app.post("/consume")
    async def consume():
        if entry == "static":
            await feature_service.enforce_static_limit(db, tenant_id, key, 1, "الفعاليات")
        elif entry == "seats":
            await feature_service.require_within_limit(db, tenant_id, key, 1, "الأعضاء")
        elif entry == "canonical":
            await entitlement_service.require_limit(db, tenant_id, key, 1)
        else:
            await usage_service.check_and_increment(db, tenant_id, key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/consume")
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert {k: detail[k] for k in ("code", "limit_key", "current", "limit", "requested")} == {
        "code": "PLAN_LIMIT_EXCEEDED", "limit_key": key, "current": 1, "limit": 1, "requested": 1,
    }
    assert "الحالي" in detail["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["static", "canonical", "monthly"])
async def test_missing_configuration_is_not_an_upgrade_error(monkeypatch, entry):
    monkeypatch.setattr(entitlement_service, "get_limits", AsyncMock(return_value=({"code": "starter"}, {})))
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        if entry == "static":
            await feature_service.get_plan_limit(db, uuid4(), "guests_max")
        elif entry == "canonical":
            await entitlement_service.require_limit(db, uuid4(), "guests_max", 0)
        else:
            await usage_service.check_and_increment(db, uuid4(), "guests_max")
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "PLAN_LIMIT_NOT_CONFIGURED"
    assert exc.value.detail["limit_key"] == "guests_max"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["wrapper", "canonical"])
@pytest.mark.parametrize("disabled", [True, False])
async def test_feature_override_and_plan_exclusion_are_distinct(monkeypatch, entry, disabled):
    monkeypatch.setattr(entitlement_service, "resolve_plan", AsyncMock(return_value={"id": uuid4()}))
    response = result(scalar=False if disabled else None)
    response.first.return_value = None
    db = SimpleNamespace(execute=AsyncMock(return_value=response))
    with pytest.raises(HTTPException) as exc:
        fn = feature_service.require_feature if entry == "wrapper" else entitlement_service.require_feature
        await fn(db, uuid4(), "email_delivery")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ("FEATURE_DISABLED" if disabled else "FEATURE_NOT_INCLUDED")
    assert exc.value.detail["feature_key"] == "email_delivery"
    assert isinstance(exc.value.detail["message"], str)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["single", "mixed_vip", "mixed_normal"])
async def test_event_quota_is_distinct_from_plan_limit(entry):
    event_id, tenant_id = str(uuid4()), str(uuid4())
    ticket_class = "vip" if entry == "mixed_vip" else "normal"
    row = {"quota": 1, "used": 1, "vip_quota": 1, "normal_quota": 1, "vip_used": 1, "normal_used": 1}
    db = SimpleNamespace(execute=AsyncMock(return_value=result(row=row)))
    with pytest.raises(HTTPException) as exc:
        if entry == "single":
            await quota_service.check_quota(db, tenant_id, event_id, ticket_class)
        else:
            await quota_service.check_quota_mixed(db, tenant_id, event_id, [{"ticket_class": ticket_class}])
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EVENT_QUOTA_EXCEEDED"
    assert exc.value.detail["ticket_class"] == ticket_class
    assert exc.value.detail["event_id"] == event_id
    assert (exc.value.detail["current"], exc.value.detail["limit"], exc.value.detail["requested"]) == (1, 1, 1)


def test_rate_limit_response_preserves_retry_headers():
    response = RateLimitMiddleware._too_many(120)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.headers["x-ratelimit-limit"] == "120"
    detail = json.loads(response.body)["detail"]
    assert detail["code"] == "RATE_LIMIT_EXCEEDED"
    assert detail["retry_after"] == 60


@pytest.mark.asyncio
async def test_public_rate_limit_uses_its_actual_window(monkeypatch):
    from app.routes import auth
    monkeypatch.setattr(auth.rate_limiter, "hit", AsyncMock(return_value=False))
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    with pytest.raises(HTTPException) as exc:
        await _enforce_public_rate_limit(request, action="test", limit=5, window_seconds=300)
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "RATE_LIMIT_EXCEEDED"
    assert exc.value.detail["retry_after"] == 300
    assert exc.value.headers["Retry-After"] == "300"
