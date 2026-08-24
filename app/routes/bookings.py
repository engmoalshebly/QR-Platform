import asyncio
from datetime import datetime, timedelta
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.audit_service import log_audit
from app.services.email_service import send_booking_request_email, send_booking_response_email
from app.services.notification_service import create_notification, notify_tenant_managers, notify_operation_members
from app.services.feature_service import enforce_static_limit, acquire_plan_limit_lock
from app.services.usage_service import check_and_increment
from app.services.permission_service import require_permission
from app.security import get_client_ip

router = APIRouter(prefix="/bookings", tags=["Organizer bookings"])


class BookingCreate(BaseModel):
    provider_tenant_id: UUID
    event_id: UUID
    contact_phone: str = Field(min_length=8, max_length=40)
    services: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = Field(default=None, max_length=4000)

class BookingResponse(BaseModel):
    action: Literal["accepted", "rejected", "needs_information"]
    note: Optional[str] = Field(default=None, max_length=2000)

class BookingScheduleUpdate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: Optional[str] = Field(default=None, max_length=2000)

class BookingReason(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)

class BookingManagerAssign(BaseModel):
    user_id: UUID


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    color: str = Field(default="#C9A96E", pattern=r"^#[0-9A-Fa-f]{6}$")


class GroupMemberAdd(BaseModel):
    user_id: UUID


class GroupBookingAssign(BaseModel):
    booking_id: UUID


class GroupOperationAssign(BaseModel):
    operation_id: UUID


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


async def _require_tenant_manager(db: AsyncSession, tenant_id: UUID, user_id: UUID, permission: str = "bookings.view") -> None:
    await require_permission(db, tenant_id, user_id, permission)
    result = await db.execute(text("""
        SELECT 1 FROM memberships m
        WHERE m.tenant_id = :tid AND m.user_id = :uid AND m.status = 'active'
          AND (m.role IN ('owner', 'admin') OR EXISTS (
            SELECT 1 FROM membership_roles mr JOIN roles r ON r.id=mr.role_id
            WHERE mr.tenant_id=m.tenant_id AND mr.user_id=m.user_id
              AND r.name='team_manager'
          ))
    """), {"tid": str(tenant_id), "uid": str(user_id)})
    if not result.first():
        raise HTTPException(403, "هذه العملية متاحة لمدير الجهة فقط")


