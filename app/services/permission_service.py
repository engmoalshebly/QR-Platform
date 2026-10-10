"""
Permission checking service.
Central place to verify if a user has a specific permission in a tenant.
Supports both simple role-based checks and granular RBAC permission checks.
Resolves ui.* keys to legacy API keys automatically.
"""
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.services.permission_aliases import resolve_permission_keys


async def _direct_has_permission(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    permission_key: str,
) -> bool:
    result = await db.execute(
        text("SELECT public.user_has_permission(:tid, :uid, :pkey)"),
        {"tid": str(tenant_id), "uid": str(user_id), "pkey": permission_key},
    )
    return result.scalar() or False


async def has_permission(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    permission_key: str,
) -> bool:
    """
    Check if a user has a specific permission in a tenant.
    Owner and Admin roles automatically have all permissions.
    ui.* keys are resolved to their legacy equivalents and vice versa.
    A suspended, cancelled or deleted tenant grants no permissions at all.
    """
    tenant_active = await db.execute(
        text("SELECT 1 FROM tenants WHERE id = :tid AND status IN ('active', 'trial')"),
        {"tid": str(tenant_id)},
    )
    if not tenant_active.first():
        return False
    for key in resolve_permission_keys(permission_key):
        if await _direct_has_permission(db, tenant_id, user_id, key):
            return True
    # Defensive explicit-role fallback. This keeps the Team Manager contract
    # correct even when a legacy database function/cache is behind the RBAC
    # tables during migration.
    result = await db.execute(text("""
        SELECT 1 FROM memberships m
        JOIN membership_roles mr ON mr.tenant_id=m.tenant_id AND mr.user_id=m.user_id
        JOIN roles r ON r.id=mr.role_id AND r.name='team_manager'
        JOIN role_permissions rp ON rp.role_id=r.id
        WHERE m.tenant_id=:tid AND m.user_id=:uid AND m.status='active'
          AND rp.permission_key = ANY(:keys)
        LIMIT 1
    """), {"tid": str(tenant_id), "uid": str(user_id), "keys": resolve_permission_keys(permission_key)})
    if result.first():
        return True
    return False


async def require_permission(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    permission_key: str,
) -> None:
    """Raise 403 if user doesn't have the required permission."""
    allowed = await has_permission(db, tenant_id, user_id, permission_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"ليس لديك صلاحية: {permission_key}",
        )


async def require_any_permission(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    *permission_keys: str,
) -> None:
    """Raise 403 unless the user has at least one of the given permissions."""
    for key in permission_keys:
        if await has_permission(db, tenant_id, user_id, key):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"ليس لديك صلاحية: {permission_keys[0]}",
    )


