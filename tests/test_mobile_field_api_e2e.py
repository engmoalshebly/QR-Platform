"""End-to-end acceptance coverage for the mobile field API.

All rows are created through the transactional fixtures and rolled back after
the test.  The test exercises the same HTTP surface used by the field PWA and
native client, without touching a real event, invitation, or device session.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text


async def _create_active_field_world(db, world):
    now = (await db.execute(text("SELECT now()"))).scalar()
    operation_id, gate_id, second_gate_id, shift_id = (uuid4() for _ in range(4))

    await db.execute(text("""
        INSERT INTO event_operations
          (id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status)
        VALUES (:id, :event_id, :requester, :provider, :manager, 'in_progress')
    """), {
        "id": str(operation_id), "event_id": str(world["event_id"]),
        "requester": str(world["requester_tenant"]), "provider": str(world["provider_tenant"]),
        "manager": str(world["provider_user"]),
    })
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id, user_id, role)
        VALUES (:operation_id, :user_id, 'manager')
    """), {"operation_id": str(operation_id), "user_id": str(world["provider_user"])})
    await db.execute(text("""
        INSERT INTO event_gates(id, event_id, name, allowed_classes, is_active)
        VALUES
          (:gate_id, :event_id, 'Field gate', ARRAY['normal', 'vip']::ticket_class[], TRUE),
          (:second_gate_id, :event_id, 'Other gate', ARRAY['normal']::ticket_class[], TRUE)
    """), {
        "gate_id": str(gate_id), "second_gate_id": str(second_gate_id),
        "event_id": str(world["event_id"]),
    })
    await db.execute(text("""
        INSERT INTO event_gate_shifts
          (id, event_id, gate_id, operation_id, starts_at, ends_at, timezone,
           status, supervisor_user_id, created_by, activated_at)
        VALUES (:shift_id, :event_id, :gate_id, :operation_id, :starts_at, :ends_at,
                'UTC', 'active', :user_id, :user_id, now())
    """), {
        "shift_id": str(shift_id), "event_id": str(world["event_id"]),
        "gate_id": str(gate_id), "operation_id": str(operation_id),
        "starts_at": now - timedelta(minutes=10), "ends_at": now + timedelta(hours=2),
        "user_id": str(world["provider_user"]),
    })
    await db.execute(text("""
        INSERT INTO event_gate_shift_members(shift_id, user_id, role, assigned_by)
        VALUES (:shift_id, :user_id, 'scanner', :user_id)
    """), {"shift_id": str(shift_id), "user_id": str(world["provider_user"])})
    return {
        "now": now, "operation_id": operation_id, "gate_id": gate_id,
        "second_gate_id": second_gate_id, "shift_id": shift_id,
    }


async def _add_invitation(db, *, tenant_id, event_id, token, name, count=1, gate_id=None, registration=False):
    invitation_id = uuid4()
    await db.execute(text("""
        INSERT INTO invitations
          (id, tenant_id, event_id, token, ticket_class, guest_name, guest_count,
           checkin_count, status, gate_id, is_registration)
        VALUES (:id, :tenant_id, :event_id, :token, 'normal', :name, :count,
                0, 'sent', :gate_id, :registration)
    """), {
        "id": str(invitation_id), "tenant_id": str(tenant_id), "event_id": str(event_id),
        "token": token, "name": name, "count": count,
        "gate_id": str(gate_id) if gate_id else None, "registration": registration,
    })
    return invitation_id


