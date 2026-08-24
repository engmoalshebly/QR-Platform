"""Teams API: CRUD + member management."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.models.team import (
    TeamCreate, TeamRead, TeamUpdate, TeamMemberRead, TeamMemberAdd,
    TeamRequestCreate, TeamRequestRead,
    EventTeamAssignmentRead, AssignmentResponse,
)
from app.services.permission_service import require_permission
from app.services.team_service import require_team_lead, is_team_lead
from app.services.audit_service import log_audit
from app.security import get_client_ip

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("", response_model=list[TeamRead])
async def list_teams(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")

    result = await db.execute(
        text("""
            SELECT t.*, 
                   (SELECT COUNT(*) FROM team_memberships tm WHERE tm.team_id = t.id) as members_count,
                   (SELECT p.full_name FROM team_memberships tm JOIN profiles p ON p.id = tm.user_id WHERE tm.team_id = t.id AND tm.role = 'team_lead' LIMIT 1) as leader_name
            FROM teams t 
            WHERE t.tenant_id = :tid 
            ORDER BY t.name
        """),
        {"tid": str(tenant_id)},
    )
    return [TeamRead(**dict(r)) for r in result.mappings().all()]


@router.post("", response_model=TeamRead, status_code=201)
async def create_team(
    body: TeamCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(403, "إنشاء فرق التنظيم متاح حصرياً عبر نموذج طلب الاعتماد وموافقة السوبر أدمن")


@router.post("/requests", response_model=TeamRequestRead, status_code=201)
async def create_team_request(
    body: TeamRequestCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(403, "استخدم نموذج طلب اعتماد فريق التنظيم العام")


@router.get("/requests", response_model=list[TeamRequestRead])
async def list_team_requests(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Requests in this tenant. Admins see all; members see their own."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.request")

    from app.services.permission_service import has_permission
    can_manage = await has_permission(db, tenant_id, user.id, "teams.manage")

    query = """
        SELECT tr.*, p.full_name AS requester_name
        FROM team_requests tr
        JOIN profiles p ON p.id = tr.requested_by
        WHERE tr.tenant_id = :tid
    """
    params = {"tid": str(tenant_id)}
    if not can_manage:
        query += " AND tr.requested_by = :uid"
        params["uid"] = str(user.id)
    query += " ORDER BY tr.created_at DESC"

    result = await db.execute(text(query), params)
    return [TeamRequestRead(**dict(r)) for r in result.mappings().all()]


# ══════════════════════════════════════════════
# TEAM LEAD: event-assignment inbox + response
# ══════════════════════════════════════════════

@router.get("/assignments/inbox", response_model=list[EventTeamAssignmentRead])
async def assignment_inbox(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pending event assignments for teams the user leads."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")

    result = await db.execute(
        text("""
            SELECT eta.*, e.title AS event_title, e.start_date AS event_start_date,
                   t.name AS team_name
            FROM event_team_assignments eta
            JOIN teams t ON t.id = eta.team_id
            JOIN team_memberships tm ON tm.team_id = eta.team_id
            JOIN events e ON e.id = eta.event_id
            WHERE eta.tenant_id = :tid
              AND tm.user_id = :uid AND tm.role = 'team_lead'
              AND eta.status = 'pending'
            ORDER BY eta.created_at DESC
        """),
        {"tid": str(tenant_id), "uid": str(user.id)},
    )
    return [EventTeamAssignmentRead(**dict(r)) for r in result.mappings().all()]


async def _respond_assignment(
    assignment_id: UUID, decision: str, note: str | None,
    tenant_id: UUID, user: CurrentUser, db: AsyncSession, request: Request,
) -> EventTeamAssignmentRead:
    result = await db.execute(
        text("SELECT * FROM event_team_assignments WHERE id = :id AND tenant_id = :tid"),
        {"id": str(assignment_id), "tid": str(tenant_id)},
    )
    assignment = result.mappings().first()
    if not assignment:
        raise HTTPException(404, "الإسناد غير موجود")
    if assignment["status"] != "pending":
        raise HTTPException(409, "تمت الاستجابة لهذا الإسناد مسبقاً")

    await require_team_lead(db, assignment["team_id"], user.id)

    updated = await db.execute(
        text("""
            UPDATE event_team_assignments
            SET status = :st, responded_by = :uid, response_note = :note, responded_at = now()
            WHERE id = :id
            RETURNING *
        """),
        {"st": decision, "uid": str(user.id), "note": note, "id": str(assignment_id)},
    )
    row = dict(updated.mappings().first())

    if decision == "accepted":
        await db.execute(
            text("UPDATE events SET team_id = :team WHERE id = :eid AND tenant_id = :tid"),
            {"team": str(assignment["team_id"]), "eid": str(assignment["event_id"]), "tid": str(tenant_id)},
        )

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action=f"event_assignment.{decision}", resource_type="event_team_assignment",
                    resource_id=str(assignment_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return EventTeamAssignmentRead(**row)


@router.post("/assignments/{assignment_id}/accept", response_model=EventTeamAssignmentRead)
async def accept_assignment(
    assignment_id: UUID, body: AssignmentResponse, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")
    return await _respond_assignment(assignment_id, "accepted", body.note, tenant_id, user, db, request)


@router.post("/assignments/{assignment_id}/reject", response_model=EventTeamAssignmentRead)
async def reject_assignment(
    assignment_id: UUID, body: AssignmentResponse, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")
    return await _respond_assignment(assignment_id, "rejected", body.note, tenant_id, user, db, request)


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")

    result = await db.execute(
        text("""
            SELECT t.*, 
                   (SELECT COUNT(*) FROM team_memberships tm WHERE tm.team_id = t.id) as members_count,
                   (SELECT p.full_name FROM team_memberships tm JOIN profiles p ON p.id = tm.user_id WHERE tm.team_id = t.id AND tm.role = 'team_lead' LIMIT 1) as leader_name
            FROM teams t 
            WHERE t.id = :id AND t.tenant_id = :tid
        """),
        {"id": str(team_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الفريق غير موجود")
    return TeamRead(**dict(row))


@router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: UUID, body: TeamUpdate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(403, "لا يمكن تعديل جهة تنظيم من هذه الواجهة")


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(403, "لا يمكن حذف جهة تنظيم؛ يمكن للسوبر أدمن تعليقها من إدارة المنصة")


# ══════════════════════════════════════════════
# TEAM MEMBERS
# ══════════════════════════════════════════════

@router.get("/{team_id}/members", response_model=list[TeamMemberRead])
async def list_team_members(
    team_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.view")

    result = await db.execute(
        text("""
            SELECT tm.id, tm.team_id, tm.user_id, tm.role, tm.joined_at,
                   p.full_name, p.avatar_url
            FROM team_memberships tm
            JOIN profiles p ON p.id = tm.user_id
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.team_id = :tid AND t.tenant_id = :org
            ORDER BY tm.joined_at
        """),
        {"tid": str(team_id), "org": str(tenant_id)},
    )
    return [TeamMemberRead(**dict(r)) for r in result.mappings().all()]


@router.post("/{team_id}/members", response_model=TeamMemberRead, status_code=201)
async def add_team_member(
    team_id: UUID, body: TeamMemberAdd, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.manage")

    # Resolve the team inside the active tenant before doing any writes. This
    # prevents a caller from using a valid member id to mutate another
    # tenant's team by guessing its UUID.
    team_check = await db.execute(
        text("SELECT 1 FROM teams WHERE id = :team AND tenant_id = :tid"),
        {"team": str(team_id), "tid": str(tenant_id)},
    )
    if not team_check.first():
        raise HTTPException(404, "الفريق غير موجود")

    # ── Plan limit: team_members_per_team ──
    from app.services.feature_service import enforce_static_limit, acquire_plan_limit_lock
    await acquire_plan_limit_lock(db, tenant_id, "team_members_per_team", str(team_id))
    members_count_res = await db.execute(
        text("SELECT COUNT(*) FROM team_memberships WHERE team_id = :tid"),
        {"tid": str(team_id)},
    )
    current_members = members_count_res.scalar() or 0
    await enforce_static_limit(db, tenant_id, "team_members_per_team", current_members, "أعضاء الفريق")

    # Verify user is a member of the org
    check = await db.execute(
        text("SELECT 1 FROM memberships WHERE tenant_id = :tid AND user_id = :uid AND status = 'active'"),
        {"tid": str(tenant_id), "uid": str(body.user_id)},
    )
    if not check.first():
        raise HTTPException(400, "المستخدم ليس عضواً في المؤسسة")

    result = await db.execute(
        text("""
            INSERT INTO team_memberships (team_id, user_id, role)
            VALUES (:tid, :uid, :role)
            ON CONFLICT (team_id, user_id) DO UPDATE SET role = :role
            RETURNING id, team_id, user_id, role, joined_at
        """),
        {"tid": str(team_id), "uid": str(body.user_id), "role": body.role},
    )
    row = result.mappings().first()

    # Get profile info
    p = await db.execute(
        text("SELECT full_name, avatar_url FROM profiles WHERE id = :uid"),
        {"uid": str(body.user_id)},
    )
    profile = p.mappings().first()

    await db.commit()
    return TeamMemberRead(
        **dict(row),
        full_name=profile["full_name"] if profile else None,
        avatar_url=profile["avatar_url"] if profile else None,
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: UUID, user_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "teams.manage")

    team_check = await db.execute(
        text("SELECT 1 FROM teams WHERE id = :team AND tenant_id = :tid"),
        {"team": str(team_id), "tid": str(tenant_id)},
    )
    if not team_check.first():
        raise HTTPException(404, "الفريق غير موجود")

    result = await db.execute(
        text("DELETE FROM team_memberships WHERE team_id = :tid AND user_id = :uid"),
        {"tid": str(team_id), "uid": str(user_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "العضو غير موجود في الفريق")
    await db.commit()
