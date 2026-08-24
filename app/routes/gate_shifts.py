"""Management API for operational gate shifts and scanner assignments."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.audit_service import extract_audit_context, log_audit
from app.services.gate_shift_service import get_shift_with_provider_access
from app.services.permission_service import (
    has_permission,
    require_any_permission,
    require_permission,
    require_provider_event_access,
)


router = APIRouter(prefix="/gate-shifts", tags=["Gate shifts"])


class GateShiftCreate(BaseModel):
    event_id: UUID
    gate_id: UUID
    operation_id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(default="Asia/Riyadh", min_length=2, max_length=64)
    supervisor_user_id: UUID


class GateShiftUpdate(BaseModel):
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    timezone: Optional[str] = Field(default=None, min_length=2, max_length=64)
    supervisor_user_id: Optional[UUID] = None
    status: Optional[Literal["scheduled", "active", "completed", "cancelled"]] = None
    cancellation_reason: Optional[str] = Field(default=None, max_length=1000)


class GateShiftMemberAssign(BaseModel):
    user_id: UUID
    role: Literal["scanner", "supervisor"] = "scanner"
    conflict_override_reason: Optional[str] = Field(default=None, min_length=3, max_length=1000)


class GateShiftGroupAssign(BaseModel):
    group_id: UUID
    role: Literal["scanner", "supervisor"] = "scanner"
    conflict_override_reason: Optional[str] = Field(default=None, min_length=3, max_length=1000)


def _integrity_detail(error: IntegrityError) -> str:
    message = str(getattr(error, "orig", error))
    if "overlapping gate shift" in message or "Member already has an overlapping" in message:
        return "يوجد تعارض مع وردية أخرى للعضو. أضف سبب تجاوز موثق إذا وافق المدير."
    if "must be assigned to the event operation" in message:
        return "لا يمكن إسناد عضو غير مكلّف بعملية هذا الحفل."
    if "must exist, belong to the shift event" in message:
        return "البوابة غير نشطة أو لا تنتمي إلى الحفل المحدد."
    return "تعذر حفظ الوردية بسبب تعارض في بيانات التشغيل."


async def _manager_shift(db: AsyncSession, shift_id: UUID, tenant_id: UUID, user_id: UUID):
    await require_permission(db, tenant_id, user_id, "gate_shifts.manage")
    row = await get_shift_with_provider_access(db, shift_id=shift_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="الوردية غير موجودة")
    await require_provider_event_access(db, row["event_id"], tenant_id, user_id, "gate_shifts.manage")
    return row


async def _write_operation_activity(
    db: AsyncSession,
    operation_id: UUID | str,
    user_id: UUID,
    action: str,
    entity_id: UUID | str,
    details: dict,
) -> None:
    await db.execute(
        text("""
            INSERT INTO event_operation_activity
              (operation_id, actor_user_id, action, entity_type, entity_id, details)
            VALUES (:operation_id, :user_id, :action, 'gate_shift', :entity_id,
                    CAST(:details AS jsonb))
        """),
        {
            "operation_id": str(operation_id), "user_id": str(user_id),
            "action": action, "entity_id": str(entity_id),
            "details": json.dumps(details, default=str),
        },
    )


async def _require_assignable_field_role(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    role: str,
) -> None:
    """Do not schedule a person whose workspace role cannot perform the job."""
    if not await has_permission(db, tenant_id, user_id, "checkin.scan"):
        raise HTTPException(422, "لا يمكن إسناد عضو لا يملك صلاحية مسح الحضور")
    if role == "supervisor" and not await has_permission(db, tenant_id, user_id, "checkin.supervise"):
        raise HTTPException(422, "لا يمكن إسناد مشرف لا يملك صلاحية الإشراف على البوابة")


@router.get("")
async def list_gate_shifts(
    event_id: UUID,
    request: Request,
    gate_id: Optional[UUID] = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_provider_event_access(db, event_id, tenant_id, user.id, "gate_shifts.view")
    query = """
        SELECT s.*, g.name AS gate_name, g.name_ar AS gate_name_ar,
               p.full_name AS supervisor_name,
               COUNT(sm.user_id) FILTER (WHERE sm.is_active) AS assigned_members,
               COUNT(sm.user_id) FILTER (WHERE sm.is_active AND sm.role = 'scanner') AS scanners,
               COUNT(sm.user_id) FILTER (WHERE sm.is_active AND sm.role = 'supervisor') AS supervisors
        FROM event_gate_shifts s
        JOIN event_gates g ON g.id = s.gate_id
        JOIN event_operations o ON o.id = s.operation_id
        JOIN profiles p ON p.id = s.supervisor_user_id
        LEFT JOIN event_gate_shift_members sm ON sm.shift_id = s.id
        WHERE s.event_id = :event_id AND o.provider_tenant_id = :tenant_id
    """
    params = {"event_id": str(event_id), "tenant_id": str(tenant_id)}
    if gate_id:
        query += " AND s.gate_id = :gate_id"
        params["gate_id"] = str(gate_id)
    query += " GROUP BY s.id, g.id, p.id ORDER BY s.starts_at, g.name"
    rows = await db.execute(text(query), params)
    return [dict(row) for row in rows.mappings().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_gate_shift(
    body: GateShiftCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
        raise HTTPException(422, "يجب إرسال وقت الوردية مع منطقة زمنية")
    if body.ends_at <= body.starts_at:
        raise HTTPException(422, "يجب أن يكون وقت نهاية الوردية بعد وقت بدايتها")
    tenant_id = get_tenant_id_from_header(request)
    await require_provider_event_access(db, body.event_id, tenant_id, user.id, "gate_shifts.manage")
    operation = await db.execute(
        text("""
        SELECT id, project_manager_id FROM event_operations
            WHERE id = :operation_id AND event_id = :event_id
              AND provider_tenant_id = :tenant_id
              AND status NOT IN ('completed', 'closed', 'cancelled')
        """),
        {"operation_id": str(body.operation_id), "event_id": str(body.event_id), "tenant_id": str(tenant_id)},
    )
    operation_row = operation.mappings().first()
    if not operation_row:
        raise HTTPException(422, "العملية لا تنتمي إلى الحفل أو فريق التشغيل الحالي")
    # A project manager is allowed to supervise their operation by design,
    # even when their tenant-role permissions have been customised narrowly.
    if body.supervisor_user_id != operation_row["project_manager_id"]:
        await _require_assignable_field_role(
            db, tenant_id=tenant_id, user_id=body.supervisor_user_id, role="supervisor",
        )
    try:
        result = await db.execute(
            text("""
                INSERT INTO event_gate_shifts
                  (event_id, gate_id, operation_id, starts_at, ends_at, timezone,
                   supervisor_user_id, created_by)
                VALUES
                  (:event_id, :gate_id, :operation_id, :starts_at, :ends_at, :timezone,
                   :supervisor_user_id, :created_by)
                RETURNING *
            """),
            {
                "event_id": str(body.event_id), "gate_id": str(body.gate_id),
                "operation_id": str(body.operation_id), "starts_at": body.starts_at,
                "ends_at": body.ends_at, "timezone": body.timezone,
                "supervisor_user_id": str(body.supervisor_user_id), "created_by": str(user.id),
            },
        )
        row = result.mappings().first()
        # The named supervisor is an actual shift participant, not merely a
        # display field.  This also gives them a controlled device session if
        # they need to take over a scanner.
        await db.execute(text("""
            INSERT INTO event_gate_shift_members
              (shift_id, user_id, role, assignment_source, assigned_by)
            VALUES (:shift_id, :user_id, 'supervisor', 'direct', :assigned_by)
            ON CONFLICT (shift_id, user_id) DO UPDATE
            SET role = 'supervisor', is_active = TRUE, assigned_by = EXCLUDED.assigned_by,
                assignment_source = 'direct', source_group_id = NULL
        """), {"shift_id": str(row["id"]), "user_id": str(body.supervisor_user_id), "assigned_by": str(user.id)})
        await _write_operation_activity(db, body.operation_id, user.id, "gate_shift.created", row["id"], {
            "gate_id": str(body.gate_id), "starts_at": body.starts_at.isoformat(), "ends_at": body.ends_at.isoformat(),
            "supervisor_user_id": str(body.supervisor_user_id),
        })
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.created",
                        resource_type="event_gate_shift", resource_id=str(row["id"]),
                        metadata={"event_id": str(body.event_id), "gate_id": str(body.gate_id)},
                        **extract_audit_context(request))
        await db.commit()
        return dict(row)
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, _integrity_detail(error)) from error


@router.get("/{shift_id}")
async def get_gate_shift(
    shift_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    row = await get_shift_with_provider_access(db, shift_id=shift_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(404, "الوردية غير موجودة")
    await require_provider_event_access(db, row["event_id"], tenant_id, user.id, "gate_shifts.view")
    members = await db.execute(text("""
        SELECT sm.user_id, sm.role, sm.assignment_source, sm.source_group_id,
               sm.conflict_override_reason, sm.is_active, sm.assigned_at,
               p.full_name, p.avatar_url
        FROM event_gate_shift_members sm
        JOIN profiles p ON p.id = sm.user_id
        WHERE sm.shift_id = :shift_id
        ORDER BY sm.is_active DESC, sm.role DESC, p.full_name
    """), {"shift_id": str(shift_id)})
    groups = await db.execute(text("""
        SELECT ga.group_id, ga.role, ga.snapshot_at, g.name, g.color,
               COUNT(gsm.user_id) AS snapshotted_members
        FROM event_gate_shift_group_assignments ga
        JOIN organizer_team_groups g ON g.id = ga.group_id
        LEFT JOIN event_gate_shift_group_snapshot_members gsm
          ON gsm.shift_id = ga.shift_id AND gsm.group_id = ga.group_id
        WHERE ga.shift_id = :shift_id
        GROUP BY ga.shift_id, ga.group_id, ga.role, ga.snapshot_at, g.id
        ORDER BY g.name
    """), {"shift_id": str(shift_id)})
    return {"shift": dict(row), "members": [dict(r) for r in members.mappings().all()],
            "groups": [dict(r) for r in groups.mappings().all()]}


@router.patch("/{shift_id}")
async def update_gate_shift(
    shift_id: UUID,
    body: GateShiftUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    current = await _manager_shift(db, shift_id, tenant_id, user.id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return dict(current)
    starts_at = changes.get("starts_at", current["starts_at"])
    ends_at = changes.get("ends_at", current["ends_at"])
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise HTTPException(422, "يجب إرسال وقت الوردية مع منطقة زمنية")
    if ends_at <= starts_at:
        raise HTTPException(422, "يجب أن يكون وقت نهاية الوردية بعد وقت بدايتها")
    target_status = changes.get("status", current["status"])
    if "supervisor_user_id" in changes and changes["supervisor_user_id"] != current["project_manager_id"]:
        await _require_assignable_field_role(
            db,
            tenant_id=tenant_id,
            user_id=changes["supervisor_user_id"],
            role="supervisor",
        )
    allowed_transitions = {
        "scheduled": {"scheduled", "active", "cancelled"},
        "active": {"active", "completed", "cancelled"},
        "completed": {"completed"},
        "cancelled": {"cancelled"},
    }
    if target_status not in allowed_transitions[current["status"]]:
        raise HTTPException(409, "انتقال حالة الوردية غير مسموح")
    if target_status == "active" and not (starts_at <= datetime.now(starts_at.tzinfo) < ends_at):
        raise HTTPException(409, "لا يمكن تفعيل الوردية خارج نافذتها الزمنية")
    if target_status == "cancelled" and not (changes.get("cancellation_reason") or current["cancellation_reason"]):
        raise HTTPException(422, "سبب إلغاء الوردية مطلوب")
    try:
        result = await db.execute(text("""
            UPDATE event_gate_shifts
            SET starts_at = :starts_at, ends_at = :ends_at,
                timezone = :timezone, supervisor_user_id = :supervisor_user_id,
                status = :status, cancellation_reason = :cancellation_reason,
                activated_at = CASE WHEN :status = 'active' AND activated_at IS NULL THEN now() ELSE activated_at END,
                closed_at = CASE WHEN :status IN ('completed', 'cancelled') THEN now() ELSE closed_at END
            WHERE id = :shift_id
            RETURNING *
        """), {
            "shift_id": str(shift_id), "starts_at": starts_at, "ends_at": ends_at,
            "timezone": changes.get("timezone", current["timezone"]),
            "supervisor_user_id": str(changes.get("supervisor_user_id", current["supervisor_user_id"])),
            "status": target_status,
            "cancellation_reason": changes.get("cancellation_reason", current["cancellation_reason"]),
        })
        row = result.mappings().first()
        if "supervisor_user_id" in changes:
            await db.execute(text("""
                INSERT INTO event_gate_shift_members
                  (shift_id, user_id, role, assignment_source, assigned_by)
                VALUES (:shift_id, :user_id, 'supervisor', 'direct', :assigned_by)
                ON CONFLICT (shift_id, user_id) DO UPDATE
                SET role = 'supervisor', is_active = TRUE, assigned_by = EXCLUDED.assigned_by,
                    assignment_source = 'direct', source_group_id = NULL
            """), {"shift_id": str(shift_id), "user_id": str(changes["supervisor_user_id"]), "assigned_by": str(user.id)})
        if target_status in ("completed", "cancelled"):
            await db.execute(text("""
                UPDATE event_gate_device_sessions
                SET status = 'closed', closed_at = now(), closure_reason = :reason
                WHERE shift_id = :shift_id AND status = 'active'
            """), {"shift_id": str(shift_id), "reason": "shift_" + target_status})
        await _write_operation_activity(db, current["operation_id"], user.id, "gate_shift.updated", shift_id, changes)
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.updated",
                        resource_type="event_gate_shift", resource_id=str(shift_id), metadata=changes,
                        **extract_audit_context(request))
        await db.commit()
        return dict(row)
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, _integrity_detail(error)) from error


@router.post("/{shift_id}/members", status_code=status.HTTP_201_CREATED)
async def assign_shift_member(
    shift_id: UUID,
    body: GateShiftMemberAssign,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    shift = await _manager_shift(db, shift_id, tenant_id, user.id)
    await _require_assignable_field_role(
        db, tenant_id=tenant_id, user_id=body.user_id, role=body.role,
    )
    try:
        result = await db.execute(text("""
            INSERT INTO event_gate_shift_members
              (shift_id, user_id, role, assignment_source, assigned_by, conflict_override_reason)
            VALUES (:shift_id, :user_id, :role, 'direct', :assigned_by, :override_reason)
            ON CONFLICT (shift_id, user_id) DO UPDATE
            SET role = EXCLUDED.role, is_active = TRUE,
                conflict_override_reason = EXCLUDED.conflict_override_reason,
                assigned_by = EXCLUDED.assigned_by,
                assignment_source = 'direct', source_group_id = NULL
            RETURNING *
        """), {
            "shift_id": str(shift_id), "user_id": str(body.user_id), "role": body.role,
            "assigned_by": str(user.id), "override_reason": body.conflict_override_reason,
        })
        row = result.mappings().first()
        await _write_operation_activity(db, shift["operation_id"], user.id, "gate_shift.member_assigned", shift_id,
                                        {"user_id": str(body.user_id), "role": body.role,
                                         "source": "direct", "override": bool(body.conflict_override_reason)})
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.member_assigned",
                        resource_type="event_gate_shift", resource_id=str(shift_id),
                        metadata={"user_id": str(body.user_id), "role": body.role},
                        **extract_audit_context(request))
        await db.commit()
        return dict(row)
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, _integrity_detail(error)) from error


@router.post("/{shift_id}/groups", status_code=status.HTTP_201_CREATED)
async def assign_shift_group(
    shift_id: UUID,
    body: GateShiftGroupAssign,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snapshot a current operational group into a shift.

    The current group is first attached to the event operation; its current
    members then become immutable shift assignments.  Later group edits do not
    alter this shift.
    """
    tenant_id = get_tenant_id_from_header(request)
    shift = await _manager_shift(db, shift_id, tenant_id, user.id)
    group = await db.execute(text("""
        SELECT id, name FROM organizer_team_groups
        WHERE id = :group_id AND tenant_id = :tenant_id
    """), {"group_id": str(body.group_id), "tenant_id": str(tenant_id)})
    group_row = group.mappings().first()
    if not group_row:
        raise HTTPException(404, "المجموعة التشغيلية غير موجودة ضمن فريقك")
    already_assigned = await db.execute(text("""
        SELECT 1 FROM event_gate_shift_group_assignments
        WHERE shift_id = :shift_id AND group_id = :group_id
    """), {"shift_id": str(shift_id), "group_id": str(body.group_id)})
    if already_assigned.first():
        raise HTTPException(409, "تم أخذ لقطة لهذه المجموعة في الوردية بالفعل؛ أنشئ إسناداً مباشراً لأي استثناء")
    group_members = await db.execute(text("""
        SELECT gm.user_id
        FROM organizer_team_group_members gm
        JOIN memberships m ON m.user_id = gm.user_id
        WHERE gm.group_id = :group_id AND m.tenant_id = :tenant_id AND m.status = 'active'
        ORDER BY gm.user_id
    """), {"group_id": str(body.group_id), "tenant_id": str(tenant_id)})
    member_ids = [row[0] for row in group_members.fetchall()]
    if not member_ids:
        raise HTTPException(422, "لا يمكن إسناد مجموعة بلا أعضاء نشطين")
    for member_id in member_ids:
        await _require_assignable_field_role(
            db, tenant_id=tenant_id, user_id=member_id, role=body.role,
        )
    conflicts = await db.execute(text("""
        SELECT p.full_name
        FROM event_gate_shift_members sm
        JOIN organizer_team_group_members gm
          ON gm.user_id = sm.user_id AND gm.group_id = :group_id
        JOIN profiles p ON p.id = sm.user_id
        WHERE sm.shift_id = :shift_id AND sm.is_active AND sm.role <> :role
        ORDER BY p.full_name
    """), {"shift_id": str(shift_id), "group_id": str(body.group_id), "role": body.role})
    conflicting_names = [row[0] for row in conflicts.fetchall()]
    if conflicting_names:
        raise HTTPException(
            409,
            "يوجد تعارض في دور أعضاء المجموعة داخل الوردية: " + "، ".join(conflicting_names[:3]),
        )
    try:
        await db.execute(text("""
            INSERT INTO event_operation_group_assignments (operation_id, group_id, assigned_by)
            VALUES (:operation_id, :group_id, :assigned_by)
            ON CONFLICT DO NOTHING
        """), {"operation_id": str(shift["operation_id"]), "group_id": str(body.group_id), "assigned_by": str(user.id)})
        # Joining the group to the operation is explicit and auditable.  This
        # makes group-based gate access satisfy the same operation-membership
        # rule as a direct assignment.
        await db.execute(text("""
            INSERT INTO event_operation_members(operation_id, user_id, role, group_id)
            SELECT :operation_id, gm.user_id, 'member', :group_id
            FROM organizer_team_group_members gm
            JOIN memberships m ON m.user_id = gm.user_id
            WHERE gm.group_id = :group_id AND m.tenant_id = :tenant_id AND m.status = 'active'
            ON CONFLICT(operation_id, user_id) DO NOTHING
        """), {"operation_id": str(shift["operation_id"]), "group_id": str(body.group_id), "tenant_id": str(tenant_id)})
        group_assignment = await db.execute(text("""
            INSERT INTO event_gate_shift_group_assignments (shift_id, group_id, role, assigned_by)
            VALUES (:shift_id, :group_id, :role, :assigned_by)
            RETURNING snapshot_at
        """), {"shift_id": str(shift_id), "group_id": str(body.group_id), "role": body.role, "assigned_by": str(user.id)})
        snapshot_at = group_assignment.scalar()
        await db.execute(text("""
            INSERT INTO event_gate_shift_group_snapshot_members(shift_id, group_id, user_id, role)
            SELECT :shift_id, :group_id, gm.user_id, :role
            FROM organizer_team_group_members gm
            JOIN memberships m ON m.user_id = gm.user_id
            WHERE gm.group_id = :group_id AND m.tenant_id = :tenant_id AND m.status = 'active'
            ON CONFLICT (shift_id, group_id, user_id) DO NOTHING
        """), {
            "shift_id": str(shift_id), "group_id": str(body.group_id), "role": body.role,
            "tenant_id": str(tenant_id),
        })
        result = await db.execute(text("""
            INSERT INTO event_gate_shift_members
              (shift_id, user_id, role, assignment_source, source_group_id, assigned_by, conflict_override_reason)
            SELECT :shift_id, gm.user_id, :role, 'group_snapshot', :group_id, :assigned_by, :override_reason
            FROM organizer_team_group_members gm
            JOIN memberships m ON m.user_id = gm.user_id
            WHERE gm.group_id = :group_id AND m.tenant_id = :tenant_id AND m.status = 'active'
            ON CONFLICT (shift_id, user_id) DO NOTHING
            RETURNING user_id
        """), {
            "shift_id": str(shift_id), "group_id": str(body.group_id), "role": body.role,
            "assigned_by": str(user.id), "override_reason": body.conflict_override_reason,
            "tenant_id": str(tenant_id),
        })
        assigned = [str(row[0]) for row in result.fetchall()]
        await _write_operation_activity(db, shift["operation_id"], user.id, "gate_shift.group_snapshotted", shift_id,
                                        {"group_id": str(body.group_id), "group_name": group_row["name"],
                                         "role": body.role, "member_count": len(assigned),
                                         "override": bool(body.conflict_override_reason)})
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.group_snapshotted",
                        resource_type="event_gate_shift", resource_id=str(shift_id),
                        metadata={"group_id": str(body.group_id), "member_count": len(assigned),
                                  "snapshot_at": snapshot_at.isoformat() if snapshot_at else None},
                        **extract_audit_context(request))
        await db.commit()
        return {"shift_id": shift_id, "group_id": body.group_id, "snapshot_at": snapshot_at,
                "assigned_member_ids": assigned}
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, _integrity_detail(error)) from error


