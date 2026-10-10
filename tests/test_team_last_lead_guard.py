"""Removing a team's only team_lead would leave any pending
event_team_assignments for that team permanently stuck (accept/reject is
gated behind require_team_lead). DELETE /teams/{id}/members/{user_id} must
refuse to remove the last team_lead."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cannot_remove_the_last_team_lead(db_session, org_world, client_factory):
    tenant_id = org_world["requester_tenant"]
    team_id = uuid4()
    lead_user = org_world["requester_user"]

    await db_session.execute(text("""
        INSERT INTO teams (id, tenant_id, name) VALUES (:id, :tid, 'فريق الاستقبال')
    """), {"id": str(team_id), "tid": str(tenant_id)})
    await db_session.execute(text("""
        INSERT INTO team_memberships (team_id, user_id, role) VALUES (:tid, :uid, 'team_lead')
    """), {"tid": str(team_id), "uid": str(lead_user)})
    await db_session.commit()

    async with client_factory(lead_user) as client:
        resp = await client.delete(
            f"/api/v1/teams/{team_id}/members/{lead_user}",
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    assert resp.status_code == 409, resp.text
    row = (await db_session.execute(text("""
        SELECT role FROM team_memberships WHERE team_id = :tid AND user_id = :uid
    """), {"tid": str(team_id), "uid": str(lead_user)})).mappings().one()
    assert row["role"] == "team_lead"


@pytest.mark.asyncio
async def test_can_remove_a_team_lead_when_another_remains(db_session, org_world, client_factory):
    tenant_id = org_world["requester_tenant"]
    team_id = uuid4()
    lead_user = org_world["requester_user"]
    second_lead = uuid4()

    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:uid, 'second-lead@example.com', 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
        ON CONFLICT (id) DO NOTHING
    """), {"uid": str(second_lead)})
    await db_session.execute(text("""
        INSERT INTO profiles (id, full_name) VALUES (:uid, 'قائد ثاني')
        ON CONFLICT (id) DO NOTHING
    """), {"uid": str(second_lead)})
    await db_session.execute(text("""
        INSERT INTO teams (id, tenant_id, name) VALUES (:id, :tid, 'فريق الاستقبال')
    """), {"id": str(team_id), "tid": str(tenant_id)})
    await db_session.execute(text("""
        INSERT INTO team_memberships (team_id, user_id, role) VALUES
          (:tid, :uid1, 'team_lead'), (:tid, :uid2, 'team_lead')
    """), {"tid": str(team_id), "uid1": str(lead_user), "uid2": str(second_lead)})
    await db_session.commit()

    async with client_factory(lead_user) as client:
        resp = await client.delete(
            f"/api/v1/teams/{team_id}/members/{lead_user}",
            headers={"X-Tenant-ID": str(tenant_id)},
        )

    assert resp.status_code == 204, resp.text
