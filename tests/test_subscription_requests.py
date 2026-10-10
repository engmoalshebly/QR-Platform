"""End-to-end coverage for the manual (staff-approved) subscription flow.

Link Gateway is disabled by business decision: a tenant submits a plan
request, a platform staff member reviews it and either activates the
subscription (after verifying payment out of band) or rejects it.
"""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user
from app.database import get_db, get_privileged_db
from app.main import app
from tests.auth_helpers import actor_client


async def _seed_tenant_with_owner(db_session, name: str):
    tenant_id, owner_id = uuid4(), uuid4()
    email = f"owner-{owner_id}@example.com"
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
    """), {"id": str(owner_id), "email": email})
    await db_session.execute(text(
        "INSERT INTO tenants (id, name, slug, status, plan) VALUES (:id, :name, :slug, 'active', 'starter')"
    ), {"id": str(tenant_id), "name": name, "slug": f"sub-{tenant_id.hex[:8]}"})
    await db_session.execute(text(
        "INSERT INTO memberships (tenant_id, user_id, role, status) VALUES (:tid, :uid, 'owner', 'active')"
    ), {"tid": str(tenant_id), "uid": str(owner_id)})
    await db_session.flush()
    return tenant_id, owner_id, email


async def _seed_staff(db_session):
    staff_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
    """), {"id": str(staff_id), "email": f"staff-{staff_id}@example.com"})
    await db_session.execute(text("UPDATE profiles SET is_staff = true WHERE id = :id"), {"id": str(staff_id)})
    await db_session.flush()
    return staff_id