async def get_user_permissions(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> list[str]:
    """Get all permissions a user has in a tenant."""
    result = await db.execute(
        text("SELECT public.get_user_permissions(:tid, :uid)"),
        {"tid": str(tenant_id), "uid": str(user_id)},
    )
    return [row[0] for row in result.fetchall()]


async def get_user_tenants_with_roles(
    db: AsyncSession,
    user_id: UUID,
) -> list[dict]:
    """Get all tenants a user belongs to with their role and status."""
    result = await db.execute(
        text("""
            SELECT t.id AS tenant_id, t.slug, t.name, t.status AS tenant_status,
                   t.plan, m.role, m.status AS membership_status,
                   COALESCE(t.workspace_type, 'institution') AS workspace_type,
                   CASE
                     WHEN t.workspace_type = 'organizer' THEN wl.institution_tenant_id
                     WHEN t.workspace_type = 'institution' THEN wl.organizer_tenant_id
                     ELSE NULL
                   END AS linked_tenant_id
            FROM memberships m
            JOIN tenants t ON t.id = m.tenant_id
            LEFT JOIN workspace_links wl
              ON (wl.organizer_tenant_id = t.id OR wl.institution_tenant_id = t.id)
             AND wl.status = 'active'
            WHERE m.user_id = :uid AND m.status = 'active'
            ORDER BY t.created_at DESC
        """),
        {"uid": str(user_id)},
    )
    return [dict(r) for r in result.mappings().all()]


# ══════════════════════════════════════════════════════════════
# Cooperative Authorization — Provider ↔ Client Event Access
# ══════════════════════════════════════════════════════════════

async def get_event_owner_tenant(
    db: AsyncSession,
    event_id: UUID,
) -> UUID | None:
    """Return the tenant_id that owns the event, or None if not found."""
    result = await db.execute(
        text("SELECT tenant_id FROM events WHERE id = :eid AND deleted_at IS NULL"),
        {"eid": str(event_id)},
    )
    row = result.first()
    return row[0] if row else None


async def check_event_access(
    db: AsyncSession,
    event_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    required_perm: str = "events.view",
) -> bool:
    """
    Check if a user can access an event through either:
      1. Owner path — user belongs to the event-owning tenant and has the permission.
      2. Provider path — user belongs to a provider tenant with an active
         event_operation for this event, and is either the project_manager
         or an operation member.
    """
    # ── Path 1: Owner tenant (standard) ──
    owner_check = await db.execute(
        text("SELECT 1 FROM events WHERE id = :eid AND tenant_id = :tid AND deleted_at IS NULL"),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    if owner_check.first():
        return await has_permission(db, tenant_id, user_id, required_perm)

    # ── Path 2: Provider tenant via event_operations ──
    if not await has_permission(db, tenant_id, user_id, required_perm):
        return False
    provider_check = await db.execute(
        text("""
            SELECT 1
            FROM event_operations o JOIN events e ON e.id=o.event_id AND e.deleted_at IS NULL
            LEFT JOIN event_operation_members om
                   ON om.operation_id = o.id AND om.user_id = :uid
            WHERE o.event_id = :eid
              AND o.provider_tenant_id = :tid
              AND o.status NOT IN ('completed', 'closed', 'cancelled')
              AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
            LIMIT 1
        """),
        {"eid": str(event_id), "tid": str(tenant_id), "uid": str(user_id)},
    )
    return provider_check.first() is not None


async def require_event_access(
    db: AsyncSession,
    event_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    required_perm: str = "events.view",
) -> None:
    """Raise 403 if the user cannot access the event."""
    allowed = await check_event_access(
        db, event_id, tenant_id, user_id, required_perm,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ليس لديك صلاحية للوصول إلى هذا الحفل",
        )


async def check_provider_event_access(
    db: AsyncSession,
    event_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    required_perm: str,
) -> bool:
    """Check team-only access to an event assigned to an active operation.

    Gates and check-in are operational controls. They must never be reachable
    through the event owner's tenant; access is granted only to a member or
    primary manager of the provider operation that is responsible for the
    event.
    """
    if not await has_permission(db, tenant_id, user_id, required_perm):
        return False

    provider_check = await db.execute(
        text("""
            SELECT 1
            FROM event_operations o JOIN events e ON e.id=o.event_id AND e.deleted_at IS NULL
            LEFT JOIN event_operation_members om
                   ON om.operation_id = o.id AND om.user_id = :uid
            WHERE o.event_id = :eid
              AND o.provider_tenant_id = :tid
              AND o.status NOT IN ('completed', 'closed', 'cancelled')
              AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
            LIMIT 1
        """),
        {"eid": str(event_id), "tid": str(tenant_id), "uid": str(user_id)},
    )
    return provider_check.first() is not None


async def require_provider_event_access(
    db: AsyncSession,
    event_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    required_perm: str,
) -> None:
    """Raise 403 unless the user is on the team operation for this event."""
    if not await check_provider_event_access(
        db, event_id, tenant_id, user_id, required_perm,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="بوابات الدخول والحضور متاحة لفريق التشغيل المكلّف بهذا الحفل فقط",
        )


async def get_provider_event_ids(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> list[UUID]:
    """Return event IDs assigned to this provider tenant for a specific user."""
    result = await db.execute(
        text("""
            SELECT DISTINCT o.event_id
            FROM event_operations o
            LEFT JOIN event_operation_members om
                   ON om.operation_id = o.id AND om.user_id = :uid
            WHERE o.provider_tenant_id = :tid
              AND o.event_id IS NOT NULL
              AND o.status NOT IN ('completed', 'closed', 'cancelled')
              AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        """),
        {"tid": str(tenant_id), "uid": str(user_id)},
    )
    return [row[0] for row in result.fetchall()]
