"""Call the real service functions — not reimplemented SQL — through the real
get_db() dependency on the real qentry_app role.

tests/test_rls_enforcement.py proves the POLICIES are correct by hand-writing
equivalent SQL and running it with SET LOCAL ROLE.  That leaves one residual
risk: the hand-written SQL might not perfectly match what the application
actually executes.  This file closes that gap by importing and calling the
exact functions migration v62 was written for:

  * app/services/notification_service.py: notify_tenant_managers, notify_operation_members
  * app/services/usage_service.py: get_current_usage, release_usage, get_seats_count
  * app/services/feature_service.py: record_non_asset_storage

Seed data is committed (get_db() opens its own connection, independent of any
test transaction) and removed in a finally block.  Skipped unless
DATABASE_APP_URL names a distinct role, exactly like test_app_role_wiring.py.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal, get_db
from app.tenant_context import clear_current_tenant, set_current_tenant

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_APP_URL"),
    reason="DATABASE_APP_URL not configured for this run",
)


async def _real_db_session_for(tenant_id):
    """Open the production get_db() generator acting for tenant_id."""
    if tenant_id is not None:
        set_current_tenant({
            "id": tenant_id, "slug": f"t-{str(tenant_id)[:8]}", "name": "x",
            "status": "active", "plan": "starter",
        })
    else:
        clear_current_tenant()
    gen = get_db()
    session = await gen.__anext__()
    return gen, session


@pytest.fixture
async def seeded():
    """Two independent tenant pairs, committed via the privileged connection:
    (a, b) linked by an active booking; (organizer, institution) linked by
    workspace_links.  Cleaned up unconditionally afterwards."""
    ids = {
        "a": str(uuid4()), "b": str(uuid4()), "unrelated": str(uuid4()),
        "organizer": str(uuid4()), "institution": str(uuid4()),
        "requested_by": str(uuid4()), "owner": str(uuid4()), "member": str(uuid4()),
        "b_manager": str(uuid4()), "unrelated_manager": str(uuid4()),
    }
    async with AsyncSessionLocal() as db:
        for key in ("a", "b", "unrelated", "organizer", "institution"):
            await db.execute(text(
                "INSERT INTO tenants (id, name, slug, status, plan) VALUES (:id, :n, :s, 'active', 'starter')"
            ), {"id": ids[key], "n": f"Seed {key}", "s": f"svc-{key}-{ids[key][:8]}"})
        for user_key in ("requested_by", "owner", "member", "b_manager", "unrelated_manager"):
            await db.execute(text("""
                INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
                VALUES (:id, :email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
                ON CONFLICT DO NOTHING
            """), {"id": ids[user_key], "email": f"{user_key}-{ids[user_key][:8]}@test.com"})
            await db.execute(text(
                "INSERT INTO profiles (id, full_name) VALUES (:id, :n) ON CONFLICT DO NOTHING"
            ), {"id": ids[user_key], "n": user_key})
        await db.execute(text("""
            INSERT INTO organizer_booking_requests
              (requester_tenant_id, provider_tenant_id, requested_by, title, event_type,
               starts_at, ends_at, guest_count, contact_name, contact_phone, status)
            VALUES (:req, :prov, :by, 'Service-function test booking', 'wedding',
                    now() + interval '1 day', now() + interval '1 day 4 hours', 50,
                    'Contact', '0500000000', 'pending')
        """), {"req": ids["a"], "prov": ids["b"], "by": ids["requested_by"]})
        await db.execute(text("""
            INSERT INTO workspace_links (organizer_tenant_id, institution_tenant_id, owner_user_id, billing_tenant_id, status)
            VALUES (:org, :inst, :owner, :inst, 'active')
        """), {"org": ids["organizer"], "inst": ids["institution"], "owner": ids["owner"]})
        await db.execute(text("""
            INSERT INTO memberships (tenant_id, user_id, role, status) VALUES (:tid, :uid, 'owner', 'active')
        """), {"tid": ids["institution"], "uid": ids["member"]})
        # notify_tenant_managers() fans out to active owner/admin members; both
        # the booking counterparty and the unrelated-tenant control need one.
        await db.execute(text("""
            INSERT INTO memberships (tenant_id, user_id, role, status) VALUES (:tid, :uid, 'owner', 'active')
        """), {"tid": ids["b"], "uid": ids["b_manager"]})
        await db.execute(text("""
            INSERT INTO memberships (tenant_id, user_id, role, status) VALUES (:tid, :uid, 'owner', 'active')
        """), {"tid": ids["unrelated"], "uid": ids["unrelated_manager"]})
        await db.commit()
    try:
        yield ids
    finally:
        async with AsyncSessionLocal() as db:
            # prevent_last_active_tenant_owner_loss fires on the membership rows
            # cascaded away by deleting their tenant below, even though the
            # tenant disappearing in the same cleanup makes "ownerless" moot.
            # This is privileged, one-shot test teardown, not production code,
            # so disabling triggers for it is the right tool.
            await db.execute(text("SET session_replication_role = replica"))
            await db.execute(text("DELETE FROM notifications WHERE tenant_id = ANY(:ids)"),
                             {"ids": [ids["a"], ids["b"], ids["unrelated"], ids["organizer"], ids["institution"]]})
            await db.execute(text("DELETE FROM usage_counters WHERE tenant_id = ANY(:ids)"),
                             {"ids": [ids["organizer"], ids["institution"]]})
            await db.execute(text("DELETE FROM workspace_links WHERE organizer_tenant_id = :org"), {"org": ids["organizer"]})
            await db.execute(text("DELETE FROM organizer_booking_requests WHERE requester_tenant_id = :a"), {"a": ids["a"]})
            await db.execute(text(
                "DELETE FROM tenants WHERE id = ANY(:ids)"
            ), {"ids": [ids["a"], ids["b"], ids["unrelated"], ids["organizer"], ids["institution"]]})
            await db.commit()


@pytest.mark.asyncio
async def test_notify_tenant_managers_reaches_the_booking_counterparty(seeded):
    from app.services.notification_service import notify_tenant_managers

    gen, db = await _real_db_session_for(seeded["a"])
    try:
        await notify_tenant_managers(
            db, seeded["b"],
            notification_type="booking.created", title="New booking", message="details",
        )
        await db.commit()
    finally:
        await gen.aclose()

    async with AsyncSessionLocal() as check:
        count = (await check.execute(
            text("SELECT count(*) FROM notifications WHERE tenant_id = :tid AND type = 'booking.created'"),
            {"tid": seeded["b"]},
        )).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_notify_tenant_managers_is_a_silent_no_op_for_an_unrelated_tenant(seeded):
    """memberships' SELECT policy filters rows rather than raising, so an
    unrelated tenant's manager list reads as empty and the fan-out loop in
    notify_tenant_managers() simply never calls create_notification().  The
    production invariant is "nobody receives it", not "an exception is thrown"."""
    from app.services.notification_service import notify_tenant_managers

    gen, db = await _real_db_session_for(seeded["a"])
    try:
        await notify_tenant_managers(
            db, seeded["unrelated"],
            notification_type="spam", title="x", message="y",
        )
        await db.commit()
    finally:
        await gen.aclose()

    async with AsyncSessionLocal() as check:
        count = (await check.execute(
            text("SELECT count(*) FROM notifications WHERE tenant_id = :tid AND type = 'spam'"),
            {"tid": seeded["unrelated"]},
        )).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_release_usage_and_get_current_usage_cross_the_billing_link(seeded):
    from app.services.usage_service import get_current_usage, release_usage

    # Seed 5 units on the institution's counter via the privileged connection
    # (mirrors what the SECURITY DEFINER try_increment_usage() would have done).
    async with AsyncSessionLocal() as seed_db:
        await seed_db.execute(text("""
            INSERT INTO usage_counters (tenant_id, period_start, period_end, key, value)
            VALUES (:tid, date_trunc('month', now())::date,
                    (date_trunc('month', now()) + interval '1 month' - interval '1 day')::date,
                    'events_per_month', 5)
        """), {"tid": seeded["institution"]})
        await seed_db.commit()

    gen, db = await _real_db_session_for(seeded["organizer"])
    try:
        await release_usage(db, seeded["organizer"], "events_per_month", 2)
        await db.commit()
    finally:
        await gen.aclose()

    gen, db = await _real_db_session_for(seeded["organizer"])
    try:
        usage = await get_current_usage(db, seeded["organizer"])
    finally:
        await gen.aclose()
    assert usage.get("events_per_month") == 3, (
        "release_usage/get_current_usage must read and write the linked institution's "
        f"counter from the organizer's own session; got {usage}"
    )


@pytest.mark.asyncio
async def test_get_seats_count_reads_the_linked_institution(seeded):
    from app.services.usage_service import get_seats_count

    gen, db = await _real_db_session_for(seeded["organizer"])
    try:
        seats = await get_seats_count(db, seeded["organizer"])
    finally:
        await gen.aclose()
    assert seats >= 1, "get_seats_count must see the institution's membership from the organizer side"


@pytest.mark.asyncio
async def test_record_non_asset_storage_writes_to_the_billing_tenant(seeded):
    from app.services.feature_service import record_non_asset_storage

    gen, db = await _real_db_session_for(seeded["organizer"])
    try:
        await record_non_asset_storage(db, seeded["organizer"], 2048)
        await db.commit()
    finally:
        await gen.aclose()

    async with AsyncSessionLocal() as check:
        value = (await check.execute(text("""
            SELECT value FROM usage_counters
            WHERE tenant_id = :tid AND key = 'storage_bytes'
        """), {"tid": seeded["institution"]})).scalar()
    assert value == 2048


@pytest.mark.asyncio
async def test_notify_operation_members_reaches_the_provider_team(seeded):
    """app/services/notification_service.py: notify_operation_members() reads
    event_operation_members JOIN event_operations -- both already covered by
    v62's party policies on event_operations.  Verified directly rather than
    assumed, matching notify_tenant_managers' own surprise."""
    from app.services.notification_service import notify_operation_members

    event_id = str(uuid4())
    operation_id = str(uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO events (id, tenant_id, title, start_date, status)
            VALUES (:id, :tid, 'svc-fn test event', now(), 'draft')
        """), {"id": event_id, "tid": seeded["a"]})
        await db.execute(text("""
            INSERT INTO event_operations
              (id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id,
               status, progress, priority, last_modified_at, created_at, updated_at)
            VALUES (:id, :eid, :req, :prov, :pm, 'planning', 0, 'medium', now(), now(), now())
        """), {"id": operation_id, "eid": event_id, "req": seeded["a"], "prov": seeded["b"], "pm": seeded["b_manager"]})
        await db.execute(text("""
            INSERT INTO event_operation_members (operation_id, user_id, role)
            VALUES (:oid, :uid, 'manager')
        """), {"oid": operation_id, "uid": seeded["b_manager"]})
        await db.commit()

    gen, db = await _real_db_session_for(seeded["a"])
    try:
        await notify_operation_members(
            db, operation_id,
            notification_type="task.approval.requested", title="Task needs approval", message="details",
        )
        await db.commit()
    finally:
        await gen.aclose()

    async with AsyncSessionLocal() as check:
        count = (await check.execute(text("""
            SELECT count(*) FROM notifications
            WHERE tenant_id = :tid AND type = 'task.approval.requested' AND user_id = :uid
        """), {"tid": seeded["b"], "uid": seeded["b_manager"]})).scalar()
        await check.execute(text("SET session_replication_role = replica"))
        await check.execute(text("DELETE FROM event_operation_members WHERE operation_id = :oid"), {"oid": operation_id})
        await check.execute(text("DELETE FROM event_operations WHERE id = :oid"), {"oid": operation_id})
        await check.execute(text("DELETE FROM events WHERE id = :eid"), {"eid": event_id})
        await check.commit()
    assert count == 1