async def _is_provider(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(text("""
        SELECT 1
        FROM organization_requests o
        JOIN memberships m ON m.tenant_id = o.created_tenant_id
        JOIN membership_roles mr ON mr.tenant_id = m.tenant_id AND mr.user_id = m.user_id
        JOIN roles r ON r.id = mr.role_id AND r.name = 'team_manager'
        WHERE o.created_tenant_id = :tid AND o.status = 'approved'
          AND m.user_id = :uid AND m.status = 'active'
    """), {"tid": str(tenant_id), "uid": str(user_id)})
    return result.first() is not None


def _booking_row(row) -> dict:
    data = dict(row)
    for key in ("id", "requester_tenant_id", "provider_tenant_id", "requested_by", "responded_by"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    return data


async def _assert_event_has_no_other_active_operation(
    db: AsyncSession,
    event_id: UUID,
    *,
    booking_id: UUID | None = None,
) -> None:
    """Keep one active operational owner for each event.

    A booking can be retried safely for its own operation, but accepting a
    different booking for an event that is already being operated would grant
    two teams control of the same gates, check-ins, and guest data.
    """
    existing = await db.execute(text("""
        SELECT id
        FROM event_operations
        WHERE event_id = :event_id
          AND status NOT IN ('completed', 'closed', 'cancelled')
          AND (
                CAST(:booking_id AS uuid) IS NULL
                OR booking_id IS DISTINCT FROM CAST(:booking_id AS uuid)
          )
        LIMIT 1
    """), {
        "event_id": str(event_id),
        "booking_id": str(booking_id) if booking_id else None,
    })
    if existing.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="هذا الحفل مسند بالفعل إلى فريق تشغيل نشط.",
        )


async def provision_operation(db: AsyncSession, booking_id: UUID, booking, manager_id: UUID):
    """Idempotently create the operational workspace for an accepted booking."""
    # Serialise acceptance per event.  A provider-level lock alone cannot
    # prevent two different providers from accepting separate requests for the
    # same event at the same moment.
    event_id = UUID(str(booking["event_id"]))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"event-operation:{event_id}"},
    )
    await _assert_event_has_no_other_active_operation(
        db, event_id, booking_id=booking_id,
    )
    operation = await db.execute(text("""
        INSERT INTO event_operations
          (booking_id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id)
        VALUES (:booking_id, :event_id, :requester, :provider, :manager)
        ON CONFLICT (booking_id) DO UPDATE SET updated_at = now()
        RETURNING id
    """), {
        "booking_id": str(booking_id), "event_id": str(booking["event_id"]),
        "requester": str(booking["requester_tenant_id"]), "provider": str(booking["provider_tenant_id"]),
        "manager": str(manager_id),
    })
    operation_id = operation.scalar()
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id, user_id, role)
        VALUES (:operation_id, :user_id, 'manager')
        ON CONFLICT(operation_id, user_id) DO UPDATE SET role = 'manager'
    """), {"operation_id": str(operation_id), "user_id": str(manager_id)})
    await db.execute(text("""
        INSERT INTO event_operation_activity
          (operation_id, actor_user_id, action, entity_type, entity_id, details)
        VALUES (:operation_id, :actor, 'operation.created', 'operation', :entity_id,
                jsonb_build_object('booking_id', CAST(:booking_id AS uuid)))
    """), {"operation_id": str(operation_id), "actor": str(manager_id),
            "entity_id": str(operation_id), "booking_id": str(booking_id)})
    # Seed per-event-type task templates only when the operation has no tasks yet
    # (keeps provisioning idempotent across retries).
    existing_tasks = await db.execute(text("""
        SELECT 1 FROM event_operation_tasks WHERE operation_id = :oid LIMIT 1
    """), {"oid": str(operation_id)})
    if not existing_tasks.first():
        from app.routes.operations import seed_tasks_from_template
        await seed_tasks_from_template(db, operation_id, booking.get("event_type"), manager_id)
    return operation_id


@router.get("/context")
async def booking_context(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    # Context is used to select the workspace. Resolve the explicit role first
    # so a stale permission cache cannot route a real team manager to the
    # requester workspace; all data/mutations remain permission protected.
    is_provider = await _is_provider(db, tenant_id, user.id)
    if is_provider:
        return {"is_team_manager": True, "team_tenant_id": str(tenant_id)}
    # Recover from a stale tenant selector after login: identify the user's
    # approved provider tenant without granting any resource access here.
    result = await db.execute(text("""
      SELECT m.tenant_id FROM memberships m
      JOIN membership_roles mr ON mr.tenant_id=m.tenant_id AND mr.user_id=m.user_id
      JOIN roles r ON r.id=mr.role_id AND r.name='team_manager'
      JOIN organization_requests o ON o.created_tenant_id=m.tenant_id AND o.status='approved'
      WHERE m.user_id=:uid AND m.status='active' LIMIT 1
    """), {"uid": str(user.id)})
    provider_tenant = result.scalar()
    if provider_tenant:
        return {"is_team_manager": True, "team_tenant_id": str(provider_tenant)}
    # Workspace discovery must not turn a missing booking permission into a
    # global navigation failure.  Resource endpoints still enforce their own
    # permission and tenant-scope checks.
    return {"is_team_manager": False, "team_tenant_id": None}


@router.get("/organizer-teams")
async def list_organizer_teams(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    result = await db.execute(text("""
        SELECT t.id::text AS tenant_id, t.name, t.slug, t.status,
               r.org_type, r.description, r.city, r.country, r.website,
               r.phone, r.contact_handle, r.expected_events_per_month,
               (SELECT COUNT(*) FROM organizer_booking_requests b
                WHERE b.provider_tenant_id = t.id AND b.status = 'completed') AS completed_bookings
        FROM organization_requests r
        JOIN tenants t ON t.id = r.created_tenant_id
        WHERE r.status = 'approved' AND t.status IN ('active', 'trial')
          AND t.id <> :current
        ORDER BY t.name
    """), {"current": str(tenant_id)})
    return [dict(row) for row in result.mappings().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_booking(body: BookingCreate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.create")
    if await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "جهة التنظيم لا ترسل طلب حجز إلى جهة تنظيم أخرى")

    provider = await db.execute(text("""
        SELECT t.id, t.name, u.email AS manager_email
        FROM tenants t
        JOIN organization_requests r ON r.created_tenant_id = t.id AND r.status = 'approved'
        LEFT JOIN memberships m ON m.tenant_id = t.id AND m.role = 'owner' AND m.status = 'active'
        LEFT JOIN auth.users u ON u.id = m.user_id
        WHERE t.id = :pid AND t.status IN ('active', 'trial')
        LIMIT 1
    """), {"pid": str(body.provider_tenant_id)})
    provider_row = provider.mappings().first()
    if not provider_row:
        raise HTTPException(404, "فريق التنظيم غير موجود أو غير معتمد")

    event_result = await db.execute(text("""
        SELECT e.*, COALESCE(et.name_ar, et.name, ec.name_ar, ec.name, 'فعالية') AS event_type_name
        FROM events e
        LEFT JOIN event_types et ON et.id = e.event_type_id
        LEFT JOIN event_categories ec ON ec.id = e.category_id
        WHERE e.id = :eid AND e.tenant_id = :tid
    """), {"eid": str(body.event_id), "tid": str(tenant_id)})
    event = event_result.mappings().first()
    if not event:
        raise HTTPException(404, "الحفل غير موجود أو لا يتبع لمؤسستك")
    await _assert_event_has_no_other_active_operation(db, body.event_id)

    duplicate = await db.execute(text("""
        SELECT 1 FROM organizer_booking_requests
        WHERE event_id = :eid AND provider_tenant_id = :pid
          AND status IN ('pending', 'needs_information', 'accepted')
    """), {"eid": str(body.event_id), "pid": str(body.provider_tenant_id)})
    if duplicate.first():
        raise HTTPException(409, "يوجد طلب فعال لهذا الحفل مع نفس الفريق")

    contact_result = await db.execute(text("""
        SELECT COALESCE(NULLIF(p.full_name, ''), u.email) AS full_name, u.email
        FROM auth.users u LEFT JOIN profiles p ON p.id = u.id
        WHERE u.id = :uid
    """), {"uid": str(user.id)})
    contact = contact_result.mappings().first()
    if not contact:
        raise HTTPException(400, "تعذر العثور على بيانات حسابك")
    contact_phone = body.contact_phone.strip()
    await db.execute(text("UPDATE profiles SET phone = :phone, updated_at = now() WHERE id = :uid"),
                     {"phone": contact_phone, "uid": str(user.id)})

    starts_at = event["start_date"]
    ends_at = event["end_date"] or (starts_at + timedelta(hours=4))
    guest_count = (event["vip_quota"] or 0) + (event["normal_quota"] or 0) or 1
    location = ", ".join(filter(None, [event["venue_name"], event["venue_address"], event["venue_city"], event["venue_country"]]))
    await check_and_increment(db, tenant_id, "monthly_bookings", 1)

    result = await db.execute(text("""
        INSERT INTO organizer_booking_requests
          (requester_tenant_id, provider_tenant_id, requested_by, event_id, title, event_type,
           starts_at, ends_at, guest_count, location, contact_name, contact_phone,
           contact_email, services, notes)
        VALUES (:requester, :provider, :uid, :event_id, :title, :event_type, :starts, :ends,
                :guests, :location, :contact_name, :contact_phone, :contact_email,
                :services, :notes)
        RETURNING *
    """), {
        "requester": str(tenant_id), "provider": str(body.provider_tenant_id), "uid": str(user.id),
        "event_id": str(body.event_id), "title": event["title"], "event_type": event["event_type_name"],
        "starts": starts_at, "ends": ends_at, "guests": guest_count, "location": location or None,
        "contact_name": contact["full_name"], "contact_phone": contact_phone,
        "contact_email": contact["email"],
        "services": body.services, "notes": body.notes,
    })
    row = result.mappings().first()
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="booking.request.create",
                    resource_type="organizer_booking_request", resource_id=str(row["id"]),
                    ip_address=get_client_ip(request))
    await notify_tenant_managers(
        db, body.provider_tenant_id,
        notification_type="booking.created", title="طلب حجز جديد",
        message=f"وصل طلب جديد لإدارة حفل {event['title']}", link="/teams",
        metadata={"booking_id": str(row["id"]), "event_id": str(body.event_id)},
    )
    await db.commit()
    if provider_row.get("manager_email"):
        asyncio.create_task(asyncio.to_thread(send_booking_request_email, provider_row["manager_email"], event["title"], starts_at))
    return _booking_row(row)


BOOKING_SELECT = """
    SELECT b.*, rt.name AS requester_name, pt.name AS provider_name,
           e.description AS event_description, e.status AS event_status,
           e.timezone AS event_timezone, e.venue_map_url AS event_map_url,
           e.cover_image_url AS event_cover_image_url
    FROM organizer_booking_requests b
    JOIN tenants rt ON rt.id = b.requester_tenant_id
    JOIN tenants pt ON pt.id = b.provider_tenant_id
    LEFT JOIN events e ON e.id = b.event_id
