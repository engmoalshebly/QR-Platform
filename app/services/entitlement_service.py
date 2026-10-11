"""Single source of truth for tenant plan entitlements.

Permissions answer *who* may act; entitlements answer *whether the plan* allows
the feature and how much can be consumed.  All callers should use this module
instead of reading plans, subscriptions or feature flags independently.
"""
from uuid import UUID
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_billing_tenant(db: AsyncSession, tenant_id: UUID) -> UUID:
    """Return the tenant that owns the subscription for this workspace.

    Linked institution/organizer workspaces share one commercial entitlement,
    while their operational data remains isolated. Standalone tenants bill
    themselves.
    """
    result = await db.execute(text("""
        SELECT billing_tenant_id
        FROM workspace_links
        WHERE status = 'active'
          AND (organizer_tenant_id = :tid OR institution_tenant_id = :tid)
        LIMIT 1
    """), {"tid": str(tenant_id)})
    billing_tenant_id = result.scalar_one_or_none()
    return UUID(str(billing_tenant_id)) if billing_tenant_id else tenant_id


async def get_billing_scope_tenant_ids(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    """Return all active workspaces that consume the same commercial plan."""
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    result = await db.execute(text("""
        SELECT organizer_tenant_id, institution_tenant_id
        FROM workspace_links
        WHERE status = 'active' AND billing_tenant_id = :billing_tenant_id
        LIMIT 1
    """), {"billing_tenant_id": str(billing_tenant_id)})
    row = result.mappings().first()
    if not row:
        return [billing_tenant_id]
    return list({
        billing_tenant_id,
        UUID(str(row["organizer_tenant_id"])),
        UUID(str(row["institution_tenant_id"])),
    })


async def sync_plan_cache(db: AsyncSession, tenant_id: UUID | str, plan_code: str) -> None:
    """Write the plan code to every workspace that shares this commercial plan.

    `tenants.plan` is a display/compatibility cache.  Linked institution and
    organizer workspaces bill as one account, so updating only the billing
    tenant left the other workspace showing "free" after an approval.
    """
    scope = await get_billing_scope_tenant_ids(db, UUID(str(tenant_id)))
    await db.execute(
        text("UPDATE tenants SET plan = :plan_code, updated_at = now() WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"plan_code": plan_code, "ids": [str(t) for t in scope]},
    )


async def resolve_plan(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    """Resolve the effective plan: active custom plan, valid subscription, safe fallback."""
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    custom = await db.execute(text("""
        SELECT p.id, p.code, p.name, p.features, cp.final_limits, 'custom' AS source
        FROM custom_plans cp JOIN plans p ON p.id = cp.base_plan_id
        WHERE cp.tenant_id = :tid
          AND cp.status = 'active'
          AND cp.activated_at IS NOT NULL
          AND cp.valid_until > now()
        ORDER BY cp.created_at DESC LIMIT 1
    """), {"tid": str(billing_tenant_id)})
    row = custom.mappings().first()
    if row:
        return dict(row)

    subscription = await db.execute(text("""
        SELECT p.id, p.code, p.name, p.features, NULL::jsonb AS final_limits, 'subscription' AS source
        FROM subscriptions s JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = :tid AND s.status IN ('active', 'trialing')
          AND (s.current_period_end IS NULL OR s.current_period_end > now())
        ORDER BY s.created_at DESC LIMIT 1
    """), {"tid": str(billing_tenant_id)})
    row = subscription.mappings().first()
    if row:
        return dict(row)

    # A tenant.plan value is a compatibility cache, not proof of a paid
    # entitlement. Use it only for legacy tenants which have never had a
    # subscription. Once subscription history exists, an expired/past-due
    # plan must fall back to the base plan instead of retaining paid access.
    fallback = await db.execute(text("""
        SELECT p.id, p.code, p.name, p.features, NULL::jsonb AS final_limits, 'tenant_fallback' AS source
        FROM tenants t JOIN plans p ON lower(p.code) = lower(coalesce(t.plan, 'starter'))
        WHERE t.id = :tid
          AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tenant_id = t.id)
        LIMIT 1
    """), {"tid": str(billing_tenant_id)})
    row = fallback.mappings().first()
    if row:
        return dict(row)

    base_plan = await db.execute(text("""
        SELECT id, code, name, features, NULL::jsonb AS final_limits, 'base_fallback' AS source
        FROM plans
        WHERE is_active = true AND lower(code) IN ('starter', 'free')
        ORDER BY CASE lower(code) WHEN 'starter' THEN 0 ELSE 1 END
        LIMIT 1
    """))
    row = base_plan.mappings().first()
    if row:
        return dict(row)
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="No valid plan is assigned to this tenant")


async def get_limits(db: AsyncSession, tenant_id: UUID) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    plan = await resolve_plan(db, tenant_id)
    result = await db.execute(text("""
        SELECT key, value, period FROM plan_limits WHERE plan_id = :pid
    """), {"pid": str(plan["id"])})
    limits = {r["key"]: dict(r) for r in result.mappings().all()}
    overrides = plan.get("final_limits") or {}
    for key, value in overrides.items():
        if not isinstance(value, int) or value < -1:
            raise HTTPException(status_code=500, detail=f"Invalid custom plan limit: {key}")
        limits[key] = {"key": key, "value": value, "period": limits.get(key, {}).get("period", "none")}
    return plan, limits


async def require_feature(db: AsyncSession, tenant_id: UUID, feature_key: str) -> None:
    """Require an explicit tenant flag or a feature declared by the effective plan."""
    override = await db.execute(text("""
        SELECT enabled FROM feature_flags WHERE tenant_id = :tid AND flag_key = :key
    """), {"tid": str(tenant_id), "key": feature_key})
    explicit = override.scalar_one_or_none()
    if explicit is not None:
        if explicit:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{feature_key}' is disabled for this tenant")
    plan = await resolve_plan(db, tenant_id)
    included = await db.execute(text("""
        SELECT 1 FROM plan_features WHERE plan_id = :pid AND feature_key = :key
    """), {"pid": str(plan["id"]), "key": feature_key})
    if included.first():
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{feature_key}' is not included in the current plan")


async def require_limit(db: AsyncSession, tenant_id: UUID, key: str, current: int, amount: int = 1) -> int:
    """Require an explicitly configured limit; -1 is the only unlimited value."""
    _, limits = await get_limits(db, tenant_id)
    if key not in limits:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Plan limit is not configured: {key}")
    value = int(limits[key]["value"])
    if value != -1 and current + amount > value:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Plan limit exceeded for {key}: {value}")
    return value
