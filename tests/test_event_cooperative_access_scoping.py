"""Mutating event routes (update/delete/restore/assign/publish) check
`require_permission` against the caller's own tenant AND filter their raw SQL
by that same tenant_id. The RLS cooperative-access clause on `events`
(`current_operated_event_ids()`, migration_v61) widens read/write VISIBILITY
to a cooperating provider tenant, but these routes' explicit
`WHERE tenant_id = :tid` (using the caller's own tenant) is at least as
restrictive as that clause, so a cooperating provider must not be able to
mutate the requester's event through these routes."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cooperating_provider_cannot_update_requester_event(
    db_session, org_world, client_factory,
):
    requester_tenant = org_world["requester_tenant"]
    provider_tenant = org_world["provider_tenant"]
    event_id = org_world["event_id"]

    # Establish a real cooperative link: provider_tenant operates this event.
    await db_session.execute(text("""
        INSERT INTO event_operations (event_id, requester_tenant_id, provider_tenant_id, project_manager_id)
        VALUES (:eid, :rtid, :ptid, :pm)
    """), {
        "eid": str(event_id), "rtid": str(requester_tenant),
        "ptid": str(provider_tenant), "pm": str(org_world["provider_user"]),
    })
    await db_session.commit()

    async with client_factory(org_world["provider_user"]) as client:
        resp = await client.patch(
            f"/api/v1/events/{event_id}",
            json={"title": "تم الاستيلاء على الحدث"},
            headers={"X-Tenant-ID": str(provider_tenant)},
        )

    assert resp.status_code == 404, resp.text
    row = (await db_session.execute(text("""
        SELECT title FROM events WHERE id = :id
    """), {"id": str(event_id)})).mappings().one()
    assert row["title"] == "حفل اختبار"