"""


@router.get("/sent")
async def sent_bookings(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    result = await db.execute(text(BOOKING_SELECT + " WHERE b.requester_tenant_id = :tid ORDER BY b.created_at DESC"), {"tid": str(tenant_id)})
    return [_booking_row(row) for row in result.mappings().all()]


@router.get("/inbox")
async def inbox_bookings(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "صندوق الطلبات متاح لمدير فريق التنظيم فقط")
    result = await db.execute(text(BOOKING_SELECT + " WHERE b.provider_tenant_id = :tid ORDER BY b.created_at DESC"), {"tid": str(tenant_id)})
    return [_booking_row(row) for row in result.mappings().all()]


@router.get("/analytics")
async def booking_analytics(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    result = await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status = 'pending') AS pending,
               COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
               COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed,
               COALESCE(SUM(guest_count) FILTER (WHERE status IN ('accepted','completed')), 0) AS guests
        FROM organizer_booking_requests WHERE provider_tenant_id = :tid
    """), {"tid": str(tenant_id)})
    return dict(result.mappings().first())


@router.post("/{booking_id}/respond")
async def respond_booking(booking_id: UUID, body: BookingResponse, request: Request,
                          user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.respond")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": str(tenant_id)})
    result = await db.execute(text(BOOKING_SELECT + " WHERE b.id = :id AND b.provider_tenant_id = :tid FOR UPDATE OF b"),
                              {"id": str(booking_id), "tid": str(tenant_id)})
    booking = result.mappings().first()
    if not booking:
        raise HTTPException(404, "طلب الحجز غير موجود")
    if booking["status"] not in ("pending", "needs_information"):
        raise HTTPException(409, "تمت معالجة هذا الطلب مسبقاً")
    if body.action in ("rejected", "needs_information") and not body.note:
        raise HTTPException(422, "A reason is required")
    if body.action == "accepted":
        conflict = await db.execute(text("""
            SELECT 1 FROM organizer_booking_requests
            WHERE provider_tenant_id = :tid AND status = 'accepted' AND id <> :id
              AND starts_at < :ends AND ends_at > :starts
            LIMIT 1
        """), {"tid": str(tenant_id), "id": str(booking_id), "starts": booking["starts_at"], "ends": booking["ends_at"]})
        if conflict.first():
            raise HTTPException(409, "يوجد حجز مقبول يتعارض مع هذا الموعد")
    updated = await db.execute(text("""
        UPDATE organizer_booking_requests
        SET status = :action, response_note = :note, status_reason = :note, responded_by = :uid,
            responded_at = now(), updated_at = now()
        WHERE id = :id AND status IN ('pending', 'needs_information')
        RETURNING *
    """), {"action": body.action, "note": body.note, "uid": str(user.id), "id": str(booking_id)})
    row = updated.mappings().first()
    operation_id = None
    if body.action == "accepted":
        operation_id = await provision_operation(db, booking_id, booking, user.id)
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action=f"booking.request.{body.action}",
                    resource_type="organizer_booking_request", resource_id=str(booking_id),
                    ip_address=get_client_ip(request))
    requester_email = await db.execute(text("SELECT email FROM auth.users WHERE id = :uid"), {"uid": str(booking["requested_by"])})
    email = requester_email.scalar()
    action_titles = {
        "accepted": ("تم قبول طلب الحجز", f"وافق فريق التنظيم على إدارة حفل {booking['title']}"),
        "rejected": ("تم رفض طلب الحجز", f"تعذر قبول طلب إدارة حفل {booking['title']}"),
        "needs_information": ("معلومات إضافية مطلوبة", f"طلب فريق التنظيم معلومات إضافية عن حفل {booking['title']}"),
    }
    notification_title, notification_message = action_titles[body.action]
    await create_notification(
        db, booking["requester_tenant_id"], f"booking.{body.action}",
        notification_title, notification_message, user_id=booking["requested_by"], link="/teams",
        metadata={"booking_id": str(booking_id), "operation_id": str(operation_id) if operation_id else None},
    )
    await db.commit()
    if email:
        asyncio.create_task(asyncio.to_thread(send_booking_response_email, email, booking["title"], body.action, body.note))
    return _booking_row(row)


