from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from starlette.requests import Request

from app.auth import CurrentUser
from app.main import app
from app.models.event import EventCreate, EventGateCreate, EventStatusTransitionRequest
from app.models.registration_form import PublicRegistrationSubmit, RegistrationFormCreate, RegistrationFormField


def _event(**overrides):
    values = {
        "title": "Production event",
        "start_date": datetime.now(timezone.utc) + timedelta(days=2),
        "end_date": datetime.now(timezone.utc) + timedelta(days=2, hours=4),
        "timezone": "Asia/Riyadh",
        "venue_name": "Main hall",
    }
    values.update(overrides)
    return EventCreate(**values)


def test_event_contract_rejects_invalid_timezone_coordinates_and_color():
    with pytest.raises(ValidationError):
        _event(timezone="Mars/Capital")
    with pytest.raises(ValidationError):
        _event(venue_lat=100)
    with pytest.raises(ValidationError):
        _event(theme_color="red")


def test_gate_contract_rejects_unknown_classes_and_duplicate_users():
    with pytest.raises(ValidationError):
        EventGateCreate(name="Gate", allowed_classes=["staff"])
    member = uuid4()
    with pytest.raises(ValidationError):
        EventGateCreate(name="Gate", assigned_users=[member, member])


def test_registration_contract_requires_idempotency_and_unique_fields():
    with pytest.raises(ValidationError):
        PublicRegistrationSubmit(guest_name="Guest", guest_phone="0500000000")
    duplicate = RegistrationFormField(id="company", type="text", label="Company")
    with pytest.raises(ValidationError):
        RegistrationFormCreate(fields=[duplicate, duplicate])


def test_event_lifecycle_routes_are_exposed():
    paths = app.openapi()["paths"]
    assert "/api/v1/events/{event_id}/transition" in paths
    assert "/api/v1/events/{event_id}/restore" in paths
    assert "/api/v1/events/{event_id}/assets" in paths
    assert "/api/v1/events/{event_id}/assets/{asset_id}" in paths


def test_v56_migration_contains_idempotency_and_public_slug_guards():
    migration = Path("supabase/migration_v56_event_lifecycle_production.sql").read_text(encoding="utf-8")
    assert "uq_registration_request_per_event" in migration
    assert "uq_events_public_slug" in migration
    assert "REVOKE ALL ON FUNCTION public.transition_event_status" in migration


@pytest.mark.asyncio
async def test_public_registration_rejects_reused_phone_and_email(
    db_session, org_world, client_factory,
):
    slug = f"duplicate-registration-{uuid4().hex[:8]}"
    await db_session.execute(text("""
        UPDATE events
        SET slug=:slug, status='published', end_date=start_date + interval '4 hours', venue_name='Main hall'
        WHERE id=:event_id
    """), {"slug": slug, "event_id": str(org_world["event_id"])})
    await db_session.execute(text("""
        INSERT INTO event_registration_forms
          (tenant_id, event_id, is_enabled, barcode_generation_mode, default_ticket_class, fields)
        VALUES (:tenant_id, :event_id, true, 'immediate', 'normal', '[]'::jsonb)
        ON CONFLICT (event_id) DO UPDATE SET is_enabled=true
    """), {
        "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]),
    })
    await db_session.execute(text("""
        INSERT INTO invitations
          (id, tenant_id, event_id, token, ticket_class, guest_name, guest_phone,
           guest_email, status, is_registration)
        VALUES (:id, :tenant_id, :event_id, :token, 'normal', 'Existing Guest',
                '+967 777-123-456', 'Guest@Example.com', 'accepted', true)
    """), {
        "id": str(uuid4()), "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]), "token": uuid4().hex,
    })

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(f"/api/v1/public/events/{slug}/register", json={
            "registration_request_id": str(uuid4()),
            "guest_name": "Duplicate Guest",
            "guest_phone": "+967 (777) 123-456",
            "guest_email": "guest@example.COM",
            "custom_answers": {},
        })

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "message": "سبق التسجيل في هذا الحدث بهذه البيانات",
        "fields": ["رقم الهاتف", "البريد الإلكتروني"],
    }


def test_gate_limit_lock_resolves_owner_before_use():
    source = Path("app/routes/events.py").read_text(encoding="utf-8")
    owner = source.index("event_owner_tid = await get_event_owner_tenant", source.index("async def create_gate"))
    lock = source.index("await acquire_plan_limit_lock", source.index("async def create_gate"))
    assert owner < lock


@pytest.mark.asyncio
async def test_locked_event_transition_runs_full_database_workflow(db_session, org_world):
    from app.routes.events import _transition_event

    await db_session.execute(text("""
        UPDATE events SET end_date=start_date + interval '4 hours', venue_name='Main hall'
        WHERE id=:id
    """), {"id": str(org_world["event_id"])})
    request = Request({"type": "http", "method": "POST", "path": "/test", "headers": []})
    actor = CurrentUser(id=org_world["requester_user"], role="authenticated")

    published = await _transition_event(
        db_session, org_world["event_id"], org_world["requester_tenant"], actor, request, "published",
    )
    assert published.status == "published"
    active = await _transition_event(
        db_session, org_world["event_id"], org_world["requester_tenant"], actor, request, "active",
    )
    assert active.status == "active"
    completed = await _transition_event(
        db_session, org_world["event_id"], org_world["requester_tenant"], actor, request, "completed",
    )
    assert completed.status == "completed"
