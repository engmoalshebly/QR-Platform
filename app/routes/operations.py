import asyncio
import json
import io
import zipfile
import secrets
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db, get_supabase_admin
from app.services.notification_service import create_notification, notify_operation_members
from app.services.permission_service import require_permission, has_permission
from app.services.feature_service import require_storage_for_upload, record_non_asset_storage, enforce_static_limit, acquire_plan_limit_lock

router = APIRouter(prefix="/operations", tags=["Event operations"])

_OPERATION_TRANSITIONS = {
    "planning": {"ready", "cancelled"},
    "ready": {"in_progress", "planning", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": {"closed"},
    "closed": {"in_progress"},
    "cancelled": {"planning"},
}


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    assigned_to: Optional[UUID] = None
    due_at: Optional[datetime] = None
    start_at: Optional[datetime] = None
    parent_task_id: Optional[UUID] = None
    approval_required: bool = False

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.start_at and self.due_at and self.due_at <= self.start_at:
            raise ValueError("due_at must be later than start_at")
        return self


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    status: Optional[Literal["todo", "in_progress", "blocked", "done"]] = None
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = None
    assigned_to: Optional[UUID] = None
    due_at: Optional[datetime] = None
    start_at: Optional[datetime] = None
    parent_task_id: Optional[UUID] = None


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class MemberRoleUpdate(BaseModel):
    user_id: UUID
    role: Literal["manager", "lead", "member", "viewer"]
    group_id: Optional[UUID] = None

class OperationCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    deadline_at: Optional[datetime] = None

class OperationEdit(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    internal_notes: Optional[str] = Field(default=None, max_length=10000)
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = None
    deadline_at: Optional[datetime] = None

class OperationProgress(BaseModel):
    progress: int = Field(ge=0, le=100)

class OperationStatus(BaseModel):
    status: Literal["planning", "ready", "in_progress", "completed", "closed", "cancelled"]
    reason: Optional[str] = Field(default=None, max_length=2000)

class OperationEscalate(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


async def _access(db: AsyncSession, operation_id: UUID, tenant_id: UUID, user_id: UUID):
    await require_permission(db, tenant_id, user_id, "operations.view")
    result = await db.execute(text("""
        SELECT o.*, om.role AS operation_role
        FROM event_operations o
        JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.id = :id AND o.provider_tenant_id = :tid
    """), {"uid": str(user_id), "id": str(operation_id), "tid": str(tenant_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(403, "ليس لديك صلاحية للوصول إلى مشروع هذا الحفل")
    return row

async def _task_access(db: AsyncSession, operation_id: UUID, task_id: UUID, tenant_id: UUID, user_id: UUID):
    access = await _access(db, operation_id, tenant_id, user_id)
    result = await db.execute(text("SELECT * FROM event_operation_tasks WHERE id=:task AND operation_id=:oid"), {"task": str(task_id), "oid": str(operation_id)})
    task = result.mappings().first()
    if not task: raise HTTPException(404, "Task not found")
    return access, task


async def _activity(db: AsyncSession, operation_id: UUID | str, user_id: UUID, action: str,
                    entity_type: str, entity_id: Optional[str] = None, details: Optional[dict] = None):
    await db.execute(text("""
        INSERT INTO event_operation_activity
          (operation_id, actor_user_id, action, entity_type, entity_id, details)
        VALUES (:oid, :uid, :action, :entity_type, :entity_id, CAST(:details AS jsonb))
    """), {"oid": str(operation_id), "uid": str(user_id), "action": action,
           "entity_type": entity_type, "entity_id": entity_id, "details": json.dumps(details or {}, default=str)})


async def _recalculate_operation_progress(db: AsyncSession, operation_id: UUID | str) -> None:
    await db.execute(text("""
        UPDATE event_operations SET progress=(
          SELECT CASE WHEN COUNT(*)=0 THEN 0
                      ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE status='done') / COUNT(*))::int END
          FROM event_operation_tasks WHERE operation_id=:oid
        ), updated_at=now() WHERE id=:oid
    """), {"oid": str(operation_id)})

def _real_content_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"): return "application/pdf"
    if content.startswith(b"\xFF\xD8\xFF"): return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP": return "image/webp"
    if content.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" in names and "word/document.xml" in names:
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except zipfile.BadZipFile:
            return None
    return None


async def seed_tasks_from_template(db: AsyncSession, operation_id: UUID | str, event_type: Optional[str], actor_id: UUID) -> int:
    """Clone the matching per-type task template (or the default one) into the operation.

    Returns the number of tasks created. Best-effort: if the event_task_templates
    table is absent (older DB not yet on migration v25), returns 0 without raising —
    template seeding is an enhancement, not a blocker for accepting a booking.
    """
    event_type_key = (event_type or "").strip()
    table_check = await db.execute(text("SELECT to_regclass('public.event_task_templates')"))
    if not table_check.scalar():
        return 0
    rows = await db.execute(text("""
        SELECT title, description, priority, approval_required
        FROM event_task_templates
        WHERE is_active = TRUE
          AND (event_type_key = :et OR event_type_key = 'default')
        ORDER BY (event_type_key = 'default')::int, sort_order
    """), {"et": event_type_key or "default"})
    templates = rows.mappings().all()
    if not templates:
        return 0
    created = 0
    for t in templates:
        await db.execute(text("""
            INSERT INTO event_operation_tasks
              (operation_id, title, description, priority, approval_required, created_by)
            VALUES (:oid, :title, :description, :priority, :approval, :uid)
        """), {"oid": str(operation_id), "title": t["title"], "description": t["description"],
               "priority": t["priority"], "approval": t["approval_required"], "uid": str(actor_id)})
        created += 1
    if created:
        await _activity(db, operation_id, actor_id, "tasks.seeded", "operation", str(operation_id),
                        {"count": created, "event_type_key": event_type_key or "default"})
    return created


@router.get("")
async def list_operations(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.view")
    rows = await db.execute(text("""
        SELECT o.*,
               COALESCE(b.title, e.title, o.title) AS title,
               COALESCE(b.starts_at, e.start_date, o.deadline_at, o.created_at) AS starts_at,
               COALESCE(b.ends_at, e.end_date) AS ends_at,
               COALESCE(b.location, e.venue_name, e.venue_city) AS location,
               COALESCE((SELECT COUNT(*) FROM invitations i WHERE i.event_id = o.event_id), 0) AS guest_count,
               rt.name AS requester_name,
               (SELECT COUNT(*) FROM event_operation_tasks t WHERE t.operation_id=o.id) AS tasks_count,
               (SELECT COUNT(*) FROM event_operation_tasks t WHERE t.operation_id=o.id AND t.status='done') AS tasks_done
        FROM event_operations o
        JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid
        LEFT JOIN organizer_booking_requests b ON b.id=o.booking_id
        LEFT JOIN events e ON e.id=o.event_id
        JOIN tenants rt ON rt.id=o.requester_tenant_id
        WHERE o.provider_tenant_id=:tid
        ORDER BY COALESCE(b.starts_at, e.start_date, o.deadline_at, o.created_at)
    """), {"uid": str(user.id), "tid": str(tenant_id)})
    return [dict(row) for row in rows.mappings().all()]


@router.post("", status_code=201)
async def create_operation(body: OperationCreate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.edit")
    await acquire_plan_limit_lock(db, tenant_id, "operations_max")
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
    current = await db.execute(text("SELECT COUNT(*) FROM event_operations WHERE provider_tenant_id=ANY(:tids)"), {"tids": [str(item) for item in scope_tenant_ids]})
    await enforce_static_limit(db, tenant_id, "operations_max", current.scalar() or 0, "العمليات")
    result = await db.execute(text("""
      INSERT INTO event_operations(provider_tenant_id, requester_tenant_id, project_manager_id, title, description, priority, deadline_at)
      VALUES(:tid,:tid,:uid,:title,:description,:priority,:deadline) RETURNING *
    """), {"tid": str(tenant_id), "uid": str(user.id), "title": body.title.strip(), "description": body.description,
           "priority": body.priority, "deadline": body.deadline_at})
    row = result.mappings().first()
    await db.execute(text("INSERT INTO event_operation_members(operation_id,user_id,role) VALUES(:oid,:uid,'manager')"), {"oid": str(row["id"]), "uid": str(user.id)})
    await _activity(db, row["id"], user.id, "operation.created.manual", "operation", str(row["id"]), {"title": body.title})
    await db.commit()
    return dict(row)


@router.patch("/{operation_id}")
async def edit_operation(operation_id: UUID, body: OperationEdit, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.edit")
    await _access(db, operation_id, tenant_id, user.id)
    values = body.model_dump(exclude_unset=True)
    if not values: raise HTTPException(400, "No changes provided")
    sets = [f"{k}=:{k}" for k in values]
    values.update({"oid": str(operation_id), "uid": str(user.id)})
    row = (await db.execute(text(f"UPDATE event_operations SET {', '.join(sets)}, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), values)).mappings().first()
    await _activity(db, operation_id, user.id, "operation.updated", "operation", str(operation_id), body.model_dump(exclude_unset=True))
    await db.commit(); return dict(row)


@router.post("/{operation_id}/progress")
async def update_operation_progress(operation_id: UUID, body: OperationProgress, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.progress.update"); await _access(db, operation_id, tenant_id, user.id)
    row = (await db.execute(text("UPDATE event_operations SET progress=:progress, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), {"progress": body.progress, "uid": str(user.id), "oid": str(operation_id)})).mappings().first()
    await _activity(db, operation_id, user.id, "operation.progress.updated", "operation", str(operation_id), {"progress": body.progress}); await db.commit(); return dict(row)


@router.post("/{operation_id}/status")
async def change_operation_status(operation_id: UUID, body: OperationStatus, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.status.change"); access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager": raise HTTPException(403, "مدير الحفل فقط يمكنه تغيير حالة العملية")
    if body.status not in _OPERATION_TRANSITIONS.get(access["status"], set()):
        raise HTTPException(409, f"لا يمكن نقل العملية من {access['status']} إلى {body.status}")
    if body.status == "completed":
        incomplete = (await db.execute(text("SELECT COUNT(*) FROM event_operation_tasks WHERE operation_id=:oid AND status<>'done'"), {"oid": str(operation_id)})).scalar() or 0
        if incomplete: raise HTTPException(409, f"لا يمكن إكمال العملية قبل إنهاء {incomplete} مهمة")
    row = (await db.execute(text("UPDATE event_operations SET status=:status, status_change_reason=:reason, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), {"status": body.status, "reason": body.reason, "uid": str(user.id), "oid": str(operation_id)})).mappings().first()
    if row.get("event_id") and body.status in ("in_progress", "completed", "cancelled"):
        event_status = {"in_progress": "active", "completed": "completed", "cancelled": "cancelled"}[body.status]
        allowed_event = {"in_progress": "published", "completed": "active", "cancelled": None}[body.status]
        event_where = "status=:allowed" if allowed_event else "status IN ('draft','published','active')"
        await db.execute(text(f"UPDATE events SET status=CAST(:status AS event_status), updated_at=now() WHERE id=:eid AND {event_where}"),
                         {"status": event_status, "allowed": allowed_event, "eid": str(row["event_id"])})
        if row.get("booking_id"):
            await db.execute(text("UPDATE organizer_booking_requests SET status=:status, status_reason='operation.status_transition', updated_at=now() WHERE id=:bid"),
                             {"status": body.status, "bid": str(row["booking_id"])})
    await _activity(db, operation_id, user.id, "operation.status.changed", "operation", str(operation_id), {"status": body.status, "reason": body.reason}); await db.commit(); return dict(row)


@router.post("/{operation_id}/escalate")
async def escalate_operation(operation_id: UUID, body: OperationEscalate, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.escalate"); await _access(db, operation_id, tenant_id, user.id)
    row = (await db.execute(text("UPDATE event_operations SET escalated_at=now(), escalated_by=:uid, escalation_reason=:reason, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), {"uid": str(user.id), "reason": body.reason, "oid": str(operation_id)})).mappings().first()
    await _activity(db, operation_id, user.id, "operation.escalated", "operation", str(operation_id), {"reason": body.reason}); await db.commit(); return dict(row)


@router.post("/{operation_id}/close")
async def close_operation(operation_id: UUID, body: OperationStatus, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.close"); access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager" or access["status"] != "completed": raise HTTPException(409, "لا يمكن إغلاق العملية إلا بعد اكتمالها بواسطة المدير")
    row = (await db.execute(text("UPDATE event_operations SET status='closed', status_change_reason=:reason, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), {"reason": body.reason, "uid": str(user.id), "oid": str(operation_id)})).mappings().first()
    await _activity(db, operation_id, user.id, "operation.closed", "operation", str(operation_id), {"reason": body.reason}); await db.commit(); return dict(row)


@router.post("/{operation_id}/reopen")
async def reopen_operation(operation_id: UUID, body: OperationStatus, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.close"); access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager" or access["status"] not in ("closed", "cancelled"): raise HTTPException(409, "لا يمكن إعادة فتح العملية من حالتها الحالية")
    row = (await db.execute(text("UPDATE event_operations SET status='in_progress', status_change_reason=:reason, last_modified_by=:uid, updated_at=now() WHERE id=:oid RETURNING *"), {"reason": body.reason, "uid": str(user.id), "oid": str(operation_id)})).mappings().first()
    await _activity(db, operation_id, user.id, "operation.reopened", "operation", str(operation_id), {"reason": body.reason}); await db.commit(); return dict(row)


@router.get("/{operation_id}")
async def operation_detail(operation_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    access = await _access(db, operation_id, tenant_id, user.id)
    result = await db.execute(text("""
        SELECT o.*, COALESCE(b.title, e.title, o.title) AS title,
               COALESCE(b.event_type, e.event_type_id::text) AS event_type,
               COALESCE(b.starts_at, e.start_date, o.deadline_at, o.created_at) AS starts_at,
               COALESCE(b.ends_at, e.end_date) AS ends_at,
               COALESCE(b.location, e.venue_name, e.venue_city) AS location,
               COALESCE((SELECT COUNT(*) FROM invitations i WHERE i.event_id = o.event_id), 0) AS guest_count,
               b.services, b.notes, b.contact_name, b.contact_phone, b.contact_email,
               e.description AS event_description, e.venue_map_url, rt.name AS requester_name
        FROM event_operations o
        LEFT JOIN organizer_booking_requests b ON b.id=o.booking_id
        LEFT JOIN events e ON e.id=o.event_id
        JOIN tenants rt ON rt.id=o.requester_tenant_id
        WHERE o.id=:id
    """), {"id": str(operation_id)})
    data = dict(result.mappings().first())
    data["my_role"] = access["operation_role"]
    for key, sql in {
        "tasks": "SELECT t.*, p.full_name AS assignee_name FROM event_operation_tasks t LEFT JOIN profiles p ON p.id=t.assigned_to WHERE t.operation_id=:id ORDER BY t.created_at DESC",
        "members": "SELECT om.*, p.full_name, u.email FROM event_operation_members om JOIN profiles p ON p.id=om.user_id JOIN auth.users u ON u.id=om.user_id WHERE om.operation_id=:id ORDER BY om.role",
        "attachments": "SELECT * FROM event_operation_attachments WHERE operation_id=:id ORDER BY created_at DESC",
        "activity": "SELECT a.*, p.full_name AS actor_name FROM event_operation_activity a LEFT JOIN profiles p ON p.id=a.actor_user_id WHERE a.operation_id=:id ORDER BY a.created_at DESC LIMIT 100",
    }.items():
        rows = await db.execute(text(sql), {"id": str(operation_id)})
        data[key] = [dict(row) for row in rows.mappings().all()]

    # The operation summary is shared by operational members, but each detail
    # collection has its own capability. This prevents direct API calls from
    # bypassing a hidden tab.
    if not await has_permission(db, tenant_id, user.id, "operations.tasks.view"):
        data["tasks"] = []
    if not await has_permission(db, tenant_id, user.id, "operations.members"):
        data["members"] = []
    if await has_permission(db, tenant_id, user.id, "operations.attachments.view"):
        storage = get_supabase_admin().storage.from_("invitations")
        for item in data["attachments"]:
            signed = await asyncio.to_thread(storage.create_signed_url, item["object_path"], 300)
            item["download_url"] = signed.get("signedURL") or signed.get("signedUrl")
    else:
        data["attachments"] = []
    return data


@router.get("/{operation_id}/event-insights")
async def operation_event_insights(operation_id: UUID, request: Request,
                                   scope: Literal["overview", "guests", "gates", "live"] = "overview",
                                   user: CurrentUser = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    """Unified, read-only event intelligence for the team managing this operation.

    Lets the provider team see the event's guests, invitations, gates, and check-in
    stats WITHOUT owning the event — access is gated by operation membership. Returns
    aggregated counts + a recent-scans feed + a guest list preview + gate roster.
    """
    from app.services.permission_service import check_event_access
    tenant_id = get_tenant_id_from_header(request)
    access = await _access(db, operation_id, tenant_id, user.id)
    event_id = access.get("event_id")
    if not event_id:
        raise HTTPException(404, "لا يوجد حدث مرتبط بهذا المشروع")
    # Verify cooperative access to the underlying event. Each screen asks only
    # for the data it actually renders; this keeps a gates-only or live-only
    # role usable without silently exposing the guest list.
    required_permissions = {
        "overview": (),
        "guests": ("guests.view", "invitations.view"),
        "gates": ("gates.view",),
        "live": ("gates.view", "checkin.view"),
    }[scope]
    for permission in required_permissions:
        if not await check_event_access(db, event_id, tenant_id, user.id, permission):
            raise HTTPException(403, f"Missing event permission: {permission}")
    if not await check_event_access(db, event_id, tenant_id, user.id, "events.view"):
        raise HTTPException(403, "ليس لديك صلاحية للوصول إلى بيانات هذا الحفل")

    # ── Invitation + RSVP aggregates ──
    booking_summary = None
    if access.get("booking_id"):
        booking_summary = (await db.execute(text("""
            SELECT guest_count, title, contact_name, contact_phone, contact_email
            FROM organizer_booking_requests
            WHERE id = :bid
        """), {"bid": str(access["booking_id"])})).mappings().first()

    inv = (await db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'sent') AS sent,
               COUNT(*) FILTER (WHERE status = 'viewed') AS viewed,
               COUNT(*) FILTER (WHERE rsvp_status = 'accepted') AS confirmed,
               COUNT(*) FILTER (WHERE rsvp_status = 'declined') AS declined,
               COUNT(*) FILTER (WHERE rsvp_status = 'pending') AS rsvp_pending,
               COUNT(*) FILTER (WHERE checked_in_at IS NOT NULL) AS checked_in,
               COUNT(*) FILTER (WHERE ticket_class = 'vip') AS vip,
               COUNT(*) FILTER (WHERE ticket_class = 'normal') AS normal,
               COALESCE(SUM(checkin_count), 0) AS total_scans,
               COALESCE(SUM(CASE WHEN rsvp_status='accepted' THEN plus_one_count ELSE 0 END), 0) AS plus_ones_confirmed
        FROM invitations WHERE event_id = :eid
    """), {"eid": str(event_id)})).mappings().first()

    # ── Gate roster + per-gate check-in traffic ──
    gates = (await db.execute(text("""
        SELECT g.id, g.name_ar, g.name, g.is_active,
               (SELECT COUNT(*) FROM checkins c WHERE c.gate_id = g.id AND c.event_id = :eid AND c.result = 'success') AS scans
        FROM event_gates g WHERE g.event_id = :eid ORDER BY g.name_ar, g.name
    """), {"eid": str(event_id)})).mappings().all()

    # ── Recent scans feed ──
    recent_scans = (await db.execute(text("""
        SELECT c.id, c.result, c.scan_method, c.created_at,
               inv.guest_name, inv.guest_name_ar, inv.ticket_class,
               p.full_name AS scanner_name, g.name_ar AS gate_name
        FROM checkins c
        LEFT JOIN invitations inv ON inv.id = c.invitation_id
        LEFT JOIN profiles p ON p.id = c.scanned_by
        LEFT JOIN event_gates g ON g.id = c.gate_id
        WHERE c.event_id = :eid
        ORDER BY c.created_at DESC LIMIT 50
    """), {"eid": str(event_id)})).mappings().all()

    # ── Guest list preview (owner tenant's guests linked via invitations) ──
    guests = (await db.execute(text("""
        SELECT DISTINCT gu.id, inv.id AS invitation_id, gu.full_name, gu.full_name_ar, gu.phone, gu.email,
               inv.ticket_class, inv.rsvp_status, inv.checked_in_at
        FROM guests gu
        JOIN invitations inv ON inv.guest_id = gu.id
        WHERE inv.event_id = :eid
        ORDER BY inv.checked_in_at DESC NULLS LAST, gu.full_name LIMIT 200
    """), {"eid": str(event_id)})).mappings().all()

    # ── Scan leaderboard per staff (top performers by accepted scans) ──
    leaderboard = (await db.execute(text("""
        SELECT p.full_name AS scanner_name, COUNT(*) AS accepted_scans
        FROM checkins c
        JOIN profiles p ON p.id = c.scanned_by
        WHERE c.event_id = :eid AND c.result = 'success' AND c.scanned_by IS NOT NULL
        GROUP BY p.id, p.full_name ORDER BY accepted_scans DESC LIMIT 10
    """), {"eid": str(event_id)})).mappings().all()

    response = {
        "my_role": access["operation_role"],
        "event_id": str(event_id),
        "booking": dict(booking_summary or {}),
        "invitations": dict(inv or {}),
        "gates": [],
        "recent_scans": [],
        "guests": [],
        "scan_leaderboard": [],
    }
    if scope in ("overview", "gates", "live"):
        response["gates"] = [dict(g) for g in gates]
    if scope == "guests":
        response["guests"] = [dict(g) for g in guests]
    if scope == "live":
        response["recent_scans"] = [dict(s) for s in recent_scans]
        response["scan_leaderboard"] = [dict(l) for l in leaderboard]
    return response


@router.post("/{operation_id}/tasks", status_code=201)
async def create_task(operation_id: UUID, body: TaskCreate, request: Request,
                      user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.create")
    access = await _access(db, operation_id, tenant_id, user.id)
    await acquire_plan_limit_lock(db, tenant_id, "tasks_per_operation", str(operation_id))
    task_count = await db.execute(text("SELECT COUNT(*) FROM event_operation_tasks WHERE operation_id = :oid"), {"oid": str(operation_id)})
    await enforce_static_limit(db, tenant_id, "tasks_per_operation", task_count.scalar() or 0, "مهام العملية")
    if access["operation_role"] not in ("manager", "lead"):
        raise HTTPException(403, "إنشاء المهام متاح لمدير الحفل وقائد المجموعة")
    if access["operation_role"] == "lead" and not body.assigned_to:
        raise HTTPException(403, "Group leads must assign tasks within their group")
    if body.assigned_to:
        member = await db.execute(text("SELECT 1 FROM event_operation_members WHERE operation_id=:id AND user_id=:uid"),
                                  {"id": str(operation_id), "uid": str(body.assigned_to)})
        if not member.first(): raise HTTPException(400, "المستخدم ليس عضوًا في هذا الحفل")
    if access["operation_role"] == "lead" and body.assigned_to:
        same_group = await db.execute(text("""
            SELECT 1 FROM event_operation_members lead
            JOIN event_operation_members member
              ON member.operation_id = lead.operation_id
             AND member.group_id = lead.group_id
            WHERE lead.operation_id=:oid AND lead.user_id=:uid
              AND member.user_id=:assignee AND lead.group_id IS NOT NULL
        """), {"oid": str(operation_id), "uid": str(user.id), "assignee": str(body.assigned_to)})
        if not same_group.first():
            raise HTTPException(403, "Group leads may create tasks for their group only")
    if body.parent_task_id:
        parent = await db.execute(text("SELECT 1 FROM event_operation_tasks WHERE id=:pid AND operation_id=:oid"),
                                 {"pid": str(body.parent_task_id), "oid": str(operation_id)})
        if not parent.first(): raise HTTPException(400, "المهمة الأصل غير موجودة في هذا الحفل")
    result = await db.execute(text("""
        INSERT INTO event_operation_tasks(operation_id,title,description,priority,assigned_to,due_at,start_at,parent_task_id,approval_required,created_by)
        VALUES(:oid,:title,:description,:priority,:assigned,:due_at,:start_at,:parent,:approval,:uid) RETURNING *
    """), {"oid": str(operation_id), "title": body.title.strip(), "description": body.description,
           "priority": body.priority, "assigned": str(body.assigned_to) if body.assigned_to else None,
           "due_at": body.due_at, "start_at": body.start_at, "parent": str(body.parent_task_id) if body.parent_task_id else None,
           "approval": body.approval_required, "uid": str(user.id)})
    row = result.mappings().first()
    await _activity(db, operation_id, user.id, "task.created", "task", str(row["id"]),
                    {"title": body.title, "subtask": bool(body.parent_task_id)})
    if body.approval_required:
        await notify_operation_members(
            db, operation_id, exclude_user_id=user.id, only_role=("manager",),
            notification_type="task.approval.requested", title="مهمة تنتظر الاعتماد",
            message=f"المهمة «{body.title}» تحتاج اعتماد المدير",
            link=f"/team-events/{operation_id}?tab=tasks", metadata={"operation_id": str(operation_id), "task_id": str(row["id"])}
        )
    if body.assigned_to:
        await create_notification(
            db, tenant_id, "task.assigned", "مهمة جديدة مسندة إليك",
            f"تم إسناد مهمة «{body.title}» إليك", user_id=body.assigned_to,
            link=f"/team-events/{operation_id}?tab=tasks",
            metadata={"operation_id": str(operation_id), "task_id": str(row["id"])},
        )
    await _recalculate_operation_progress(db, operation_id)
    await db.commit()
    return dict(row)


@router.patch("/{operation_id}/tasks/{task_id}")
async def update_task(operation_id: UUID, task_id: UUID, body: TaskUpdate, request: Request,
                      user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    access = await _access(db, operation_id, tenant_id, user.id)
    task_result = await db.execute(text("SELECT * FROM event_operation_tasks WHERE id=:task AND operation_id=:oid"),
                                   {"task": str(task_id), "oid": str(operation_id)})
    task = task_result.mappings().first()
    if not task: raise HTTPException(404, "المهمة غير موجودة")
    if access["operation_role"] == "member" and str(task["assigned_to"]) != str(user.id):
        raise HTTPException(403, "يمكنك تحديث المهام المسندة إليك فقط")
    if access["operation_role"] == "manager":
        await require_permission(db, tenant_id, user.id, "operations.tasks.update_any")
    elif access["operation_role"] == "lead":
        await require_permission(db, tenant_id, user.id, "operations.tasks.update_any")
        if not task["assigned_to"]:
            raise HTTPException(403, "Group leads cannot manage unassigned tasks")
        same_group = await db.execute(text("""
            SELECT 1 FROM event_operation_members a JOIN event_operation_members b
              ON b.operation_id=a.operation_id AND b.group_id=a.group_id
            WHERE a.operation_id=:oid AND a.user_id=:uid AND b.user_id=:assignee
              AND a.group_id IS NOT NULL
        """), {"oid": str(operation_id), "uid": str(user.id), "assignee": str(task["assigned_to"])})
        if not same_group.first(): raise HTTPException(403, "Lead can manage tasks in their group only")
    elif str(task["assigned_to"]) == str(user.id):
        await require_permission(db, tenant_id, user.id, "operations.tasks.update_own")
    else:
        raise HTTPException(403, "You may update assigned tasks only")
    allowed = {"status"} if access["operation_role"] in ("member", "viewer") else {"title","description","status","priority","assigned_to","due_at","start_at","parent_task_id"}
    values = body.model_dump(exclude_unset=True)
    values = {k: v for k, v in values.items() if k in allowed}
    if not values: raise HTTPException(400, "لا توجد تغييرات مسموحة")
    effective_start = values.get("start_at", task.get("start_at"))
    effective_due = values.get("due_at", task.get("due_at"))
    if effective_start and effective_due and effective_due <= effective_start:
        raise HTTPException(422, "يجب أن يكون موعد استحقاق المهمة بعد وقت بدايتها")
    if access["operation_role"] == "lead" and values.get("assigned_to"):
        same_group = await db.execute(text("""
            SELECT 1 FROM event_operation_members a JOIN event_operation_members b
              ON b.operation_id=a.operation_id AND b.group_id=a.group_id
            WHERE a.operation_id=:oid AND a.user_id=:uid AND b.user_id=:assignee
              AND a.group_id IS NOT NULL
        """), {"oid": str(operation_id), "uid": str(user.id), "assignee": str(values["assigned_to"])})
        if not same_group.first():
            raise HTTPException(403, "Group leads may not assign tasks outside their group")
    if access["operation_role"] == "member" and values.get("status") == "done" and task.get("approval_required") and not task.get("approved_by"):
        raise HTTPException(403, "هذه المهمة تتطلب اعتماد مدير الحفل قبل إكمالها")
    sets, params = [], {"task": str(task_id), "oid": str(operation_id)}
    for key, value in values.items():
        sets.append(f"{key}=:{key}")
        params[key] = str(value) if isinstance(value, UUID) else value
    sets += ["completed_at=CASE WHEN :new_status='done' THEN COALESCE(completed_at, now()) ELSE NULL END", "updated_at=now()"]
    params["new_status"] = values.get("status", task["status"])
    result = await db.execute(text(f"UPDATE event_operation_tasks SET {', '.join(sets)} WHERE id=:task AND operation_id=:oid RETURNING *"), params)
    row = result.mappings().first()
    await _activity(db, operation_id, user.id, "task.updated", "task", str(task_id), values)
    new_assignee = values.get("assigned_to")
    if new_assignee and str(new_assignee) != str(user.id) and str(new_assignee) != str(task["assigned_to"]):
        await create_notification(
            db, tenant_id, "task.assigned", "مهمة جديدة مسندة إليك",
            f"تم إسناد مهمة «{task['title']}» إليك", user_id=new_assignee,
            link=f"/team-events/{operation_id}?tab=tasks",
            metadata={"operation_id": str(operation_id), "task_id": str(task_id)},
        )
    if values.get("status") == "done":
        await notify_operation_members(
            db, operation_id, exclude_user_id=user.id, only_role=("manager", "lead"),
            notification_type="task.completed", title="اكتملت مهمة",
            message=f"أُكملت مهمة «{task['title']}»", link=f"/team-events/{operation_id}?tab=tasks",
            metadata={"operation_id": str(operation_id), "task_id": str(task_id)},
        )
    await _recalculate_operation_progress(db, operation_id)
    await db.commit()
    return dict(row)


@router.delete("/{operation_id}/tasks/{task_id}", status_code=204)
async def delete_task(operation_id: UUID, task_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.delete")
    access, task = await _task_access(db, operation_id, task_id, tenant_id, user.id)
    if access["operation_role"] not in ("manager", "lead"):
        raise HTTPException(403, "Only manager or lead can delete tasks")
    if task["status"] == "done":
        await require_permission(db, tenant_id, user.id, "operations.tasks.delete_completed")
    await db.execute(text("DELETE FROM event_operation_tasks WHERE id=:task AND operation_id=:oid"), {"task": str(task_id), "oid": str(operation_id)})
    await _activity(db, operation_id, user.id, "task.deleted", "task", str(task_id), {"status": task["status"]})
    await _recalculate_operation_progress(db, operation_id)
    await db.commit()

@router.post("/{operation_id}/members", status_code=204)
async def set_member(operation_id: UUID, body: MemberRoleUpdate, request: Request,
                     user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.members")
    access = await _access(db, operation_id, tenant_id, user.id)
    existing = await db.execute(text("SELECT role FROM event_operation_members WHERE operation_id=:oid AND user_id=:uid"), {"oid": str(operation_id), "uid": str(body.user_id)})
    existing_role = existing.scalar()
    if not existing_role:
        await acquire_plan_limit_lock(db, tenant_id, "operation_members_max", str(operation_id))
        member_count = await db.execute(text("SELECT COUNT(*) FROM event_operation_members WHERE operation_id=:oid"), {"oid": str(operation_id)})
        await enforce_static_limit(db, tenant_id, "operation_members_max", member_count.scalar() or 0, "أعضاء العملية")
    if access["operation_role"] != "manager": raise HTTPException(403, "إدارة الأعضاء متاحة لمدير الحفل فقط")
    if existing_role == "manager" and body.role != "manager":
        raise HTTPException(409, "Assign a replacement manager before changing the current manager role")
    valid = await db.execute(text("SELECT 1 FROM memberships WHERE tenant_id=:tid AND user_id=:uid AND status='active'"),
                             {"tid": str(tenant_id), "uid": str(body.user_id)})
    if not valid.first(): raise HTTPException(400, "المستخدم ليس عضوًا نشطًا في فريق التنظيم")
    if body.group_id:
        group = await db.execute(text("SELECT 1 FROM organizer_team_groups WHERE id=:gid AND tenant_id=:tid"), {"gid": str(body.group_id), "tid": str(tenant_id)})
        if not group.first(): raise HTTPException(400, "Group does not belong to this tenant")
    await db.execute(text("""
        INSERT INTO event_operation_members(operation_id,user_id,role,group_id) VALUES(:oid,:uid,:role,:gid)
        ON CONFLICT(operation_id,user_id) DO UPDATE SET role=excluded.role, group_id=excluded.group_id
    """), {"oid": str(operation_id), "uid": str(body.user_id), "role": body.role, "gid": str(body.group_id) if body.group_id else None})
    await _activity(db, operation_id, user.id, "member.role.changed", "member", str(body.user_id), {"role": body.role})
    if str(body.user_id) != str(user.id):
        role_label = {"manager": "مدير حفل", "lead": "قائد مجموعة", "member": "عضو فريق"}.get(body.role, body.role)
        await create_notification(
            db, tenant_id, "member.assigned", "تمت إضافتك إلى حفل",
            f"تمت إضافتك كـ{role_label} في مشروع الحفل", user_id=body.user_id,
            link=f"/team-events/{operation_id}",
            metadata={"operation_id": str(operation_id), "role": body.role},
        )
    await db.commit()


@router.delete("/{operation_id}/members/{member_id}", status_code=204)
async def remove_member(operation_id: UUID, member_id: UUID, request: Request,
                        user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.members")
    access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager":
        raise HTTPException(403, "إزالة الأعضاء متاحة لمدير الحفل فقط")
    if str(member_id) == str(access["project_manager_id"]):
        raise HTTPException(400, "لا يمكن إزالة مدير المشروع الأساسي")
    result = await db.execute(text("""
        DELETE FROM event_operation_members
        WHERE operation_id = :oid AND user_id = :uid
        RETURNING role
    """), {"oid": str(operation_id), "uid": str(member_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "العضو غير موجود في فريق الحفل")
    await _activity(db, operation_id, user.id, "member.removed", "member", str(member_id), {"role": row["role"]})
    await create_notification(db, tenant_id, "member.removed", "تمت إزالتك من العملية",
                              "تمت إزالتك من فريق العملية التشغيلية", user_id=member_id,
                              link=f"/team-events/{operation_id}", metadata={"operation_id": str(operation_id)})
    await db.commit()


@router.get("/{operation_id}/workload")
async def operation_workload(operation_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.view")
    await _access(db, operation_id, tenant_id, user.id)
    rows = await db.execute(text("""
      SELECT om.user_id, om.role, om.group_id, p.full_name,
        COUNT(t.id) FILTER (WHERE t.status <> 'done') AS open_tasks,
        COUNT(t.id) FILTER (WHERE t.status='done') AS completed_tasks,
        COUNT(t.id) AS total_tasks
      FROM event_operation_members om JOIN profiles p ON p.id=om.user_id
      LEFT JOIN event_operation_tasks t ON t.operation_id=om.operation_id AND t.assigned_to=om.user_id
      WHERE om.operation_id=:oid GROUP BY om.user_id,om.role,om.group_id,p.full_name ORDER BY open_tasks DESC
    """), {"oid": str(operation_id)})
    return [dict(row) for row in rows.mappings().all()]

@router.patch("/{operation_id}/members/{member_id}/group")
async def move_member_group(operation_id: UUID, member_id: UUID, group_id: Optional[UUID] = None, request: Request = None, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.members")
    access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager": raise HTTPException(403, "Only the operation manager can move members")
    if group_id:
        valid = await db.execute(text("SELECT 1 FROM organizer_team_groups WHERE id=:gid AND tenant_id=:tid"), {"gid": str(group_id), "tid": str(tenant_id)})
        if not valid.first(): raise HTTPException(400, "Group does not belong to this tenant")
    row = (await db.execute(text("UPDATE event_operation_members SET group_id=:gid WHERE operation_id=:oid AND user_id=:uid RETURNING *"), {"gid": str(group_id) if group_id else None, "oid": str(operation_id), "uid": str(member_id)})).mappings().first()
    if not row: raise HTTPException(404, "Member not found")
    await _activity(db, operation_id, user.id, "member.group.moved", "member", str(member_id), {"group_id": str(group_id) if group_id else None})
    await db.commit(); return dict(row)

@router.post("/{operation_id}/attachments", status_code=201)
async def upload_attachment(operation_id: UUID, request: Request, task_id: Optional[UUID] = None,
                            file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.attachments.upload")
    await _access(db, operation_id, tenant_id, user.id)
    await acquire_plan_limit_lock(db, tenant_id, "attachments_per_operation", str(operation_id))
    attachment_count = await db.execute(text("SELECT COUNT(*) FROM event_operation_attachments WHERE operation_id=:oid"), {"oid": str(operation_id)})
    await enforce_static_limit(db, tenant_id, "attachments_per_operation", attachment_count.scalar() or 0, "مرفقات العملية")
    if task_id:
        task = await db.execute(text("SELECT 1 FROM event_operation_tasks WHERE id=:task AND operation_id=:oid"), {"task": str(task_id), "oid": str(operation_id)})
        if not task.first(): raise HTTPException(404, "Task does not belong to this operation")
    content = await file.read()
    await require_storage_for_upload(db, tenant_id, len(content))
    if not content or len(content) > 15 * 1024 * 1024: raise HTTPException(413, "حجم الملف غير صالح أو يتجاوز 15 ميجابايت")
    allowed = {"application/pdf","image/jpeg","image/png","image/webp","application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if file.content_type not in allowed: raise HTTPException(400, "نوع الملف غير مدعوم")
    detected = _real_content_type(content)
    if file.content_type not in allowed or detected != file.content_type:
        raise HTTPException(400, "File content does not match its declared type")
    suffix = Path(file.filename or "file").suffix.lower()
    path = f"operations/{operation_id}/{secrets.token_hex(16)}{suffix}"
    storage = get_supabase_admin().storage.from_("invitations")
    await asyncio.to_thread(storage.upload, path, content, {"content-type": file.content_type, "upsert": "false"})
    result = await db.execute(text("""
        INSERT INTO event_operation_attachments(operation_id,task_id,file_name,object_path,content_type,size_bytes,uploaded_by)
        VALUES(:oid,:task,:name,:path,:type,:size,:uid) RETURNING *
    """), {"oid": str(operation_id), "task": str(task_id) if task_id else None, "name": file.filename or "file",
           "path": path, "type": file.content_type, "size": len(content), "uid": str(user.id)})
    row = result.mappings().first()
    await record_non_asset_storage(db, tenant_id, len(content))
    await _activity(db, operation_id, user.id, "attachment.uploaded", "attachment", str(row["id"]), {"name": row["file_name"]})
    await notify_operation_members(
        db, operation_id, exclude_user_id=user.id, notification_type="attachment.uploaded",
        title="تم رفع ملف جديد", message=f"تم رفع الملف «{row['file_name']}» إلى العملية",
        link=f"/team-events/{operation_id}?tab=files", metadata={"operation_id": str(operation_id), "attachment_id": str(row["id"])}
    )
    await db.commit()
    return dict(row)


@router.get("/{operation_id}/attachments/{attachment_id}")
async def get_attachment(operation_id: UUID, attachment_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.attachments.view")
    await _access(db, operation_id, tenant_id, user.id)
    row = (await db.execute(text("SELECT * FROM event_operation_attachments WHERE id=:aid AND operation_id=:oid"), {"aid": str(attachment_id), "oid": str(operation_id)})).mappings().first()
    if not row: raise HTTPException(404, "Attachment not found")
    return dict(row)

@router.post("/{operation_id}/attachments/{attachment_id}/download")
async def download_attachment(operation_id: UUID, attachment_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.attachments.download")
    await _access(db, operation_id, tenant_id, user.id)
    row = (await db.execute(text("SELECT * FROM event_operation_attachments WHERE id=:aid AND operation_id=:oid"), {"aid": str(attachment_id), "oid": str(operation_id)})).mappings().first()
    if not row: raise HTTPException(404, "Attachment not found")
    signed = await asyncio.to_thread(get_supabase_admin().storage.from_("invitations").create_signed_url, row["object_path"], 300)
    await db.execute(text("INSERT INTO event_operation_attachment_downloads(attachment_id,operation_id,user_id) VALUES(:aid,:oid,:uid)"), {"aid": str(attachment_id), "oid": str(operation_id), "uid": str(user.id)})
    await _activity(db, operation_id, user.id, "attachment.downloaded", "attachment", str(attachment_id))
    await db.commit()
    return {"download_url": signed.get("signedURL") or signed.get("signedUrl"), "expires_in": 300}

@router.delete("/{operation_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(operation_id: UUID, attachment_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request); await require_permission(db, tenant_id, user.id, "operations.attachments.delete")
    access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] not in ("manager", "lead"): raise HTTPException(403, "Only manager or lead can delete attachments")
    row = (await db.execute(text("DELETE FROM event_operation_attachments WHERE id=:aid AND operation_id=:oid RETURNING *"), {"aid": str(attachment_id), "oid": str(operation_id)})).mappings().first()
    if not row: raise HTTPException(404, "Attachment not found")
    await asyncio.to_thread(get_supabase_admin().storage.from_("invitations").remove, [row["object_path"]])
    await _activity(db, operation_id, user.id, "attachment.deleted", "attachment", str(attachment_id), {"path": row["object_path"]})
    await db.commit()

@router.post("/{operation_id}/tasks/{task_id}/approve")
async def approve_task(operation_id: UUID, task_id: UUID, request: Request,
                       user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.approve")
    access = await _access(db, operation_id, tenant_id, user.id)
    if access["operation_role"] != "manager":
        raise HTTPException(403, "اعتماد المهام متاح لمدير الحفل فقط")
    task_result = await db.execute(text("""
        SELECT * FROM event_operation_tasks WHERE id=:task AND operation_id=:oid
    """), {"task": str(task_id), "oid": str(operation_id)})
    task = task_result.mappings().first()
    if not task:
        raise HTTPException(404, "المهمة غير موجودة")
    if not task.get("approval_required"):
        raise HTTPException(400, "هذه المهمة لا تتطلب اعتمادًا")
    if task.get("approved_by"):
        raise HTTPException(409, "تم اعتماد هذه المهمة مسبقًا")
    result = await db.execute(text("""
        UPDATE event_operation_tasks
        SET approved_by = :uid, approved_at = now(), updated_at = now()
        WHERE id = :task RETURNING *
    """), {"uid": str(user.id), "task": str(task_id)})
    row = result.mappings().first()
    await _activity(db, operation_id, user.id, "task.approved", "task", str(task_id), {"title": task["title"]})
    if task.get("assigned_to") and str(task["assigned_to"]) != str(user.id):
        await create_notification(
            db, tenant_id, "task.approved", "تم اعتماد مهمتك",
            f"اعتمد مدير الحفل مهمة «{task['title']}»", user_id=task["assigned_to"],
            link=f"/team-events/{operation_id}?tab=tasks",
            metadata={"operation_id": str(operation_id), "task_id": str(task_id)},
        )
    await db.commit()
    return dict(row)


@router.get("/{operation_id}/tasks/{task_id}/comments")
async def list_task_comments(operation_id: UUID, task_id: UUID, request: Request,
                             user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.view")
    await _task_access(db, operation_id, task_id, tenant_id, user.id)
    rows = await db.execute(text("""
        SELECT c.*, p.full_name AS author_name
        FROM event_operation_task_comments c
        JOIN profiles p ON p.id = c.author_id
        WHERE c.task_id = :task
        ORDER BY c.created_at ASC
    """), {"task": str(task_id)})
    return [dict(row) for row in rows.mappings().all()]


@router.post("/{operation_id}/tasks/{task_id}/comments", status_code=201)
async def create_task_comment(operation_id: UUID, task_id: UUID, body: TaskCommentCreate, request: Request,
                              user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.comment")
    access = await _access(db, operation_id, tenant_id, user.id)
    task_result = await db.execute(text("SELECT 1 FROM event_operation_tasks WHERE id=:task AND operation_id=:oid"),
                                   {"task": str(task_id), "oid": str(operation_id)})
    if not task_result.first():
        raise HTTPException(404, "المهمة غير موجودة")
    result = await db.execute(text("""
        INSERT INTO event_operation_task_comments(task_id, author_id, body)
        VALUES (:task, :uid, :body) RETURNING *
    """), {"task": str(task_id), "uid": str(user.id), "body": body.body.strip()})
    row = result.mappings().first()
    await _activity(db, operation_id, user.id, "task.commented", "task", str(task_id), {"comment_id": str(row["id"])})
    await notify_operation_members(
        db, operation_id, exclude_user_id=user.id,
        notification_type="task.commented", title="تعليق جديد على مهمة",
        message="تمت إضافة تعليق جديد على مهمة في مشروع الحفل",
        link=f"/team-events/{operation_id}?tab=tasks",
        metadata={"operation_id": str(operation_id), "task_id": str(task_id)},
    )
    _ = access
    await db.commit()
    return dict(row)


@router.delete("/{operation_id}/tasks/{task_id}/comments/{comment_id}", status_code=204)
async def delete_task_comment(operation_id: UUID, task_id: UUID, comment_id: UUID, request: Request,
                              user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "operations.tasks.comment")
    access, _task = await _task_access(db, operation_id, task_id, tenant_id, user.id)
    result = await db.execute(text("""
        DELETE FROM event_operation_task_comments
        WHERE id = :cid AND task_id = :task
          AND (author_id = :uid OR :is_manager)
        RETURNING 1
    """), {"cid": str(comment_id), "task": str(task_id), "uid": str(user.id),
           "is_manager": access["operation_role"] == "manager"})
    if not result.first():
        raise HTTPException(403, "لا يمكنك حذف هذا التعليق")
    await db.commit()