async def _as_staff(db_session, staff_id):
    """A client for the exempt, staff-only /api/v1/platform/* routes — no
    tenant header or membership check applies there."""
    async def _staff_user():
        return CurrentUser(id=staff_id, email="staff@example.com", role="authenticated", aal="aal2")
    app.dependency_overrides[get_current_user] = _staff_user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_privileged_db] = lambda: db_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_tenant_request_then_staff_approval_activates_the_plan(db_session, monkeypatch):
    from app.routes import platform as platform_routes
    monkeypatch.setattr(platform_routes, "send_subscription_upgraded_email", lambda *a, **k: None)

    tenant_id, owner_id, _ = await _seed_tenant_with_owner(db_session, "Requesting Co")
    plan_id = (await db_session.execute(text("SELECT id FROM plans WHERE code = 'basic'"))).scalar()
    if plan_id is None:
        pytest.skip("no 'basic' plan seeded in this database")
    staff_id = await _seed_staff(db_session)

    async with actor_client(db_session, owner_id) as client:
        resp = await client.post(
            "/api/v1/subscriptions/request",
            json={"plan_code": "basic", "period": "monthly", "notes": "حوالة بنكية رقم 12345"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending_review"
    request_id = body["request_id"]

    pending = (await db_session.execute(
        text("SELECT provider, metadata FROM pending_subscriptions WHERE id = :id"), {"id": request_id}
    )).mappings().one()
    assert pending["provider"] == "manual"
    assert pending["metadata"]["plan_code"] == "basic"

    # A second request while one is pending must be refused.
    async with actor_client(db_session, owner_id) as client:
        dup = await client.post(
            "/api/v1/subscriptions/request",
            json={"plan_code": "basic", "period": "monthly"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
    assert dup.status_code == 409

    client = await _as_staff(db_session, staff_id)
    try:
        approval = await client.post(
            f"/api/v1/platform/subscription-requests/{request_id}/approve",
            json={"payment_reference": "TRX-998877", "valid_until": "2099-01-01T00:00:00Z"},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
    assert approval.status_code == 200, approval.text

    sub = (await db_session.execute(text("""
        SELECT s.status, s.provider_subscription_id, p.code
        FROM subscriptions s JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = :tid
    """), {"tid": str(tenant_id)})).mappings().one()
    assert sub["status"] == "active"
    assert sub["provider_subscription_id"] == "TRX-998877"
    assert sub["code"] == "basic"

    tenant_plan = await db_session.scalar(text("SELECT plan FROM tenants WHERE id = :id"), {"id": str(tenant_id)})
    assert tenant_plan == "basic"

    still_pending = await db_session.scalar(
        text("SELECT count(*) FROM pending_subscriptions WHERE id = :id"), {"id": request_id}
    )
    assert still_pending == 0

    notified = await db_session.scalar(text("""
        SELECT count(*) FROM notifications WHERE tenant_id = :tid AND type = 'subscription.activated'
    """), {"tid": str(tenant_id)})
    assert notified == 1


@pytest.mark.asyncio
async def test_staff_rejection_frees_the_tenant_to_request_again(db_session, monkeypatch):
    from app.routes import platform as platform_routes
    monkeypatch.setattr(platform_routes, "send_subscription_request_rejected", lambda *a, **k: None)

    tenant_id, owner_id, _ = await _seed_tenant_with_owner(db_session, "Rejected Co")
    plan_id = (await db_session.execute(text("SELECT id FROM plans WHERE code = 'basic'"))).scalar()
    if plan_id is None:
        pytest.skip("no 'basic' plan seeded in this database")
    staff_id = await _seed_staff(db_session)

    async with actor_client(db_session, owner_id) as client:
        resp = await client.post(
            "/api/v1/subscriptions/request",
            json={"plan_code": "basic"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
    request_id = resp.json()["request_id"]

    client = await _as_staff(db_session, staff_id)
    try:
        rejection = await client.post(
            f"/api/v1/platform/subscription-requests/{request_id}/reject",
            json={"note": "الحوالة غير واضحة، يرجى إعادة الإرسال"},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
    assert rejection.status_code == 200, rejection.text

    remaining = await db_session.scalar(
        text("SELECT count(*) FROM pending_subscriptions WHERE id = :id"), {"id": request_id}
    )
    assert remaining == 0

    rejected_audit = await db_session.scalar(text("""
        SELECT count(*) FROM audit_logs WHERE tenant_id = :tid AND action = 'subscription.rejected_manual'
    """), {"tid": str(tenant_id)})
    assert rejected_audit == 1

    # The tenant can submit a new request now that the old one is gone.
    async with actor_client(db_session, owner_id) as client:
        again = await client.post(
            "/api/v1/subscriptions/request",
            json={"plan_code": "basic"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
    assert again.status_code == 202, again.text


@pytest.mark.asyncio
async def test_custom_plan_submit_review_activate_cycle(db_session, monkeypatch):
    from app.routes import platform as platform_routes
    monkeypatch.setattr(platform_routes, "send_subscription_upgraded_email", lambda *a, **k: None)

    tenant_id, owner_id, _ = await _seed_tenant_with_owner(db_session, "Custom Plan Co")
    staff_id = await _seed_staff(db_session)

    async with actor_client(db_session, owner_id) as client:
        created = await client.post(
            "/api/v1/custom-plans",
            json={"base_plan_code": "starter", "items": [], "name": "خطتي"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
        assert created.status_code == 201, created.text
        custom_plan_id = created.json()["id"]

        submitted = await client.post(
            f"/api/v1/custom-plans/{custom_plan_id}/request",
            json={"period": "yearly", "notes": "دفع نقدي عند التوقيع"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
    assert submitted.status_code == 202, submitted.text

    status_value = await db_session.scalar(
        text("SELECT status FROM custom_plans WHERE id = :id"), {"id": custom_plan_id}
    )
    assert status_value == "pending_review"

    client = await _as_staff(db_session, staff_id)
    try:
        pending_list = await client.get("/api/v1/platform/custom-plans/pending")
        assert any(row["id"] == custom_plan_id for row in pending_list.json())

        activated = await client.post(
            f"/api/v1/platform/custom-plans/{custom_plan_id}/activate",
            json={"payment_reference": "CASH-001", "valid_until": "2099-01-01T00:00:00Z"},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
    assert activated.status_code == 200, activated.text

    final_status = await db_session.scalar(
        text("SELECT status FROM custom_plans WHERE id = :id"), {"id": custom_plan_id}
    )
    assert final_status == "active"


@pytest.mark.asyncio
async def test_custom_plan_rejection_returns_it_to_draft(db_session, monkeypatch):
    from app.routes import platform as platform_routes
    monkeypatch.setattr(platform_routes, "send_subscription_request_rejected", lambda *a, **k: None)

    tenant_id, owner_id, _ = await _seed_tenant_with_owner(db_session, "Custom Reject Co")
    staff_id = await _seed_staff(db_session)

    async with actor_client(db_session, owner_id) as client:
        created = await client.post(
            "/api/v1/custom-plans",
            json={"base_plan_code": "starter", "items": [], "name": "خطتي الثانية"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
        custom_plan_id = created.json()["id"]
        await client.post(
            f"/api/v1/custom-plans/{custom_plan_id}/request",
            json={"period": "monthly"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    client = await _as_staff(db_session, staff_id)
    try:
        rejected = await client.post(
            f"/api/v1/platform/custom-plans/{custom_plan_id}/reject",
            json={"note": "السعر لا يطابق الإضافات المطلوبة"},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
    assert rejected.status_code == 200, rejected.text

    row = (await db_session.execute(
        text("SELECT status, requested_period FROM custom_plans WHERE id = :id"), {"id": custom_plan_id}
    )).mappings().one()
    assert row["status"] == "draft"
    assert row["requested_period"] is None
