"""Two concurrent POST /subscriptions/request calls for the same tenant must
not both create a pending_subscriptions row. The route's own check-then-insert
is a fast path, not a correctness guarantee under concurrency; migration_v68's
partial unique index (tenant_id WHERE provider='manual') is the real backstop,
mirroring the one migration_v64 already has for provider='link'."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_unique_index_rejects_a_second_concurrent_manual_request(db_session, org_world):
    """Directly exercises the DB-level backstop, independent of the route's
    own pre-check, the way a true race (two INSERTs between two SELECTs)
    would actually be caught."""
    tenant_id = org_world["requester_tenant"]
    plan_row = (await db_session.execute(text(
        "SELECT id FROM plans WHERE is_active = true LIMIT 1"
    ))).mappings().first()

    await db_session.execute(text("""
        INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id)
        VALUES (:tid, :pid, 'manual', :ref)
    """), {"tid": str(tenant_id), "pid": str(plan_row["id"]), "ref": f"manual_{uuid4().hex[:16]}"})

    with pytest.raises(IntegrityError):
        await db_session.execute(text("""
            INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id)
            VALUES (:tid, :pid, 'manual', :ref)
        """), {"tid": str(tenant_id), "pid": str(plan_row["id"]), "ref": f"manual_{uuid4().hex[:16]}"})
    await db_session.rollback()


@pytest.mark.asyncio
async def test_request_endpoint_returns_clean_409_not_500_on_conflict(
    db_session, org_world, client_factory,
):
    """Even if the app-level pre-check somehow missed a pending row (the exact
    race this guards against), the route must still surface a clean 409 via
    the IntegrityError handler, not an unhandled 500."""
    tenant_id = org_world["requester_tenant"]
    plan_row = (await db_session.execute(text(
        "SELECT id FROM plans WHERE is_active = true LIMIT 1"
    ))).mappings().first()
    plan_code = (await db_session.execute(text(
        "SELECT code FROM plans WHERE id = :id"
    ), {"id": str(plan_row["id"])})).scalar()

    await db_session.execute(text("""
        INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id)
        VALUES (:tid, :pid, 'manual', :ref)
    """), {"tid": str(tenant_id), "pid": str(plan_row["id"]), "ref": f"manual_{uuid4().hex[:16]}"})
    await db_session.commit()

    async with client_factory(org_world["requester_user"]) as client:
        resp = await client.post(
            "/api/v1/subscriptions/request",
            json={"plan_code": plan_code, "period": "monthly"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    assert resp.status_code == 409, resp.text
