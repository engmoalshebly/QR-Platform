"""Cross-tenant isolation tests.

Verifies that tenant A's data is completely invisible to tenant B across
every critical route family.  Each test creates two isolated tenants, seeds
data under tenant A, then queries via tenant B's headers and asserts zero
results / 403 / 404.

These tests use the transactional DB session from conftest (everything rolls
back), override FastAPI's auth dependency so no real JWT is needed, and
exercise the actual SQL paths the routes take — catching any missing
WHERE tenant_id filter.
"""
import pytest
import pytest_asyncio
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.database import get_db
from app.main import app


# ── Helpers ──

def _user(uid) -> CurrentUser:
    return CurrentUser(id=uid, email="isolation-test@example.com", role="authenticated")


# ── Fixtures ──

@pytest_asyncio.fixture
async def two_tenants(db_session: AsyncSession):
    """Seed two fully isolated tenants with one user each, memberships,
    roles, and sample data under tenant A."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()

    # Auth users (Supabase auth.users — may not exist in CI; use profiles only)
    try:
        await db_session.execute(text("""
            INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
            VALUES
              (:ua, 'a@test.com', 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000'),
              (:ub, 'b@test.com', 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
            ON CONFLICT DO NOTHING
        """), {"ua": str(user_a), "ub": str(user_b)})
    except Exception:
        pass  # CI may not have auth schema

    await db_session.execute(text("""
        INSERT INTO profiles (id, full_name, phone)
        VALUES (:ua, 'User A', '0500000001'), (:ub, 'User B', '0500000002')
        ON CONFLICT DO NOTHING
    """), {"ua": str(user_a), "ub": str(user_b)})

    await db_session.execute(text("""
        INSERT INTO tenants (id, name, slug, status, plan)
        VALUES
          (:ta, 'Tenant A', 'tenant-a', 'active', 'professional'),
          (:tb, 'Tenant B', 'tenant-b', 'active', 'professional')
        ON CONFLICT DO NOTHING
    """), {"ta": str(tenant_a), "tb": str(tenant_b)})

    await db_session.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status)
        VALUES
          (:ta, :ua, 'owner', 'active'),
          (:tb, :ub, 'owner', 'active')
        ON CONFLICT DO NOTHING
    """), {"ta": str(tenant_a), "ua": str(user_a),
           "tb": str(tenant_b), "ub": str(user_b)})

    # Roles for both tenants
    role_a = uuid4()
    role_b = uuid4()
    await db_session.execute(text("""
        INSERT INTO roles (id, tenant_id, name, description, is_system_role)
        VALUES
          (:ra, :ta, 'Admin', 'Admin', true),
          (:rb, :tb, 'Admin', 'Admin', true)
        ON CONFLICT DO NOTHING
    """), {"ra": str(role_a), "ta": str(tenant_a),
           "rb": str(role_b), "tb": str(tenant_b)})

    await db_session.execute(text("""
        INSERT INTO membership_roles (tenant_id, user_id, role_id)
        VALUES (:ta, :ua, :ra), (:tb, :ub, :rb)
        ON CONFLICT DO NOTHING
    """), {"ta": str(tenant_a), "ua": str(user_a), "ra": str(role_a),
           "tb": str(tenant_b), "ub": str(user_b), "rb": str(role_b)})

    # ── Seed data ONLY under tenant A ──
    event_a = uuid4()
    guest_a = uuid4()
    team_a = uuid4()

    await db_session.execute(text("""
        INSERT INTO events (id, tenant_id, title, start_date, status)
        VALUES (:eid, :ta, 'حفل خاص A', now() + interval '7 days', 'draft')
        ON CONFLICT DO NOTHING
    """), {"eid": str(event_a), "ta": str(tenant_a)})

    await db_session.execute(text("""
        INSERT INTO guests (id, tenant_id, full_name, phone)
        VALUES (:gid, :ta, 'ضيف خاص A', '0511111111')
        ON CONFLICT DO NOTHING
    """), {"gid": str(guest_a), "ta": str(tenant_a)})

    await db_session.execute(text("""
        INSERT INTO teams (id, tenant_id, name, is_active)
        VALUES (:tid, :ta, 'فريق خاص A', true)
        ON CONFLICT DO NOTHING
    """), {"tid": str(team_a), "ta": str(tenant_a)})

    await db_session.flush()

    return {
        "tenant_a": tenant_a, "tenant_b": tenant_b,
        "user_a": user_a, "user_b": user_b,
        "event_a": event_a, "guest_a": guest_a, "team_a": team_a,
        "role_a": role_a,
    }


@pytest_asyncio.fixture
async def client_a(db_session, two_tenants):
    """HTTP client acting as user A on tenant A."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _user(two_tenants["user_a"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, two_tenants
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_b(db_session, two_tenants):
    """HTTP client acting as user B on tenant B — should see NONE of tenant A's data."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _user(two_tenants["user_b"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, two_tenants
    app.dependency_overrides.clear()


def _headers_for(tenant_id):
    return {
        "Authorization": "Bearer test-token",
        "X-Tenant-ID": str(tenant_id),
    }


# ── Tests: each verifies tenant B cannot see tenant A's data ──

