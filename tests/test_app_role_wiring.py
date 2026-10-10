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
from app.database import AppSessionLocal
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
