"""Invitation capacity is measured in people, including RSVP companions."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.services.quota_service import check_quota


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_quota_counts_group_guest_count_not_just_invitation_rows(db_session, org_world):
    """One group invitation for two people exhausts a quota of two."""
    await db_session.execute(text("""
        UPDATE events SET normal_quota = 2 WHERE id = :event_id
    """), {"event_id": str(org_world["event_id"])})
    await db_session.execute(text("""
        INSERT INTO invitations (
            id, tenant_id, event_id, token, ticket_class, guest_count, status
        ) VALUES (
            :id, :tenant_id, :event_id, 'group-capacity-token', 'normal', 2, 'accepted'
        )
    """), {
        "id": str(uuid4()),
        "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]),
    })

    with pytest.raises(HTTPException) as exc_info:
        await check_quota(
            db_session,
            str(org_world["requester_tenant"]),
            str(org_world["event_id"]),
            "normal",
            count=1,
        )
    assert exc_info.value.status_code == 400
    assert "المستخدم: 2" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_rsvp_companion_updates_entitlement_and_respects_event_quota(
    db_session, org_world, client_factory,
):
    """A confirmed companion gets a gate slot, but cannot overbook the event."""
    token = "rsvp-companion-capacity-token"
    invitation_id = uuid4()
    await db_session.execute(text("""
        UPDATE events
        SET normal_quota = 2, allow_rsvp = TRUE, allow_plus_one = TRUE
        WHERE id = :event_id
    """), {"event_id": str(org_world["event_id"])})
    await db_session.execute(text("""
        INSERT INTO invitations (
            id, tenant_id, event_id, token, ticket_class, guest_count,
            status, rsvp_status, metadata
        ) VALUES (
            :id, :tenant_id, :event_id, :token, 'normal', 1,
            'created', 'pending', '{}'::jsonb
        )
    """), {
        "id": str(invitation_id),
        "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]),
        "token": token,
    })

    async with client_factory(org_world["requester_user"]) as client:
        accepted = await client.post(
            f"/api/v1/invitations/rsvp/{token}",
            json={"status": "accepted", "plus_one_count": 1},
        )
        over_quota = await client.post(
            f"/api/v1/invitations/rsvp/{token}",
            json={"status": "accepted", "plus_one_count": 2},
        )

    assert accepted.status_code == 200, accepted.text
    assert over_quota.status_code == 400
    row = (await db_session.execute(text("""
        SELECT guest_count, plus_one_count, rsvp_status, metadata
        FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert (row["guest_count"], row["plus_one_count"], row["rsvp_status"]) == (2, 1, "accepted")
    assert row["metadata"]["rsvp_base_guest_count"] == 1
