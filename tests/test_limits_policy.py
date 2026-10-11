"""Behavioral regression coverage for docs/LIMITS_POLICY_AR.md."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import CurrentUser
from app.models.template import TemplateCreate, TemplateUpdate
from app.routes import events, templates
from app.services import entitlement_service, feature_service, usage_service

pytestmark = pytest.mark.unit


def result(*, row=None, scalar=None, rowcount=1):
    value = MagicMock()
    value.mappings.return_value.first.return_value = row
    value.scalar.return_value = scalar
    value.rowcount = rowcount
    return value


@pytest.fixture
def actor(monkeypatch):
    tenant_id = uuid4()
    user = CurrentUser(id=uuid4(), role="authenticated")
    request = Request({"type": "http", "method": "POST", "path": "/test", "headers": []})
    for route in (events, templates):
        monkeypatch.setattr(route, "get_tenant_id_from_header", lambda _request: tenant_id)
        monkeypatch.setattr(route, "require_permission", AsyncMock())
        monkeypatch.setattr(route, "log_audit", AsyncMock())
    return tenant_id, user, request


@pytest.mark.asyncio
async def test_archive_and_restore_do_not_change_creation_usage(actor, monkeypatch):
    tenant_id, user, request = actor
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    event = dict(id=event_id, tenant_id=tenant_id, title="Existing event", start_date=now,
                 timezone="UTC", vip_quota=0, normal_quota=0, allow_rsvp=False,
                 allow_plus_one=False, allow_reentry=False, require_name=False,
                 status="draft", created_at=now, updated_at=now)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(row=event), result(),
                                                       result(row=event), result(row=event)]),
                         commit=AsyncMock())
    charge = AsyncMock(side_effect=AssertionError("Restoration is not creation"))
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", charge)
    await events.delete_event(event_id, request, user, db)
    restored = await events.restore_event(event_id, request, user, db)
    assert restored.id == event_id
    assert db.commit.await_count == 2
    charge.assert_not_awaited()
    assert all("usage" not in str(call.args[0]) for call in db.execute.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["published", "active"])
async def test_archive_keeps_existing_lifecycle_restrictions(actor, status):
    _, user, request = actor
    db = SimpleNamespace(execute=AsyncMock(return_value=result(row={"status": status})),
                         commit=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await events.delete_event(uuid4(), request, user, db)
    assert exc.value.status_code == 409
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "ai", "conversion"])
async def test_all_designed_template_paths_reject_at_capacity(actor, monkeypatch, path):
    _, user, request = actor
    db = SimpleNamespace(execute=AsyncMock(return_value=result(row={"template_type": "quick"})),
                         commit=AsyncMock())
    denied = AsyncMock(side_effect=HTTPException(429, "Template capacity exhausted"))
    charge = AsyncMock()
    monkeypatch.setattr(feature_service, "require_designed_template_capacity", denied)
    monkeypatch.setattr(feature_service, "acquire_plan_limit_lock", AsyncMock())
    monkeypatch.setattr(feature_service, "require_feature", AsyncMock())
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", charge)
    with pytest.raises(HTTPException) as exc:
        if path == "manual":
            await templates.create_template(TemplateCreate(name="New", template_type="designed"), request, user, db)
        elif path == "ai":
            await templates.generate_template_ai(templates.AITemplateGenerateRequest(prompt="New template"), request, user, db)
        else:
            await templates.update_template(uuid4(), TemplateUpdate(template_type="designed"), request, user, db)
    assert exc.value.status_code == 429
    denied.assert_awaited_once()
    charge.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert all("INSERT" not in str(call.args[0]) and "UPDATE" not in str(call.args[0]).split("FOR")[0]
               for call in db.execute.await_args_list)


@pytest.mark.asyncio
async def test_edit_existing_designed_template_at_capacity_is_allowed(actor, monkeypatch):
    tenant_id, user, request = actor
    now = datetime.now(timezone.utc)
    template = dict(id=uuid4(), tenant_id=tenant_id, name="Changed", template_type="designed",
                    ticket_class="normal", is_default=False, is_active=True, created_at=now, updated_at=now)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(row={"template_type": "designed"}),
                                                       result(row=template)]), commit=AsyncMock())
    capacity = AsyncMock(side_effect=AssertionError("Existing template needs no slot"))
    monkeypatch.setattr(feature_service, "require_designed_template_capacity", capacity)
    monkeypatch.setattr(feature_service, "acquire_plan_limit_lock", AsyncMock())
    changed = await templates.update_template(template["id"], TemplateUpdate(name="Changed", template_type="designed"), request, user, db)
    assert changed.name == "Changed"
    capacity.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("used,allowed", [(0, True), (1, False)])
async def test_designed_template_live_count_is_enforced_across_billing_scope(monkeypatch, used, allowed):
    tenant_id, linked_id = uuid4(), uuid4()
    db = SimpleNamespace(execute=AsyncMock(return_value=result(scalar=used)))
    monkeypatch.setattr(feature_service, "acquire_plan_limit_lock", AsyncMock())
    monkeypatch.setattr(entitlement_service, "get_billing_scope_tenant_ids", AsyncMock(return_value=[tenant_id, linked_id]))
    monkeypatch.setattr(feature_service, "get_plan_limit", AsyncMock(return_value=1))
    if allowed:
        await feature_service.require_designed_template_capacity(db, tenant_id)
    else:
        with pytest.raises(HTTPException) as exc:
            await feature_service.require_designed_template_capacity(db, tenant_id)
        assert exc.value.status_code == 429
    assert db.execute.await_args.args[1]["tids"] == [str(tenant_id), str(linked_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize("current,upload,limit,allowed", [
    (0, 1024 * 1024, 1, True), (1024 * 1024 - 1, 1, 1, True),
    (1024 * 1024, 1, 1, False), (0, 1, 0, False), (1024 * 1024, 1, -1, True),
])
async def test_upload_allows_exact_cap_and_rejects_overflow(monkeypatch, current, upload, limit, allowed):
    monkeypatch.setattr(feature_service, "acquire_plan_limit_lock", AsyncMock())
    monkeypatch.setattr(feature_service, "get_tenant_storage_bytes", AsyncMock(return_value=current))
    monkeypatch.setattr(feature_service, "get_plan_limit", AsyncMock(return_value=limit))
    if allowed:
        await feature_service.require_storage_for_upload(None, uuid4(), upload)
    else:
        with pytest.raises(HTTPException) as exc:
            await feature_service.require_storage_for_upload(None, uuid4(), upload)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_group_invitation_consumes_people_but_only_one_event_record(actor, monkeypatch):
    from app.models.invitation import InvitationCreate
    from app.routes import digital_invitations

    tenant_id, user, request = actor
    event_id, invitation_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    row = dict(id=invitation_id, tenant_id=tenant_id, event_id=event_id,
               ticket_class="normal", status="accepted", token="test-token",
               guest_count=4, created_at=now, updated_at=now)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result(scalar=2), result(row=row), result(row=row)]),
                         commit=AsyncMock())
    monthly, static, quota = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(digital_invitations, "get_tenant_id_from_header", lambda _request: tenant_id)
    monkeypatch.setattr(digital_invitations, "require_permission", AsyncMock())
    monkeypatch.setattr(digital_invitations, "_quota_check_single", quota)
    monkeypatch.setattr(digital_invitations, "_generate_barcode_for_row", AsyncMock())
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", monthly)
    monkeypatch.setattr(feature_service, "enforce_static_limit", static)
    created = await digital_invitations.create_invitation(
        InvitationCreate(event_id=event_id, guest_count=4, require_rsvp=False), request, user, db,
    )
    assert created.guest_count == 4
    assert quota.await_args.kwargs["count"] == 4
    assert monthly.await_args.kwargs["count"] == 4
    assert static.await_args.kwargs["requested"] == 1
    insert = db.execute.await_args_list[1]
    assert insert.args[1]["guest_count"] == 4
    assert "guest_count" in str(insert.args[0])
    db.commit.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_archive_restore_preserves_monthly_counter(db_session, org_world, client_factory):
    from sqlalchemy import text

    tenant_id, event_id = org_world["requester_tenant"], org_world["event_id"]
    await db_session.execute(text("""
        INSERT INTO usage_counters (tenant_id, period_start, period_end, key, value)
        VALUES (:tid, date_trunc('month', CURRENT_DATE)::date,
                (date_trunc('month', CURRENT_DATE) + interval '1 month - 1 day')::date,
                'events_per_month', 9999)
        ON CONFLICT (tenant_id, period_start, key) DO UPDATE SET value=9999
    """), {"tid": str(tenant_id)})
    await db_session.commit()
    async with client_factory(org_world["requester_user"]) as client:
        headers = {"X-Tenant-ID": str(tenant_id)}
        archived = await client.delete(f"/api/v1/events/{event_id}", headers=headers)
        assert archived.status_code == 204, archived.text
        restored = await client.post(f"/api/v1/events/{event_id}/restore", headers=headers)
        assert restored.status_code == 200, restored.text
    counter = (await db_session.execute(text("""
        SELECT value FROM usage_counters WHERE tenant_id=:tid
          AND period_start=date_trunc('month', CURRENT_DATE)::date AND key='events_per_month'
    """), {"tid": str(tenant_id)})).scalar()
    assert counter == 9999


@pytest.mark.integration
@pytest.mark.asyncio
async def test_usage_screen_counts_active_records_not_group_people(db_session, org_world):
    from sqlalchemy import text

    tenant_id, event_id = org_world["requester_tenant"], org_world["event_id"]
    for status, people in [("accepted", 4), ("created", 1), ("revoked", 3), ("expired", 2)]:
        await db_session.execute(text("""
            INSERT INTO invitations (tenant_id, event_id, token, ticket_class, status, guest_count)
            VALUES (:tid, :eid, :token, 'normal', :status, :people)
        """), {"tid": str(tenant_id), "eid": str(event_id), "token": uuid4().hex,
                 "status": status, "people": people})
    usage = await usage_service.get_static_usage(db_session, tenant_id)
    assert usage["invitations_per_event"] == 2
