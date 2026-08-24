"""Supervisory attendance APIs and retired legacy scan endpoints.

All admission decisions now go through ``POST /api/v1/mobile/checkins``. It
uses the atomic field-check-in routine and a mandatory client scan identifier;
the historical routes below remain only to give old clients an explicit,
safe migration response rather than a weaker validation path.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.models.invitation import CheckinRead, CheckinRequest, CheckinResponse
from app.services.permission_service import (
    check_provider_event_access,
    get_event_owner_tenant,
    require_permission,
)


router = APIRouter(prefix="/checkin", tags=["Check-in"])

LEGACY_FIELD_CHECKIN_DETAIL = (
    "تم إيقاف مسار المسح القديم لحماية قواعد RSVP وإعادة الدخول. "
    "استخدم POST /api/v1/mobile/checkins مع جلسة جهاز نشطة ومعرّف client_scan_id."
)


@router.post("/scan", response_model=CheckinResponse, deprecated=True)
async def scan_checkin(
    body: CheckinRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retire the pre-field-client scanner path without inspecting QR data."""
    # Keep the old endpoint visible for a deliberate 410 migration response.
    # It must never fall back to validate_checkin(), which predates the field
    # transaction's RSVP, registration and re-entry policy.
    _ = (body, request, user, db)
    raise HTTPException(status_code=410, detail=LEGACY_FIELD_CHECKIN_DETAIL)


@router.post("/manual", response_model=CheckinResponse, deprecated=True)
async def manual_checkin(
    invitation_id: UUID,
    gate_id: UUID,
    device_session_id: UUID,
    device_session_token: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retire the legacy manual route; mobile manual confirmation is scoped."""
    _ = (invitation_id, gate_id, device_session_id, device_session_token, request, user, db)
    raise HTTPException(status_code=410, detail=LEGACY_FIELD_CHECKIN_DETAIL)


@router.get("/history", response_model=list[CheckinRead])
async def checkin_history(
    request: Request,
    event_id: Optional[UUID] = None,
    result_filter: Optional[str] = Query(None, alias="result"),
    limit: int = Query(100, le=500),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """View history. This is supervisory access, not field-scan access."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.view")
    if not event_id:
        raise HTTPException(422, "يجب تحديد الحفل لعرض سجل الحضور")
    if not await check_provider_event_access(db, event_id, tenant_id, user.id, "checkin.view"):
        raise HTTPException(403, "سجل الحضور متاح لفريق التشغيل المكلّف بالحفل فقط")
    query = "SELECT c.* FROM checkins c WHERE c.event_id = :event_id"
    params: dict = {"event_id": str(event_id), "limit": limit}
    if result_filter:
        query += " AND c.result = :result"
        params["result"] = result_filter
    query += " ORDER BY c.created_at DESC LIMIT :limit"
    result = await db.execute(text(query), params)
    return [CheckinRead(**dict(row)) for row in result.mappings().all()]


@router.get("/live/{event_id}")
async def live_stats(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live attendance metrics for the responsible operational team."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "checkin.live")
    if not await check_provider_event_access(db, event_id, tenant_id, user.id, "checkin.live"):
        raise HTTPException(403, "الحضور المباشر متاح لفريق التشغيل المكلّف بالحفل فقط")
    owner_tenant_id = await get_event_owner_tenant(db, event_id)
    result = await db.execute(text("""
        SELECT
          COUNT(*) FILTER (WHERE status = 'checked_in') AS checked_in,
          COUNT(*) FILTER (WHERE ticket_class = 'vip' AND status = 'checked_in') AS vip_checked_in,
          COUNT(*) FILTER (WHERE ticket_class = 'normal' AND status = 'checked_in') AS normal_checked_in,
          COUNT(*) FILTER (WHERE status NOT IN ('revoked', 'expired')) AS total_valid,
          COUNT(*) FILTER (WHERE ticket_class = 'vip' AND status NOT IN ('revoked', 'expired')) AS total_vip,
          COUNT(*) FILTER (WHERE ticket_class = 'normal' AND status NOT IN ('revoked', 'expired')) AS total_normal
        FROM invitations
        WHERE event_id = :event_id AND tenant_id = :tenant_id
    """), {"event_id": str(event_id), "tenant_id": str(owner_tenant_id)})
    recent = await db.execute(text("""
        SELECT c.created_at, c.result, i.guest_name, i.ticket_class, c.scan_method
        FROM checkins c JOIN invitations i ON i.id = c.invitation_id
        WHERE c.event_id = :event_id AND c.result = 'success'
        ORDER BY c.created_at DESC LIMIT 10
    """), {"event_id": str(event_id)})
    return {
        "stats": dict(result.mappings().first()),
        "recent_checkins": [dict(row) for row in recent.mappings().all()],
    }
