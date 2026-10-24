"""pytest fixtures for Phase 1 integration tests.

Strategy: spin up a single async SQLAlchemy connection per test, wrap every
fixture + request in one transaction, and roll it back at teardown. This gives
real-DB isolation with no cleanup boilerplate.

The FastAPI app's `get_current_user` and `get_db` dependencies are overridden so
the tests do NOT need a real Supabase JWT: we synthesize a CurrentUser and a
tenant, and the DB session the routes receive is the test's transactional
session, so all writes roll back automatically.
"""
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.database import AsyncSessionLocal, engine, get_db, get_privileged_db
from app.main import app
from tests.auth_helpers import BorrowedSession, make_access_token

# These legacy files are interactive/manual scripts. Several perform HTTP
# calls at import time, so importing them is not a valid test collection step.
collect_ignore = [
    "test_asset.py", "test_connections.py", "test_auth_provisioning.py",
    "test_connectivity.py", "test_custom_plans.py", "test_db.py",
    "test_db_direct.py", "test_debug.py", "test_event_creation.py",
    "test_events_api.py", "test_full_api.py", "test_gate_create.py",
    "test_health.py", "test_plans_api.py", "test_plans_quick.py",
    "test_platform_admin.py", "test_quick.py", "test_req.py",
    "test_users_endpoints.py", "test_users_simple.py",
]


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A transactional session: everything is rolled back at test end."""
    try:
        connection = await engine.connect()
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {type(exc).__name__}")
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


def _make_current_user(user_id) -> CurrentUser:
    return CurrentUser(id=user_id, email="test-actor@example.com", role="authenticated")


@pytest.fixture
def auth_headers():
    """Tenant selection header only.  The bearer token belongs to the actor the
    client is built for (client_factory), so membership is checked for real."""
    def _build(tenant_id):
        return {"X-Tenant-ID": str(tenant_id)}
    return _build


@pytest.fixture
def tenant_headers():
    return lambda tenant_id: {"X-Tenant-ID": str(tenant_id)}


@pytest_asyncio.fixture
async def org_world(db_session: AsyncSession):
    """Create a minimal two-tenant world: an organizer org + an approved provider team.

    Returns a dict with ids + the requester/provider user profile ids and the
    X-Tenant-ID header value to use for each actor.
    """
    requester_user = uuid4()
    provider_user = uuid4()
    requester_tenant = uuid4()
    provider_tenant = uuid4()
    event_id = uuid4()

    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES
          (:ruid, 'org-test@example.com', 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000'),
          (:puid, 'team-test@example.com', 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
        ON CONFLICT (id) DO NOTHING
    """), {"ruid": str(requester_user), "puid": str(provider_user)})

    await db_session.execute(text("""
        INSERT INTO profiles (id, full_name, phone) VALUES
          (:ruid, 'مدير المؤسسة', '0500000001'),
          (:puid, 'مدير الفريق', '0500000002')
        ON CONFLICT (id) DO NOTHING
    """), {"ruid": str(requester_user), "puid": str(provider_user)})

    await db_session.execute(text("""
        INSERT INTO tenants (id, name, slug, status) VALUES
          (:rtid, 'مؤسسة اختبار', 'org-test', 'active'),
          (:ptid, 'فريق تنظيم اختبار', 'team-test', 'active')
        ON CONFLICT (id) DO NOTHING
    """), {"rtid": str(requester_tenant), "ptid": str(provider_tenant)})

    await db_session.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status) VALUES
          (:rtid, :ruid, 'owner', 'active'),
          (:ptid, :puid, 'owner', 'active')
        ON CONFLICT DO NOTHING
    """), {"rtid": str(requester_tenant), "ruid": str(requester_user),
           "ptid": str(provider_tenant), "puid": str(provider_user)})

    # Mark the provider team as an approved organizer so booking/inbox flows
    # treat it as a bookable provider. created_tenant_id links the approval to
    # the provider tenant; full_name/email/phone mirror the applicant.
    await db_session.execute(text("""
        INSERT INTO organization_requests
          (status, full_name, email, phone, org_name, org_type, created_tenant_id, reviewed_at)
        VALUES ('approved', 'مدير الفريق', 'team-test@example.com', '0500000002',
                'فريق تنظيم اختبار', 'تنظيم فعاليات', :ptid, now())
        ON CONFLICT DO NOTHING
    """), {"ptid": str(provider_tenant)})

    await db_session.execute(text("""
        INSERT INTO events (id, tenant_id, title, start_date, status)
        VALUES (:eid, :rtid, 'حفل اختبار', now() + interval '7 days', 'draft')
        ON CONFLICT (id) DO NOTHING
    """), {"eid": str(event_id), "rtid": str(requester_tenant)})

    return {
        "requester_user": requester_user,
        "provider_user": provider_user,
        "requester_tenant": requester_tenant,
        "provider_tenant": provider_tenant,
        "event_id": event_id,
    }


@pytest_asyncio.fixture
async def client_factory(db_session: AsyncSession, org_world):
    """Build an AsyncClient whose requests see the transactional DB session and a
    synthetic authenticated user. Call with the user_id of the actor for this request.
    """

    patcher = patch("app.middleware.AsyncSessionLocal", lambda: BorrowedSession(db_session))
    patcher.start()

    def _build(actor_user_id):
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_privileged_db] = lambda: db_session

        async def _current_user():
            return _make_current_user(actor_user_id)

        from app.auth import get_current_user
        app.dependency_overrides[get_current_user] = _current_user

        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {make_access_token(actor_user_id)}"}
        return AsyncClient(transport=transport, base_url="http://test", headers=headers)

    yield _build

    patcher.stop()
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Tenant/membership answers are cached per process; never across tests."""
    from app.services import access_cache
    access_cache.clear()
    yield
    access_cache.clear()
