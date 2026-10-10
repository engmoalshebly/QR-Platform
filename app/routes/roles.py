"""
Roles & Permissions CRUD API.
Manages custom roles per tenant and lists system permissions.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from pydantic import BaseModel

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.services.membership_service import require_owner, verify_membership
from app.services.audit_service import log_audit
from app.security import get_client_ip

router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


# ── Models ──

class PermissionRead(BaseModel):
    key: str
    description: Optional[str] = None


class RoleRead(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    is_system_role: bool
    created_at: str
    permissions: Optional[list[str]] = None


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[str]] = None


# ── Current User Permissions ──
@router.get("/me/permissions", response_model=list[str])
async def get_my_permissions(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all permission keys for the current user in the current tenant."""
    from app.services.permission_service import get_user_permissions
    tenant_id = get_tenant_id_from_header(request)
    await verify_membership(db, tenant_id, user.id)
    return await get_user_permissions(db, tenant_id, user.id)


async def _require_role_admin(db: AsyncSession, tenant_id: UUID, user_id) -> None:
    """Only a tenant owner can change the authorization graph.

    `roles.manage` is deliberately not sufficient: otherwise a limited role
    manager can create a privileged role and assign it to themselves.
    Platform staff use the dedicated `/platform/tenants/{id}/roles` endpoints.
    """
    await require_owner(db, tenant_id, user_id)


# ── List All System Permissions ──
@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available permissions for the active workspace administrator."""
    tenant_id = get_tenant_id_from_header(request)
    await _require_role_admin(db, tenant_id, user.id)

    result = await db.execute(
        text("SELECT key, description FROM permissions ORDER BY key")
    )
    rows = result.mappings().all()
    return [PermissionRead(**dict(r)) for r in rows]


# ── List Roles in Tenant ──
@router.get("", response_model=list[RoleRead])
async def list_roles(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List roles in the current tenant (names only for org members; full for platform staff)."""
    tenant_id = get_tenant_id_from_header(request)
    await verify_membership(db, tenant_id, user.id)

    role_admin = (await verify_membership(db, tenant_id, user.id))["role"] == "owner"
    if role_admin:
        result = await db.execute(
            text("""
                SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                       r.created_at::text,
                       ARRAY(
                           SELECT rp.permission_key FROM role_permissions rp WHERE rp.role_id = r.id
                       ) AS permissions
                FROM roles r
                WHERE r.tenant_id = :tid
                ORDER BY r.is_system_role DESC, r.name
            """),
            {"tid": str(tenant_id)},
        )
    else:
        result = await db.execute(
            text("""
                SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                       r.created_at::text, NULL::text[] AS permissions
                FROM roles r
                WHERE r.tenant_id = :tid
                ORDER BY r.is_system_role DESC, r.name
            """),
            {"tid": str(tenant_id)},
        )
    rows = result.mappings().all()
    return [RoleRead(**dict(r)) for r in rows]