async def _transition_booking(booking_id: UUID, target: str, reason: str, request: Request, user: CurrentUser, db: AsyncSession):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "Provider team manager required")
    current = (await db.execute(text("""
        SELECT b.*, e.status AS event_status
        FROM organizer_booking_requests b JOIN events e ON e.id=b.event_id
        WHERE b.id=:id AND b.provider_tenant_id=:tid FOR UPDATE OF b, e
    """), {"id": str(booking_id), "tid": str(tenant_id)})).mappings().first()
    if not current:
        raise HTTPException(404, "Booking not found")
    allowed = {
        "in_progress": {"accepted", "reopened"},
        "cancelled": {"pending", "needs_information", "accepted", "reopened", "in_progress"},
        "reopened": {"cancelled"},
    }
    if current["status"] not in allowed.get(target, set()):
        raise HTTPException(409, f"Cannot move booking from {current['status']} to {target}")
    if target == "in_progress" and current["event_status"] != "published":
        raise HTTPException(409, "يجب نشر الحدث قبل بدء التشغيل")

    row = (await db.execute(text("""
        UPDATE organizer_booking_requests
        SET status=:target, status_reason=:reason, response_note=:reason,
            responded_by=:uid, responded_at=now(), updated_at=now()
        WHERE id=:id AND provider_tenant_id=:tid RETURNING *
    """), {"target": target, "reason": reason, "uid": str(user.id), "id": str(booking_id), "tid": str(tenant_id)})).mappings().first()
    if not row: raise HTTPException(404, "Booking not found")
    operation_status = {"in_progress": "in_progress", "cancelled": "cancelled", "reopened": "in_progress"}.get(target)
    if operation_status:
        await db.execute(text("""
            UPDATE event_operations SET status=:status, status_change_reason=:reason,
              last_modified_by=:uid, updated_at=now() WHERE booking_id=:booking_id
        """), {"status": operation_status, "reason": reason, "uid": str(user.id), "booking_id": str(booking_id)})
    event_status = {"in_progress": "active", "cancelled": "cancelled", "reopened": "published"}.get(target)
    if event_status:
        await db.execute(text("""
            UPDATE events SET status=CAST(:status AS event_status), updated_at=now()
            WHERE id=:event_id AND deleted_at IS NULL
        """), {"status": event_status, "event_id": str(current["event_id"])})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action=f"booking.{target}", resource_type="organizer_booking_request", resource_id=str(booking_id))
    await db.commit()
    return _booking_row(row)

