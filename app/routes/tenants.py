import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel as PydanticBaseModel, EmailStr, Field

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db, get_supabase_admin, get_privileged_db
from app.models.tenant import TenantCreate, TenantRead, TenantUpdate, TenantSettingRead, TenantSettingWrite, TenantDomainRead, TenantDomainCreate
import json
import logging

logger = logging.getLogger(__name__)
from app.models.membership import MembershipRead, MemberWithProfile, MembershipUpdate
from app.services.membership_service import verify_membership, require_owner
from app.services.audit_service import log_audit
from app.services.provisioning_service import provision_tenant_manual
from app.services.permission_service import require_permission
from app.services.email_service import send_invite_email, send_temporary_access_email
from app.config import get_settings
from app.security import get_client_ip

router = APIRouter(prefix="/tenants", tags=["Tenants"])
settings = get_settings()


async def _locked_member(db: AsyncSession, tenant_id: UUID, member_id: UUID) -> dict:
    """Load a membership under a row lock before a privilege-changing action."""
    result = await db.execute(
        text("""
            SELECT tenant_id, user_id, role, status, created_at, updated_at
            FROM memberships
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            FOR UPDATE
        """),
        {"tenant_id": str(tenant_id), "user_id": str(member_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")
    return dict(row)


async def _active_owner_count_for_update(db: AsyncSession, tenant_id: UUID) -> int:
    """Lock owners so concurrent demotions/removals cannot orphan a tenant."""
    result = await db.execute(
        text("""
            SELECT user_id
            FROM memberships
            WHERE tenant_id = :tenant_id AND role = 'owner' AND status = 'active'
            FOR UPDATE
        """),
        {"tenant_id": str(tenant_id)},
    )
    return len(result.all())


async def _require_member_change_authority(
    db: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID,
    target: dict,
    requested_role: str | None = None,
    requested_status: str | None = None,
) -> None:
    """Keep owner/admin lifecycle controls non-delegable."""
    is_sensitive = (
        target["role"] in {"owner", "admin"}
        or requested_role in {"owner", "admin"}
        or (target["role"] == "owner" and requested_status not in {None, "active"})
    )
    if is_sensitive:
        await require_owner(db, tenant_id, actor_id)


async def _locked_members(
    db: AsyncSession,
    tenant_id: UUID,
    member_ids: list[UUID],
) -> list[dict]:
    """Lock a deterministic set of members to make bulk actions race-safe."""
    unique_member_ids = sorted(set(member_ids), key=str)
    if not unique_member_ids:
        raise HTTPException(status_code=400, detail="يجب تحديد عضو واحد على الأقل")
    members = []
    for member_id in unique_member_ids:
        members.append(await _locked_member(db, tenant_id, member_id))
    return members


async def _validate_member_batch_change(
    db: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID,
    targets: list[dict],
    *,
    requested_role: str | None = None,
    requested_status: str | None = None,
    removing: bool = False,
) -> None:
    """Apply the same privileged-member and owner-invariant rules in bulk."""
    if any(UUID(str(target["user_id"])) == actor_id for target in targets):
        raise HTTPException(status_code=400, detail="لا يمكن تعديل أو إزالة حسابك من إجراء جماعي")

    sensitive = any(
        target["role"] in {"owner", "admin"}
        or requested_role in {"owner", "admin"}
        or (target["role"] == "owner" and requested_status not in {None, "active"})
        for target in targets
    )
    if sensitive:
        await require_owner(db, tenant_id, actor_id)

    losing_owners = sum(
        1
        for target in targets
        if target["role"] == "owner"
        and target["status"] == "active"
        and (
            removing
            or requested_role not in {None, "owner"}
            or requested_status not in {None, "active"}
        )
    )
    if losing_owners and await _active_owner_count_for_update(db, tenant_id) <= losing_owners:
        raise HTTPException(
            status_code=409,
            detail="لا يمكن إزالة أو تخفيض آخر مالك للمؤسسة. انقل الملكية أولاً.",
        )


async def _sync_base_membership_roles(
    db: AsyncSession,
    tenant_id: UUID,
    member_ids: list[UUID],
    base_role: str,
) -> None:
    """Keep the legacy membership role and RBAC assignment transactionally aligned."""
    role_name = {"owner": "Admin", "admin": "Admin", "member": "Member", "viewer": "Viewer"}.get(
        base_role,
        "Member",
    )
    role_result = await db.execute(
        text("SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = :name LIMIT 1"),
        {"tenant_id": str(tenant_id), "name": role_name},
    )
    role_id = role_result.scalar()
    if not role_id:
        raise HTTPException(status_code=500, detail="أدوار المؤسسة غير مهيأة بشكل صحيح")

    for member_id in member_ids:
        await db.execute(
            text("DELETE FROM membership_roles WHERE tenant_id = :tenant_id AND user_id = :user_id"),
            {"tenant_id": str(tenant_id), "user_id": str(member_id)},
        )
        await db.execute(
            text("""
                INSERT INTO membership_roles (tenant_id, user_id, role_id)
                VALUES (:tenant_id, :user_id, :role_id)
                ON CONFLICT DO NOTHING
            """),
            {"tenant_id": str(tenant_id), "user_id": str(member_id), "role_id": str(role_id)},
        )


class BulkMemberUpdateRequest(PydanticBaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=100)
    role: Literal["admin", "member", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None


class BulkMemberDeleteRequest(PydanticBaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=100)


# ── Create Tenant ──
@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Create a new tenant and assign the creator as owner."""
    # Check slug uniqueness
    existing = await db.execute(
        text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": body.slug},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="Slug already taken")

    # Create tenant
    result = await db.execute(
        text("""
            INSERT INTO tenants (slug, name, created_by, metadata)
            VALUES (:slug, :name, :created_by, CAST(:metadata AS jsonb))
            RETURNING id, slug, name, created_by, status, plan, metadata, expires_at, created_at, updated_at
        """),
        {
            "slug": body.slug,
            "name": body.name,
            "created_by": str(user.id),
            "metadata": json.dumps(body.metadata or {}, default=str),
        },
    )
    tenant = result.mappings().first()

    # Create owner membership
    await db.execute(
        text("""
            INSERT INTO memberships (tenant_id, user_id, role, status)
            VALUES (:tenant_id, :user_id, 'owner', 'active')
        """),
        {"tenant_id": str(tenant["id"]), "user_id": str(user.id)},
    )

    # Create free trial subscription
    await db.execute(
        text("""
            INSERT INTO subscriptions (tenant_id, plan_id, status, current_period_start, current_period_end, trial_ends_at)
            VALUES (
                :tenant_id,
                (SELECT id FROM plans WHERE code = 'starter'),
                'active',
                now(),
                now() + INTERVAL '30 days',
                now() + INTERVAL '14 days'
            )
        """),
        {"tenant_id": str(tenant["id"])},
    )

    # Provision: create default roles, permissions, settings
    await provision_tenant_manual(db, tenant["id"], user.id)

    # Audit log
    await log_audit(
        db,
        tenant_id=tenant["id"],
        actor_user_id=user.id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=str(tenant["id"]),
        ip_address=get_client_ip(request),
    )

    await db.commit()
    return TenantRead(**dict(tenant))


# ── List My Tenants ──
@router.get("", response_model=list[TenantRead])
async def list_my_tenants(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List all tenants the current user belongs to."""
    result = await db.execute(
        text("""
            SELECT t.id, t.slug, t.name, t.created_by, t.status, t.plan, t.metadata, t.expires_at,
                   t.created_at, t.updated_at
            FROM tenants t
            JOIN memberships m ON m.tenant_id = t.id
            WHERE m.user_id = :user_id AND m.status = 'active'
            ORDER BY t.created_at DESC
        """),
        {"user_id": str(user.id)},
    )
    rows = result.mappings().all()
    return [TenantRead(**dict(r)) for r in rows]


# ── Get Tenant Details ──
@router.get("/current", response_model=TenantRead)
async def get_current_tenant(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of the current tenant (from X-Tenant-ID header)."""
    tenant_id = get_tenant_id_from_header(request)
    await verify_membership(db, tenant_id, user.id)

    result = await db.execute(
        text("SELECT id, slug, name, created_by, status, plan, metadata, expires_at, created_at, updated_at FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantRead(**dict(row))


# ── Update Tenant ──
@router.patch("/current", response_model=TenantRead)
async def update_tenant(
    body: TenantUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update tenant details."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.manage")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(tenant_id)

    result = await db.execute(
        text(f"""
            UPDATE tenants SET {set_clauses}, updated_at = now()
            WHERE id = :id
            RETURNING id, slug, name, created_by, status, plan, metadata, expires_at, created_at, updated_at
        """),
        updates,
    )
    row = result.mappings().first()

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="tenant.update",
        resource_type="tenant",
        resource_id=str(tenant_id),
        metadata=updates,
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return TenantRead(**dict(row))


# ── List Members ──
@router.get("/current/members", response_model=list[MemberWithProfile])
async def list_members(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all members of the current tenant with their profiles."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.view")

    result = await db.execute(
        text("""
            SELECT m.tenant_id, m.user_id, m.role, m.status, m.created_at,
                   p.full_name, p.avatar_url, au.email
            FROM memberships m
            JOIN profiles p ON p.id = m.user_id
            LEFT JOIN auth.users au ON au.id = m.user_id
            WHERE m.tenant_id = :tenant_id
            ORDER BY m.created_at
        """),
        {"tenant_id": str(tenant_id)},
    )
    rows = result.mappings().all()
    return [MemberWithProfile(**dict(r)) for r in rows]


# ── Bulk Member Changes ──
@router.patch("/current/members/bulk")
async def bulk_update_members(
    body: BulkMemberUpdateRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a safe base-role or status update to a bounded member set."""
    if body.role is None and body.status is None:
        raise HTTPException(status_code=400, detail="يلزم إرسال الدور أو الحالة")

    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")
    targets = await _locked_members(db, tenant_id, body.user_ids)
    await _validate_member_batch_change(
        db,
        tenant_id,
        user.id,
        targets,
        requested_role=body.role,
        requested_status=body.status,
    )

    set_clauses = []
    update_values = {"tenant_id": str(tenant_id)}
    if body.role is not None:
        set_clauses.append("role = :role")
        update_values["role"] = body.role
    if body.status is not None:
        set_clauses.append("status = :status")
        update_values["status"] = body.status
    statement = text(
        f"UPDATE memberships SET {', '.join(set_clauses)}, updated_at = now() "
        "WHERE tenant_id = :tenant_id AND user_id = :user_id"
    )
    for target in targets:
        await db.execute(statement, {**update_values, "user_id": str(target["user_id"])})

    if body.role is not None:
        await _sync_base_membership_roles(
            db,
            tenant_id,
            [UUID(str(target["user_id"])) for target in targets],
            body.role,
        )

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.bulk_update",
        resource_type="membership",
        metadata={
            "member_ids": [str(target["user_id"]) for target in targets],
            "role": body.role,
            "status": body.status,
        },
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"updated": len(targets)}


@router.post("/current/members/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_remove_members(
    body: BulkMemberDeleteRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a bounded member set while preserving tenant ownership."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")
    targets = await _locked_members(db, tenant_id, body.user_ids)
    await _validate_member_batch_change(
        db,
        tenant_id,
        user.id,
        targets,
        removing=True,
    )

    for target in targets:
        await db.execute(
            text("DELETE FROM memberships WHERE tenant_id = :tenant_id AND user_id = :user_id"),
            {"tenant_id": str(tenant_id), "user_id": str(target["user_id"])},
        )

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.bulk_remove",
        resource_type="membership",
        metadata={"member_ids": [str(target["user_id"]) for target in targets]},
        ip_address=get_client_ip(request),
    )
    await db.commit()


@router.post("/current/members/{member_id}/transfer-ownership", response_model=MembershipRead)
async def transfer_ownership(
    member_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Atomically promote an active member and demote the current owner to admin."""
    if member_id == user.id:
        raise HTTPException(status_code=400, detail="لا يمكن نقل الملكية إلى الحساب نفسه")

    tenant_id = get_tenant_id_from_header(request)
    await require_owner(db, tenant_id, user.id)
    locked = await _locked_members(db, tenant_id, [user.id, member_id])
    members_by_id = {str(member["user_id"]): member for member in locked}
    current_owner = members_by_id[str(user.id)]
    target = members_by_id[str(member_id)]
    if current_owner["role"] != "owner" or current_owner["status"] != "active":
        raise HTTPException(status_code=403, detail="يلزم أن يكون المالك الحالي نشطاً")
    if target["status"] != "active":
        raise HTTPException(status_code=409, detail="يجب تفعيل العضو قبل نقل الملكية")

    await db.execute(
        text("""
            UPDATE memberships SET role = 'owner', updated_at = now()
            WHERE tenant_id = :tenant_id AND user_id = :user_id
        """),
        {"tenant_id": str(tenant_id), "user_id": str(member_id)},
    )
    await db.execute(
        text("""
            UPDATE memberships SET role = 'admin', updated_at = now()
            WHERE tenant_id = :tenant_id AND user_id = :user_id
        """),
        {"tenant_id": str(tenant_id), "user_id": str(user.id)},
    )
    await _sync_base_membership_roles(db, tenant_id, [member_id, user.id], "admin")

    result = await db.execute(
        text("""
            SELECT tenant_id, user_id, role, status, created_at, updated_at
            FROM memberships
            WHERE tenant_id = :tenant_id AND user_id = :user_id
        """),
        {"tenant_id": str(tenant_id), "user_id": str(member_id)},
    )
    row = result.mappings().first()
    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.ownership_transfer",
        resource_type="membership",
        resource_id=str(member_id),
        old_values={"former_owner_id": str(user.id), "target_role": target["role"]},
        new_values={"former_owner_role": "admin", "target_role": "owner"},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return MembershipRead(**dict(row))


# ── Update Member Role ──
@router.patch("/current/members/{member_id}", response_model=MembershipRead)
async def update_member(
    member_id: UUID,
    body: MembershipUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role or status. Requires members.manage permission."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")

    # Cannot change own role or disable the active account through this route.
    if member_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    target = await _locked_member(db, tenant_id, member_id)
    requested_role = updates.get("role")
    requested_status = updates.get("status")
    if requested_role is not None:
        requested_role = getattr(requested_role, "value", requested_role)
        updates["role"] = requested_role
        if requested_role == "owner":
            raise HTTPException(
                status_code=400,
                detail="استخدم مسار نقل الملكية الصريح بدلاً من ترقية عضو إلى مالك",
            )
    if requested_status is not None:
        requested_status = getattr(requested_status, "value", requested_status)
        updates["status"] = requested_status

    await _require_member_change_authority(
        db,
        tenant_id,
        user.id,
        target,
        requested_role=requested_role,
        requested_status=requested_status,
    )

    removes_active_owner = (
        target["role"] == "owner"
        and target["status"] == "active"
        and (requested_role not in {None, "owner"} or requested_status not in {None, "active"})
    )
    if removes_active_owner and await _active_owner_count_for_update(db, tenant_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="لا يمكن تعطيل أو تخفيض آخر مالك للمؤسسة. انقل الملكية أولاً.",
        )

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["tenant_id"] = str(tenant_id)
    updates["user_id"] = str(member_id)

    result = await db.execute(
        text(f"""
            UPDATE memberships SET {set_clauses}, updated_at = now()
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            RETURNING tenant_id, user_id, role, status, created_at, updated_at
        """),
        updates,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    if "role" in updates:
        await _sync_base_membership_roles(db, tenant_id, [member_id], updates["role"])

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.update",
        resource_type="membership",
        resource_id=str(member_id),
        old_values={"role": target["role"], "status": target["status"]},
        new_values={"role": row["role"], "status": row["status"]},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return MembershipRead(**dict(row))


# ── Invite Member (legacy endpoint retained without password handling) ──
class CreateMemberRequest(PydanticBaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=120)
    role: str = "member"


class MemberInviteResponse(PydanticBaseModel):
    message: str
    invite_id: UUID
    email: EmailStr
    role: str
    status: str
    expires_at: datetime


class DirectMemberCreateRequest(PydanticBaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=120)
    temporary_password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str = "member"


@router.post("/current/members/direct", response_model=MemberWithProfile, status_code=status.HTTP_201_CREATED)
async def add_existing_member_directly(
    body: DirectMemberCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an existing account, or create one with emailed temporary credentials."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="الدور غير صالح")
    if body.role == "admin":
        await require_owner(db, tenant_id, user.id)

    from app.services.feature_service import check_seats_limit
    await check_seats_limit(db, tenant_id)
    email = str(body.email).lower().strip()
    account_result = await db.execute(
        text("""
            SELECT u.id, u.email, u.email_confirmed_at, p.full_name, p.avatar_url
            FROM auth.users u
            LEFT JOIN profiles p ON p.id=u.id
            WHERE lower(u.email)=:email
            LIMIT 1
        """),
        {"email": email},
    )
    account = account_result.mappings().first()
    created_auth_user = False
    temporary_password = body.temporary_password
    if not account:
        full_name = body.full_name.strip()
        if len(full_name) < 2:
            raise HTTPException(status_code=422, detail="الاسم الكامل مطلوب لإنشاء حساب جديد")
        if not temporary_password:
            raise HTTPException(status_code=422, detail="أدخل كلمة مرور مؤقتة من 8 أحرف على الأقل")
        try:
            created = await asyncio.to_thread(
                get_supabase_admin().auth.admin.create_user,
                {
                    "email": email,
                    "password": temporary_password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": full_name, "temporary_password": True},
                },
            )
            created_user = getattr(created, "user", None)
            created_user_id = getattr(created_user, "id", None)
            if not created_user_id:
                raise RuntimeError("Identity provider did not return a user id")
            created_auth_user = True
            await db.execute(
                text("""
                    INSERT INTO profiles (id, full_name, email_verified_at)
                    VALUES (:uid, :name, now())
                    ON CONFLICT (id) DO UPDATE SET full_name=EXCLUDED.full_name
                """),
                {"uid": str(created_user_id), "name": full_name},
            )
            account = {
                "id": created_user_id,
                "email": email,
                "email_confirmed_at": datetime.now(timezone.utc),
                "full_name": full_name,
                "avatar_url": None,
            }
        except Exception as auth_error:
            logger.exception("Failed to create direct member identity for %s", email)
            raise HTTPException(status_code=502, detail="تعذر إنشاء حساب المستخدم في بوابة الهوية") from auth_error
    elif not account["email_confirmed_at"]:
        raise HTTPException(status_code=409, detail="يجب على المستخدم تأكيد بريده قبل إضافته مباشرة.")

    existing = await db.execute(
        text("SELECT 1 FROM memberships WHERE tenant_id=:tid AND user_id=:uid"),
        {"tid": str(tenant_id), "uid": str(account["id"])},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="المستخدم عضو بالفعل في هذه المؤسسة")

    try:
        result = await db.execute(
            text("""
                INSERT INTO memberships (tenant_id,user_id,role,status,invited_by,accepted_at)
                VALUES (:tid,:uid,:role,'active',:actor,now())
                RETURNING tenant_id,user_id,role,status,created_at
            """),
            {"tid": str(tenant_id), "uid": str(account["id"]), "role": body.role, "actor": str(user.id)},
        )
        membership = dict(result.mappings().first())
        await _sync_base_membership_roles(db, tenant_id, [UUID(str(account["id"]))], body.role)
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="member.direct_add", resource_type="membership", resource_id=str(account["id"]),
            metadata={"email": email, "role": body.role, "account_created": created_auth_user},
            ip_address=get_client_ip(request),
        )
        tenant_name = (await db.execute(
            text("SELECT name FROM tenants WHERE id=:tid"), {"tid": str(tenant_id)}
        )).scalar_one()
        await db.commit()
    except Exception:
        await db.rollback()
        if created_auth_user:
            try:
                await asyncio.to_thread(get_supabase_admin().auth.admin.delete_user, str(account["id"]))
            except Exception:
                logger.exception("Failed to roll back identity %s", account["id"])
        raise

    if created_auth_user and temporary_password:
        background_tasks.add_task(
            send_temporary_access_email,
            email,
            account["full_name"] or "",
            tenant_name,
            temporary_password,
        )
    return MemberWithProfile(
        **membership, full_name=account["full_name"], avatar_url=account["avatar_url"], email=account["email"]
    )


@router.post("/current/members", response_model=MemberInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_member(
    body: CreateMemberRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite a member without exposing or choosing their password.

    This legacy URL is retained for existing clients, but follows the same
    email-bound acceptance flow as `/invites`.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")

    from app.services.feature_service import check_seats_limit
    await check_seats_limit(db, tenant_id)

    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="الدور غير صالح")
    if body.role == "admin":
        await require_owner(db, tenant_id, user.id)

    email = str(body.email).lower().strip()
    existing = await db.execute(
        text("""
            SELECT 1 FROM memberships m
            WHERE m.tenant_id = :tid
              AND EXISTS (
                  SELECT 1 FROM auth.users au
                  WHERE au.id = m.user_id AND lower(au.email) = :email
              )
        """),
        {"tid": str(tenant_id), "email": email},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="المستخدم عضو بالفعل في هذه المؤسسة")

    pending = await db.execute(
        text("""
            SELECT 1 FROM invites
            WHERE tenant_id = :tenant_id AND email = :email AND status = 'pending'
        """),
        {"tenant_id": str(tenant_id), "email": email},
    )
    if pending.first():
        raise HTTPException(status_code=409, detail="هناك دعوة معلقة لهذا البريد الإلكتروني")

    invite_result = await db.execute(
        text("""
            INSERT INTO invites (tenant_id, email, role, invited_by)
            VALUES (:tenant_id, :email, :role, :invited_by)
            RETURNING id, email, role, status, expires_at, token
        """),
        {
            "tenant_id": str(tenant_id),
            "email": email,
            "role": body.role,
            "invited_by": str(user.id),
        },
    )
    invite = invite_result.mappings().first()

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.invite",
        resource_type="invite",
        resource_id=str(invite["id"]),
        metadata={"email": email, "role": body.role, "legacy_member_endpoint": True},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    tenant_name_result = await db.execute(
        text("SELECT name FROM tenants WHERE id = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )
    tenant_name = tenant_name_result.scalar() or "Your workspace"
    background_tasks.add_task(
        send_invite_email,
        email,
        f"{settings.app_url}/invites/accept/{invite['token']}",
        tenant_name,
        user.email or "A team member",
    )

    return MemberInviteResponse(
        message="تم إرسال دعوة آمنة للعضو",
        invite_id=invite["id"],
        email=email,
        role=invite["role"],
        status=invite["status"],
        expires_at=invite["expires_at"],
    )


# ── Remove Member ──
@router.delete("/current/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the tenant. Requires members.manage permission."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "members.manage")

    if member_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    target = await _locked_member(db, tenant_id, member_id)
    await _require_member_change_authority(db, tenant_id, user.id, target)
    if target["role"] == "owner" and target["status"] == "active":
        if await _active_owner_count_for_update(db, tenant_id) <= 1:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إزالة آخر مالك للمؤسسة. انقل الملكية أولاً.",
            )

    result = await db.execute(
        text("DELETE FROM memberships WHERE tenant_id = :tenant_id AND user_id = :user_id"),
        {"tenant_id": str(tenant_id), "user_id": str(member_id)},
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Member not found")

    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="member.remove",
        resource_type="membership",
        resource_id=str(member_id),
        old_values={"role": target["role"], "status": target["status"]},
        ip_address=get_client_ip(request),
    )
    await db.commit()


# ── Tenant Settings ──
@router.get("/current/settings", response_model=list[TenantSettingRead])
async def list_settings(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.view")

    result = await db.execute(
        text("SELECT tenant_id, key, value, updated_at FROM tenant_settings WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
    rows = result.mappings().all()
    return [TenantSettingRead(**dict(r)) for r in rows]


@router.put("/current/settings", response_model=TenantSettingRead)
async def upsert_setting(
    body: TenantSettingWrite,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.manage")

    old_result = await db.execute(
        text("SELECT value FROM tenant_settings WHERE tenant_id = :tid AND key = :key"),
        {"tid": str(tenant_id), "key": body.key},
    )
    old_row = old_result.mappings().first()

    result = await db.execute(
        text("""
            INSERT INTO tenant_settings (tenant_id, key, value)
            VALUES (:tid, :key, CAST(:value AS jsonb))
            ON CONFLICT (tenant_id, key)
            DO UPDATE SET value = CAST(:value AS jsonb), updated_at = now()
            RETURNING tenant_id, key, value, updated_at
        """),
        {"tid": str(tenant_id), "key": body.key, "value": str(body.value)},
    )
    row = result.mappings().first()
    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="tenant.setting.upsert",
        resource_type="tenant_setting",
        resource_id=body.key,
        old_values={"value": old_row["value"]} if old_row else None,
        new_values={"value": row["value"]},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return TenantSettingRead(**dict(row))


# ══════════════════════════════════════════════
# TENANT DOMAINS
# ══════════════════════════════════════════════

@router.get("/current/domains", response_model=list[TenantDomainRead])
async def list_domains(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all custom domains for the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.view")

    result = await db.execute(
        text("SELECT id, tenant_id, domain, is_primary, is_verified, created_at FROM tenant_domains WHERE tenant_id = :tid ORDER BY is_primary DESC, created_at"),
        {"tid": str(tenant_id)},
    )
    rows = result.mappings().all()
    return [TenantDomainRead(**dict(r)) for r in rows]


@router.post("/current/domains", response_model=TenantDomainRead, status_code=status.HTTP_201_CREATED)
async def add_domain(
    body: TenantDomainCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a custom domain to the current tenant. Requires settings.manage."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.manage")

    # Check domain uniqueness
    existing = await db.execute(
        text("SELECT 1 FROM tenant_domains WHERE domain = :domain"),
        {"domain": body.domain},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="هذا النطاق مسجل مسبقاً")

    # If setting as primary, unset other primaries
    if body.is_primary:
        await db.execute(
            text("UPDATE tenant_domains SET is_primary = false WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

    result = await db.execute(
        text("""
            INSERT INTO tenant_domains (tenant_id, domain, is_primary)
            VALUES (:tid, :domain, :is_primary)
            RETURNING id, tenant_id, domain, is_primary, is_verified, created_at
        """),
        {"tid": str(tenant_id), "domain": body.domain, "is_primary": body.is_primary},
    )
    row = result.mappings().first()

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="domain.add", resource_type="tenant_domain",
        resource_id=str(row["id"]),
        metadata={"domain": body.domain},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return TenantDomainRead(**dict(row))


@router.delete("/current/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_domain(
    domain_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a custom domain from the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "settings.manage")

    result = await db.execute(
        text("DELETE FROM tenant_domains WHERE id = :did AND tenant_id = :tid RETURNING domain"),
        {"did": str(domain_id), "tid": str(tenant_id)},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="النطاق غير موجود")

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="domain.remove", resource_type="tenant_domain",
        resource_id=str(domain_id),
        metadata={"domain": row[0]},
        ip_address=get_client_ip(request),
    )
    await db.commit()


# ══════════════════════════════════════════════
# FEATURE FLAGS
# ══════════════════════════════════════════════

@router.get("/current/features", response_model=list)
async def list_feature_flags(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all feature flags for the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await verify_membership(db, tenant_id, user.id)

    result = await db.execute(
        text("SELECT tenant_id, flag_key, enabled, metadata, updated_at FROM feature_flags WHERE tenant_id = :tid ORDER BY flag_key"),
        {"tid": str(tenant_id)},
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.put("/current/features/{flag_key}")
async def toggle_feature_flag(
    flag_key: str,
    request: Request,
    enabled: bool = True,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a feature flag. Requires features.manage."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "features.manage")

    result = await db.execute(
        text("""
            INSERT INTO feature_flags (tenant_id, flag_key, enabled)
            VALUES (:tid, :key, :enabled)
            ON CONFLICT (tenant_id, flag_key)
            DO UPDATE SET enabled = :enabled, updated_at = now()
            RETURNING tenant_id, flag_key, enabled, metadata, updated_at
        """),
        {"tid": str(tenant_id), "key": flag_key, "enabled": enabled},
    )
    row = result.mappings().first()

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="feature.toggle", resource_type="feature_flag",
        resource_id=flag_key,
        metadata={"enabled": enabled},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return dict(row)
