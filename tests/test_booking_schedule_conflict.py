"""PATCH /bookings/{id}/schedule must not let a provider reschedule a booking
into a time slot that collides with another of the provider's own
accepted/in_progress/reopened bookings — previously it ran no overlap check
at all."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def _insert_booking(db, requester_tenant, provider_tenant, requester_user, event_id, status, starts, ends):
    booking_id = uuid4()
    await db.execute(text("""
        INSERT INTO organizer_booking_requests
          (id, requester_tenant_id, provider_tenant_id, requested_by, event_id,
           title, event_type, starts_at, ends_at, guest_count, location,
           contact_name, contact_phone, contact_email, status)
        VALUES (:id, :rtid, :ptid, :ruid, :eid,
                'حفل اختبار', 'زفاف', :starts, :ends,
                50, 'موقع اختبار', 'مدير المؤسسة', '0500000001', 'org-test@example.com', :status)
    """), {
        "id": str(booking_id), "rtid": str(requester_tenant), "ptid": str(provider_tenant),
        "ruid": str(requester_user), "eid": str(event_id), "status": status,
        "starts": starts, "ends": ends,
    })
    return booking_id


@pytest.mark.asyncio
async def test_reschedule_into_an_accepted_bookings_slot_is_rejected(
    db_session, org_world, client_factory,
):
    from datetime import datetime, timedelta, timezone
    requester_tenant = org_world["requester_tenant"]
    provider_tenant = org_world["provider_tenant"]
    requester_user = org_world["requester_user"]
    event_id = org_world["event_id"]

    base = datetime.now(timezone.utc) + timedelta(days=10)
    accepted_start, accepted_end = base, base + timedelta(hours=4)

    await _insert_booking(
        db_session, requester_tenant, provider_tenant, requester_user, event_id,
        "accepted", accepted_start, accepted_end,
    )
    pending_id = await _insert_booking(
        db_session, requester_tenant, provider_tenant, requester_user, event_id,
        "pending", base + timedelta(days=1), base + timedelta(days=1, hours=4),
    )
    await db_session.commit()

    overlap_start = accepted_start + timedelta(hours=1)
    overlap_end = accepted_end + timedelta(hours=1)

    async with client_factory(org_world["provider_user"]) as client:
        resp = await client.patch(
            f"/api/v1/bookings/{pending_id}/schedule",
            json={
                "starts_at": overlap_start.isoformat(),
                "ends_at": overlap_end.isoformat(),
            },
            headers={"X-Tenant-ID": str(provider_tenant)},
        )

    assert resp.status_code == 409, resp.text
