"""PATCH /operations/{id}/tasks/{id} must restrict a "viewer" operation-role
assignee to status-only changes, exactly like "member" — previously only the
literal string "member" was special-cased, so a viewer assigned to their own
task fell through to the full manager/lead field set (title, priority,
assigned_to, due_at, start_at, parent_task_id)."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_viewer_assignee_cannot_reassign_or_reprioritize_their_own_task(
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
        VALUES (:oid, :uid, 'viewer')
    """), {"oid": str(operation_id), "uid": str(provider_user)})
    task_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO event_operation_tasks (id, operation_id, title, status, priority, assigned_to, created_by)
        VALUES (:id, :oid, 'مهمة اختبار', 'todo', 'medium', :uid, :uid)
    """), {"id": str(task_id), "oid": str(operation_id), "uid": str(provider_user)})
    await db_session.commit()

    other_user = org_world["requester_user"]

    async with client_factory(provider_user) as client:
        resp = await client.patch(
            f"/api/v1/operations/{operation_id}/tasks/{task_id}",
            json={"status": "done", "priority": "urgent", "assigned_to": str(other_user)},
            headers={"X-Tenant-ID": str(provider_tenant)},
        )

    assert resp.status_code == 200, resp.text
    row = (await db_session.execute(text("""
        SELECT status, priority, assigned_to FROM event_operation_tasks WHERE id = :id
    """), {"id": str(task_id)})).mappings().one()
    assert row["status"] == "done"
    assert row["priority"] == "medium", "a viewer must not be able to change task priority"
    assert str(row["assigned_to"]) == str(provider_user), "a viewer must not be able to reassign their own task"
