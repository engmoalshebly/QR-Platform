"""GET /operations/{id}/event-insights must not crash when the operation was
created via direct team assignment (app/routes/events.py's assign_event_to_team),
which leaves event_operations.booking_id NULL. str(None) used to be bound as
the literal string "None" against a uuid column, raising an unhandled 500."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_event_insights_without_a_booking_does_not_500(
    db_session, org_world, client_factory,
):
    requester_tenant = org_world["requester_tenant"]
    provider_tenant = org_world["provider_tenant"]
    provider_user = org_world["provider_user"]
    event_id = org_world["event_id"]

    operation_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO event_operations (id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id)
        VALUES (:id, :eid, :rtid, :ptid, :pm)
    """), {
        "id": str(operation_id), "eid": str(event_id),
        "rtid": str(requester_tenant), "ptid": str(provider_tenant), "pm": str(provider_user),
    })
    await db_session.execute(text("""
        INSERT INTO event_operation_members (operation_id, user_id, role)
        VALUES (:oid, :uid, 'manager')
    """), {"oid": str(operation_id), "uid": str(provider_user)})
    await db_session.commit()

    async with client_factory(provider_user) as client:
        resp = await client.get(
            f"/api/v1/operations/{operation_id}/event-insights",
            params={"scope": "overview"},
            headers={"X-Tenant-ID": str(provider_tenant)},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["booking"] == {}
