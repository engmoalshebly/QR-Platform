"""The real get_db() must run on the RLS-enforced role with the tenant context set.

The rest of the suite overrides get_db to use the transactional test session,
which hides this wiring.  This test calls the real dependency.  It runs only when
DATABASE_APP_URL names a distinct role, as in CI, so it cannot pass by accident
on a superuser-only setup.
"""
import os

import pytest
from sqlalchemy import text

from app.database import get_db
from app.database import AppSessionLocal, AsyncSessionLocal
from app.tenant_context import clear_current_tenant, set_current_tenant

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_APP_URL"),
    reason="DATABASE_APP_URL not configured for this run",
)


@pytest.mark.asyncio
async def test_get_db_connects_as_rls_role_and_sets_tenant():
    tenant_id = "11111111-2222-3333-4444-555555555555"
    set_current_tenant({"id": tenant_id, "slug": "wiring", "name": "w", "status": "active", "plan": "p"})
    try:
        gen = get_db()
        session = await gen.__anext__()
        try:
            row = (await session.execute(text("""
                SELECT current_user, r.rolbypassrls, r.rolsuper, current_tenant_id()
                FROM pg_roles r WHERE r.rolname = current_user
            """))).first()
            assert row[0] == "qentry_app"
            assert row[1] is False and row[2] is False
            assert str(row[3]) == tenant_id
        finally:
            await gen.aclose()
    finally:
        clear_current_tenant()


@pytest.mark.asyncio
async def test_get_db_without_tenant_context_returns_no_tenant_rows():
    clear_current_tenant()
    gen = get_db()
    session = await gen.__anext__()
    try:
        visible = (await session.execute(text("SELECT count(*) FROM events"))).scalar()
        assert visible == 0
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_qentry_app_can_execute_every_security_definer_function():
    """migration_v49 revokes PUBLIC's default EXECUTE on every SECURITY
    DEFINER function in public schema; each one then needs an explicit grant
    to qentry_app (or the default-privileges rule from migration_v70) or the
    RLS-enforced session gets "permission denied for function X" the moment
    application code calls it -- not a business-logic denial, a hard SQL
    error, on the *first* real request (confirmed live: user_has_permission()
    broke every require_permission() call; GET /dashboard/analytics 500'd).

    This is deliberately generic over every current SECURITY DEFINER
    function, not just user_has_permission, because the gap was never
    "one function someone forgot" -- 17 of 21 had it. The business-logic
    tests elsewhere in this suite run through db_session (the privileged
    engine, for convenience), which has no grants to miss, so none of them
    could have caught this; this file is the one place already wired to the
    real qentry_app login.
    """
    clear_current_tenant()
    gen = get_db()
    session = await gen.__anext__()
    try:
        rows = (await session.execute(text("""
            SELECT p.oid::regprocedure::text AS signature
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef = true
        """))).all()
        assert rows, "expected at least one SECURITY DEFINER function to check"
        missing = []
        for (signature,) in rows:
            has_exec = (await session.execute(
                text("SELECT has_function_privilege('qentry_app', :sig, 'EXECUTE')"),
                {"sig": signature},
            )).scalar()
            if not has_exec:
                missing.append(signature)
        assert not missing, f"qentry_app missing EXECUTE on: {missing}"
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_qentry_app_can_read_auth_users_email():
    """auth.users lives outside every public-schema migration, so qentry_app
    never automatically inherited access the way public tables do through
    migration_v52's blanket grants. migration_v71 grants column-level
    SELECT(id, email) plus a permissive RLS policy scoped to this one role
    -- both were needed: real Supabase enables RLS on auth.users with zero
    policies defined, so the grant alone still silently returned NULL for
    every row (GET /api/v1/tenants/current/members showed a real member
    with email=None, no error, before the policy was added). A column grant
    without the matching policy is exactly the kind of gap that looks fixed
    in a quick check but isn't; this asserts the actual value round-trips,
    not just that the grant exists.
    """
    import uuid
    user_id = uuid.uuid4()
    email = f"wiring-check-{user_id.hex[:8]}@example.com"

    async with AsyncSessionLocal() as privileged:
        await privileged.execute(text("""
            INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
            VALUES (:id, :email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
            ON CONFLICT (id) DO NOTHING
        """), {"id": str(user_id), "email": email})
        await privileged.commit()

    clear_current_tenant()
    gen = get_db()
    session = await gen.__anext__()
    try:
        result = (await session.execute(
            text("SELECT email FROM auth.users WHERE id = :id"),
            {"id": str(user_id)},
        )).scalar()
        assert result == email
    finally:
        await gen.aclose()
