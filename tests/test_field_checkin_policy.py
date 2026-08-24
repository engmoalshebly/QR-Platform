"""Regression coverage for the database-owned field admission policy."""
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text


ROOT = Path(__file__).parents[1]
POLICY_MIGRATION = ROOT / "supabase" / "migration_v51_field_checkin_policy.sql"


async def _install_policy_function_in_test_transaction(db_session) -> None:
    """Install the migration on this rollback-only connection for real policy tests."""
    source = POLICY_MIGRATION.read_text(encoding="utf-8")
    source = source.replace("\nBEGIN;\n", "\n", 1).rsplit("\nCOMMIT;", 1)[0]
    connection = await db_session.connection()
    raw_connection = await connection.get_raw_connection()
    await raw_connection.driver_connection.execute(source)


async def _scan(db_session, *, token: str, event_id, gate_id, user_id, entry_count: int = 1):
    result = await db_session.execute(text("""
        SELECT * FROM public.process_field_checkin_fast(
          :token,
          CAST(:event_id AS UUID), CAST(:gate_id AS UUID),
          NULL::UUID, NULL::UUID, CAST(:user_id AS UUID), NULL::UUID,
          NULL::TIMESTAMPTZ, 'camera', repeat('0', 64), :entry_count,
          NULL::UUID, FALSE, NULL::UUID, NULL::TEXT, NULL::INET, FALSE
        )
    """), {
        "token": token,
        "event_id": str(event_id),
        "gate_id": str(gate_id),
        "user_id": str(user_id),
        "entry_count": entry_count,
    })
    return result.mappings().one()


async def _invitation(
    db_session,
    *,
    tenant_id,
    event_id,
    token: str,
    rsvp_status: str = "accepted",
    metadata: str = "{}",
    is_registration: bool = False,
    expires_at_sql: str | None = None,
    guest_count: int = 1,
):
    invitation_id = uuid4()
    expires_value = "NULL" if expires_at_sql is None else expires_at_sql
    await db_session.execute(text(f"""
        INSERT INTO invitations (
          id, tenant_id, event_id, token, ticket_class, status, rsvp_status,
          guest_count, checkin_count, metadata, is_registration, expires_at
        ) VALUES (
          :id, :tenant_id, :event_id, :token, 'normal', 'sent',
          CAST(:rsvp_status AS rsvp_status), :guest_count, 0,
          CAST(:metadata AS jsonb), :is_registration, {expires_value}
        )
    """), {
        "id": str(invitation_id),
        "tenant_id": str(tenant_id),
        "event_id": str(event_id),
        "token": token,
        "rsvp_status": rsvp_status,
        "guest_count": guest_count,
        "metadata": metadata,
        "is_registration": is_registration,
    })
    return invitation_id


@pytest.mark.asyncio
async def test_atomic_field_checkin_enforces_rsvp_expiry_registration_and_reentry(
    db_session, org_world,
):
    """Every field entry point reaches these immutable invitation rules."""
    await _install_policy_function_in_test_transaction(db_session)
    gate_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO event_gates(id, event_id, name, allowed_classes, is_active)
        VALUES (:gate_id, :event_id, 'Policy gate', ARRAY['normal']::ticket_class[], TRUE)
    """), {"gate_id": str(gate_id), "event_id": str(org_world["event_id"])})

    pending_id = await _invitation(
        db_session,
        tenant_id=org_world["requester_tenant"],
        event_id=org_world["event_id"],
        token="policy-rsvp-pending-001",
        rsvp_status="pending",
        metadata='{"require_rsvp": true}',
    )
    pending = await _scan(
        db_session, token="policy-rsvp-pending-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert pending["result"] == "rsvp_required"
    unchanged = await db_session.execute(
        text("SELECT checkin_count FROM invitations WHERE id = :id"), {"id": str(pending_id)},
    )
    assert unchanged.scalar() == 0

    await db_session.execute(text("""
        UPDATE invitations SET rsvp_status = 'accepted' WHERE id = :id
    """), {"id": str(pending_id)})
    accepted = await _scan(
        db_session, token="policy-rsvp-pending-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert accepted["result"] == "success"

    await _invitation(
        db_session,
        tenant_id=org_world["requester_tenant"],
        event_id=org_world["event_id"],
        token="policy-expired-001",
        expires_at_sql="now() - interval '1 second'",
    )
    expired = await _scan(
        db_session, token="policy-expired-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert expired["result"] == "expired"

    await _invitation(
        db_session,
        tenant_id=org_world["requester_tenant"],
        event_id=org_world["event_id"],
        token="policy-declined-001",
        rsvp_status="declined",
    )
    declined = await _scan(
        db_session, token="policy-declined-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert declined["result"] == "declined"

    await _invitation(
        db_session,
        tenant_id=org_world["requester_tenant"],
        event_id=org_world["event_id"],
        token="policy-registration-001",
        is_registration=True,
    )
    registration = await _scan(
        db_session, token="policy-registration-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert registration["result"] == "registration_code"

    await db_session.execute(text("""
        UPDATE events SET allow_reentry = TRUE WHERE id = :event_id
    """), {"event_id": str(org_world["event_id"])})
    reentry_id = await _invitation(
        db_session,
        tenant_id=org_world["requester_tenant"],
        event_id=org_world["event_id"],
        token="policy-reentry-001",
    )
    first_entry = await _scan(
        db_session, token="policy-reentry-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    second_entry = await _scan(
        db_session, token="policy-reentry-001", event_id=org_world["event_id"],
        gate_id=gate_id, user_id=org_world["provider_user"],
    )
    assert first_entry["result"] == "success"
    assert second_entry["result"] == "success"
    checkins = await db_session.execute(
        text("SELECT checkin_count FROM invitations WHERE id = :id"), {"id": str(reentry_id)},
    )
    assert checkins.scalar() == 2


def test_field_policy_migration_and_legacy_routes_are_explicit():
    migration = POLICY_MIGRATION.read_text(encoding="utf-8")
    route_source = (ROOT / "app" / "routes" / "checkin.py").read_text(encoding="utf-8")

    assert "COALESCE(v_inv.is_registration, FALSE)" in migration
    assert "COALESCE(v_inv.rsvp_status::TEXT, '') = 'declined'" in migration
    assert "v_inv.expires_at <= now()" in migration
    assert "'rsvp_required'" in migration
    assert "AND NOT COALESCE(v_inv.allow_reentry, FALSE)" in migration
    assert "status_code=410" in route_source
    assert "POST /api/v1/mobile/checkins" in route_source
    assert 'SELECT * FROM public.validate_checkin' not in route_source


@pytest.mark.asyncio
async def test_legacy_scan_endpoint_is_safely_retired():
    """Old clients receive an explicit migration response, never a weaker scan."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.auth import CurrentUser
    from app.models.invitation import CheckinRequest
    from app.routes.checkin import LEGACY_FIELD_CHECKIN_DETAIL, scan_checkin

    request = Request({"type": "http", "method": "POST", "path": "/checkin/scan", "headers": []})
    with pytest.raises(HTTPException) as retired:
        await scan_checkin(
            CheckinRequest(token="legacy-scanner-token"),
            request,
            CurrentUser(id=uuid4(), email="scanner@example.test", role="authenticated"),
            None,
        )
    assert retired.value.status_code == 410
    assert retired.value.detail == LEGACY_FIELD_CHECKIN_DETAIL
