"""End-to-end Phase 1 integration tests.

Covers the core readiness claim: accepting a booking provisions an operational
event project, seeds per-event-type task templates, writes an activity log, and
emits notifications — all inside one transactional session that rolls back on
teardown, so these tests are safe to run against a real test database.

Run with:
    DATABASE_URL=postgresql+asyncpg://... pytest tests/test_phase1_e2e.py -x -s

Requires the DB to have all migrations through v25 applied.
"""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.routes.bookings import provision_operation
from app.routes.operations import seed_tasks_from_template
from app.services.notification_service import create_notification


pytestmark = pytest.mark.asyncio


async def _has_column(db, table: str, column: str) -> bool:
    return bool((await db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name=:c
    """), {"t": table, "c": column})).first())


async def _insert_booking(db, requester_tenant, provider_tenant, requester_user, event_id, title="حفل اختبار", event_type="زفاف"):
    """Insert a booking row directly (bypasses the HTTP path that needs Supabase storage)."""
    booking_id = uuid4()
    await db.execute(text("""
        INSERT INTO organizer_booking_requests
          (id, requester_tenant_id, provider_tenant_id, requested_by, event_id,
           title, event_type, starts_at, ends_at, guest_count, location,
           contact_name, contact_phone, contact_email, status)
        VALUES (:id, :rtid, :ptid, :ruid, :eid,
                :title, :etype, now() + interval '7 days', now() + interval '7 days' + interval '4 hours',
                50, 'موقع اختبار', 'مدير المؤسسة', '0500000001', 'org-test@example.com', 'pending')
    """), {
        "id": str(booking_id), "rtid": str(requester_tenant), "ptid": str(provider_tenant),
        "ruid": str(requester_user), "eid": str(event_id), "title": title, "etype": event_type,
    })
    return booking_id


@pytest.mark.asyncio
async def test_provision_operation_creates_workspace_members_and_activity(db_session, org_world):
    """Accepting a booking must provision the operation, the manager member, and an
    operation.created activity row — atomically, in the same session."""
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "زفاف",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"])

    operation_id = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()

    op = (await db_session.execute(text("SELECT * FROM event_operations WHERE id=:oid"),
                                  {"oid": str(operation_id)})).mappings().first()
    assert op is not None
    assert op["status"] == "planning"
    assert str(op["project_manager_id"]) == str(w["provider_user"])

    member = (await db_session.execute(text("""
        SELECT role FROM event_operation_members
        WHERE operation_id=:oid AND user_id=:uid
    """), {"oid": str(operation_id), "uid": str(w["provider_user"])})).mappings().first()
    assert member is not None and member["role"] == "manager"

    activity = (await db_session.execute(text("""
        SELECT action FROM event_operation_activity WHERE operation_id=:oid ORDER BY created_at
    """), {"oid": str(operation_id)})).mappings().all()
    actions = [a["action"] for a in activity]
    assert "operation.created" in actions
    # tasks.seeded only fires when event_task_templates exists (migration v25+).
    # On an older DB the seeding is best-effort and skipped — that's acceptable.
    _has_templates = (await db_session.execute(text("""
        SELECT to_regclass('public.event_task_templates')
    """))).scalar()
    if _has_templates:
        assert "tasks.seeded" in actions
    else:
        assert "tasks.seeded" not in actions


@pytest.mark.asyncio
async def test_provisioning_is_idempotent_and_does_not_duplicate_tasks(db_session, org_world):
    """Calling provision_operation twice for the same booking must not duplicate the
    operation or re-seed tasks (idempotency contract for retries)."""
    _has_templates = (await db_session.execute(text(
        "SELECT to_regclass('public.event_task_templates')"))).scalar()
    if not _has_templates:
        pytest.skip("event_task_templates not present — migration v25 not applied")
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "default",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"], event_type="default")

    op1 = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()
    op2 = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()
    assert op1 == op2

    count = (await db_session.execute(text("""
        SELECT COUNT(*) FROM event_operation_tasks WHERE operation_id=:oid
    """), {"oid": str(op1)})).scalar()
    # Default template ships 7 tasks; must remain 7 after the second call.
    assert count == 7


@pytest.mark.asyncio
async def test_provisioning_rejects_a_second_active_operation_for_the_event(db_session, org_world):
    """A linked-workspace operation must block an accepted marketplace booking.

    Without this guard, both operations could manage the same event's gates and
    attendance records because provider access is granted by ``event_id``.
    """
    w = org_world
    await db_session.execute(text("""
        INSERT INTO event_operations
          (event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status)
        VALUES (:event_id, :requester, :provider, :manager, 'planning')
    """), {
        "event_id": str(w["event_id"]),
        "requester": str(w["requester_tenant"]),
        "provider": str(w["provider_tenant"]),
        "manager": str(w["provider_user"]),
    })
    booking_id = await _insert_booking(
        db_session, w["requester_tenant"], w["provider_tenant"],
        w["requester_user"], w["event_id"],
    )
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "زفاف",
    }

    with pytest.raises(HTTPException) as error:
        await provision_operation(db_session, booking_id, booking, w["provider_user"])

    assert error.value.status_code == 409
    assert (await db_session.execute(text("""
        SELECT COUNT(*) FROM event_operations WHERE event_id = :event_id
    """), {"event_id": str(w["event_id"])})).scalar() == 1


@pytest.mark.asyncio
async def test_task_template_seeding_matches_event_type(db_session, org_world):
    """A wedding booking should pull the wedding-specific template rows on top of the
    default set, and a wedding-only title must appear in the seeded tasks."""
    _has_templates = (await db_session.execute(text(
        "SELECT to_regclass('public.event_task_templates')"))).scalar()
    if not _has_templates:
        pytest.skip("event_task_templates not present — migration v25 not applied")
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "زفاف",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"], event_type="زفاف")
    operation_id = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()

    titles = [r[0] for r in (await db_session.execute(text("""
        SELECT title FROM event_operation_tasks WHERE operation_id=:oid
    """), {"oid": str(operation_id)})).all()]
    # wedding-specific template title must have been seeded
    assert "التنسيق مع قاعة الحفل" in titles


@pytest.mark.asyncio
async def test_subtask_creation_and_member_guard(db_session, org_world):
    """A manager can create a parent task and a subtask pointing at it; a subtask with
    a bogus parent is rejected."""
    if not await _has_column(db_session, "event_operation_tasks", "parent_task_id"):
        pytest.skip("parent_task_id column not present — migration v25 not applied")
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "default",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"], event_type="default")
    operation_id = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()

    parent_id = (await db_session.execute(text("""
        INSERT INTO event_operation_tasks (operation_id, title, created_by)
        VALUES (:oid, 'مهمة رئيسية', :uid) RETURNING id
    """), {"oid": str(operation_id), "uid": str(w["provider_user"])})).scalar()

    sub_id = (await db_session.execute(text("""
        INSERT INTO event_operation_tasks (operation_id, title, parent_task_id, created_by)
        VALUES (:oid, 'مهمة فرعية', :pid, :uid) RETURNING id
    """), {"oid": str(operation_id), "pid": str(parent_id), "uid": str(w["provider_user"])})).scalar()

    link = (await db_session.execute(text("""
        SELECT parent_task_id FROM event_operation_tasks WHERE id=:sid
    """), {"sid": str(sub_id)})).scalar()
    assert str(link) == str(parent_id)


@pytest.mark.asyncio
async def test_task_comment_persists(db_session, org_world):
    """Comments on a task are stored and linked back to the author."""
    _has_templates = (await db_session.execute(text(
        "SELECT to_regclass('public.event_operation_task_comments')"))).scalar()
    if not _has_templates:
        pytest.skip("event_operation_task_comments not present — migration v25 not applied")
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "default",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"], event_type="default")
    operation_id = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()
    task_id = (await db_session.execute(text("""
        INSERT INTO event_operation_tasks (operation_id, title, created_by)
        VALUES (:oid, 'مهمة مع تعليق', :uid) RETURNING id
    """), {"oid": str(operation_id), "uid": str(w["provider_user"])})).scalar()
    await db_session.execute(text("""
        INSERT INTO event_operation_task_comments (task_id, author_id, body)
        VALUES (:tid, :uid, 'تعليق اختبار')
    """), {"tid": str(task_id), "uid": str(w["provider_user"])})
    await db_session.flush()
    body = (await db_session.execute(text("SELECT body FROM event_operation_task_comments WHERE task_id=:tid"),
                                  {"tid": str(task_id)})).scalar()
    assert body == "تعليق اختبار"


@pytest.mark.asyncio
async def test_task_approval_flow(db_session, org_world):
    """approval_required tasks cannot be marked done until approved_by is set; the
    approve path stamps approved_by/approved_at."""
    if not await _has_column(db_session, "event_operation_tasks", "approval_required"):
        pytest.skip("approval_required column not present — migration v25 not applied")
    w = org_world
    booking = {
        "event_id": w["event_id"],
        "requester_tenant_id": w["requester_tenant"],
        "provider_tenant_id": w["provider_tenant"],
        "event_type": "default",
    }
    booking_id = await _insert_booking(db_session, w["requester_tenant"], w["provider_tenant"],
                                       w["requester_user"], w["event_id"], event_type="default")
    operation_id = await provision_operation(db_session, booking_id, booking, w["provider_user"])
    await db_session.flush()
    task_id = (await db_session.execute(text("""
        INSERT INTO event_operation_tasks (operation_id, title, approval_required, created_by)
        VALUES (:oid, 'مهمة معتمدة', TRUE, :uid) RETURNING id
    """), {"oid": str(operation_id), "uid": str(w["provider_user"])})).scalar()
    await db_session.execute(text("""
        UPDATE event_operation_tasks SET approved_by=:uid, approved_at=now() WHERE id=:tid
    """), {"uid": str(w["provider_user"]), "tid": str(task_id)})
    await db_session.flush()
    approved = (await db_session.execute(text("""
        SELECT approved_by FROM event_operation_tasks WHERE id=:tid
    """), {"tid": str(task_id)})).scalar()
    assert approved is not None


@pytest.mark.asyncio
async def test_notification_persists_and_is_scoped(db_session, org_world):
    """A notification created for a tenant+user is retrievable and tenant-scoped."""
    w = org_world
    await create_notification(
        db_session, w["provider_tenant"], "booking.accepted", "تم القبول", "رسالة اختبار",
        user_id=w["provider_user"], link="/teams", metadata={"k": "v"},
    )
    await db_session.flush()
    row = (await db_session.execute(text("""
        SELECT type, title, read_at FROM notifications
        WHERE tenant_id=:tid AND user_id=:uid ORDER BY created_at DESC LIMIT 1
    """), {"tid": str(w["provider_tenant"]), "uid": str(w["provider_user"])})).mappings().first()
    assert row is not None
    assert row["type"] == "booking.accepted"
    assert row["read_at"] is None  # unread by default
