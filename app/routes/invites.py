from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timezone

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.config import get_settings
from app.database import get_db
from app.models.invite import InviteCreate, InviteRead
from app.services.membership_service import require_owner, verify_membership
from app.services.permission_service import require_permission
from app.services.usage_service import get_tenant_plan_limits, get_seats_count
from app.services.audit_service import log_audit
from app.services.email_service import send_invite_email
from app.security import get_client_ip

settings = get_settings()

router = APIRouter(prefix="/invites", tags=["Invites"])


# ── Send Invite ──
@router.post("", response_model=InviteRead, status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user to the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    body.email = body.email.lower().strip()
    await require_permission(db, tenant_id, user.id, "members.manage")
    if body.role.value == "admin":
        await require_owner(db, tenant_id, user.id)

    # ── Plan limit: seats_max (centralized) ──
    from app.services.feature_service import check_seats_limit
    await check_seats_limit(db, tenant_id)

    # Best-effort duplicate membership check.
    # Some deployments restrict direct reads from auth.users, so we avoid
    # failing invite creation if that catalog is not accessible here.
    try:
        existing_member = await db.execute(
            text("""
                SELECT 1
                FROM memberships m
                WHERE m.tenant_id = :tid
                  AND EXISTS (
                      SELECT 1
                      FROM auth.users au
                      WHERE au.id = m.user_id
                        AND lower(au.email) = lower(:email)
                  )
            """),
            {"tid": str(tenant_id), "email": body.email},
        )
        if existing_member.first():
            raise HTTPException(status_code=409, detail="User is already a member")
    except HTTPException:
        raise
    except Exception:
        pass

    # Check if already invited (pending)
    existing_invite = await db.execute(
        text("""
            SELECT 1 FROM invites
            WHERE tenant_id = :tid AND email = :email AND status = 'pending'
        """),
        {"tid": str(tenant_id), "email": body.email},
    )
    if existing_invite.first():
        raise HTTPException(status_code=409, detail="Invite already pending for this email")

    # Create invite
    result = await db.execute(
        text("""
            INSERT INTO invites (tenant_id, email, role, invited_by)
            VALUES (:tid, :email, :role, :invited_by)
            RETURNING id, tenant_id, email, role, status, invited_by, token, expires_at, accepted_at, created_at
        """),
        {
            "tid": str(tenant_id),
            "email": body.email,
            "role": body.role.value,
            "invited_by": str(user.id),
        },
    )
    invite = result.mappings().first()
    if not invite:
        raise HTTPException(status_code=500, detail="Failed to create invite")

    invite_read = InviteRead(**dict(invite))

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.invite",
        resource_type="invite",
        resource_id=str(invite["id"]),
        metadata={"email": body.email, "role": body.role.value},
        ip_address=get_client_ip(request),
    )
    invite_link = f"{settings.app_url}/invites/accept/{invite['token']}"
    tenant_name = "Your workspace"
    inviter_name = user.email or "A team member"

    try:
        tenant_result = await db.execute(
            text("SELECT name FROM tenants WHERE id = :tid"),
            {"tid": str(tenant_id)},
        )
        tenant_row = tenant_result.mappings().first()
        if tenant_row and tenant_row.get("name"):
            tenant_name = tenant_row["name"]

        profile_result = await db.execute(
            text("SELECT full_name FROM profiles WHERE id = :uid"),
            {"uid": str(user.id)},
        )
        profile_row = profile_result.mappings().first()
        if profile_row and profile_row.get("full_name"):
            inviter_name = profile_row["full_name"]
    except Exception:
        pass

    await db.commit()
    background_tasks.add_task(send_invite_email, body.email, invite_link, tenant_name, inviter_name)

    return invite_read


