"""Mobile-first field APIs.

This module is intentionally the only browser-facing field surface.  It never
returns a general invitation list or raw QR data, and every operation is bound
to an active device session, scheduled shift, operation membership and gate.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime
import hashlib
import hmac
import json
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.audit_service import extract_audit_context, log_audit
from app.services.field_checkin_service import (
    FIELD_MESSAGES,
    FieldCheckinResult,
    claim_client_scan,
    code_fingerprint,
    process_field_checkin,
    record_field_attempt,
)
from app.services.field_qr_service import FieldQRCodeError, parse_invitation_code
from app.services.gate_shift_service import (
    get_shift_with_provider_access,
    hash_device_session_token,
    require_active_gate_session,
)
from app.services.permission_service import get_user_permissions, require_permission


router = APIRouter(prefix="/mobile", tags=["Mobile field foundation"])

# Field sessions have no background heartbeat while a scanner is idle.  We only
# hand over a session automatically after a deliberately conservative window:
# a normal gate shift must never be displaced just because nobody scanned for a
# few minutes.  A current session still requires an explicit handover by its
# scanner or a supervisor.
STALE_DEVICE_SESSION_IDLE_HOURS = 6


# The field client needs a compact, explainable view of its capabilities.  Do
# not expose the tenant's complete permission graph to a scanner device.
FIELD_SETTINGS_PERMISSION_KEYS = (
    "checkin.scan",
    "checkin.search",
    "checkin.manual",
    "checkin.supervise",
    "gates.view",
    "gate.shift.manage",
)


class DeviceSessionStart(BaseModel):
    shift_id: UUID
    device_id: str = Field(min_length=8, max_length=200)
    device_name: Optional[str] = Field(default=None, max_length=160)
    platform: Optional[str] = Field(default=None, max_length=64)
    app_version: Optional[str] = Field(default=None, max_length=64)


class FieldCheckinRequest(BaseModel):
    raw_code: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    invitation_id: Optional[UUID] = None
    entry_count: int = Field(default=1, ge=1, le=10000)
    client_scan_id: UUID
    client_captured_at: Optional[datetime] = None
    scan_method: Literal["camera", "manual", "code128"] = "camera"

    @model_validator(mode="after")
    def require_code_or_manual_invitation(self) -> "FieldCheckinRequest":
        if bool(self.raw_code) == bool(self.invitation_id):
            raise ValueError("أرسل رمز دعوة واحداً أو دعوة مختارة يدوياً، وليس كليهما")
        return self


class OfflineCheckinItem(BaseModel):
    client_scan_id: UUID
    captured_at: datetime
    raw_code: str = Field(min_length=1, max_length=4096)
    entry_count: int = Field(ge=1, le=10000)
    pack_version: int = Field(ge=1)
    scan_method: Literal["camera", "manual", "code128"] = "camera"


class OfflineSyncRequest(BaseModel):
    pack_id: UUID
    items: list[OfflineCheckinItem] = Field(min_length=1, max_length=100)


class AssistanceRequest(BaseModel):
    assistance_type: Literal["duplicate", "manual_confirmation", "access", "device", "offline_conflict", "other"]
    note: Optional[str] = Field(default=None, max_length=500)


async def _create_assistance_request(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session: dict,
    requested_by: UUID,
    assistance_type: str,
    note: str | None,
) -> dict:
    """Create a PII-free assistance alert and fan it out to shift supervisors."""
    created = await db.execute(text("""
        INSERT INTO gate_assistance_requests
          (device_session_id, shift_id, event_id, gate_id, requested_by, assistance_type, note)
        VALUES (:session_id, :shift_id, :event_id, :gate_id, :user_id, :assistance_type, :note)
        RETURNING id, status, created_at
    """), {"session_id": str(session["id"]), "shift_id": str(session["shift_id"]),
            "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]),
            "user_id": str(requested_by), "assistance_type": assistance_type, "note": note})
    row = dict(created.mappings().first())
    supervisors = await db.execute(text("""
        SELECT DISTINCT sm.user_id FROM event_gate_shift_members sm
        WHERE sm.shift_id = :shift_id AND sm.role = 'supervisor' AND sm.is_active
    """), {"shift_id": str(session["shift_id"])})
    for supervisor in supervisors.scalars().all():
        if supervisor == requested_by:
            continue
        await db.execute(text("""
            INSERT INTO notifications (tenant_id, user_id, type, title, message, metadata)
            VALUES (:tenant_id, :user_id, 'gate_assistance', 'طلب مساعدة عند البوابة',
                    :message, CAST(:metadata AS jsonb))
        """), {"tenant_id": str(tenant_id), "user_id": str(supervisor),
                "message": f"طلب مساعدة: {assistance_type}",
                "metadata": json.dumps({"request_id": str(row["id"]), "shift_id": str(session["shift_id"]), "gate_id": str(session["gate_id"])})})
    return row


def _field_headers(
    device_session_id: Optional[UUID] = Header(default=None, alias="X-Field-Device-Session"),
    device_session_token: Optional[str] = Header(default=None, alias="X-Field-Device-Token", min_length=20, max_length=512),
) -> tuple[UUID | None, str | None]:
    """Keep the opaque session secret out of JSON bodies and sync queues."""
    return device_session_id, device_session_token


async def _require_field_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    device_session_id: UUID | None,
    device_session_token: str | None,
) -> dict:
    """Resolve a session only after the full shift/gate access decision."""
    if not device_session_id:
        raise HTTPException(403, "ابدأ جلسة جهاز صالحة قبل استخدام أدوات البوابة")
    candidate_result = await db.execute(text("""
        SELECT ds.event_id, ds.gate_id
        FROM event_gate_device_sessions ds
        JOIN event_gate_shifts s ON s.id = ds.shift_id
        JOIN event_operations o ON o.id = s.operation_id
        WHERE ds.id = :session_id AND ds.user_id = :user_id
          AND o.provider_tenant_id = :tenant_id
    """), {"session_id": str(device_session_id), "user_id": str(user_id), "tenant_id": str(tenant_id)})
    candidate = candidate_result.mappings().first()
    if not candidate:
        raise HTTPException(403, "جلسة جهاز البوابة غير صالحة")
    session = await require_active_gate_session(
        db, tenant_id=tenant_id, user_id=user_id,
        event_id=candidate["event_id"], gate_id=candidate["gate_id"],
        device_session_id=device_session_id, device_session_token=device_session_token,
    )
    return dict(session)


async def _auditable_stale_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    device_session_id: UUID | None,
    device_session_token: str | None,
) -> dict | None:
    """Resolve an expired/revoked session only to log late offline syncs."""
    if not device_session_id or not device_session_token:
        return None
    result = await db.execute(text("""
        SELECT ds.id, ds.session_token_hash, ds.shift_id, ds.event_id, ds.gate_id,
               ds.status AS device_status, s.status AS shift_status, sm.role AS shift_role
        FROM event_gate_device_sessions ds
        JOIN event_gate_shifts s ON s.id = ds.shift_id
        JOIN event_gate_shift_members sm ON sm.shift_id = s.id AND sm.user_id = ds.user_id
        JOIN event_operations o ON o.id = s.operation_id
        WHERE ds.id = :session_id AND ds.user_id = :user_id
          AND o.provider_tenant_id = :tenant_id
        LIMIT 1
    """), {"session_id": str(device_session_id), "user_id": str(user_id), "tenant_id": str(tenant_id)})
    row = result.mappings().first()
    if not row:
        return None
    if not hmac.compare_digest(hashlib.sha256(device_session_token.encode("utf-8")).hexdigest(), row["session_token_hash"]):
        return None
    return dict(row)


async def _manual_raw_code(
    db: AsyncSession,
    *,
    invitation_id: UUID,
    session: dict,
) -> str:
    """Fetch only the server-side token of a selected, same-event invitation."""
    result = await db.execute(text("""
        SELECT token FROM invitations
        WHERE id = :invitation_id AND event_id = :event_id
          AND COALESCE(is_registration, FALSE) = FALSE
    """), {"invitation_id": str(invitation_id), "event_id": str(session["event_id"])})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدعوة غير متاحة للتأكيد اليدوي في هذا الحفل")
    return row["token"]


@router.get("/shifts")
async def my_mobile_shifts(
    request: Request,
    date_value: Optional[date] = Query(default=None, alias="date"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return only the caller's shifts for a local operating day."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    target_day = date_value or date.today()
    result = await db.execute(text("""
        SELECT s.id AS shift_id, s.event_id, s.gate_id, s.operation_id,
               s.starts_at, s.ends_at, s.timezone, s.status,
               sm.role AS shift_role, g.name AS gate_name, g.name_ar AS gate_name_ar,
               e.title AS event_title, e.title_ar AS event_title_ar,
               EXISTS (
                 SELECT 1 FROM event_gate_device_sessions ds
                 WHERE ds.shift_id = s.id AND ds.user_id = :user_id AND ds.status = 'active'
               ) AS has_active_device_session,
               (s.status = 'active' AND now() >= s.starts_at AND now() < s.ends_at AND g.is_active) AS can_start
        FROM event_gate_shifts s
        JOIN event_gate_shift_members sm
          ON sm.shift_id = s.id AND sm.user_id = :user_id AND sm.is_active
        JOIN event_gates g ON g.id = s.gate_id AND g.is_active
        JOIN event_operations o ON o.id = s.operation_id
        JOIN events e ON e.id = s.event_id
        WHERE o.provider_tenant_id = :tenant_id
          AND o.status NOT IN ('completed', 'closed', 'cancelled')
          AND s.status IN ('scheduled', 'active')
          AND (s.starts_at AT TIME ZONE s.timezone)::date <= :target_day
          AND (s.ends_at AT TIME ZONE s.timezone)::date >= :target_day
        ORDER BY s.starts_at, g.name
    """), {"user_id": str(user.id), "tenant_id": str(tenant_id), "target_day": target_day})
    return [dict(row) for row in result.mappings().all()]


@router.get("/settings")
async def mobile_field_settings(
    request: Request,
    device_id: Optional[str] = Query(default=None, min_length=8, max_length=200),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the signed-in operator's field-safe account and device context.

    This is deliberately a self-service profile endpoint, not a user directory.
    It returns no invitation data, no auth token, and only the small set of
    permissions that affect field operation.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")

    membership_result = await db.execute(text("""
        SELECT p.full_name, p.avatar_url, p.phone, p.status AS profile_status,
               p.email_verified_at,
               m.role AS membership_role, m.status AS membership_status,
               t.id AS tenant_id, t.name AS tenant_name, t.slug, t.plan,
               COALESCE(t.workspace_type, 'institution') AS workspace_type
        FROM memberships m
        JOIN tenants t ON t.id = m.tenant_id
        LEFT JOIN profiles p ON p.id = m.user_id
        WHERE m.tenant_id = :tenant_id AND m.user_id = :user_id
          AND m.status = 'active'
        LIMIT 1
    """), {"tenant_id": str(tenant_id), "user_id": str(user.id)})
    membership = membership_result.mappings().first()
    if not membership:
        raise HTTPException(403, "لا توجد عضوية نشطة لمساحة العمل الحالية")

    active_session_result = await db.execute(text("""
        SELECT ds.id, ds.device_id, ds.device_name, ds.platform, ds.app_version,
               ds.started_at, ds.last_seen_at,
               g.name AS gate_name, g.name_ar AS gate_name_ar,
               e.title AS event_title, e.title_ar AS event_title_ar
        FROM event_gate_device_sessions ds
        JOIN event_gate_shifts s ON s.id = ds.shift_id
        JOIN event_operations o ON o.id = s.operation_id
        JOIN event_gates g ON g.id = ds.gate_id
        JOIN events e ON e.id = ds.event_id
        WHERE ds.user_id = :user_id AND o.provider_tenant_id = :tenant_id
          AND ds.status = 'active'
          AND (CAST(:device_id AS TEXT) IS NULL OR ds.device_id = CAST(:device_id AS TEXT))
        ORDER BY ds.last_seen_at DESC
        LIMIT 1
    """), {
        "tenant_id": str(tenant_id),
        "user_id": str(user.id),
        "device_id": device_id.strip() if device_id else None,
    })
    active_session = active_session_result.mappings().first()
    granted_permissions = set(await get_user_permissions(db, tenant_id, user.id))

    return {
        "user": {
            "id": str(user.id),
            "full_name": membership["full_name"],
            "email": user.email,
            "phone": membership["phone"],
            "avatar_url": membership["avatar_url"],
            "status": membership["profile_status"],
            "email_verified": membership["email_verified_at"] is not None,
        },
        "workspace": {
            "tenant_id": str(membership["tenant_id"]),
            "name": membership["tenant_name"],
            "slug": membership["slug"],
            "plan": membership["plan"],
            "workspace_type": membership["workspace_type"],
            "membership_role": membership["membership_role"],
            "membership_status": membership["membership_status"],
        },
        "permissions": [
            permission
            for permission in FIELD_SETTINGS_PERMISSION_KEYS
            if permission in granted_permissions
        ],
        "device": {
            "device_id": device_id.strip() if device_id else (
                active_session["device_id"] if active_session else None
            ),
            "active_session": dict(active_session) if active_session else None,
        },
    }


@router.get("/events")
async def my_mobile_events(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List only events for which the caller has an operational gate assignment.

    This endpoint intentionally returns event identity and schedule only.  It
    lets a field member plan ahead without disclosing invitation statistics or
    guest information before the event's local operating day.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    result = await db.execute(text("""
        SELECT e.id AS event_id, o.id AS operation_id, e.title, e.title_ar,
               e.start_date, e.end_date, e.timezone, e.venue_name, e.venue_name_ar,
               COUNT(DISTINCT s.gate_id)::int AS assigned_gate_count,
               COUNT(DISTINCT s.id)::int AS assigned_shift_count,
               BOOL_OR(
                 (now() AT TIME ZONE e.timezone)::date >= (e.start_date AT TIME ZONE e.timezone)::date
                 AND (now() AT TIME ZONE e.timezone)::date <= COALESCE(
                   (e.end_date AT TIME ZONE e.timezone)::date,
                   (e.start_date AT TIME ZONE e.timezone)::date
                 )
               ) AS is_available_today,
               BOOL_OR(ds.id IS NOT NULL) AS has_active_device_session
        FROM event_gate_shifts s
        JOIN event_gate_shift_members sm
          ON sm.shift_id = s.id AND sm.user_id = :user_id AND sm.is_active
        JOIN event_operations o ON o.id = s.operation_id
        JOIN events e ON e.id = s.event_id
        LEFT JOIN event_gate_device_sessions ds
          ON ds.shift_id = s.id AND ds.user_id = :user_id AND ds.status = 'active'
        WHERE o.provider_tenant_id = :tenant_id
          AND o.status NOT IN ('completed', 'closed', 'cancelled')
          AND s.status IN ('scheduled', 'active')
        GROUP BY e.id, o.id
        ORDER BY e.start_date, e.title
    """), {"user_id": str(user.id), "tenant_id": str(tenant_id)})
    return [dict(row) for row in result.mappings().all()]


@router.get("/events/{event_id}/briefing")
async def mobile_event_briefing(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a field-safe event briefing only on the event's local date.

    The gate member receives aggregate invitation numbers and their own gates,
    never a list of invitees.  The same local-date rule is enforced here and
    in device-session creation so a manipulated mobile UI cannot open a future
    event early.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    event_result = await db.execute(text("""
        SELECT e.id AS event_id, e.title, e.title_ar, e.description,
               e.start_date, e.end_date, e.timezone, e.venue_name, e.venue_name_ar,
               (
                 (now() AT TIME ZONE e.timezone)::date >= (e.start_date AT TIME ZONE e.timezone)::date
                 AND (now() AT TIME ZONE e.timezone)::date <= COALESCE(
                   (e.end_date AT TIME ZONE e.timezone)::date,
                   (e.start_date AT TIME ZONE e.timezone)::date
                 )
               ) AS is_available_today
        FROM events e
        WHERE e.id = :event_id
          AND EXISTS (
            SELECT 1
            FROM event_gate_shifts s
            JOIN event_gate_shift_members sm
              ON sm.shift_id = s.id AND sm.user_id = :user_id AND sm.is_active
            JOIN event_operations o ON o.id = s.operation_id
            WHERE s.event_id = e.id
              AND o.provider_tenant_id = :tenant_id
              AND o.status NOT IN ('completed', 'closed', 'cancelled')
              AND s.status IN ('scheduled', 'active')
          )
    """), {"event_id": str(event_id), "user_id": str(user.id), "tenant_id": str(tenant_id)})
    event = event_result.mappings().first()
    if not event:
        raise HTTPException(404, "الحفل غير متاح ضمن إسناداتك التشغيلية")
    if not event["is_available_today"]:
        raise HTTPException(403, "يتاح ملف الحفل وتشغيل البوابة في يوم الحفل المحدد فقط")

    statistics_result = await db.execute(text("""
        SELECT COUNT(*)::int AS total_invitations,
               COUNT(*) FILTER (WHERE i.ticket_class = 'vip')::int AS vip_invitations,
               COUNT(*) FILTER (WHERE i.ticket_class = 'normal')::int AS normal_invitations,
               COALESCE(SUM(COALESCE(i.guest_count, 1)), 0)::int AS expected_guests,
               COALESCE(SUM(i.checkin_count), 0)::int AS checked_in_guests
        FROM invitations i
        WHERE i.event_id = :event_id
          AND COALESCE(i.is_registration, FALSE) = FALSE
          AND i.status NOT IN ('revoked', 'expired', 'declined')
    """), {"event_id": str(event_id)})
    statistics = dict(statistics_result.mappings().one())

    shifts_result = await db.execute(text("""
        SELECT s.id AS shift_id, s.event_id, s.gate_id, s.operation_id,
               s.starts_at, s.ends_at, s.timezone, s.status,
               sm.role AS shift_role, g.name AS gate_name, g.name_ar AS gate_name_ar,
               e.title AS event_title, e.title_ar AS event_title_ar,
               EXISTS (
                 SELECT 1 FROM event_gate_device_sessions ds
                 WHERE ds.shift_id = s.id AND ds.user_id = :user_id AND ds.status = 'active'
               ) AS has_active_device_session,
               (s.status = 'active' AND now() >= s.starts_at AND now() < s.ends_at AND g.is_active) AS can_start
        FROM event_gate_shifts s
        JOIN event_gate_shift_members sm
          ON sm.shift_id = s.id AND sm.user_id = :user_id AND sm.is_active
        JOIN event_gates g ON g.id = s.gate_id AND g.is_active
        JOIN event_operations o ON o.id = s.operation_id
        JOIN events e ON e.id = s.event_id
        WHERE s.event_id = :event_id AND o.provider_tenant_id = :tenant_id
          AND o.status NOT IN ('completed', 'closed', 'cancelled')
          AND s.status IN ('scheduled', 'active')
        ORDER BY s.starts_at, g.name
    """), {"event_id": str(event_id), "user_id": str(user.id), "tenant_id": str(tenant_id)})
    payload = dict(event)
    payload["statistics"] = statistics
    payload["shifts"] = [dict(row) for row in shifts_result.mappings().all()]
    return payload


@router.post("/device-sessions", status_code=status.HTTP_201_CREATED)
async def start_device_session(
    body: DeviceSessionStart,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the one allowed field-device session for the current shift."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    shift = await get_shift_with_provider_access(db, shift_id=body.shift_id, tenant_id=tenant_id)
    if not shift:
        raise HTTPException(404, "الوردية غير موجودة")
    event_day = await db.execute(text("""
        SELECT (
          (now() AT TIME ZONE e.timezone)::date >= (e.start_date AT TIME ZONE e.timezone)::date
          AND (now() AT TIME ZONE e.timezone)::date <= COALESCE(
            (e.end_date AT TIME ZONE e.timezone)::date,
            (e.start_date AT TIME ZONE e.timezone)::date
          )
        ) AS is_available_today
        FROM events e WHERE e.id = :event_id
    """), {"event_id": str(shift["event_id"])})
    if not event_day.scalar():
        raise HTTPException(403, "لا يمكن تشغيل بوابة الحفل قبل يوم الحفل أو بعد انتهائه")
    eligible = await db.execute(text("""
        SELECT sm.role
        FROM event_gate_shift_members sm
        JOIN event_gate_shifts s ON s.id = sm.shift_id
        JOIN event_gates g ON g.id = s.gate_id
        WHERE sm.shift_id = :shift_id AND sm.user_id = :user_id AND sm.is_active
          AND sm.role IN ('scanner', 'supervisor')
          AND s.status = 'active' AND now() >= s.starts_at AND now() < s.ends_at
          AND g.is_active
    """), {"shift_id": str(body.shift_id), "user_id": str(user.id)})
    role = eligible.scalar()
    if not role:
        raise HTTPException(403, "لا تملك وردية فعّالة على بوابة نشطة لبدء جلسة الجهاز")

    session_token = secrets.token_urlsafe(32)
    try:
        # A device can lose its locally stored session after an app reinstall or
        # a test/emulator reset.  Release only a demonstrably stale session that
        # would violate one of the active-session uniqueness rules.  Marking it
        # revoked (rather than deleting it) keeps the audit trail and revokes
        # any offline pack through the database trigger.
        stale_sessions = await db.execute(text("""
            UPDATE event_gate_device_sessions
            SET status = 'revoked', revoked_at = now(), revoked_by = :actor_user_id,
                closure_reason = 'stale_device_session_replaced'
            WHERE shift_id = :shift_id
              AND status = 'active'
              AND last_seen_at < now() - make_interval(hours => :idle_hours)
              AND (user_id = :user_id OR device_id = :device_id)
            RETURNING id, user_id, device_id, last_seen_at
        """), {
            "shift_id": str(body.shift_id),
            "actor_user_id": str(user.id),
            "user_id": str(user.id),
            "device_id": body.device_id.strip(),
            "idle_hours": STALE_DEVICE_SESSION_IDLE_HOURS,
        })
        for stale_session in stale_sessions.mappings().all():
            await log_audit(
                db,
                tenant_id=tenant_id,
                actor_user_id=user.id,
                action="gate_device_session.stale_replaced",
                resource_type="event_gate_device_session",
                resource_id=str(stale_session["id"]),
                metadata={
                    "shift_id": str(body.shift_id),
                    "previous_user_id": str(stale_session["user_id"]),
                    "previous_device_id": stale_session["device_id"],
                    "last_seen_at": stale_session["last_seen_at"].isoformat(),
                    "idle_hours_threshold": STALE_DEVICE_SESSION_IDLE_HOURS,
                },
                **extract_audit_context(request),
            )
        result = await db.execute(text("""
            INSERT INTO event_gate_device_sessions
              (shift_id, event_id, gate_id, user_id, device_id, device_name,
               platform, app_version, session_token_hash)
            VALUES (:shift_id, :event_id, :gate_id, :user_id, :device_id, :device_name,
                    :platform, :app_version, :session_token_hash)
            RETURNING id, shift_id, event_id, gate_id, user_id, device_id, device_name,
                      platform, app_version, status, started_at, last_seen_at
        """), {
            "shift_id": str(body.shift_id), "event_id": str(shift["event_id"]),
            "gate_id": str(shift["gate_id"]), "user_id": str(user.id),
            "device_id": body.device_id.strip(), "device_name": body.device_name,
            "platform": body.platform, "app_version": body.app_version,
            "session_token_hash": hash_device_session_token(session_token),
        })
        row = result.mappings().first()
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_device_session.started",
                        resource_type="event_gate_device_session", resource_id=str(row["id"]),
                        metadata={"shift_id": str(body.shift_id), "gate_id": str(shift["gate_id"]),
                                  "device_id": body.device_id.strip(), "shift_role": role},
                        **extract_audit_context(request))
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            409,
            "لديك جلسة جهاز فعّالة لهذه الوردية. اطلب من مشرف البوابة إلغاءها قبل البدء من جهاز آخر.",
        ) from error

    response = dict(row)
    # This opaque secret is returned once. It is not stored in a readable form
    # and must be held only by the authenticated field app.
    response["session_token"] = session_token
    return response


@router.get("/checkin-pack/{shift_id}")
async def download_checkin_pack(
    shift_id: UUID,
    request: Request,
    field_session: tuple[UUID | None, str | None] = Depends(_field_headers),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a minimal offline pack for the caller's current gate session.

    The response purposefully exposes only salted token fingerprints and entry
    constraints.  Names, email, phone, unmasked QR content, and the database
    invitation id never cross this endpoint.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    session = await _require_field_session(
        db, tenant_id=tenant_id, user_id=user.id,
        device_session_id=field_session[0], device_session_token=field_session[1],
    )
    if str(session["shift_id"]) != str(shift_id):
        raise HTTPException(403, "لا يمكن تنزيل حزمة وردية لبوابة أخرى")

    # Previous active pack stays stable: a device cannot silently refresh its
    # offline view half-way through a shift after invitations are revised.
    existing = await db.execute(text("""
        SELECT id, version, fingerprint_salt, valid_from, valid_until
        FROM event_gate_offline_packs
        WHERE device_session_id = :session_id AND shift_id = :shift_id
          AND status = 'active' AND valid_until > now()
        ORDER BY version DESC LIMIT 1
    """), {"session_id": str(session["id"]), "shift_id": str(shift_id)})
    pack = existing.mappings().first()
    if not pack:
        salt = secrets.token_urlsafe(32)
        created = await db.execute(text("""
            INSERT INTO event_gate_offline_packs
              (device_session_id, shift_id, event_id, gate_id, version,
               fingerprint_salt, valid_from, valid_until)
            VALUES (:session_id, :shift_id, :event_id, :gate_id, 1,
                    :salt, now(), :valid_until)
            RETURNING id, version, fingerprint_salt, valid_from, valid_until
        """), {
            "session_id": str(session["id"]), "shift_id": str(shift_id),
            "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]),
            "salt": salt, "valid_until": session["ends_at"],
        })
        pack = created.mappings().first()
        invitations = await db.execute(text("""
            SELECT i.id, i.token, i.ticket_class::text AS ticket_class,
                   COALESCE(i.guest_count, 1) AS guest_count, i.checkin_count, i.expires_at
            FROM invitations i
            JOIN event_gates g ON g.id = :gate_id
            WHERE i.event_id = :event_id
              AND COALESCE(i.is_registration, FALSE) = FALSE
              AND i.status NOT IN ('revoked', 'expired', 'declined')
              AND (i.expires_at IS NULL OR i.expires_at >= now())
              -- RSVP is mutable after a pack is downloaded. Keep every
              -- RSVP-required invitation online-only so an offline scanner
              -- can never admit a guest from a stale pending/declined state.
              AND LOWER(COALESCE(i.metadata ->> 'require_rsvp', 'false'))
                  NOT IN ('true', 't', '1', 'yes', 'on')
              AND i.ticket_class = ANY(g.allowed_classes)
              AND (i.gate_id IS NULL OR i.gate_id = :gate_id)
        """), {"event_id": str(session["event_id"]), "gate_id": str(session["gate_id"])})
        for invitation in invitations.mappings().all():
            await db.execute(text("""
                INSERT INTO event_gate_offline_pack_items
                  (pack_id, invitation_id, code_fingerprint, ticket_class,
                   allowed_count, remaining_count, expires_at)
                VALUES (:pack_id, :invitation_id, :fingerprint, CAST(:ticket_class AS ticket_class),
                        :allowed_count, :remaining_count, :expires_at)
            """), {
                "pack_id": str(pack["id"]), "invitation_id": str(invitation["id"]),
                "fingerprint": code_fingerprint(invitation["token"], salt=pack["fingerprint_salt"]),
                "ticket_class": invitation["ticket_class"], "allowed_count": invitation["guest_count"],
                "remaining_count": max(invitation["guest_count"] - invitation["checkin_count"], 0),
                "expires_at": invitation["expires_at"],
            })
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_offline_pack.created",
                        resource_type="event_gate_offline_pack", resource_id=str(pack["id"]),
                        metadata={"shift_id": str(shift_id), "gate_id": str(session["gate_id"]), "version": 1},
                        **extract_audit_context(request))
        await db.commit()

    items = await db.execute(text("""
        SELECT code_fingerprint, ticket_class::text AS ticket_class, allowed_count,
               remaining_count, expires_at
        FROM event_gate_offline_pack_items WHERE pack_id = :pack_id
    """), {"pack_id": str(pack["id"])})
    return {
        "pack_id": str(pack["id"]), "shift_id": str(shift_id), "gate_id": str(session["gate_id"]),
        "version": pack["version"], "fingerprint_salt": pack["fingerprint_salt"],
        "valid_from": pack["valid_from"], "valid_until": pack["valid_until"],
        "items": [dict(item) for item in items.mappings().all()],
    }


@router.post("/checkins")
async def field_checkin(
    body: FieldCheckinRequest,
    request: Request,
    field_session: tuple[UUID | None, str | None] = Depends(_field_headers),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Perform one online, session-bound atomic check-in from raw scan text."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    if body.invitation_id:
        # Lookup and confirmation are separate capabilities: a scanner cannot
        # turn raw scan access into a manual-admission bypass.
        await require_permission(db, tenant_id, user.id, "checkin.manual")
    session = await _require_field_session(
        db, tenant_id=tenant_id, user_id=user.id,
        device_session_id=field_session[0], device_session_token=field_session[1],
    )
    raw_code = body.raw_code or await _manual_raw_code(db, invitation_id=body.invitation_id, session=session)
    result = await process_field_checkin(
        db, session=session, user_id=user.id, raw_code=raw_code, entry_count=body.entry_count,
        scan_method=body.scan_method, client_scan_id=body.client_scan_id,
        client_captured_at=body.client_captured_at, request=request,
        expected_invitation_id=body.invitation_id,
    )
    await db.commit()
    return result.public_payload(include_guest_name=True)


@router.post("/checkins/sync")
async def sync_offline_checkins(
    body: OfflineSyncRequest,
    request: Request,
    field_session: tuple[UUID | None, str | None] = Depends(_field_headers),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Idempotently reconcile a device's encrypted offline queue.

    A stale/revoked pack can only create review audit entries: it cannot add a
    check-in.  Valid packs use the same atomic server routine as online scans;
    first valid arrival wins any inter-device offline conflict.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    try:
        session = await _require_field_session(
            db, tenant_id=tenant_id, user_id=user.id,
            device_session_id=field_session[0], device_session_token=field_session[1],
        )
    except HTTPException:
        session = await _auditable_stale_session(
            db, tenant_id=tenant_id, user_id=user.id,
            device_session_id=field_session[0], device_session_token=field_session[1],
        )
        if not session:
            raise

    pack_result = await db.execute(text("""
        SELECT * FROM event_gate_offline_packs
        WHERE id = :pack_id AND device_session_id = :session_id
          AND shift_id = :shift_id AND event_id = :event_id AND gate_id = :gate_id
    """), {"pack_id": str(body.pack_id), "session_id": str(session["id"]),
            "shift_id": str(session["shift_id"]), "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"])})
    pack = pack_result.mappings().first()
    if not pack:
        raise HTTPException(403, "حزمة العمل لا تخص جلسة هذا الجهاز")

    valid_pack = pack["status"] == "active" and pack["valid_until"] > datetime.now(pack["valid_until"].tzinfo)
    outcomes: list[dict] = []
    for item in body.items:
        # An offline replay must be identified before checking the mutable
        # cached remaining count; otherwise a successful first sync would make
        # its own retry look invalid.
        prior = await claim_client_scan(
            db, session=session, user_id=user.id, client_scan_id=item.client_scan_id,
            scan_method=f"offline_{item.scan_method}", raw_code=item.raw_code,
            client_captured_at=item.captured_at, request=request,
        )
        if prior:
            outcomes.append(prior.public_payload(include_guest_name=False))
            continue
        if not valid_pack or item.pack_version != pack["version"]:
            result = FieldCheckinResult(result="pack_invalid", message=FIELD_MESSAGES["pack_invalid"],
                                        entry_count=item.entry_count, requires_assistance=True)
            await record_field_attempt(db, session=session, user_id=user.id, client_scan_id=item.client_scan_id,
                                       scan_method=f"offline_{item.scan_method}", raw_code=item.raw_code, result=result,
                                       client_captured_at=item.captured_at, request=request, offline_pack_id=body.pack_id)
            outcomes.append(result.public_payload(include_guest_name=False))
            continue
        try:
            parsed = parse_invitation_code(item.raw_code)
            item_fingerprint = code_fingerprint(parsed.canonical_code, salt=pack["fingerprint_salt"])
        except FieldQRCodeError:
            item_fingerprint = ""
        pack_item_result = await db.execute(text("""
            SELECT invitation_id, remaining_count, allowed_count, expires_at
            FROM event_gate_offline_pack_items
            WHERE pack_id = :pack_id AND code_fingerprint = :fingerprint
        """), {"pack_id": str(body.pack_id), "fingerprint": item_fingerprint})
        pack_item = pack_item_result.mappings().first()
        if not pack_item or (pack_item["expires_at"] and pack_item["expires_at"] < datetime.now(pack["valid_until"].tzinfo)) or item.entry_count > pack_item["remaining_count"]:
            result = FieldCheckinResult(result="invalid", message=FIELD_MESSAGES["invalid"], entry_count=item.entry_count,
                                        requires_assistance=True)
            await record_field_attempt(db, session=session, user_id=user.id, client_scan_id=item.client_scan_id,
                                       scan_method=f"offline_{item.scan_method}", raw_code=item.raw_code, result=result,
                                       client_captured_at=item.captured_at, request=request, offline_pack_id=body.pack_id)
            outcomes.append(result.public_payload(include_guest_name=False))
            continue
        result = await process_field_checkin(
            db, session=session, user_id=user.id, raw_code=item.raw_code, entry_count=item.entry_count,
            scan_method=f"offline_{item.scan_method}", client_scan_id=item.client_scan_id,
            client_captured_at=item.captured_at, request=request,
            expected_invitation_id=pack_item["invitation_id"], offline_pack_id=body.pack_id, from_offline=True,
            client_scan_already_claimed=True,
        )
        if result.result == "success":
            await db.execute(text("""
                UPDATE event_gate_offline_pack_items
                SET remaining_count = GREATEST(remaining_count - :entry_count, 0)
                WHERE pack_id = :pack_id AND invitation_id = :invitation_id
            """), {"pack_id": str(body.pack_id), "invitation_id": str(pack_item["invitation_id"]), "entry_count": item.entry_count})
        elif result.result == "offline_conflict":
            await _create_assistance_request(
                db, tenant_id=tenant_id, session=session, requested_by=user.id,
                assistance_type="offline_conflict",
                note="تعارض مزامنة دون اتصال؛ يلزم مراجعة المشرف.",
            )
        outcomes.append(result.public_payload(include_guest_name=False))
    await db.commit()
    return {"pack_id": str(body.pack_id), "results": outcomes}


@router.get("/invitations/search")
async def search_field_invitations(
    request: Request,
    query: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=20),
    field_session: tuple[UUID | None, str | None] = Depends(_field_headers),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Minimal, scoped manual lookup — never a browsable guest list."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.search")
    session = await _require_field_session(
        db, tenant_id=tenant_id, user_id=user.id,
        device_session_id=field_session[0], device_session_token=field_session[1],
    )
    term = f"%{query.strip()}%"
    result = await db.execute(text("""
        SELECT i.id, COALESCE(NULLIF(i.guest_name_ar, ''), NULLIF(i.guest_name, ''), 'دعوة بلا اسم') AS label,
               i.ticket_class::text AS ticket_class, COALESCE(i.guest_count, 1) AS guest_count,
               i.checkin_count, GREATEST(COALESCE(i.guest_count, 1) - i.checkin_count, 0) AS remaining_count
        FROM invitations i
        JOIN event_gates g ON g.id = :gate_id
        WHERE i.event_id = :event_id AND COALESCE(i.is_registration, FALSE) = FALSE
          AND i.status NOT IN ('revoked', 'expired', 'declined')
          AND i.ticket_class = ANY(g.allowed_classes)
          AND (i.gate_id IS NULL OR i.gate_id = :gate_id)
          AND (COALESCE(i.guest_name_ar, '') ILIKE :term OR COALESCE(i.guest_name, '') ILIKE :term
               OR COALESCE(i.seat_number, '') ILIKE :term OR COALESCE(i.table_number, '') ILIKE :term)
        ORDER BY i.created_at DESC LIMIT :limit
    """), {"event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]), "term": term, "limit": limit})
    return [dict(row) for row in result.mappings().all()]


@router.post("/assistance", status_code=status.HTTP_201_CREATED)
async def request_gate_assistance(
    body: AssistanceRequest,
    request: Request,
    field_session: tuple[UUID | None, str | None] = Depends(_field_headers),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    session = await _require_field_session(
        db, tenant_id=tenant_id, user_id=user.id,
        device_session_id=field_session[0], device_session_token=field_session[1],
    )
    row = await _create_assistance_request(
        db, tenant_id=tenant_id, session=session, requested_by=user.id,
        assistance_type=body.assistance_type, note=body.note,
    )
    await db.commit()
    return row


@router.post("/device-sessions/{session_id}/close")
async def close_device_session(
    session_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close the caller's own device session as a documented handover."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.scan")
    result = await db.execute(text("""
        UPDATE event_gate_device_sessions ds
        SET status = 'closed', closed_at = now(), closure_reason = 'scanner_closed'
        FROM event_gate_shifts s
        JOIN event_operations o ON o.id = s.operation_id
        WHERE ds.id = :session_id AND ds.shift_id = s.id
          AND ds.user_id = :user_id AND ds.status = 'active'
          AND o.provider_tenant_id = :tenant_id
        RETURNING ds.id, ds.shift_id, ds.gate_id
    """), {"session_id": str(session_id), "user_id": str(user.id), "tenant_id": str(tenant_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "جلسة الجهاز غير نشطة أو لا تخصك")
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_device_session.closed",
                    resource_type="event_gate_device_session", resource_id=str(session_id),
                    metadata={"shift_id": str(row["shift_id"]), "gate_id": str(row["gate_id"])},
                    **extract_audit_context(request))
    await db.commit()
    return {"id": str(session_id), "status": "closed"}
