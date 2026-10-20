"""Events API: CRUD + publish + stats + gates."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query, UploadFile, File
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.models.event import (
    EventCreate, EventRead, EventUpdate, EventStats,
    EventCategoryRead, EventCategoryCreate,
    EventTypeRead, EventTypeCreate,
    EventGateRead, EventGateCreate, EventAssetRead, EventAssetCreate,
    EventStatusTransitionRequest,
)
from app.models.team import EventAssignCreate, EventTeamAssignmentRead
from app.services.permission_service import (
    require_permission, has_permission,
    require_event_access, require_provider_event_access,
    get_event_owner_tenant, get_provider_event_ids,
)
from app.services.team_service import get_user_team_ids
from app.services.limit_errors import plan_limit_exceeded
from app.services.audit_service import log_audit
from app.security import get_client_ip

router = APIRouter(prefix="/events", tags=["Events"])

_EVENT_TRANSITIONS = {
    "draft": {"published", "cancelled"},
    "published": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


async def _validate_gate_assignments(
    db: AsyncSession, provider_tenant_id: UUID, body: EventGateCreate,
) -> None:
    if body.team_id:
        team = await db.execute(
            text("SELECT 1 FROM teams WHERE id=:id AND tenant_id=:tid AND is_active=true"),
            {"id": str(body.team_id), "tid": str(provider_tenant_id)},
        )
        if not team.first():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الفريق المحدد لا يتبع جهة التشغيل")
    if body.assigned_users:
        users = await db.execute(
            text("""
                SELECT user_id FROM memberships
                WHERE tenant_id=:tid AND status='active' AND user_id=ANY(:uids)
            """),
            {"tid": str(provider_tenant_id), "uids": [str(item) for item in body.assigned_users]},
        )
        found = {str(row[0]) for row in users.fetchall()}
        missing = [str(item) for item in body.assigned_users if str(item) not in found]
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "كل مستخدمي البوابة يجب أن يكونوا أعضاء نشطين في جهة التشغيل")


async def _event_readiness_issues(db: AsyncSession, event_id: UUID, tenant_id: UUID) -> list[str]:
    row = (await db.execute(text("""
        SELECT title, start_date, end_date, timezone, venue_name, venue_address,
               capacity, vip_capacity, normal_capacity
        FROM events WHERE id=:id AND tenant_id=:tid AND deleted_at IS NULL
    """), {"id": str(event_id), "tid": str(tenant_id)})).mappings().first()
    if not row:
        raise HTTPException(404, "الحدث غير موجود")
    issues: list[str] = []
    if not row["title"]: issues.append("عنوان الحدث مطلوب")
    if not row["end_date"]: issues.append("وقت نهاية الحدث مطلوب قبل النشر")
    if not row["venue_name"] and not row["venue_address"]: issues.append("موقع الحدث مطلوب قبل النشر")
    return issues


async def _validate_event_references(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    category_id: Optional[UUID],
    event_type_id: Optional[UUID],
    team_id: Optional[UUID],
) -> None:
    """Ensure referenced event setup records are active and belong to this tenant."""
    if category_id is not None:
        category_result = await db.execute(
            text("""
                SELECT id FROM event_categories
                WHERE id = :id AND is_active = true
                  AND (tenant_id IS NULL OR tenant_id = :tenant_id OR is_system = true)
            """),
            {"id": str(category_id), "tenant_id": str(tenant_id)},
        )
        if not category_result.first():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "تصنيف الحدث غير متاح لهذه المؤسسة")

    if event_type_id is not None:
        type_result = await db.execute(
            text("""
                SELECT et.category_id
                FROM event_types et
                JOIN event_categories ec ON ec.id = et.category_id
                WHERE et.id = :id
                  AND et.is_active = true
                  AND ec.is_active = true
                  AND (et.tenant_id IS NULL OR et.tenant_id = :tenant_id OR et.is_system = true)
                  AND (ec.tenant_id IS NULL OR ec.tenant_id = :tenant_id OR ec.is_system = true)
            """),
            {"id": str(event_type_id), "tenant_id": str(tenant_id)},
        )
        event_type = type_result.mappings().first()
        if not event_type:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نوع الحدث غير متاح لهذه المؤسسة")
        if category_id is not None and str(event_type["category_id"]) != str(category_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نوع الحدث لا يتبع التصنيف المحدد")

    if team_id is not None:
        team_result = await db.execute(
            text("""
                SELECT id FROM teams
                WHERE id = :id AND tenant_id = :tenant_id AND is_active = true
            """),
            {"id": str(team_id), "tenant_id": str(tenant_id)},
        )
        if not team_result.first():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الفريق المحدد غير متاح لهذه المؤسسة")


def _validate_event_schedule_and_capacity(
    *,
    start_date,
    end_date,
    capacity: Optional[int],
    vip_capacity: Optional[int],
    normal_capacity: Optional[int],
    vip_quota: int,
    normal_quota: int,
) -> None:
    """Apply cross-field rules also when an event is patched incrementally."""
    if end_date is not None and end_date <= start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "يجب أن يكون وقت نهاية الحدث بعد وقت بدايته")

    class_capacity = sum(value for value in (vip_capacity, normal_capacity) if value is not None)
    if capacity is not None and class_capacity > capacity:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "سعات الفئات لا يمكن أن تتجاوز السعة الإجمالية")
    if vip_capacity is not None and vip_quota > 0 and vip_quota > vip_capacity:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "حصة VIP لا يمكن أن تتجاوز سعة VIP")
    if normal_capacity is not None and normal_quota > 0 and normal_quota > normal_capacity:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الحصة العادية لا يمكن أن تتجاوز السعة العادية")

# ══════════════════════════════════════════════
# EVENT CATEGORIES
# ══════════════════════════════════════════════

@router.get("/categories", response_model=list[EventCategoryRead])
async def list_categories(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all event categories (system + tenant-specific)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.view")
    result = await db.execute(
        text("""
            SELECT id, tenant_id, name, name_ar, icon, color, sort_order, is_system, created_at
            FROM event_categories
            WHERE is_active = true
              AND (tenant_id IS NULL OR tenant_id = :tenant_id OR is_system = true)
            ORDER BY sort_order, name
        """),
        {"tenant_id": str(tenant_id)},
    )
    return [EventCategoryRead(**dict(r)) for r in result.mappings().all()]


@router.post("/categories", response_model=EventCategoryRead, status_code=201)
async def create_category(
    body: EventCategoryCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.create")

    result = await db.execute(
        text("""
            INSERT INTO event_categories (tenant_id, name, name_ar, icon, color)
            VALUES (:tid, :name, :name_ar, :icon, :color)
            RETURNING id, tenant_id, name, name_ar, icon, color, sort_order, is_system, created_at
        """),
        {"tid": str(tenant_id), "name": body.name, "name_ar": body.name_ar, "icon": body.icon, "color": body.color},
    )
    row = result.mappings().first()
    await db.commit()
    return EventCategoryRead(**dict(row))


# ══════════════════════════════════════════════
# EVENT TYPES
# ══════════════════════════════════════════════

@router.get("/types", response_model=list[EventTypeRead])
async def list_types(
    request: Request,
    category_id: Optional[UUID] = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List event types, optionally filtered by category."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.view")
    query = """
        SELECT et.id, et.category_id, et.tenant_id, et.name, et.name_ar, et.description, et.is_system, et.created_at
        FROM event_types et
        JOIN event_categories ec ON ec.id = et.category_id
        WHERE et.is_active = true
          AND ec.is_active = true
          AND (et.tenant_id IS NULL OR et.tenant_id = :tenant_id OR et.is_system = true)
          AND (ec.tenant_id IS NULL OR ec.tenant_id = :tenant_id OR ec.is_system = true)
    """
    params = {"tenant_id": str(tenant_id)}
    if category_id:
        query += " AND category_id = :cid"
        params["cid"] = str(category_id)
    query += " ORDER BY name"

    result = await db.execute(text(query), params)
    return [EventTypeRead(**dict(r)) for r in result.mappings().all()]


@router.post("/types", response_model=EventTypeRead, status_code=201)
async def create_event_type(
    body: EventTypeCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a tenant-scoped type under an available event category."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.create")
    await _validate_event_references(
        db,
        tenant_id,
        category_id=body.category_id,
        event_type_id=None,
        team_id=None,
    )
    result = await db.execute(
        text("""
            INSERT INTO event_types (category_id, tenant_id, name, name_ar, description)
            VALUES (:category_id, :tenant_id, :name, :name_ar, :description)
            RETURNING id, category_id, tenant_id, name, name_ar, description, is_system, created_at
        """),
        {
            "category_id": str(body.category_id),
            "tenant_id": str(tenant_id),
            "name": body.name,
            "name_ar": body.name_ar,
            "description": body.description,
        },
    )
    row = result.mappings().first()
    await db.commit()
    return EventTypeRead(**dict(row))


# ══════════════════════════════════════════════
# EVENTS CRUD
# ══════════════════════════════════════════════

@router.post("", response_model=EventRead, status_code=201)
async def create_event(
    body: EventCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.create")
    await _validate_event_references(
        db,
        tenant_id,
        category_id=body.category_id,
        event_type_id=body.event_type_id,
        team_id=body.team_id,
    )

    # ── Plan limit: events_per_month ──
    from app.services.feature_service import enforce_monthly_limit, get_plan_limit
    await enforce_monthly_limit(db, tenant_id, "events_per_month", "الأحداث الشهرية")

    # ── Plan limit: vip_quota + normal_quota ──
    inv_limit = await get_plan_limit(db, tenant_id, "invitations_per_month")
    total_requested_quota = (body.vip_quota or 0) + (body.normal_quota or 0)
    if inv_limit != -1 and total_requested_quota > inv_limit:
        raise plan_limit_exceeded(
            "invitations_per_month", 0, inv_limit, total_requested_quota,
            message=f"مجموع التذاكر المحددة ({total_requested_quota}) يتجاوز الحد الأقصى للدعوات الشهرية المسموح به في خطتك ({inv_limit}).",
            operation="event_capacity_configuration",
        )

    import re, secrets
    slug_base = re.sub(r'[^a-z0-9]+', '-', body.title.lower()).strip('-') or "event"
    slug = f"{slug_base}-{secrets.token_hex(3)}"

    # Persist the entire public EventCreate contract.  Selecting a subset here
    # causes otherwise valid setup data (location, capacity and assignment)
    # to disappear after a successful create response.
    result = await db.execute(
        text("""
            INSERT INTO events (
                tenant_id, event_type_id, category_id,
                title, title_ar, description, slug,
                start_date, end_date, timezone,
                venue_name, venue_name_ar, venue_address, venue_city, venue_country,
                venue_map_url, venue_lat, venue_lng,
                vip_quota, normal_quota, capacity, vip_capacity, normal_capacity,
                allow_rsvp, allow_plus_one, allow_reentry, require_name,
                cover_image_url, theme_color, status, created_by, team_id, metadata
            )
            VALUES (
                :tid, :event_type_id, :category_id,
                :title, :title_ar, :description, :slug,
                :start, :end, :tz,
                :venue_name, :venue_name_ar, :venue_address, :venue_city, :venue_country,
                :venue_map_url, :venue_lat, :venue_lng,
                :vip_quota, :normal_quota, :capacity, :vip_capacity, :normal_capacity,
                :allow_rsvp, :allow_plus_one, :allow_reentry, :require_name,
                :cover_image_url, :theme_color, :status, :uid, :team_id, CAST(:metadata AS jsonb)
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id),
            "event_type_id": str(body.event_type_id) if body.event_type_id else None,
            "category_id": str(body.category_id) if body.category_id else None,
            "title": body.title,
            "title_ar": body.title_ar,
            "description": body.description,
            "slug": slug,
            "start": body.start_date,
            "end": body.end_date,
            "tz": body.timezone,
            "venue_name": body.venue_name,
            "venue_name_ar": body.venue_name_ar,
            "venue_address": body.venue_address,
            "venue_city": body.venue_city,
            "venue_country": body.venue_country,
            "venue_map_url": body.venue_map_url,
            "venue_lat": body.venue_lat,
            "venue_lng": body.venue_lng,
            "uid": str(user.id),
            "vip_quota": body.vip_quota,
            "normal_quota": body.normal_quota,
            "capacity": body.capacity,
            "vip_capacity": body.vip_capacity,
            "normal_capacity": body.normal_capacity,
            "allow_rsvp": body.allow_rsvp,
            "allow_plus_one": body.allow_plus_one,
            "allow_reentry": body.allow_reentry,
            "require_name": body.require_name,
            "status": "draft",
            "cover_image_url": body.cover_image_url,
            "theme_color": body.theme_color,
            "team_id": str(body.team_id) if body.team_id else None,
            "metadata": json.dumps(body.metadata or {}),
        }
    )
    row = result.mappings().first()

    # A companion institution always hands new events to its linked organizer.
    # The event remains owned by the institution, while the organizer receives
    # one operational workspace to run it.  Keeping this in the same database
    # transaction guarantees that a linked event cannot be created unassigned.
    link_result = await db.execute(
        text("""
            SELECT organizer_tenant_id
            FROM workspace_links
            WHERE institution_tenant_id = :tid AND status = 'active'
            LIMIT 1
        """),
        {"tid": str(tenant_id)},
    )
    organizer_tenant_id = link_result.scalar()
    if organizer_tenant_id:
        manager_result = await db.execute(
            text("""
                SELECT user_id
                FROM memberships
                WHERE tenant_id = :organizer_tenant_id
                  AND status = 'active'
                  AND role IN ('owner', 'admin')
                ORDER BY CASE role::text WHEN 'owner' THEN 0 ELSE 1 END
                LIMIT 1
            """),
            {"organizer_tenant_id": str(organizer_tenant_id)},
        )
        project_manager_id = manager_result.scalar()
        if not project_manager_id:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="لا يمكن إسناد الحدث: لا يوجد مدير نشط لفريق التشغيل المرتبط.",
            )

        operation_result = await db.execute(
            text("""
                INSERT INTO event_operations (
                    event_id, requester_tenant_id, provider_tenant_id,
                    project_manager_id, title, description, deadline_at,
                    last_modified_by
                )
                VALUES (
                    :event_id, :requester_tenant_id, :provider_tenant_id,
                    :project_manager_id, :title, :description, :deadline_at,
                    :actor_user_id
                )
                RETURNING id
            """),
            {
                "event_id": str(row["id"]),
                "requester_tenant_id": str(tenant_id),
                "provider_tenant_id": str(organizer_tenant_id),
                "project_manager_id": str(project_manager_id),
                "title": body.title,
                "description": body.description,
                "deadline_at": body.start_date,
                "actor_user_id": str(user.id),
            },
        )
        operation_id = operation_result.scalar_one()
        await db.execute(
            text("""
                INSERT INTO event_operation_members (operation_id, user_id, role)
                VALUES (:operation_id, :user_id, 'manager')
                ON CONFLICT (operation_id, user_id) DO UPDATE SET role = 'manager'
            """),
            {"operation_id": str(operation_id), "user_id": str(project_manager_id)},
        )
        await db.execute(
            text("""
                INSERT INTO event_operation_activity
                    (operation_id, actor_user_id, action, entity_type, entity_id, details)
                VALUES (
                    :operation_id, :actor_user_id, 'operation.created.linked_event',
                    'event', :event_id,
                    jsonb_build_object('source', 'institution_event_create')
                )
            """),
            {
                "operation_id": str(operation_id),
                "actor_user_id": str(user.id),
                "event_id": str(row["id"]),
            },
        )
    
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.create", resource_type="event", resource_id=str(row["id"]),
                    ip_address=get_client_ip(request))
    await db.commit()
    
    # Convert row to dict and return EventRead
    return EventRead(**dict(row))