@pytest.mark.asyncio
async def test_mobile_field_api_full_scanner_lifecycle(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """A scanner can only operate an assigned active gate session end-to-end."""
    # The application tenant middleware intentionally opens its own database
    # transaction before routing.  This acceptance test instead keeps every
    # fixture row in one rollback-only transaction; route handlers still
    # enforce X-Tenant-ID, membership, permissions, shifts and sessions.

    state = await _create_active_field_world(db_session, org_world)
    # The shared fixture creates a future event for general tests.  This
    # acceptance path explicitly operates it today so briefing and scanner
    # authorization can exercise the field-day gate.
    await db_session.execute(text("""
        UPDATE events
        SET start_date = now() - interval '1 hour',
            end_date = now() + interval '4 hours', timezone = 'UTC'
        WHERE id = :event_id
    """), {"event_id": str(org_world["event_id"])})
    group_invitation = await _add_invitation(
        db_session, tenant_id=org_world["requester_tenant"], event_id=org_world["event_id"],
        token="field-group-token-001", name="Field Group Guest", count=3,
    )
    sync_invitation = await _add_invitation(
        db_session, tenant_id=org_world["requester_tenant"], event_id=org_world["event_id"],
        token="field-sync-token-0001", name="Offline Queue Guest", count=1,
    )
    wrong_gate_invitation = await _add_invitation(
        db_session, tenant_id=org_world["requester_tenant"], event_id=org_world["event_id"],
        token="field-other-gate-001", name="Wrong Gate Guest", gate_id=state["second_gate_id"],
    )
    registration_invitation = await _add_invitation(
        db_session, tenant_id=org_world["requester_tenant"], event_id=org_world["event_id"],
        token="field-register-token1", name="Registration Code", registration=True,
    )
    headers = auth_headers(org_world["provider_tenant"])
    captured_at = datetime.now(timezone.utc).isoformat()

    async with client_factory(org_world["provider_user"]) as client:
        settings = await client.get(
            "/api/v1/mobile/settings",
            params={"device_id": "field-e2e-test-device-0001"},
            headers=headers,
        )
        assert settings.status_code == 200, settings.text
        settings_payload = settings.json()
        assert settings_payload["user"]["id"] == str(org_world["provider_user"])
        assert settings_payload["workspace"]["tenant_id"] == str(org_world["provider_tenant"])
        assert "checkin.scan" in settings_payload["permissions"]
        assert settings_payload["device"]["active_session"] is None
        assert "guest_name" not in str(settings_payload)
        assert "invitation" not in str(settings_payload).lower()

        # The device starts with only its own active shift; no guest list leaks here.
        shifts = await client.get("/api/v1/mobile/shifts", params={"date": state["now"].date().isoformat()}, headers=headers)
        assert shifts.status_code == 200, shifts.text
        payload = shifts.json()
        assert len(payload) == 1
        assert payload[0]["shift_id"] == str(state["shift_id"])
        assert payload[0]["gate_id"] == str(state["gate_id"])
        assert payload[0]["can_start"] is True

        # Every assigned event is visible for planning, but the protected
        # briefing contains only event-level totals and is gated by its local
        # event day.
        events = await client.get("/api/v1/mobile/events", headers=headers)
        assert events.status_code == 200, events.text
        assert events.json()[0]["event_id"] == str(org_world["event_id"])
        assert events.json()[0]["is_available_today"] is True
        briefing = await client.get(f"/api/v1/mobile/events/{org_world['event_id']}/briefing", headers=headers)
        assert briefing.status_code == 200, briefing.text
        briefing_payload = briefing.json()
        assert briefing_payload["statistics"] == {
            "total_invitations": 3,
            "vip_invitations": 0,
            "normal_invitations": 3,
            "expected_guests": 5,
            "checked_in_guests": 0,
        }
        assert "guest_name" not in str(briefing_payload)
        assert briefing_payload["shifts"][0]["gate_id"] == str(state["gate_id"])

        # RSVP can change after an offline pack is created. These invitations
        # are deliberately online-only, so a stale pending/declined response
        # can never become a physical offline admission.
        rsvp_pending_id = uuid4()
        await db_session.execute(text("""
            INSERT INTO invitations
              (id, tenant_id, event_id, token, ticket_class, guest_name,
               guest_count, checkin_count, status, rsvp_status, metadata)
            VALUES
              (:id, :tenant_id, :event_id, 'field-rsvp-pending-001', 'normal',
               'RSVP Pending Guest', 1, 0, 'sent', 'pending',
               '{"require_rsvp": true}'::jsonb)
        """), {
            "id": str(rsvp_pending_id),
            "tenant_id": str(org_world["requester_tenant"]),
            "event_id": str(org_world["event_id"]),
        })

        started = await client.post("/api/v1/mobile/device-sessions", headers=headers, json={
            "shift_id": str(state["shift_id"]), "device_id": "field-e2e-test-device-0001",
            "device_name": "Field API acceptance device", "platform": "android", "app_version": "1.0.0",
        })
        assert started.status_code == 201, started.text
        session = started.json()
        assert session["gate_id"] == str(state["gate_id"])
        assert len(session["session_token"]) >= 20
        field_headers = {
            **headers,
            "X-Field-Device-Session": session["id"],
            "X-Field-Device-Token": session["session_token"],
        }

        pack = await client.get(f"/api/v1/mobile/checkin-pack/{state['shift_id']}", headers=field_headers)
        assert pack.status_code == 200, pack.text
        pack_payload = pack.json()
        assert {"pack_id", "fingerprint_salt", "items", "valid_until"} <= set(pack_payload)
        assert pack_payload["items"]
        assert "guest_name" not in str(pack_payload)
        assert "phone" not in str(pack_payload).lower()
        rsvp_pack_item = await db_session.execute(text("""
            SELECT COUNT(*)
            FROM event_gate_offline_pack_items
            WHERE pack_id = :pack_id AND invitation_id = :invitation_id
        """), {"pack_id": pack_payload["pack_id"], "invitation_id": str(rsvp_pending_id)})
        assert rsvp_pack_item.scalar() == 0

        # Raw legacy/Code128 values are accepted, with atomic partial entry of a group invitation.
        online_id = str(uuid4())
        first_checkin = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-group-token-001", "entry_count": 2,
            "client_scan_id": online_id, "client_captured_at": captured_at, "scan_method": "code128",
        })
        assert first_checkin.status_code == 200, first_checkin.text
        assert first_checkin.json()["result"] == "success"
        assert first_checkin.json()["remaining_count"] == 1
        assert first_checkin.json()["guest_name"] == "Field Group Guest"

        # Replaying the identical request never adds a second check-in.
        replay = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-group-token-001", "entry_count": 2,
            "client_scan_id": online_id, "client_captured_at": captured_at, "scan_method": "code128",
        })
        assert replay.status_code == 200
        assert replay.json()["idempotent"] is True
        count = await db_session.execute(text("SELECT checkin_count FROM invitations WHERE id = :id"), {"id": str(group_invitation)})
        assert count.scalar() == 2

        capacity = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-group-token-001", "entry_count": 2,
            "client_scan_id": str(uuid4()), "client_captured_at": captured_at, "scan_method": "camera",
        })
        assert capacity.status_code == 200
        assert capacity.json()["result"] == "capacity_exceeded"
        assert capacity.json()["requires_assistance"] is True

        # Gate scope and registration scope are enforced server-side, not by UI hiding.
        wrong_gate = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-other-gate-001", "entry_count": 1,
            "client_scan_id": str(uuid4()), "client_captured_at": captured_at, "scan_method": "camera",
        })
        assert wrong_gate.status_code == 200
        assert wrong_gate.json()["result"] == "wrong_gate"
        registration = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-register-token1", "entry_count": 1,
            "client_scan_id": str(uuid4()), "client_captured_at": captured_at, "scan_method": "camera",
        })
        assert registration.status_code == 200
        assert registration.json()["result"] == "registration_code"

        # Search is limited to the active event/gate, and manual admission uses a separate capability.
        search = await client.get("/api/v1/mobile/invitations/search", params={"query": "Field Group"}, headers=field_headers)
        assert search.status_code == 200
        assert [row["id"] for row in search.json()] == [str(group_invitation)]
        manual = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "invitation_id": str(group_invitation), "entry_count": 1,
            "client_scan_id": str(uuid4()), "client_captured_at": captured_at, "scan_method": "manual",
        })
        assert manual.status_code == 200
        assert manual.json()["result"] == "success"
        assert manual.json()["remaining_count"] == 0

        # The offline pack accepts a queue item once, omits PII in the outcome, and is idempotent.
        sync_item = {
            "client_scan_id": str(uuid4()), "captured_at": captured_at,
            "raw_code": "field-sync-token-0001", "entry_count": 1,
            "pack_version": pack_payload["version"], "scan_method": "camera",
        }
        synced = await client.post("/api/v1/mobile/checkins/sync", headers=field_headers, json={
            "pack_id": pack_payload["pack_id"], "items": [sync_item],
        })
        assert synced.status_code == 200, synced.text
        assert synced.json()["results"][0]["result"] == "success"
        assert synced.json()["results"][0]["guest_name"] is None
        sync_replay = await client.post("/api/v1/mobile/checkins/sync", headers=field_headers, json={
            "pack_id": pack_payload["pack_id"], "items": [sync_item],
        })
        assert sync_replay.status_code == 200
        assert sync_replay.json()["results"][0]["idempotent"] is True
        sync_count = await db_session.execute(text("SELECT checkin_count FROM invitations WHERE id = :id"), {"id": str(sync_invitation)})
        assert sync_count.scalar() == 1

        assistance = await client.post("/api/v1/mobile/assistance", headers=field_headers, json={
            "assistance_type": "device", "note": "Acceptance test request",
        })
        assert assistance.status_code == 201
        assert assistance.json()["status"] == "open"

        closed = await client.post(f"/api/v1/mobile/device-sessions/{session['id']}/close", headers=headers)
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        after_close = await client.post("/api/v1/mobile/checkins", headers=field_headers, json={
            "raw_code": "field-group-token-001", "entry_count": 1,
            "client_scan_id": str(uuid4()), "client_captured_at": captured_at, "scan_method": "camera",
        })
        assert after_close.status_code == 403

        # A second active device for the same scanner/shift is explicitly
        # rejected.  It runs last because its expected integrity rollback is
        # intentionally observable by the rollback-only test transaction.
        replacement = await client.post("/api/v1/mobile/device-sessions", headers=headers, json={
            "shift_id": str(state["shift_id"]), "device_id": "field-e2e-test-device-0002",
        })
        assert replacement.status_code == 201
        duplicate_device = await client.post("/api/v1/mobile/device-sessions", headers=headers, json={
            "shift_id": str(state["shift_id"]), "device_id": "field-e2e-test-device-0003",
        })
        assert duplicate_device.status_code == 409


@pytest.mark.asyncio
async def test_mobile_event_briefing_and_scanner_are_locked_until_event_day(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """A future assignment can be planned, but cannot expose briefing or scan."""

    state = await _create_active_field_world(db_session, org_world)
    headers = auth_headers(org_world["provider_tenant"])
    async with client_factory(org_world["provider_user"]) as client:
        events = await client.get("/api/v1/mobile/events", headers=headers)
        assert events.status_code == 200
        assert events.json()[0]["is_available_today"] is False

        briefing = await client.get(f"/api/v1/mobile/events/{org_world['event_id']}/briefing", headers=headers)
        assert briefing.status_code == 403

        start = await client.post("/api/v1/mobile/device-sessions", headers=headers, json={
            "shift_id": str(state["shift_id"]), "device_id": "future-event-lock-test-device",
        })
        assert start.status_code == 403