# ── Get Role Details ──
@router.get("/{role_id}", response_model=RoleRead)
async def get_role(
    role_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get role details. Permission list visible to platform staff only."""
    tenant_id = get_tenant_id_from_header(request)
    await verify_membership(db, tenant_id, user.id)
    role_admin = (await verify_membership(db, tenant_id, user.id))["role"] == "owner"

    if role_admin:
        result = await db.execute(
            text("""
                SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                       r.created_at::text,
                       ARRAY(
                           SELECT rp.permission_key FROM role_permissions rp WHERE rp.role_id = r.id
                       ) AS permissions
                FROM roles r
                WHERE r.id = :rid AND r.tenant_id = :tid
            """),
            {"rid": str(role_id), "tid": str(tenant_id)},
        )
    else:
        result = await db.execute(
            text("""
                SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                       r.created_at::text, NULL::text[] AS permissions
                FROM roles r
                WHERE r.id = :rid AND r.tenant_id = :tid
            """),
            {"rid": str(role_id), "tid": str(tenant_id)},
        )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="الدور غير موجود")
    return RoleRead(**dict(row))


# ── Create Custom Role ──
@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a custom role. Self-service for the tenant owner; platform staff
    have the parallel /platform/tenants/{id}/roles for support/override cases."""
    tenant_id = get_tenant_id_from_header(request)
    await _require_role_admin(db, tenant_id, user.id)

    # Check name uniqueness within tenant
    existing = await db.execute(
        text("SELECT 1 FROM roles WHERE tenant_id = :tid AND name = :name"),
        {"tid": str(tenant_id), "name": body.name},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="يوجد دور بنفس الاسم")

    # Validate permissions exist
    if body.permissions:
        valid = await db.execute(
            text("SELECT key FROM permissions WHERE key = ANY(:keys)"),
            {"keys": body.permissions},
        )
        valid_keys = {r[0] for r in valid.fetchall()}
        invalid = set(body.permissions) - valid_keys
        if invalid:
            raise HTTPException(status_code=400, detail=f"صلاحيات غير موجودة: {', '.join(invalid)}")

    # Create role
    result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, :name, :desc, false)
            RETURNING id, tenant_id, name, description, is_system_role, created_at::text
        """),
        {"tid": str(tenant_id), "name": body.name, "desc": body.description},
    )
    role = result.mappings().first()

    # Assign permissions
    if body.permissions:
        for pkey in body.permissions:
            await db.execute(
                text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:rid, :pkey)"),
                {"rid": str(role["id"]), "pkey": pkey},
            )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="role.create", resource_type="role", resource_id=str(role["id"]),
        metadata={"name": body.name, "permissions": body.permissions},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return RoleRead(**dict(role), permissions=body.permissions)


# ── Update Role ──
@router.patch("/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: UUID,
    body: RoleUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a role. Self-service for the tenant owner; platform staff
    have the parallel /platform/tenants/{id}/roles/{role_id} for support/override cases."""
    tenant_id = get_tenant_id_from_header(request)
    await _require_role_admin(db, tenant_id, user.id)

    # Check role exists and is not system role
    existing = await db.execute(
        text("SELECT id, is_system_role FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": str(role_id), "tid": str(tenant_id)},
    )
    role_row = existing.mappings().first()
    if not role_row:
        raise HTTPException(status_code=404, detail="الدور غير موجود")
    is_system = role_row["is_system_role"]

    # System roles are part of the authorization baseline and must stay stable.
    if is_system:
        raise HTTPException(status_code=403, detail="لا يمكن تعديل الأدوار النظامية")

    updates = body.model_dump(exclude_unset=True, exclude={"permissions"})
    if updates:
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["rid"] = str(role_id)
        await db.execute(
            text(f"UPDATE roles SET {set_clauses} WHERE id = :rid"),
            updates,
        )

    # Update permissions if provided
    if body.permissions is not None:
        # Validate
        if body.permissions:
            valid = await db.execute(
                text("SELECT key FROM permissions WHERE key = ANY(:keys)"),
                {"keys": body.permissions},
            )
            valid_keys = {r[0] for r in valid.fetchall()}
            invalid = set(body.permissions) - valid_keys
            if invalid:
                raise HTTPException(status_code=400, detail=f"صلاحيات غير موجودة: {', '.join(invalid)}")

        # Replace all permissions
        await db.execute(
            text("DELETE FROM role_permissions WHERE role_id = :rid"),
            {"rid": str(role_id)},
        )
        for pkey in body.permissions:
            await db.execute(
                text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:rid, :pkey)"),
                {"rid": str(role_id), "pkey": pkey},
            )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="role.update", resource_type="role", resource_id=str(role_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()

    # Return updated role
    result = await db.execute(
        text("""
            SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                   r.created_at::text,
                   ARRAY(SELECT rp.permission_key FROM role_permissions rp WHERE rp.role_id = r.id) AS permissions
            FROM roles r WHERE r.id = :rid
        """),
        {"rid": str(role_id)},
    )
    row = result.mappings().first()
    return RoleRead(**dict(row))


# ── Delete Role ──
@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom role. Self-service for the tenant owner."""
    tenant_id = get_tenant_id_from_header(request)
    await _require_role_admin(db, tenant_id, user.id)

    existing = await db.execute(
        text("SELECT id, is_system_role FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": str(role_id), "tid": str(tenant_id)},
    )
    role_row = existing.mappings().first()
    if not role_row:
        raise HTTPException(status_code=404, detail="الدور غير موجود")
    if role_row["is_system_role"]:
        raise HTTPException(status_code=403, detail="لا يمكن حذف الأدوار النظامية")

    # Check if role is assigned to any member
    assigned = await db.execute(
        text("SELECT 1 FROM membership_roles WHERE role_id = :rid LIMIT 1"),
        {"rid": str(role_id)},
    )
    if assigned.first():
        raise HTTPException(status_code=409, detail="لا يمكن حذف دور مُسند لأعضاء. قم بإزالة الدور من الأعضاء أولاً.")

    await db.execute(
        text("DELETE FROM roles WHERE id = :rid"),
        {"rid": str(role_id)},
    )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="role.delete", resource_type="role", resource_id=str(role_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()


# ── Assign Role to Member ──
@router.post("/assign")
async def assign_role_to_member(
    request: Request,
    member_id: UUID = None,
    role_id: UUID = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a role to a member in the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    # Assigning a role can elevate access, so it is governed by role
    # administration rather than the broader member-management capability.
    await _require_role_admin(db, tenant_id, user.id)

    # Verify role belongs to tenant
    role_check = await db.execute(
        text("SELECT 1 FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": str(role_id), "tid": str(tenant_id)},
    )
    if not role_check.first():
        raise HTTPException(status_code=404, detail="الدور غير موجود في هذا المستأجر")

    # Verify member exists
    member_check = await db.execute(
        text("SELECT 1 FROM memberships WHERE tenant_id = :tid AND user_id = :uid AND status = 'active'"),
        {"tid": str(tenant_id), "uid": str(member_id)},
    )
    if not member_check.first():
        raise HTTPException(status_code=404, detail="العضو غير موجود أو غير نشط")

    await db.execute(
        text("""
            INSERT INTO membership_roles (tenant_id, user_id, role_id)
            VALUES (:tid, :uid, :rid)
            ON CONFLICT DO NOTHING
        """),
        {"tid": str(tenant_id), "uid": str(member_id), "rid": str(role_id)},
    )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="role.assign", resource_type="membership_role",
        resource_id=f"{member_id}:{role_id}",
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"message": "تم إسناد الدور بنجاح"}


# ── Unassign Role from Member ──
@router.post("/unassign")
async def unassign_role_from_member(
    request: Request,
    member_id: UUID = None,
    role_id: UUID = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a role from a member in the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await _require_role_admin(db, tenant_id, user.id)

    result = await db.execute(
        text("DELETE FROM membership_roles WHERE tenant_id = :tid AND user_id = :uid AND role_id = :rid"),
        {"tid": str(tenant_id), "uid": str(member_id), "rid": str(role_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="الدور غير مُسند لهذا العضو")

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="role.unassign", resource_type="membership_role",
        resource_id=f"{member_id}:{role_id}",
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"message": "تم إزالة الدور بنجاح"}
