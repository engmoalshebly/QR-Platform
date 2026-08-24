"""Regression coverage for event setup data and its cross-field validation."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.models.event import EventCreate


pytestmark = pytest.mark.integration


def test_event_create_rejects_invalid_schedule_and_capacity():
    with pytest.raises(ValidationError, match="end_date must be later"):
        EventCreate(
            title="حدث اختبار",
            start_date=datetime.fromisoformat("2027-01-10T12:00:00+00:00"),
            end_date=datetime.fromisoformat("2027-01-10T11:00:00+00:00"),
        )

    with pytest.raises(ValidationError, match="cannot exceed total capacity"):
        EventCreate(
            title="حدث اختبار",
            start_date=datetime.fromisoformat("2027-01-10T12:00:00+00:00"),
            capacity=100,
            vip_capacity=40,
            normal_capacity=70,
        )


@pytest.mark.asyncio
async def test_event_create_persists_full_setup_contract(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """The create endpoint must preserve every setup field advertised by EventCreate."""
    from app.middleware import TenantResolutionMiddleware
    from app.routes import events as events_routes
    from app.services import feature_service

    async def _transactional_tenant_context(_middleware, _request, call_next):
        return await call_next(_request)

    async def _allow(*_args, **_kwargs):
        return None

    async def _unlimited(*_args, **_kwargs):
        return -1

    monkeypatch.setattr(TenantResolutionMiddleware, "dispatch", _transactional_tenant_context)
    monkeypatch.setattr(events_routes, "require_permission", _allow)
    monkeypatch.setattr(events_routes, "log_audit", _allow)
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", _allow)
    monkeypatch.setattr(feature_service, "get_plan_limit", _unlimited)

    category_id, event_type_id, team_id = uuid4(), uuid4(), uuid4()
    await db_session.execute(text("""
        INSERT INTO event_categories (id, tenant_id, name)
        VALUES (:id, :tenant_id, 'اختبار مخصص')
    """), {"id": str(category_id), "tenant_id": str(org_world["requester_tenant"])})
    await db_session.execute(text("""
        INSERT INTO event_types (id, category_id, tenant_id, name)
        VALUES (:id, :category_id, :tenant_id, 'نوع اختبار مخصص')
    """), {
        "id": str(event_type_id), "category_id": str(category_id),
        "tenant_id": str(org_world["requester_tenant"]),
    })
    await db_session.execute(text("""
        INSERT INTO teams (id, tenant_id, name, created_by)
        VALUES (:id, :tenant_id, 'فريق الإعداد', :user_id)
    """), {
        "id": str(team_id), "tenant_id": str(org_world["requester_tenant"]),
        "user_id": str(org_world["requester_user"]),
    })

    payload = {
        "event_type_id": str(event_type_id),
        "category_id": str(category_id),
        "title": "حفل التخرج 2027",
        "title_ar": "حفل التخرج بالعربية",
        "description": "وصف كامل للحدث",
        "start_date": "2027-06-01T18:00:00+03:00",
        "end_date": "2027-06-01T22:00:00+03:00",
        "timezone": "Asia/Riyadh",
        "venue_name": "قاعة الاختبار",
        "venue_name_ar": "قاعة الاختبار العربية",
        "venue_address": "شارع الاختبار 1",
        "venue_city": "الرياض",
        "venue_country": "SA",
        "venue_map_url": "https://maps.example.test/event",
        "venue_lat": 24.7136,
        "venue_lng": 46.6753,
        "vip_quota": 5,
        "normal_quota": 20,
        "capacity": 120,
        "vip_capacity": 10,
        "normal_capacity": 90,
        "allow_rsvp": True,
        "allow_plus_one": True,
        "allow_reentry": True,
        "require_name": False,
        "cover_image_url": "https://cdn.example.test/cover.webp",
        "theme_color": "#123456",
        "team_id": str(team_id),
        "metadata": {"source": "event-setup-regression", "locale": "ar"},
    }

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post("/api/v1/events", json=payload, headers=auth_headers(org_world["requester_tenant"]))

    assert response.status_code == 201, response.text
    event_id = response.json()["id"]
    row = (await db_session.execute(text("SELECT * FROM events WHERE id = :id"), {"id": event_id})).mappings().one()

    assert str(row["event_type_id"]) == str(event_type_id)
    assert str(row["category_id"]) == str(category_id)
    assert row["title_ar"] == payload["title_ar"]
    assert row["description"] == payload["description"]
    assert row["end_date"] - row["start_date"] == timedelta(hours=4)
    assert row["venue_name"] == payload["venue_name"]
    assert row["venue_name_ar"] == payload["venue_name_ar"]
    assert row["venue_address"] == payload["venue_address"]
    assert row["venue_city"] == payload["venue_city"]
    assert row["venue_map_url"] == payload["venue_map_url"]
    assert float(row["venue_lat"]) == pytest.approx(payload["venue_lat"])
    assert float(row["venue_lng"]) == pytest.approx(payload["venue_lng"])
    assert (row["capacity"], row["vip_capacity"], row["normal_capacity"]) == (120, 10, 90)
    assert str(row["team_id"]) == str(team_id)
    assert row["cover_image_url"] == payload["cover_image_url"]
    assert row["metadata"] == payload["metadata"]


@pytest.mark.asyncio
async def test_arabic_only_event_title_gets_valid_public_slug(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    from app.middleware import TenantResolutionMiddleware
    from app.routes import events as events_routes
    from app.services import feature_service

    async def _transactional_tenant_context(_middleware, _request, call_next):
        return await call_next(_request)

    async def _allow(*_args, **_kwargs):
        return None

    async def _unlimited(*_args, **_kwargs):
        return -1

    monkeypatch.setattr(TenantResolutionMiddleware, "dispatch", _transactional_tenant_context)
    monkeypatch.setattr(events_routes, "require_permission", _allow)
    monkeypatch.setattr(events_routes, "log_audit", _allow)
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", _allow)
    monkeypatch.setattr(feature_service, "get_plan_limit", _unlimited)

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post("/api/v1/events", headers=auth_headers(org_world["requester_tenant"]), json={
            "title": "فعالية عربية",
            "start_date": "2027-07-01T18:00:00+03:00",
            "end_date": "2027-07-01T21:00:00+03:00",
            "venue_name": "قاعة الاختبار",
        })

    assert response.status_code == 201, response.text
    assert response.json()["slug"].startswith("event-")
    assert not response.json()["slug"].startswith("-")


@pytest.mark.asyncio
async def test_registration_form_can_be_created_and_saved_with_expiry(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """Regression: v10 omitted expires_at although both GET and save use it."""
    from app.middleware import TenantResolutionMiddleware
    from app.routes import registration_forms

    async def _transactional_tenant_context(_middleware, _request, call_next):
        return await call_next(_request)

    async def _allow(*_args, **_kwargs):
        return None

    monkeypatch.setattr(TenantResolutionMiddleware, "dispatch", _transactional_tenant_context)
    monkeypatch.setattr(registration_forms, "require_permission", _allow)
    monkeypatch.setattr(registration_forms, "log_audit", _allow)

    event_id = str(org_world["event_id"])
    tenant_id = org_world["requester_tenant"]
    await db_session.execute(
        text("DELETE FROM event_registration_forms WHERE event_id = :event_id"),
        {"event_id": event_id},
    )

    headers = auth_headers(tenant_id)
    async with client_factory(org_world["requester_user"]) as client:
        initial = await client.get(
            f"/api/v1/events/{event_id}/registration-form", headers=headers,
        )
        assert initial.status_code == 200, initial.text
        assert initial.json()["expires_at"] is None

        saved = await client.post(
            f"/api/v1/events/{event_id}/registration-form",
            headers=headers,
            json={
                "is_enabled": False,
                "barcode_generation_mode": "immediate",
                "default_ticket_class": "normal",
                "fields": [{
                    "id": "guest_name", "type": "text",
                    "label": "الاسم الكامل", "required": True, "system": True,
                }],
                "expires_at": "2027-06-02T00:00:00+03:00",
            },
        )

    assert saved.status_code == 200, saved.text
    assert saved.json()["expires_at"].startswith("2027-06-01T21:00:00")
