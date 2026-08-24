"""Database-backed regression coverage for gate shifts and device sessions."""
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services.gate_shift_service import hash_device_session_token, require_active_gate_session
from app.services.field_checkin_service import FieldCheckinResult, claim_client_scan, record_field_attempt


async def _create_gate_shift_world(db, world):
    operation_id = uuid4()
    gate_id = uuid4()
    shift_id = uuid4()
    now = (await db.execute(text("SELECT now()"))).scalar()

    await db.execute(text("""
        INSERT INTO event_operations
          (id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status)
        VALUES (:operation_id, :event_id, :requester_tenant_id, :provider_tenant_id, :manager_id, 'in_progress')
    """), {
        "operation_id": str(operation_id), "event_id": str(world["event_id"]),
        "requester_tenant_id": str(world["requester_tenant"]),
        "provider_tenant_id": str(world["provider_tenant"]), "manager_id": str(world["provider_user"]),
    })
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id, user_id, role)
        VALUES (:operation_id, :user_id, 'manager')
    """), {"operation_id": str(operation_id), "user_id": str(world["provider_user"])})
    await db.execute(text("""
        INSERT INTO event_gates(id, event_id, name, is_active)
        VALUES (:gate_id, :event_id, 'Test gate', TRUE)
    """), {"gate_id": str(gate_id), "event_id": str(world["event_id"])})
    await db.execute(text("""
        INSERT INTO event_gate_shifts
          (id, event_id, gate_id, operation_id, starts_at, ends_at, status, supervisor_user_id, created_by)
        VALUES (:shift_id, :event_id, :gate_id, :operation_id, :starts_at, :ends_at,
                'active', :user_id, :user_id)
    """), {
        "shift_id": str(shift_id), "event_id": str(world["event_id"]),
        "gate_id": str(gate_id), "operation_id": str(operation_id),
        "starts_at": now - timedelta(minutes=5), "ends_at": now + timedelta(hours=1),
        "user_id": str(world["provider_user"]),
    })
    await db.execute(text("""
        INSERT INTO event_gate_shift_members(shift_id, user_id, role, assigned_by)
        VALUES (:shift_id, :user_id, 'scanner', :user_id)
    """), {"shift_id": str(shift_id), "user_id": str(world["provider_user"])})
    token = "field-session-token-for-test"
    session_id = uuid4()
    await db.execute(text("""
        INSERT INTO event_gate_device_sessions
          (id, shift_id, event_id, gate_id, user_id, device_id, session_token_hash)
        VALUES (:session_id, :shift_id, :event_id, :gate_id, :user_id, 'test-device-0001', :token_hash)
    """), {
        "session_id": str(session_id), "shift_id": str(shift_id),
        "event_id": str(world["event_id"]), "gate_id": str(gate_id),
        "user_id": str(world["provider_user"]), "token_hash": hash_device_session_token(token),
    })
    return {"operation_id": operation_id, "gate_id": gate_id, "shift_id": shift_id,
            "session_id": session_id, "token": token, "now": now}


@pytest.mark.asyncio
async def test_active_device_session_requires_the_exact_event_and_gate(db_session, org_world):
    state = await _create_gate_shift_world(db_session, org_world)

    allowed = await require_active_gate_session(
        db_session, tenant_id=org_world["provider_tenant"], user_id=org_world["provider_user"],
        event_id=org_world["event_id"], gate_id=state["gate_id"],
        device_session_id=state["session_id"], device_session_token=state["token"],
    )
    assert allowed["id"] == state["session_id"]

    with pytest.raises(HTTPException) as denied:
        await require_active_gate_session(
            db_session, tenant_id=org_world["provider_tenant"], user_id=org_world["provider_user"],
            event_id=org_world["event_id"], gate_id=uuid4(),
            device_session_id=state["session_id"], device_session_token=state["token"],
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_database_rejects_overlapping_shift_assignments_without_override(db_session, org_world):
    state = await _create_gate_shift_world(db_session, org_world)
    second_gate_id = uuid4()
    second_shift_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO event_gates(id, event_id, name, is_active)
        VALUES (:gate_id, :event_id, 'Second test gate', TRUE)
    """), {"gate_id": str(second_gate_id), "event_id": str(org_world["event_id"])})
    await db_session.execute(text("""
        INSERT INTO event_gate_shifts
          (id, event_id, gate_id, operation_id, starts_at, ends_at, status, supervisor_user_id, created_by)
        VALUES (:shift_id, :event_id, :gate_id, :operation_id, :starts_at, :ends_at,
                'active', :user_id, :user_id)
    """), {
        "shift_id": str(second_shift_id), "event_id": str(org_world["event_id"]),
        "gate_id": str(second_gate_id), "operation_id": str(state["operation_id"]),
        "starts_at": state["now"] - timedelta(minutes=1), "ends_at": state["now"] + timedelta(minutes=30),
        "user_id": str(org_world["provider_user"]),
    })

    with pytest.raises(IntegrityError):
        await db_session.execute(text("""
            INSERT INTO event_gate_shift_members(shift_id, user_id, role, assigned_by)
            VALUES (:shift_id, :user_id, 'scanner', :user_id)
        """), {"shift_id": str(second_shift_id), "user_id": str(org_world["provider_user"])})
    await db_session.rollback()