@router.delete("/{shift_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_shift_member(
    shift_id: UUID,
    member_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    shift = await _manager_shift(db, shift_id, tenant_id, user.id)
    removed = await db.execute(text("""
        UPDATE event_gate_shift_members SET is_active = FALSE
        WHERE shift_id = :shift_id AND user_id = :member_id AND is_active = TRUE
        RETURNING user_id
    """), {"shift_id": str(shift_id), "member_id": str(member_id)})
    if not removed.first():
        raise HTTPException(404, "العضو غير مكلّف بهذه الوردية")
    await db.execute(text("""
        UPDATE event_gate_device_sessions
        SET status = 'revoked', revoked_at = now(), revoked_by = :actor, closure_reason = 'shift_assignment_removed'
        WHERE shift_id = :shift_id AND user_id = :member_id AND status = 'active'
    """), {"shift_id": str(shift_id), "member_id": str(member_id), "actor": str(user.id)})
    await _write_operation_activity(db, shift["operation_id"], user.id, "gate_shift.member_removed", shift_id,
                                    {"user_id": str(member_id)})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.member_removed",
                    resource_type="event_gate_shift", resource_id=str(shift_id), metadata={"user_id": str(member_id)},
                    **extract_audit_context(request))
    await db.commit()


async def _supervisor_or_manager(db: AsyncSession, shift, tenant_id: UUID, user_id: UUID) -> None:
    if await _is_shift_supervisor(db, shift["id"], user_id):
        await require_permission(db, tenant_id, user_id, "checkin.supervise")
        return
    await _manager_shift(db, shift["id"], tenant_id, user_id)


