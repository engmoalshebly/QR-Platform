"""PATCH /invitations/{id} must reject invalid enum values with a clean 422,
not let them reach Postgres and surface as an unhandled 500."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_patch_invalid_status_is_rejected_before_reaching_the_database(
    db_session, org_world, client_factory,
):
    tenant_id = org_world["requester_tenant"]
    event_id = org_world["event_id"]
    invitation_id = uuid4()

    await db_session.execute(text("""
        INSERT INTO invitations (id, tenant_id, event_id, token, ticket_class, status)
        VALUES (:id, :tid, :eid, 'update-validation-token', 'normal', 'created')
    """), {"id": str(invitation_id), "tid": str(tenant_id), "eid": str(event_id)})
    await db_session.commit()

    async with client_factory(org_world["requester_user"]) as client:
        resp = await client.patch(
            f"/api/v1/invitations/{invitation_id}",
            json={"status": "bogus-status"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    assert resp.status_code == 422, resp.text

    row = (await db_session.execute(text("""
        SELECT status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert row["status"] == "created"