@router.get("", response_model=list[EventRead])
async def list_events(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.view")

    query = "SELECT * FROM events WHERE tenant_id = :tid AND deleted_at IS NULL"
    params: dict = {"tid": str(tenant_id)}
    if status_filter:
        query += " AND status = :status"
        params["status"] = status_filter

    # ── Team visibility isolation ──
    # Org-wide managers (events.edit) see every event. Other users see only
    # unassigned events plus events assigned to teams they belong to.
    can_view_all = await has_permission(db, tenant_id, user.id, "events.edit")
    if not can_view_all:
        team_ids = await get_user_team_ids(db, tenant_id, user.id)
        if team_ids:
            placeholders = ", ".join(f":team_{i}" for i in range(len(team_ids)))
            query += f" AND (team_id IS NULL OR team_id IN ({placeholders}))"
            for i, tid in enumerate(team_ids):
                params[f"team_{i}"] = tid
        else:
            query += " AND team_id IS NULL"

    query += " ORDER BY start_date DESC"

    result = await db.execute(text(query), params)
    own_events = [EventRead(**dict(r)) for r in result.mappings().all()]

    # ── Provider events: events assigned via event_operations ──
    provider_eids = await get_provider_event_ids(db, tenant_id, user.id)
    if provider_eids:
        own_event_ids = {str(e.id) for e in own_events}
        # Filter out already-listed events and apply status filter
        new_eids = [eid for eid in provider_eids if str(eid) not in own_event_ids]
        if new_eids:
            ph = ", ".join(f":peid_{i}" for i in range(len(new_eids)))
            pq = f"SELECT * FROM events WHERE deleted_at IS NULL AND id IN ({ph})"
            pp: dict = {f"peid_{i}": str(eid) for i, eid in enumerate(new_eids)}
            if status_filter:
                pq += " AND status = :pstatus"
                pp["pstatus"] = status_filter
            pq += " ORDER BY start_date DESC"
            pr = await db.execute(text(pq), pp)
            own_events.extend(EventRead(**dict(r)) for r in pr.mappings().all())

    return own_events


@router.get("/{event_id}", response_model=EventRead)
async def get_event(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Cooperative Authorization: owner OR assigned provider
    await require_event_access(db, event_id, tenant_id, user.id, "events.view")

    # Fetch using the event's actual owner tenant
    event_owner_tid = await get_event_owner_tenant(db, event_id)
    result = await db.execute(
        text("SELECT * FROM events WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL"),
        {"id": str(event_id), "tid": str(event_owner_tid)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الحدث غير موجود")
    return EventRead(**dict(row))


@router.patch("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: UUID,
    body: EventUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "لا توجد حقول للتعديل")

    non_nullable_fields = {
        "title", "start_date", "timezone", "vip_quota", "normal_quota",
        "allow_rsvp", "allow_plus_one", "allow_reentry", "require_name",
    }
    if any(field in updates and updates[field] is None for field in non_nullable_fields):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا يمكن إفراغ حقل إلزامي في الحدث")

    existing_res = await db.execute(
        text("""
            SELECT event_type_id, category_id, team_id, start_date, end_date,
                   vip_quota, normal_quota, capacity, vip_capacity, normal_capacity
            FROM events
            WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL
        """),
        {"id": str(event_id), "tid": str(tenant_id)},
    )
    existing = existing_res.mappings().first()
    if not existing:
        raise HTTPException(404, "الحدث غير موجود")

    new_event_type_id = updates["event_type_id"] if "event_type_id" in updates else existing["event_type_id"]
    new_category_id = updates["category_id"] if "category_id" in updates else existing["category_id"]
    new_team_id = updates["team_id"] if "team_id" in updates else existing["team_id"]
    await _validate_event_references(
        db,
        tenant_id,
        category_id=new_category_id,
        event_type_id=new_event_type_id,
        team_id=new_team_id,
    )
    _validate_event_schedule_and_capacity(
        start_date=updates.get("start_date", existing["start_date"]),
        end_date=updates["end_date"] if "end_date" in updates else existing["end_date"],
        capacity=updates["capacity"] if "capacity" in updates else existing["capacity"],
        vip_capacity=updates["vip_capacity"] if "vip_capacity" in updates else existing["vip_capacity"],
        normal_capacity=updates["normal_capacity"] if "normal_capacity" in updates else existing["normal_capacity"],
        vip_quota=updates.get("vip_quota", existing["vip_quota"]),
        normal_quota=updates.get("normal_quota", existing["normal_quota"]),
    )

    # ── Plan limit: vip_quota + normal_quota (update check) ──
    if "vip_quota" in updates or "normal_quota" in updates:
        new_vip = updates.get("vip_quota", existing["vip_quota"])
        new_normal = updates.get("normal_quota", existing["normal_quota"])

        from app.services.feature_service import get_plan_limit
        inv_limit = await get_plan_limit(db, tenant_id, "invitations_per_month")
        total_requested_quota = (new_vip or 0) + (new_normal or 0)
        if inv_limit != -1 and total_requested_quota > inv_limit:
            raise plan_limit_exceeded(
                "invitations_per_month", 0, inv_limit, total_requested_quota,
                message=f"مجموع التذاكر المحددة ({total_requested_quota}) يتجاوز الحد الأقصى للدعوات الشهرية المسموح به في خطتك ({inv_limit}).",
                operation="event_capacity_configuration",
            )

    # Convert UUIDs to strings
    for k in ["event_type_id", "category_id", "team_id"]:
        if k in updates and updates[k] is not None:
            updates[k] = str(updates[k])

    if "metadata" in updates and updates["metadata"] is not None:
        updates["metadata"] = json.dumps(updates["metadata"])

    set_clauses = ", ".join(
        f"{k} = CAST(:{k} AS jsonb)" if k == "metadata" else f"{k} = :{k}"
        for k in updates
    )
    updates["id"] = str(event_id)
    updates["tid"] = str(tenant_id)

    result = await db.execute(
        text(f"UPDATE events SET {set_clauses}, updated_at = now() WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL RETURNING *"),
        updates,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الحدث غير موجود")

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.update", resource_type="event", resource_id=str(event_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return EventRead(**dict(row))


@router.post("/{event_id}/cover")
async def upload_event_cover(
    event_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a cover image for an event. Stores in Supabase Storage."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")

    # Verify event exists
    event_res = await db.execute(
        text("SELECT id FROM events WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL"),
        {"id": str(event_id), "tid": str(tenant_id)},
    )
    if not event_res.mappings().first():
        raise HTTPException(404, "الحدث غير موجود")

    # Validate file type
    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(400, f"نوع الملف غير مدعوم. المسموح: {', '.join(allowed)}")

    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "الملف فارغ أو حجمه يتجاوز 10MB")
    detected = None
    if content.startswith(b"\x89PNG\r\n\x1a\n"): detected = "image/png"
    elif content.startswith(b"\xff\xd8\xff"): detected = "image/jpeg"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP": detected = "image/webp"
    if detected != file.content_type:
        raise HTTPException(400, "محتوى الصورة لا يطابق نوع الملف المعلن")

    from app.services.feature_service import require_storage_for_upload, record_non_asset_storage
    await require_storage_for_upload(db, tenant_id, len(content))

    import uuid
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[detected]
    safe_name = f"cover_{uuid.uuid4().hex[:8]}.{ext}"
    
    from app.services import storage_service
    path = storage_service.build_path(
        tenant_id, event_id, "cover", safe_name
    )
    import asyncio
    await asyncio.to_thread(storage_service.upload_file, path, content, detected)
    await record_non_asset_storage(db, tenant_id, len(content))
    cover_url = storage_service.get_signed_url(path, expires_in=86400 * 365)

    old_asset = (await db.execute(text("""
        SELECT id, file_url FROM event_assets
        WHERE event_id=:eid AND asset_type='cover_image'
        ORDER BY created_at DESC LIMIT 1
    """), {"eid": str(event_id)})).mappings().first()
    try:
        await db.execute(text("UPDATE events SET cover_image_url=:url, updated_at=now() WHERE id=:id AND tenant_id=:tid"),
                         {"url": cover_url, "id": str(event_id), "tid": str(tenant_id)})
        await db.execute(text("""
            INSERT INTO event_assets(event_id,asset_type,file_url,file_name,mime_type,size,metadata)
            VALUES(:eid,'cover_image',:path,:name,:mime,:size,'{}'::jsonb)
        """), {"eid": str(event_id), "path": path, "name": safe_name, "mime": detected, "size": len(content)})
        if old_asset:
            await db.execute(text("DELETE FROM event_assets WHERE id=:id"), {"id": str(old_asset["id"])})
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(storage_service.delete_file, path)
        raise
    if old_asset and old_asset["file_url"].startswith(f"{tenant_id}/{event_id}/"):
        await asyncio.to_thread(storage_service.delete_file, old_asset["file_url"])

    return {"cover_image_url": cover_url}


@router.get("/{event_id}/logo")
async def get_event_logo(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_event_access(db, event_id, tenant_id, user.id, "events.view")
    owner_tenant = await get_event_owner_tenant(db, event_id)
    row = (await db.execute(text("""
        SELECT file_url FROM event_assets
        WHERE event_id=:eid AND asset_type='logo'
        ORDER BY created_at DESC LIMIT 1
    """), {"eid": str(event_id)})).mappings().first()
    if not row:
        return {"logo_url": None}
    from app.services import storage_service
    path = row["file_url"]
    url = (storage_service.get_signed_url(path, expires_in=86400 * 365)
           if path.startswith(f"{owner_tenant}/{event_id}/") else path)
    return {"logo_url": url}


@router.post("/{event_id}/logo")
async def upload_event_logo(
    event_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload and replace the event logo used by public forms and entry cards."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")

    event_res = await db.execute(
        text("SELECT id FROM events WHERE id=:id AND tenant_id=:tid AND deleted_at IS NULL"),
        {"id": str(event_id), "tid": str(tenant_id)},
    )
    if not event_res.first():
        raise HTTPException(404, "الحدث غير موجود")

    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(400, "نوع الشعار غير مدعوم. المسموح: PNG, JPG, WEBP")
    content = await file.read()
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "ملف الشعار فارغ أو حجمه يتجاوز 5MB")
    detected = None
    if content.startswith(b"\x89PNG\r\n\x1a\n"): detected = "image/png"
    elif content.startswith(b"\xff\xd8\xff"): detected = "image/jpeg"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP": detected = "image/webp"
    if detected != file.content_type:
        raise HTTPException(400, "محتوى الشعار لا يطابق نوع الملف المعلن")

    from app.services.feature_service import require_storage_for_upload, record_non_asset_storage
    await require_storage_for_upload(db, tenant_id, len(content))
    from app.services import storage_service
    import asyncio
    import uuid
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[detected]
    safe_name = f"logo_{uuid.uuid4().hex[:8]}.{ext}"
    path = storage_service.build_path(tenant_id, event_id, "logo", safe_name)
    await asyncio.to_thread(storage_service.upload_file, path, content, detected)
    await record_non_asset_storage(db, tenant_id, len(content))

    old_asset = (await db.execute(text("""
        SELECT id, file_url FROM event_assets
        WHERE event_id=:eid AND asset_type='logo'
        ORDER BY created_at DESC LIMIT 1
    """), {"eid": str(event_id)})).mappings().first()
    try:
        row = (await db.execute(text("""
            INSERT INTO event_assets(event_id,asset_type,file_url,file_name,mime_type,size,metadata)
            VALUES(:eid,'logo',:path,:name,:mime,:size,'{}'::jsonb)
            RETURNING id
        """), {"eid": str(event_id), "path": path, "name": safe_name,
                 "mime": detected, "size": len(content)})).mappings().first()
        if old_asset:
            await db.execute(text("DELETE FROM event_assets WHERE id=:id"), {"id": str(old_asset["id"])})
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                        action="event.logo.update", resource_type="event_asset",
                        resource_id=str(row["id"]), ip_address=get_client_ip(request))
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(storage_service.delete_file, path)
        raise
    if old_asset and old_asset["file_url"].startswith(f"{tenant_id}/{event_id}/"):
        await asyncio.to_thread(storage_service.delete_file, old_asset["file_url"])

    return {
        "asset_id": str(row["id"]),
        "logo_url": storage_service.get_signed_url(path, expires_in=86400 * 365),
    }



@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.delete")

    # Archive instead of cascading a destructive delete through invitations,
    # check-ins, batches, gates and assets.
    event_res = await db.execute(
        text("SELECT status FROM events WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL FOR UPDATE"),
        {"id": str(event_id), "tid": str(tenant_id)},
    )
    event_row = event_res.mappings().first()
    if not event_row:
        raise HTTPException(404, "الحدث غير موجود")
    if event_row["status"] in ("published", "active"):
        raise HTTPException(409, "يجب إلغاء الحدث أو إكماله قبل الأرشفة")

    result = await db.execute(
        text("""
            UPDATE events
            SET deleted_at=now(), deleted_by=:uid, updated_at=now()
            WHERE id=:id AND tenant_id=:tid AND deleted_at IS NULL
        """),
        {"id": str(event_id), "tid": str(tenant_id), "uid": str(user.id)},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "الحدث غير موجود")

    # Monthly usage measures successful creations, not unarchived events.
    # Archiving never refunds a creation (docs/LIMITS_POLICY_AR.md).

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.archive", resource_type="event", resource_id=str(event_id),
                    ip_address=get_client_ip(request))
    await db.commit()


@router.post("/{event_id}/restore", response_model=EventRead)
async def restore_event(
    event_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.delete")
    existing = (await db.execute(
        text("SELECT id FROM events WHERE id=:id AND tenant_id=:tid AND deleted_at IS NOT NULL FOR UPDATE"),
        {"id": str(event_id), "tid": str(tenant_id)},
    )).mappings().first()
    if not existing:
        raise HTTPException(404, "الحدث المؤرشف غير موجود")
    # Restoring the same event is not another creation, even at the plan cap.
    row = (await db.execute(text("""
        UPDATE events SET deleted_at=NULL, deleted_by=NULL, updated_at=now()
        WHERE id=:id AND tenant_id=:tid RETURNING *
    """), {"id": str(event_id), "tid": str(tenant_id)})).mappings().first()
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.restore", resource_type="event", resource_id=str(event_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return EventRead(**dict(row))


# ══════════════════════════════════════════════
# EVENT → TEAM ASSIGNMENT (admin assigns; team lead accepts)
# ══════════════════════════════════════════════

@router.post("/{event_id}/assign", response_model=EventTeamAssignmentRead, status_code=201)
async def assign_event_to_team(
    event_id: UUID, body: EventAssignCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an event to a team. The team lead must then accept/reject."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.assign_events")

    ev = await db.execute(
        text("SELECT 1 FROM events WHERE id = :id AND tenant_id = :tid"),
        {"id": str(event_id), "tid": str(tenant_id)},
    )
    if not ev.first():
        raise HTTPException(404, "الحدث غير موجود")

    team = await db.execute(
        text("SELECT 1 FROM teams WHERE id = :id AND tenant_id = :tid"),
        {"id": str(body.team_id), "tid": str(tenant_id)},
    )
    if not team.first():
        raise HTTPException(404, "الفريق غير موجود")

    try:
        result = await db.execute(
            text("""
                INSERT INTO event_team_assignments (event_id, team_id, tenant_id, assigned_by)
                VALUES (:eid, :team, :tid, :uid)
                RETURNING *
            """),
            {"eid": str(event_id), "team": str(body.team_id),
             "tid": str(tenant_id), "uid": str(user.id)},
        )
    except Exception:
        await db.rollback()
        raise HTTPException(409, "هذا الحدث مُسند لهذا الفريق بالفعل")

    row = dict(result.mappings().first())
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.assign_team", resource_type="event", resource_id=str(event_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return EventTeamAssignmentRead(**row)


@router.get("/{event_id}/assignments", response_model=list[EventTeamAssignmentRead])
async def list_event_assignments(
    event_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.view")

    result = await db.execute(
        text("""
            SELECT eta.*, t.name AS team_name
            FROM event_team_assignments eta
            JOIN teams t ON t.id = eta.team_id
            WHERE eta.event_id = :eid AND eta.tenant_id = :tid
            ORDER BY eta.created_at DESC
        """),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    return [EventTeamAssignmentRead(**dict(r)) for r in result.mappings().all()]


@router.post("/{event_id}/publish", response_model=EventRead)
async def publish_event(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.publish")
    return await _transition_event(db, event_id, tenant_id, user, request, "published")


async def _transition_event(
    db: AsyncSession, event_id: UUID, tenant_id: UUID,
    user: CurrentUser, request: Request, new_status: str,
) -> EventRead:
    current = (await db.execute(text("""
        SELECT * FROM events
        WHERE id=:id AND tenant_id=:tid AND deleted_at IS NULL
        FOR UPDATE
    """), {"id": str(event_id), "tid": str(tenant_id)})).mappings().first()
    if not current:
        raise HTTPException(404, "الحدث غير موجود")
    if new_status not in _EVENT_TRANSITIONS.get(current["status"], set()):
        raise HTTPException(409, f"لا يمكن نقل الحدث من {current['status']} إلى {new_status}")
    if new_status == "published":
        issues = await _event_readiness_issues(db, event_id, tenant_id)
        if issues:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "الحدث غير جاهز للنشر", "issues": issues})
    if new_status == "active":
        blocked_operation = await db.execute(text("""
            SELECT 1 FROM event_operations
            WHERE event_id=:event_id AND status NOT IN ('ready','in_progress','completed','closed','cancelled')
            LIMIT 1
        """), {"event_id": str(event_id)})
        if blocked_operation.first():
            raise HTTPException(409, "يجب تجهيز العملية التشغيلية قبل تفعيل الحدث")
    if new_status == "completed":
        incomplete_tasks = (await db.execute(text("""
            SELECT COUNT(*) FROM event_operation_tasks t
            JOIN event_operations o ON o.id=t.operation_id
            WHERE o.event_id=:event_id AND t.status<>'done'
        """), {"event_id": str(event_id)})).scalar() or 0
        if incomplete_tasks:
            raise HTTPException(409, f"لا يمكن إكمال الحدث قبل إنهاء {incomplete_tasks} مهمة تشغيلية")

    row = (await db.execute(text("""
        UPDATE events
        SET status=CAST(:new_status AS event_status),
            published_at=CASE WHEN :new_status='published' THEN COALESCE(published_at, now()) ELSE published_at END,
            updated_at=now()
        WHERE id=:id AND tenant_id=:tid RETURNING *
    """), {"new_status": new_status, "id": str(event_id), "tid": str(tenant_id)})).mappings().first()

    operation_status = {"active": "in_progress", "completed": "completed", "cancelled": "cancelled"}.get(new_status)
    if operation_status:
        await db.execute(text("""
            UPDATE event_operations
            SET status=:status,
                progress=CASE WHEN :status='completed' THEN 100 ELSE progress END,
                status_change_reason='event.status_transition', last_modified_by=:uid, updated_at=now()
            WHERE event_id=:event_id AND (
              (:status='in_progress' AND status IN ('ready','in_progress')) OR
              (:status='completed' AND status='in_progress') OR
              (:status='cancelled' AND status NOT IN ('closed','completed','cancelled'))
            )
        """), {"status": operation_status, "uid": str(user.id), "event_id": str(event_id)})
        await db.execute(text("""
            UPDATE organizer_booking_requests
            SET status=:status, status_reason='event.status_transition', updated_at=now()
            WHERE event_id=:event_id AND (
              (:status='in_progress' AND status IN ('accepted','reopened','in_progress')) OR
              (:status='completed' AND status='in_progress') OR
              (:status='cancelled' AND status NOT IN ('completed','cancelled','rejected'))
            )
        """), {"status": operation_status, "event_id": str(event_id)})

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.status_transition", resource_type="event", resource_id=str(event_id),
                    metadata={"from_status": current["status"], "to_status": new_status},
                    ip_address=get_client_ip(request))
    await db.commit()
    return EventRead(**dict(row))


@router.post("/{event_id}/transition", response_model=EventRead)
async def transition_event(
    event_id: UUID, body: EventStatusTransitionRequest, request: Request,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.publish")
    return await _transition_event(db, event_id, tenant_id, user, request, body.new_status)


# ══════════════════════════════════════════════
# EVENT ASSETS
# ══════════════════════════════════════════════

@router.get("/{event_id}/assets", response_model=list[EventAssetRead])
async def list_event_assets(
    event_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_event_access(db, event_id, tenant_id, user.id, "events.view")
    owner_tenant = await get_event_owner_tenant(db, event_id)
    rows = await db.execute(text("""
        SELECT a.* FROM event_assets a JOIN events e ON e.id=a.event_id
        WHERE a.event_id=:eid AND e.tenant_id=:tid AND e.deleted_at IS NULL
        ORDER BY a.sort_order, a.created_at
    """), {"eid": str(event_id), "tid": str(owner_tenant)})
    return [EventAssetRead(**dict(row)) for row in rows.mappings().all()]


@router.post("/{event_id}/assets", response_model=EventAssetRead, status_code=201)
async def create_event_asset(
    event_id: UUID, body: EventAssetCreate, request: Request,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")
    if body.event_id != event_id:
        raise HTTPException(422, "event_id في المسار والطلب غير متطابقين")
    event = await db.execute(text(
        "SELECT 1 FROM events WHERE id=:id AND tenant_id=:tid AND deleted_at IS NULL"
    ), {"id": str(event_id), "tid": str(tenant_id)})
    if not event.first():
        raise HTTPException(404, "الحدث غير موجود")
    from app.services import storage_service
    owned_prefix = f"{tenant_id}/{event_id}/"
    if not (body.file_url.startswith(owned_prefix) or storage_service.is_trusted_storage_url(body.file_url)):
        raise HTTPException(422, "يجب أن يشير أصل الحدث إلى ملف موثوق في مساحة التخزين")
    row = (await db.execute(text("""
        INSERT INTO event_assets(event_id,asset_type,file_url,file_name,mime_type,size,metadata,sort_order)
        VALUES(:eid,:kind,:url,:name,:mime,:size,CAST(:metadata AS jsonb),:sort) RETURNING *
    """), {"eid": str(event_id), "kind": body.asset_type, "url": body.file_url,
            "name": body.file_name, "mime": body.mime_type, "size": body.size,
            "metadata": json.dumps(body.metadata or {}), "sort": body.sort_order})).mappings().first()
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="event.asset.create",
                    resource_type="event_asset", resource_id=str(row["id"]), ip_address=get_client_ip(request))
    await db.commit()
    return EventAssetRead(**dict(row))


@router.delete("/{event_id}/assets/{asset_id}", status_code=204)
async def delete_event_asset(
    event_id: UUID, asset_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")
    row = (await db.execute(text("""
        DELETE FROM event_assets a USING events e
        WHERE a.id=:aid AND a.event_id=:eid AND e.id=a.event_id AND e.tenant_id=:tid
        RETURNING a.file_url
    """), {"aid": str(asset_id), "eid": str(event_id), "tid": str(tenant_id)})).mappings().first()
    if not row:
        raise HTTPException(404, "أصل الحدث غير موجود")
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="event.asset.delete",
                    resource_type="event_asset", resource_id=str(asset_id), ip_address=get_client_ip(request))
    await db.commit()
    if row["file_url"].startswith(f"{tenant_id}/{event_id}/"):
        import asyncio
        from app.services import storage_service
        await asyncio.to_thread(storage_service.delete_file, row["file_url"])


# ══════════════════════════════════════════════
# EVENT STATS
# ══════════════════════════════════════════════

@router.get("/{event_id}/stats", response_model=EventStats)
async def get_event_stats(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Cooperative Authorization: owner OR assigned provider
    await require_event_access(db, event_id, tenant_id, user.id, "events.view")

    # Use the event's actual owner tenant for querying invitations
    event_owner_tid = await get_event_owner_tenant(db, event_id)
    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_invitations,
                COUNT(*) FILTER (WHERE ticket_class = 'vip') AS vip_count,
                COUNT(*) FILTER (WHERE ticket_class = 'normal') AS normal_count,
                COALESCE(SUM(guest_count) FILTER (WHERE ticket_class='vip' AND status NOT IN ('revoked','expired')),0)::int AS vip_quota_used,
                COALESCE(SUM(guest_count) FILTER (WHERE ticket_class='normal' AND status NOT IN ('revoked','expired')),0)::int AS normal_quota_used,
                COUNT(*) FILTER (WHERE status = 'sent') AS sent_count,
                COUNT(*) FILTER (WHERE status = 'viewed') AS viewed_count,
                COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_count,
                COUNT(*) FILTER (WHERE status = 'declined') AS declined_count,
                COUNT(*) FILTER (WHERE status = 'checked_in') AS checked_in_count,
                COUNT(*) FILTER (WHERE status = 'revoked') AS revoked_count,
                COALESCE(SUM(guest_count) FILTER (WHERE status NOT IN ('revoked','expired','declined')), 0)::int AS invited_people,
                COALESCE(SUM(guest_count) FILTER (WHERE status IN ('accepted','checked_in')), 0)::int AS accepted_people,
                COALESCE(SUM(checkin_count), 0)::int AS checked_in_people,
                (SELECT capacity FROM events WHERE id=:eid) AS capacity
            FROM invitations
            WHERE event_id = :eid AND tenant_id = :tid
        """),
        {"eid": str(event_id), "tid": str(event_owner_tid)},
    )
    row = result.mappings().first()
    return EventStats(**dict(row))


# ══════════════════════════════════════════════
# EVENT GATES
# ══════════════════════════════════════════════

@router.get("/{event_id}/gates", response_model=list[EventGateRead])
async def list_gates(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Gate controls belong exclusively to the provider operation team.
    await require_provider_event_access(db, event_id, tenant_id, user.id, "gates.view")

    # Use event's actual owner tenant
    event_owner_tid = await get_event_owner_tenant(db, event_id)
    result = await db.execute(
        text("""
            SELECT g.*, 
                   COALESCE(
                       (SELECT array_agg(user_id) FROM event_gate_users WHERE gate_id = g.id), 
                       '{}'::uuid[]
                   ) AS assigned_users
            FROM event_gates g
            JOIN events e ON e.id = g.event_id
            WHERE g.event_id = :eid AND e.tenant_id = :tid
            ORDER BY g.name
        """),
        {"eid": str(event_id), "tid": str(event_owner_tid)},
    )
    return [EventGateRead(**dict(r)) for r in result.mappings().all()]


@router.post("/{event_id}/gates", response_model=EventGateRead, status_code=201)
async def create_gate(
    event_id: UUID,
    body: EventGateCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Gate controls belong exclusively to the provider operation team.
    await require_provider_event_access(db, event_id, tenant_id, user.id, "gates.manage")
    await _validate_gate_assignments(db, tenant_id, body)

    # ── Plan limit: gates_per_event (use event owner's tenant for limit checks) ──
    from app.services.feature_service import enforce_static_limit, acquire_plan_limit_lock
    event_owner_tid = await get_event_owner_tenant(db, event_id)
    if not event_owner_tid:
        raise HTTPException(404, "الحدث غير موجود")
    await acquire_plan_limit_lock(db, event_owner_tid, "gates_per_event", str(event_id))
    gates_count_res = await db.execute(
        text("SELECT COUNT(*) FROM event_gates WHERE event_id = :eid AND is_active = true"),
        {"eid": str(event_id)},
    )
    current_gates = gates_count_res.scalar() or 0
    await enforce_static_limit(db, event_owner_tid, "gates_per_event", current_gates, "البوابات لكل حدث")

    result = await db.execute(
        text("""
            INSERT INTO event_gates (event_id, name, name_ar, allowed_classes, team_id)
            VALUES (:eid, :name, :name_ar, CAST(:classes AS ticket_class[]), :team_id)
            RETURNING id
        """),
        {
            "eid": str(event_id),
            "name": body.name,
            "name_ar": body.name_ar,
            "classes": body.allowed_classes,
            "team_id": str(body.team_id) if body.team_id else None,
        },
    )
    gate_row = result.mappings().first()
    gate_id = gate_row["id"]

    if body.assigned_users:
        for u_id in body.assigned_users:
            await db.execute(
                text("INSERT INTO event_gate_users (gate_id, user_id) VALUES (:gid, :uid) ON CONFLICT DO NOTHING"),
                {"gid": str(gate_id), "uid": str(u_id)}
            )

    gate_res = await db.execute(
        text("""
            SELECT g.*, 
                   COALESCE(
                       (SELECT array_agg(user_id) FROM event_gate_users WHERE gate_id = g.id), 
                       '{}'::uuid[]
                   ) AS assigned_users
            FROM event_gates g
            WHERE g.id = :gid
        """),
        {"gid": str(gate_id)},
    )
    row = gate_res.mappings().first()
    await db.commit()
    return EventGateRead(**dict(row))


@router.put("/{event_id}/gates/{gate_id}", response_model=EventGateRead)
async def update_gate(
    event_id: UUID,
    gate_id: UUID,
    body: EventGateCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Gate controls belong exclusively to the provider operation team.
    await require_provider_event_access(db, event_id, tenant_id, user.id, "gates.manage")
    await _validate_gate_assignments(db, tenant_id, body)

    result = await db.execute(
        text("""
            UPDATE event_gates
            SET name = :name,
                name_ar = :name_ar,
                allowed_classes = CAST(:classes AS ticket_class[]),
                team_id = :team_id
            WHERE id = :gid AND event_id = :eid
            RETURNING id
        """),
        {
            "gid": str(gate_id),
            "eid": str(event_id),
            "name": body.name,
            "name_ar": body.name_ar,
            "classes": body.allowed_classes,
            "team_id": str(body.team_id) if body.team_id else None,
        },
    )
    if result.rowcount == 0:
        raise HTTPException(404, "البوابة غير موجودة")

    await db.execute(
        text("DELETE FROM event_gate_users WHERE gate_id = :gid"),
        {"gid": str(gate_id)}
    )

    if body.assigned_users:
        for u_id in body.assigned_users:
            await db.execute(
                text("INSERT INTO event_gate_users (gate_id, user_id) VALUES (:gid, :uid)"),
                {"gid": str(gate_id), "uid": str(u_id)}
            )

    gate_res = await db.execute(
        text("""
            SELECT g.*, 
                   COALESCE(
                       (SELECT array_agg(user_id) FROM event_gate_users WHERE gate_id = g.id), 
                       '{}'::uuid[]
                   ) AS assigned_users
            FROM event_gates g
            WHERE g.id = :gid
        """),
        {"gid": str(gate_id)},
    )
    row = gate_res.mappings().first()
    await db.commit()
    return EventGateRead(**dict(row))


@router.delete("/{event_id}/gates/{gate_id}", status_code=204)
async def delete_gate(
    event_id: UUID,
    gate_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    # Gate controls belong exclusively to the provider operation team.
    await require_provider_event_access(db, event_id, tenant_id, user.id, "gates.manage")

    dependencies = await db.execute(text("""
        SELECT
          EXISTS(SELECT 1 FROM event_gate_shifts WHERE gate_id=:gid) AS has_shifts,
          EXISTS(SELECT 1 FROM checkins WHERE gate_id=:gid) AS has_checkins
    """), {"gid": str(gate_id)})
    dependency_row = dependencies.mappings().first()
    if dependency_row and (dependency_row["has_shifts"] or dependency_row["has_checkins"]):
        result = await db.execute(
            text("UPDATE event_gates SET is_active=false WHERE id=:gid AND event_id=:eid"),
            {"gid": str(gate_id), "eid": str(event_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "البوابة غير موجودة")
        await db.commit()
        return

    result = await db.execute(
        text("DELETE FROM event_gates WHERE id = :gid AND event_id = :eid"),
        {"gid": str(gate_id), "eid": str(event_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "البوابة غير موجودة")
    await db.commit()