async def _is_shift_supervisor(db: AsyncSession, shift_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(text("""
        SELECT 1 FROM event_gate_shifts s
        LEFT JOIN event_gate_shift_members sm
          ON sm.shift_id = s.id AND sm.user_id = :user_id AND sm.is_active AND sm.role = 'supervisor'
        WHERE s.id = :shift_id AND (s.supervisor_user_id = :user_id OR sm.user_id IS NOT NULL)
    """), {"shift_id": str(shift_id), "user_id": str(user_id)})
    return result.first() is not None


@router.get("/{shift_id}/device-sessions")
async def list_device_sessions(
    shift_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    shift = await get_shift_with_provider_access(db, shift_id=shift_id, tenant_id=tenant_id)
    if not shift:
        raise HTTPException(404, "الوردية غير موجودة")
    await _supervisor_or_manager(db, shift, tenant_id, user.id)
    result = await db.execute(text("""
        SELECT id, user_id, device_id, device_name, platform, app_version, status,
               started_at, last_seen_at, closed_at, revoked_at, closure_reason
        FROM event_gate_device_sessions
        WHERE shift_id = :shift_id
        ORDER BY status = 'active' DESC, last_seen_at DESC
    """), {"shift_id": str(shift_id)})
    return [dict(row) for row in result.mappings().all()]


@router.post("/{shift_id}/device-sessions/{session_id}/revoke")
async def revoke_device_session(
    shift_id: UUID,
    session_id: UUID,
    request: Request,
    reason: str = "supervisor_revoked",
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    shift = await get_shift_with_provider_access(db, shift_id=shift_id, tenant_id=tenant_id)
    if not shift:
        raise HTTPException(404, "الوردية غير موجودة")
    await _supervisor_or_manager(db, shift, tenant_id, user.id)
    result = await db.execute(text("""
        UPDATE event_gate_device_sessions
        SET status = 'revoked', revoked_at = now(), revoked_by = :actor, closure_reason = :reason
        WHERE id = :session_id AND shift_id = :shift_id AND status = 'active'
        RETURNING id, user_id
    """), {"session_id": str(session_id), "shift_id": str(shift_id), "actor": str(user.id), "reason": reason[:1000]})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "جلسة الجهاز غير نشطة أو لا تنتمي إلى الوردية")
    await _write_operation_activity(db, shift["operation_id"], user.id, "gate_shift.device_revoked", shift_id,
                                    {"device_session_id": str(session_id), "user_id": str(row["user_id"]), "reason": reason})
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="gate_shift.device_revoked",
                    resource_type="event_gate_device_session", resource_id=str(session_id),
                    metadata={"shift_id": str(shift_id), "reason": reason}, **extract_audit_context(request))
    await db.commit()
    return {"id": str(session_id), "status": "revoked"}
