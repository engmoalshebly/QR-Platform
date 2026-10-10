"""Regression tests for tenant-status enforcement and exemption matching.

Before this change, TENANT_EXEMPT_PATHS matched by prefix, so
/api/v1/tenants/current/* skipped the tenant status check entirely and a
suspended tenant's owner could keep managing members and settings.
"""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.middleware import is_tenant_exempt
from app.services.permission_service import has_permission
from tests.auth_helpers import actor_client


# ── Exemption matching (pure, no database) ──

@pytest.mark.parametrize("path", [
    "/health",
    "/health/ready",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/change-password",
    "/api/v1/tenants",
    "/api/v1/plans",
    "/api/v1/platform/tenants",
    "/api/v1/auth/org-request/1234",
    "/api/v1/invites/accept/abc-token",
    "/api/v1/invitations/view/tok",
    "/api/v1/public/events/my-event/register",
    "/field/assets/app.js",
    "/api/v1/templates/fonts/file/Cairo.ttf",
])
def test_public_and_staff_paths_are_exempt(path):
    assert is_tenant_exempt(path)


@pytest.mark.parametrize("path", [
    "/api/v1/tenants/current",
    "/api/v1/tenants/current/members",
    "/api/v1/tenants/current/settings",
    "/api/v1/tenantsanything",
    "/api/v1/auth/unknown-future-route",
    "/api/v1/events",
    "/fieldx",
    "/api/v1/platformx/tenants",
])
def test_tenant_scoped_paths_are_not_exempt(path):
    assert not is_tenant_exempt(path)


# ── Enforcement against a real database transaction ──

@pytest_asyncio.fixture
async def suspended_world(db_session):
    """One owner whose tenant is suspended, and one healthy tenant for control."""
    owner = uuid4()
    suspended = uuid4()
    healthy = uuid4()
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:u, 'owner-status@test.com', 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
        ON CONFLICT DO NOTHING
    """), {"u": str(owner)})
    await db_session.execute(text(
        "INSERT INTO profiles (id, full_name) VALUES (:u, 'Owner') ON CONFLICT DO NOTHING"
    ), {"u": str(owner)})
    await db_session.execute(text("""
        INSERT INTO tenants (id, name, slug, status, plan) VALUES
          (:s, 'Suspended Co', :ss, 'suspended', 'professional'),
          (:h, 'Healthy Co', :hs, 'active', 'professional')
    """), {"s": str(suspended), "ss": f"susp-{suspended.hex[:8]}",
           "h": str(healthy), "hs": f"ok-{healthy.hex[:8]}"})
    await db_session.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status) VALUES
          (:s, :u, 'owner', 'active'), (:h, :u, 'owner', 'active')
    """), {"s": str(suspended), "h": str(healthy), "u": str(owner)})
    await db_session.flush()
    return {"owner": owner, "suspended": suspended, "healthy": healthy}


@pytest.mark.asyncio
async def test_suspended_tenant_owner_is_blocked_on_tenant_settings_routes(db_session, suspended_world):
    w = suspended_world
    async with actor_client(db_session, w["owner"]) as client:
        resp = await client.get(
            "/api/v1/tenants/current/members",
            headers={"X-Tenant-ID": str(w["suspended"])},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_suspended_tenant_owner_is_blocked_on_tenant_update(db_session, suspended_world):
    w = suspended_world
    async with actor_client(db_session, w["owner"]) as client:
        resp = await client.patch(
            "/api/v1/tenants/current",
            json={"name": "Renamed while suspended"},
            headers={"X-Tenant-ID": str(w["suspended"])},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_healthy_tenant_owner_still_reaches_tenant_routes(db_session, suspended_world):
    w = suspended_world
    async with actor_client(db_session, w["owner"]) as client:
        resp = await client.get(
            "/api/v1/tenants/current",
            headers={"X-Tenant-ID": str(w["healthy"])},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_has_permission_denies_every_permission_for_suspended_tenant(db_session, suspended_world):
    w = suspended_world
    assert await has_permission(db_session, w["suspended"], w["owner"], "settings.manage") is False
    assert await has_permission(db_session, w["healthy"], w["owner"], "settings.manage") is True