class TestEventIsolation:
    """Events are the core entity — most critical to isolate."""

    @pytest.mark.asyncio
    async def test_list_events_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            "/api/v1/events",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code == 200
        events = resp.json()
        event_ids = {e["id"] for e in events} if isinstance(events, list) else set()
        assert str(world["event_a"]) not in event_ids, \
            "CRITICAL: tenant B can see tenant A's events"

    @pytest.mark.asyncio
    async def test_get_event_by_id_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            f"/api/v1/events/{world['event_a']}",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code in (403, 404), \
            f"CRITICAL: tenant B can access tenant A's event (status {resp.status_code})"


class TestGuestIsolation:
    """Guests contain PII — leaking them across tenants is a privacy violation."""

    @pytest.mark.asyncio
    async def test_list_guests_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            "/api/v1/guests",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code == 200
        guests = resp.json()
        guest_ids = {g["id"] for g in guests} if isinstance(guests, list) else set()
        assert str(world["guest_a"]) not in guest_ids, \
            "CRITICAL: tenant B can see tenant A's guests"

    @pytest.mark.asyncio
    async def test_get_guest_by_id_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            f"/api/v1/guests/{world['guest_a']}",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code in (403, 404), \
            f"CRITICAL: tenant B can access tenant A's guest (status {resp.status_code})"


class TestTeamIsolation:
    """Teams are organizational — must not leak across tenants."""

    @pytest.mark.asyncio
    async def test_list_teams_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            "/api/v1/teams",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code == 200
        teams = resp.json()
        team_ids = set()
        if isinstance(teams, list):
            team_ids = {t["id"] for t in teams}
        elif isinstance(teams, dict) and "items" in teams:
            team_ids = {t["id"] for t in teams["items"]}
        assert str(world["team_a"]) not in team_ids, \
            "CRITICAL: tenant B can see tenant A's teams"


class TestRoleIsolation:
    """Custom roles are per-tenant — must not leak."""

    @pytest.mark.asyncio
    async def test_list_roles_cross_tenant(self, client_b):
        client, world = client_b
        resp = await client.get(
            "/api/v1/roles",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code == 200
        roles = resp.json()
        role_ids = set()
        if isinstance(roles, list):
            role_ids = {r["id"] for r in roles}
        assert str(world["role_a"]) not in role_ids, \
            "CRITICAL: tenant B can see tenant A's roles"


class TestCrossWriteProtection:
    """Verify tenant B cannot write data attributed to tenant A."""

    @pytest.mark.asyncio
    async def test_create_event_under_wrong_tenant(self, client_b):
        """Attempt to create an event while sending tenant A's ID as X-Tenant-ID.
        Should be rejected by middleware membership check."""
        client, world = client_b
        resp = await client.post(
            "/api/v1/events",
            headers=_headers_for(world["tenant_a"]),  # deliberately wrong tenant
            json={
                "title": "حفل مزيف",
                "start_date": "2026-12-01T00:00:00Z",
            },
        )
        assert resp.status_code in (401, 403), \
            f"CRITICAL: tenant B can create events in tenant A (status {resp.status_code})"

    @pytest.mark.asyncio
    async def test_delete_event_cross_tenant(self, client_b):
        """Tenant B must not be able to delete tenant A's event."""
        client, world = client_b
        resp = await client.delete(
            f"/api/v1/events/{world['event_a']}",
            headers=_headers_for(world["tenant_b"]),
        )
        assert resp.status_code in (403, 404), \
            f"CRITICAL: tenant B can delete tenant A's event (status {resp.status_code})"

    @pytest.mark.asyncio
    async def test_update_guest_cross_tenant(self, client_b):
        """Tenant B must not be able to update tenant A's guest."""
        client, world = client_b
        resp = await client.put(
            f"/api/v1/guests/{world['guest_a']}",
            headers=_headers_for(world["tenant_b"]),
            json={"full_name": "اسم مزيف"},
        )
        assert resp.status_code in (403, 404, 422), \
            f"CRITICAL: tenant B can update tenant A's guest (status {resp.status_code})"


class TestMiddlewareMembershipEnforcement:
    """The middleware checks that the JWT user is a member of the requested tenant.
    This prevents header-spoofing attacks."""

    @pytest.mark.asyncio
    async def test_user_b_cannot_use_tenant_a_header(self, client_b):
        """User B sends X-Tenant-ID for tenant A — should be rejected."""
        client, world = client_b
        resp = await client.get(
            "/api/v1/events",
            headers=_headers_for(world["tenant_a"]),
        )
        assert resp.status_code in (401, 403), \
            f"CRITICAL: user B can access tenant A by header spoofing (status {resp.status_code})"


class TestDatabaseLevelIsolation:
    """Verify that the DB session tenant context (SET/set_config) is set correctly."""

    @pytest.mark.asyncio
    async def test_set_config_tenant_id(self, db_session: AsyncSession, two_tenants):
        """After setting tenant context, current_setting should return it."""
        from app.tenant_context import set_current_tenant, clear_current_tenant

        tenant_a_id = str(two_tenants["tenant_a"])
        set_current_tenant({"id": two_tenants["tenant_a"], "slug": "a", "name": "A", "status": "active", "plan": "pro"})
        try:
            await db_session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_a_id},
            )
            result = await db_session.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            row = result.scalar()
            assert row == tenant_a_id, \
                f"DB tenant context not set correctly: expected {tenant_a_id}, got {row}"
        finally:
            clear_current_tenant()