# ── List Invites ──
@router.get("", response_model=list[InviteRead])
async def list_invites(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all invites for the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.view")

    result = await db.execute(
        text("""
            SELECT id, tenant_id, email, role, status, invited_by, expires_at, accepted_at, created_at
            FROM invites
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
        """),
        {"tid": str(tenant_id)},
    )
    rows = result.mappings().all()
    return [InviteRead(**dict(r)) for r in rows]


# ── Accept Invite (by token — no auth required for lookup, auth required for accept) ──
@router.post("/accept/{token}")
async def accept_invite(
    token: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept an invite using the token. User must be authenticated."""
    # Find the invite
    result = await db.execute(
        text("""
            SELECT id, tenant_id, email, role, status, expires_at, invited_by, created_at
            FROM invites
            WHERE token = :token
            FOR UPDATE
        """),
        {"token": token},
    )
    invite = result.mappings().first()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Invite is {invite['status']}")

    if invite["role"] == "owner":
        # Legacy owner invitations may exist.  They must not silently become a
        # privileged account; ownership transfer has its own controlled flow.
        await db.execute(
            text("UPDATE invites SET status = 'revoked' WHERE id = :id"),
            {"id": str(invite["id"])}
        )
        await db.commit()
        raise HTTPException(status_code=409, detail="لا يمكن قبول دعوة مالك؛ اطلب نقل ملكية صريحاً من المالك الحالي")

    if invite["expires_at"] < datetime.now(timezone.utc):
        # Mark as expired
        await db.execute(
            text("UPDATE invites SET status = 'expired' WHERE id = :id"),
            {"id": str(invite["id"])},
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")

    # Verify email matches (optional but recommended)
    if user.email and user.email.lower() != invite["email"].lower():
        raise HTTPException(
            status_code=403,
            detail="This invite was sent to a different email address",
        )

    # Check if already a member
    existing = await db.execute(
        text("""
            SELECT 1 FROM memberships
            WHERE tenant_id = :tid AND user_id = :uid
        """),
        {"tid": str(invite["tenant_id"]), "uid": str(user.id)},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="You are already a member of this tenant")

    # Create membership with invited_by and accepted_at tracking. The row lock
    # above makes this transition single-use even when two tabs accept at once.
    membership_insert = await db.execute(
        text("""
            INSERT INTO memberships (tenant_id, user_id, role, status, invited_by, invited_at, accepted_at)
            VALUES (:tid, :uid, :role, 'active', :invited_by, :invited_at, now())
            ON CONFLICT (tenant_id, user_id) DO NOTHING
        """),
        {
            "tid": str(invite["tenant_id"]),
            "uid": str(user.id),
            "role": invite["role"],
            "invited_by": str(invite.get("invited_by")) if invite.get("invited_by") else None,
            "invited_at": invite.get("created_at"),
        },
    )

    if membership_insert.rowcount == 0:
        raise HTTPException(status_code=409, detail="You are already a member of this tenant")

    # Assign the matching RBAC role from roles table
    role_map = {"owner": "Admin", "admin": "Admin", "member": "Member", "viewer": "Viewer"}
    rbac_role_name = role_map.get(invite["role"], "Member")
    role_result = await db.execute(
        text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name LIMIT 1"),
        {"tid": str(invite["tenant_id"]), "name": rbac_role_name},
    )
    rbac_role = role_result.scalar()
    if rbac_role:
        await db.execute(
            text("""
                INSERT INTO membership_roles (tenant_id, user_id, role_id)
                VALUES (:tid, :uid, :rid)
                ON CONFLICT DO NOTHING
            """),
            {"tid": str(invite["tenant_id"]), "uid": str(user.id), "rid": str(rbac_role)},
        )

    # Mark invite as accepted
    await db.execute(
        text("UPDATE invites SET status = 'accepted', accepted_at = now() WHERE id = :id"),
        {"id": str(invite["id"])},
    )

    await log_audit(
        db,
        tenant_id=invite["tenant_id"],
        actor_user_id=user.id,
        action="member.join",
        resource_type="invite",
        resource_id=str(invite["id"]),
        metadata={"role": invite["role"], "email": invite["email"]},
    )
    await db.commit()

    return {
        "message": "تم قبول الدعوة بنجاح",
        "tenant_id": str(invite["tenant_id"]),
        "role": invite["role"],
    }


# ── Revoke Invite ──
@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a pending invite."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")

    result = await db.execute(
        text("""
            UPDATE invites SET status = 'revoked'
            WHERE id = :id AND tenant_id = :tid AND status = 'pending'
        """),
        {"id": str(invite_id), "tid": str(tenant_id)},
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Pending invite not found")

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="invite.revoke",
        resource_type="invite",
        resource_id=str(invite_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()