@pytest.mark.asyncio
async def test_field_checkin_is_atomic_for_group_invitation(db_session, org_world):
    """Two competing scans cannot admit more people than the invitation allows."""
    state = await _create_gate_shift_world(db_session, org_world)
    invitation_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO invitations
          (id, tenant_id, event_id, token, ticket_class, guest_name, guest_count, checkin_count, status)
        VALUES (:id, :tenant_id, :event_id, 'group-field-token-001', 'normal', 'Group guest', 3, 0, 'sent')
    """), {"id": str(invitation_id), "tenant_id": str(org_world["requester_tenant"]), "event_id": str(org_world["event_id"])})

    first = await db_session.execute(text("""
        SELECT * FROM public.validate_field_checkin(
          'group-field-token-001', :event_id, :gate_id, 2, :invitation_id
        )
    """), {"event_id": str(org_world["event_id"]), "gate_id": str(state["gate_id"]), "invitation_id": str(invitation_id)})
    first_row = first.mappings().first()
    assert first_row["result"] == "success"
    assert first_row["remaining_count"] == 1

    rejected = await db_session.execute(text("""
        SELECT * FROM public.validate_field_checkin(
          'group-field-token-001', :event_id, :gate_id, 2, :invitation_id
        )
    """), {"event_id": str(org_world["event_id"]), "gate_id": str(state["gate_id"]), "invitation_id": str(invitation_id)})
    rejected_row = rejected.mappings().first()
    assert rejected_row["result"] == "capacity_exceeded"
    assert rejected_row["remaining_count"] == 1

    remaining = await db_session.execute(text("SELECT checkin_count FROM invitations WHERE id = :id"), {"id": str(invitation_id)})
    assert remaining.scalar() == 2


@pytest.mark.asyncio
async def test_field_client_scan_id_is_idempotent(db_session, org_world):
    state = await _create_gate_shift_world(db_session, org_world)
    session = {
        "id": state["session_id"], "shift_id": state["shift_id"],
        "event_id": org_world["event_id"], "gate_id": state["gate_id"],
    }
    request = Request({"type": "http", "method": "POST", "path": "/mobile/checkins", "headers": [], "client": ("127.0.0.1", 443)})
    scan_id = uuid4()
    first = await claim_client_scan(
        db_session, session=session, user_id=org_world["provider_user"], client_scan_id=scan_id,
        scan_method="camera", raw_code="dedupe-field-token", client_captured_at=None, request=request,
    )
    assert first is None
    await record_field_attempt(
        db_session, session=session, user_id=org_world["provider_user"], client_scan_id=scan_id,
        scan_method="camera", raw_code="dedupe-field-token",
        result=FieldCheckinResult(result="invalid", message="رفض للاختبار"),
        client_captured_at=None, request=request,
    )
    repeated = await claim_client_scan(
        db_session, session=session, user_id=org_world["provider_user"], client_scan_id=scan_id,
        scan_method="camera", raw_code="dedupe-field-token", client_captured_at=None, request=request,
    )
    assert repeated is not None
    assert repeated.idempotent is True
    assert repeated.result == "invalid"

    attempts = await db_session.execute(text("""
        SELECT COUNT(*) FROM event_gate_scan_attempts
        WHERE device_session_id = :session_id AND client_scan_id = :scan_id
    """), {"session_id": str(state["session_id"]), "scan_id": str(scan_id)})
    assert attempts.scalar() == 1