@router.post("/{booking_id}/start")
async def start_booking(booking_id: UUID, body: BookingReason, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _transition_booking(booking_id, "in_progress", body.reason, request, user, db)

@router.post("/{booking_id}/cancel")
async def cancel_booking(booking_id: UUID, body: BookingReason, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _transition_booking(booking_id, "cancelled", body.reason, request, user, db)

@router.post("/{booking_id}/reopen")
async def reopen_booking(booking_id: UUID, body: BookingReason, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _transition_booking(booking_id, "reopened", body.reason, request, user, db)

@router.patch("/{booking_id}/schedule")
async def update_booking_schedule(booking_id: UUID, body: BookingScheduleUpdate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.ends_at <= body.starts_at: raise HTTPException(422, "End time must be after start time")
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    row = (await db.execute(text("""
        UPDATE organizer_booking_requests SET starts_at=:starts, ends_at=:ends, scheduled_starts_at=:starts, scheduled_ends_at=:ends,
          status_reason=:reason, responded_by=:uid, updated_at=now()
        WHERE id=:id AND provider_tenant_id=:tid AND status IN ('pending','needs_information','accepted','reopened') RETURNING *
    """), {"starts": body.starts_at, "ends": body.ends_at, "reason": body.reason, "uid": str(user.id), "id": str(booking_id), "tid": str(tenant_id)})).mappings().first()
    if not row: raise HTTPException(409, "Booking cannot be rescheduled in its current state")
    await db.execute(text("""
        UPDATE events SET start_date=:starts, end_date=:ends, updated_at=now()
        WHERE id=:event_id AND tenant_id=:requester AND deleted_at IS NULL
    """), {"starts": body.starts_at, "ends": body.ends_at,
            "event_id": str(row["event_id"]), "requester": str(row["requester_tenant_id"])})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="booking.schedule.update", resource_type="organizer_booking_request", resource_id=str(booking_id))
    await db.commit()
    return _booking_row(row)

@router.post("/{booking_id}/assign-manager")
async def assign_booking_manager(booking_id: UUID, body: BookingManagerAssign, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    result = await db.execute(text("""
      UPDATE event_operations o SET project_manager_id=:manager, last_modified_by=:actor, updated_at=now()
      WHERE o.booking_id=:bid AND o.provider_tenant_id=:tid AND EXISTS
       (SELECT 1 FROM memberships m WHERE m.tenant_id=:tid AND m.user_id=:manager AND m.status='active') RETURNING o.id
    """), {"manager": str(body.user_id), "actor": str(user.id), "bid": str(booking_id), "tid": str(tenant_id)})
    if not result.first(): raise HTTPException(409, "Manager must be an active member of this tenant")
    await db.execute(text("UPDATE event_operation_members SET role='lead' WHERE operation_id=(SELECT id FROM event_operations WHERE booking_id=:bid) AND role='manager'"), {"bid": str(booking_id)})
    await db.execute(text("INSERT INTO event_operation_members(operation_id,user_id,role) SELECT id,:manager,'manager' FROM event_operations WHERE booking_id=:bid ON CONFLICT(operation_id,user_id) DO UPDATE SET role='manager'"), {"bid": str(booking_id), "manager": str(body.user_id)})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="booking.manager.assign", resource_type="organizer_booking_request", resource_id=str(booking_id))
    await db.commit()
    return {"booking_id": str(booking_id), "manager_id": str(body.user_id)}

@router.post("/{booking_id}/complete")
async def complete_booking(booking_id: UUID, request: Request,
                           user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "هذه العملية متاحة لمدير فريق التنظيم فقط")
    updated = await db.execute(text("""
        UPDATE organizer_booking_requests
        SET status = 'completed', updated_at = now()
        WHERE id = :id AND provider_tenant_id = :tid AND status = 'in_progress'
        RETURNING *
    """), {"id": str(booking_id), "tid": str(tenant_id)})
    row = updated.mappings().first()
    if not row:
        raise HTTPException(409, "لا يمكن إكمال الحفل إلا بعد قبوله")
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="booking.request.completed",
                    resource_type="organizer_booking_request", resource_id=str(booking_id),
                    ip_address=get_client_ip(request))
    await db.execute(text("""
        UPDATE event_operations
        SET status = 'completed', progress = 100,
            status_change_reason = 'booking.completed',
            last_modified_by = :actor,
            updated_at = now()
        WHERE booking_id = :booking_id
    """), {"booking_id": str(booking_id), "actor": str(user.id)})
    await db.execute(text("""
        UPDATE events SET status='completed', updated_at=now()
        WHERE id=:event_id AND status='active' AND deleted_at IS NULL
    """), {"event_id": str(row["event_id"])})
    operation_row = await db.execute(text("SELECT id FROM event_operations WHERE booking_id=:booking_id"), {"booking_id": str(booking_id)})
    operation_id_for_notify = operation_row.scalar()
    if operation_id_for_notify:
        await notify_operation_members(
            db, operation_id_for_notify, exclude_user_id=user.id,
            notification_type="operation.completed", title="اكتملت العملية",
            message=f"اكتملت عملية «{row['title']}»", link="/teams?tab=events",
            metadata={"booking_id": str(booking_id), "operation_id": str(operation_id_for_notify)}
        )
    await db.execute(text("""
        INSERT INTO event_operation_activity(operation_id, actor_user_id, action, entity_type, entity_id)
        SELECT id, :actor, 'operation.completed', 'operation', id::text
        FROM event_operations WHERE booking_id = :booking_id
    """), {"booking_id": str(booking_id), "actor": str(user.id)})
    await notify_tenant_managers(
        db, row["requester_tenant_id"],
        notification_type="event.completed", title="اكتمل الحفل",
        message=f"اكتمل حفل {row['title']}", link="/teams",
        metadata={"booking_id": str(booking_id)},
    )
    await db.commit()
    return _booking_row(row)


@router.get("/groups")
async def list_groups(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    result = await db.execute(text("""
        SELECT g.*,
               (SELECT COUNT(*) FROM organizer_team_group_members gm WHERE gm.group_id = g.id) AS members_count,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'operation_id', assigned.operation_id::text,
                       'title', assigned.title,
                       'status', assigned.status,
                       'assigned_at', assigned.assigned_at::text
                   ) ORDER BY assigned.assigned_at DESC)
                   FROM (
                       SELECT o.id AS operation_id,
                              COALESCE(e.title, b.title, o.title, 'حفل بدون عنوان') AS title,
                              o.status,
                              MAX(assignment.created_at) AS assigned_at
                       FROM (
                           SELECT oga.operation_id, oga.group_id, oga.created_at
                           FROM event_operation_group_assignments oga
                           UNION ALL
                           SELECT o.id, legacy.group_id, legacy.created_at
                           FROM organizer_booking_group_assignments legacy
                           JOIN event_operations o ON o.booking_id = legacy.booking_id
                       ) assignment
                       JOIN event_operations o ON o.id = assignment.operation_id
                       LEFT JOIN events e ON e.id = o.event_id
                       LEFT JOIN organizer_booking_requests b ON b.id = o.booking_id
                       WHERE assignment.group_id = g.id
                       GROUP BY o.id, e.title, b.title, o.title, o.status
                   ) assigned
               ), '[]'::jsonb) AS assignments
        FROM organizer_team_groups g WHERE g.tenant_id = :tid ORDER BY g.name
    """), {"tid": str(tenant_id)})
    return [dict(row) for row in result.mappings().all()]


@router.post("/groups", status_code=201)
async def create_group(body: GroupCreate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "المجموعات متاحة لفرق التنظيم المعتمدة فقط")
    await acquire_plan_limit_lock(db, tenant_id, "operation_groups_max")
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
    groups = await db.execute(text("SELECT COUNT(*) FROM organizer_team_groups WHERE tenant_id=ANY(:tids)"), {"tids": [str(item) for item in scope_tenant_ids]})
    await enforce_static_limit(db, tenant_id, "operation_groups_max", groups.scalar() or 0, "مجموعات الفريق")
    try:
        result = await db.execute(text("""
            INSERT INTO organizer_team_groups (tenant_id, name, description, color, created_by)
            VALUES (:tid, :name, :description, :color, :uid) RETURNING *
        """), {"tid": str(tenant_id), "name": body.name.strip(), "description": body.description,
                "color": body.color, "uid": str(user.id)})
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "توجد مجموعة بهذا الاسم بالفعل")
    return dict(result.mappings().first())


@router.get("/groups/{group_id}/members")
async def list_group_members(group_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id)
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø§Øª Ù…ØªØ§Ø­Ø© Ù„ÙØ±Ù‚ Ø§Ù„ØªÙ†Ø¸ÙŠÙ… Ø§Ù„Ù…Ø¹ØªÙ…Ø¯Ø© ÙÙ‚Ø·")
    group = await db.execute(text("SELECT 1 FROM organizer_team_groups WHERE id = :gid AND tenant_id = :tid"),
                             {"gid": str(group_id), "tid": str(tenant_id)})
    if not group.first():
        raise HTTPException(404, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©")
    result = await db.execute(text("""
        SELECT gm.user_id::text, gm.created_at, p.full_name, p.avatar_url, p.phone,
               u.email, m.role AS tenant_role, m.status
        FROM organizer_team_group_members gm
        JOIN profiles p ON p.id = gm.user_id
        JOIN auth.users u ON u.id = gm.user_id
        JOIN memberships m ON m.user_id = gm.user_id
        WHERE gm.group_id = :gid AND m.tenant_id = :tid
        ORDER BY p.full_name NULLS LAST, u.email
    """), {"gid": str(group_id), "tid": str(tenant_id)})
    return [dict(row) for row in result.mappings().all()]


@router.patch("/groups/{group_id}")
async def update_group(group_id: UUID, body: GroupUpdate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    if not await _is_provider(db, tenant_id, user.id):
        raise HTTPException(403, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø§Øª Ù…ØªØ§Ø­Ø© Ù„ÙØ±Ù‚ Ø§Ù„ØªÙ†Ø¸ÙŠÙ… Ø§Ù„Ù…Ø¹ØªÙ…Ø¯Ø© ÙÙ‚Ø·")
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "Ù„Ø§ ØªÙˆØ¬Ø¯ ØªØºÙŠÙŠØ±Ø§Øª")
    if values.get("name"):
        values["name"] = values["name"].strip()
    params = {"gid": str(group_id), "tid": str(tenant_id), **values}
    sets = ", ".join(f"{key} = :{key}" for key in values)
    try:
        result = await db.execute(text(f"""
            UPDATE organizer_team_groups SET {sets}
            WHERE id = :gid AND tenant_id = :tid
            RETURNING *
        """), params)
        row = result.mappings().first()
        if not row:
            raise HTTPException(404, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©")
        await db.commit()
        return dict(row)
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(409, "ØªØ¹Ø°Ø± ØªØ­Ø¯ÙŠØ« Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø©ØŒ ØªØ­Ù‚Ù‚ Ù…Ù† Ø¹Ø¯Ù… ØªÙƒØ±Ø§Ø± Ø§Ù„Ø§Ø³Ù…")


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    result = await db.execute(text("""
        DELETE FROM organizer_team_groups
        WHERE id = :gid AND tenant_id = :tid
        RETURNING 1
    """), {"gid": str(group_id), "tid": str(tenant_id)})
    if not result.first():
        raise HTTPException(404, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©")
    await db.commit()


@router.post("/groups/{group_id}/members", status_code=204)
async def add_group_member(group_id: UUID, body: GroupMemberAdd, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    valid = await db.execute(text("""
        SELECT 1 FROM organizer_team_groups g JOIN memberships m ON m.tenant_id = g.tenant_id
        WHERE g.id = :gid AND g.tenant_id = :tid AND m.user_id = :uid AND m.status = 'active'
    """), {"gid": str(group_id), "tid": str(tenant_id), "uid": str(body.user_id)})
    if not valid.first():
        raise HTTPException(400, "العضو أو المجموعة غير صالحين")
    await db.execute(text("INSERT INTO organizer_team_group_members (group_id, user_id) VALUES (:gid, :uid) ON CONFLICT DO NOTHING"),
                     {"gid": str(group_id), "uid": str(body.user_id)})
    await db.commit()


@router.delete("/groups/{group_id}/members/{member_id}", status_code=204)
async def remove_group_member(group_id: UUID, member_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    group = await db.execute(text("SELECT 1 FROM organizer_team_groups WHERE id = :gid AND tenant_id = :tid"),
                             {"gid": str(group_id), "tid": str(tenant_id)})
    if not group.first():
        raise HTTPException(404, "Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø© ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯Ø©")
    result = await db.execute(text("""
        DELETE FROM organizer_team_group_members
        WHERE group_id = :gid AND user_id = :uid
        RETURNING 1
    """), {"gid": str(group_id), "uid": str(member_id)})
    if not result.first():
        raise HTTPException(404, "Ø§Ù„Ø¹Ø¶Ùˆ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯ ÙÙŠ Ø§Ù„Ù…Ø¬Ù…ÙˆØ¹Ø©")
    await db.commit()


@router.post("/groups/{group_id}/assign", status_code=204)
async def assign_group(group_id: UUID, body: GroupBookingAssign, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    valid = await db.execute(text("""
        SELECT 1 FROM organizer_team_groups g, organizer_booking_requests b
        WHERE g.id = :gid AND g.tenant_id = :tid
          AND b.id = :bid AND b.provider_tenant_id = :tid AND b.status = 'accepted'
    """), {"gid": str(group_id), "bid": str(body.booking_id), "tid": str(tenant_id)})
    if not valid.first():
        raise HTTPException(400, "لا يمكن إسناد المجموعة لهذا الحجز")
    await db.execute(text("""
        INSERT INTO organizer_booking_group_assignments (booking_id, group_id, assigned_by)
        VALUES (:bid, :gid, :uid) ON CONFLICT DO NOTHING
    """), {"bid": str(body.booking_id), "gid": str(group_id), "uid": str(user.id)})
    await db.execute(text("""
        INSERT INTO event_operation_group_assignments (operation_id, group_id, assigned_by)
        SELECT o.id, :gid, :uid FROM event_operations o WHERE o.booking_id = :bid
        ON CONFLICT DO NOTHING
    """), {"bid": str(body.booking_id), "gid": str(group_id), "uid": str(user.id)})
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id, user_id, role, group_id)
        SELECT o.id, gm.user_id, 'member', :gid
        FROM event_operations o
        JOIN organizer_team_group_members gm ON gm.group_id = :gid
        WHERE o.booking_id = :bid
        ON CONFLICT(operation_id, user_id) DO NOTHING
    """), {"bid": str(body.booking_id), "gid": str(group_id)})
    group_title = await db.execute(text("SELECT name FROM organizer_team_groups WHERE id = :gid"), {"gid": str(group_id)})
    group_name = group_title.scalar() or "مجموعة"
    member_rows = await db.execute(text("""
        SELECT DISTINCT gm.user_id, o.id AS operation_id
        FROM organizer_team_group_members gm
        JOIN event_operations o ON o.booking_id = :bid
        WHERE gm.group_id = :gid AND gm.user_id <> :uid
    """), {"bid": str(body.booking_id), "gid": str(group_id), "uid": str(user.id)})
    for mr in member_rows.mappings().all():
        await create_notification(
            db, tenant_id, "group.assigned", "تمت إضافتك إلى حفل",
            f"تمت إضافة مجموعتك «{group_name}» إلى حفل", user_id=mr["user_id"],
            link=f"/team-events/{mr['operation_id']}",
            metadata={"operation_id": str(mr["operation_id"]), "group_id": str(group_id)},
        )
    await db.commit()


@router.post("/groups/{group_id}/assign-operation", status_code=204)
async def assign_group_to_operation(
    group_id: UUID,
    body: GroupOperationAssign,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an operational group to any active operation owned by this team.

    This supports both accepted booking projects and events created directly in a
    linked institution workspace. Existing manual/member assignments are never
    overwritten; a manager must explicitly move a person between groups.
    """
    tenant_id = get_tenant_id_from_header(request)
    await _require_tenant_manager(db, tenant_id, user.id, "bookings.manage")
    operation = await db.execute(text("""
        SELECT o.id, COALESCE(e.title, b.title, o.title, 'حفل') AS title
        FROM event_operations o
        LEFT JOIN events e ON e.id = o.event_id
        LEFT JOIN organizer_booking_requests b ON b.id = o.booking_id
        WHERE o.id = :operation_id
          AND o.provider_tenant_id = :tid
          AND o.status NOT IN ('completed', 'closed', 'cancelled')
        LIMIT 1
    """), {"operation_id": str(body.operation_id), "tid": str(tenant_id)})
    operation_row = operation.mappings().first()
    if not operation_row:
        raise HTTPException(400, "لا يمكن إسناد المجموعة إلى هذا الحفل")

    group = await db.execute(text("""
        SELECT name FROM organizer_team_groups
        WHERE id = :group_id AND tenant_id = :tid
        LIMIT 1
    """), {"group_id": str(group_id), "tid": str(tenant_id)})
    group_name = group.scalar()
    if not group_name:
        raise HTTPException(404, "المجموعة غير موجودة")

    await db.execute(text("""
        INSERT INTO event_operation_group_assignments (operation_id, group_id, assigned_by)
        VALUES (:operation_id, :group_id, :actor_user_id)
        ON CONFLICT DO NOTHING
    """), {
        "operation_id": str(body.operation_id),
        "group_id": str(group_id),
        "actor_user_id": str(user.id),
    })
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id, user_id, role, group_id)
        SELECT :operation_id, gm.user_id, 'member', :group_id
        FROM organizer_team_group_members gm
        WHERE gm.group_id = :group_id
        ON CONFLICT(operation_id, user_id) DO NOTHING
    """), {"operation_id": str(body.operation_id), "group_id": str(group_id)})
    await db.execute(text("""
        INSERT INTO event_operation_activity
            (operation_id, actor_user_id, action, entity_type, entity_id, details)
        VALUES (
            :operation_id, :actor_user_id, 'group.assigned', 'group', :group_id,
            jsonb_build_object('group_name', :group_name)
        )
    """), {
        "operation_id": str(body.operation_id),
        "actor_user_id": str(user.id),
        "group_id": str(group_id),
        "group_name": group_name,
    })
    member_rows = await db.execute(text("""
        SELECT gm.user_id FROM organizer_team_group_members gm
        WHERE gm.group_id = :group_id AND gm.user_id <> :actor_user_id
    """), {"group_id": str(group_id), "actor_user_id": str(user.id)})
    for member in member_rows.mappings().all():
        await create_notification(
            db, tenant_id, "group.assigned", "تمت إضافتك إلى حفل",
            f"تم إسناد مجموعتك «{group_name}» إلى حفل «{operation_row['title']}»",
            user_id=member["user_id"], link=f"/team-events/{body.operation_id}",
            metadata={"operation_id": str(body.operation_id), "group_id": str(group_id)},
        )
    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="group.assign_operation", resource_type="event_operation",
        resource_id=str(body.operation_id),
        metadata={"group_id": str(group_id), "group_name": group_name},
    )
    await db.commit()
