"""The gates_per_event plan limit must count only active gates. A gate that
delete_gate soft-deactivated (because it has check-in history) must not
permanently consume quota and block creating a replacement gate."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_deactivated_gate_does_not_block_new_gate_creation(
    db_session, org_world, client_factory,
):
    requester_tenant = org_world["requester_tenant"]
    provider_tenant = org_world["provider_tenant"]
    event_id = org_world["event_id"]

    await db_session.execute(text("""
        INSERT INTO event_operations (event_id, requester_tenant_id, provider_tenant_id, project_manager_id)
        VALUES (:eid, :rtid, :ptid, :pm)
    """), {
        "eid": str(event_id), "rtid": str(requester_tenant),
        "ptid": str(provider_tenant), "pm": str(org_world["provider_user"]),
    })
    await db_session.commit()

    async with client_factory(org_world["provider_user"]) as client:
        headers = {"X-Tenant-ID": str(provider_tenant)}

        first = await client.post(
            f"/api/v1/events/{event_id}/gates",
            json={"name": "Gate A"},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        gate_id = first.json()["id"]

        # Give the gate check-in history so delete_gate soft-deactivates
        # instead of hard-deleting it.
        await db_session.execute(text("""
            INSERT INTO checkins (event_id, gate_id, result) VALUES (:eid, :gid, 'success')
        """), {"eid": str(event_id), "gid": str(gate_id)})
        await db_session.commit()

        deleted = await client.delete(
            f"/api/v1/events/{event_id}/gates/{gate_id}",
            headers=headers,
        )
        assert deleted.status_code == 204, deleted.text

        row = (await db_session.execute(text("""
            SELECT is_active FROM event_gates WHERE id = :id
        """), {"id": gate_id})).mappings().one()
        assert row["is_active"] is False

        second = await client.post(
            f"/api/v1/events/{event_id}/gates",
            json={"name": "Gate B"},
            headers=headers,
        )
    assert second.status_code == 201, second.text
