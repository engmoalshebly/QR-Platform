"""POST /invitations/bulk-from-guests must not charge the monthly quota for
guest_ids that do not resolve to an actual invitation (stale/cross-tenant ids)."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bulk_create_releases_quota_for_unresolved_guest_ids(
    db_session, org_world, client_factory,
):
    tenant_id = org_world["requester_tenant"]
    event_id = org_world["event_id"]
    valid_guest_id = uuid4()
    missing_guest_id = uuid4()

    await db_session.execute(text("""
        INSERT INTO guests (id, tenant_id, full_name, phone)
        VALUES (:id, :tid, 'ضيف صالح', '0511111111')
    """), {"id": str(valid_guest_id), "tid": str(tenant_id)})
    await db_session.commit()

    async with client_factory(org_world["requester_user"]) as client:
        resp = await client.post(
            "/api/v1/invitations/bulk-from-guests",
            json={
                "event_id": str(event_id),
                "guest_ids": [str(valid_guest_id), str(missing_guest_id)],
                "ticket_class": "normal",
                "require_rsvp": False,
            },
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 1

    inv_count = (await db_session.execute(text("""
        SELECT COUNT(*) FROM invitations WHERE event_id = :eid
    """), {"eid": str(event_id)})).scalar()
    assert inv_count == 1

    usage = (await db_session.execute(text("""
        SELECT value FROM usage_counters
        WHERE tenant_id = :tid AND key = 'invitations_per_month'
    """), {"tid": str(tenant_id)})).scalar()
    assert usage == 1, f"quota reservation was not released for the unresolved guest_id (got {usage})"
