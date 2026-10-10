"""
Feature Gating Service.
Checks plan limits and feature flags before allowing actions.
"""
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)


async def check_feature_flag(
    db: AsyncSession,
    tenant_id: UUID,
    flag_key: str,
) -> bool:
    """Check if a feature flag is enabled for a tenant."""
    # 1. Check explicit override in feature_flags table
    result = await db.execute(
        text("SELECT enabled FROM feature_flags WHERE tenant_id = :tid AND flag_key = :key"),
        {"tid": str(tenant_id), "key": flag_key},
    )
    row = result.scalar()
    if row is not None:
        return bool(row)

    # Resolve every plan through the canonical entitlement service. This keeps
    # feature checks aligned with subscription expiry and linked workspaces.
    from app.services.entitlement_service import resolve_plan
    plan = await resolve_plan(db, tenant_id)
    feature = await db.execute(
        text("SELECT 1 FROM plan_features WHERE plan_id = :pid AND feature_key = :key"),
        {"pid": str(plan["id"]), "key": flag_key},
    )
    return feature.first() is not None


async def require_feature(
    db: AsyncSession,
    tenant_id: UUID,
    flag_key: str,
) -> None:
    """Raise 403 if feature is not enabled for the tenant."""
    enabled = await check_feature_flag(db, tenant_id, flag_key)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"الميزة '{flag_key}' غير مُفعّلة في خطتك الحالية. يرجى ترقية خطتك.",
        )


async def get_plan_limit(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
) -> int:
    """Get a specific plan limit value for a tenant. Returns -1 for unlimited."""
    from app.services.entitlement_service import get_limits
    _, limits = await get_limits(db, tenant_id)
    if limit_key in limits:
        return int(limits[limit_key]["value"])
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Plan limit is not configured: {limit_key}")


async def check_limit(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
    current_count: int,
) -> dict:
    """
    Check if a tenant has reached a specific limit.
    Returns dict with allowed, limit, current, remaining.
    """
    limit_value = await get_plan_limit(db, tenant_id, limit_key)

    if limit_value == -1:
        return {"allowed": True, "limit": -1, "current": current_count, "remaining": -1}

    remaining = max(0, limit_value - current_count)
    return {
        "allowed": current_count < limit_value,
        "limit": limit_value,
        "current": current_count,
        "remaining": remaining,
    }


async def require_within_limit(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
    current_count: int,
    resource_name: str = "المورد",
) -> None:
    """Raise 429 if tenant has reached the limit."""
    result = await check_limit(db, tenant_id, limit_key, current_count)
    if not result["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"تم الوصول لحد {resource_name} ({result['limit']}). قم بترقية خطتك.",
        )


async def check_seats_limit(
    db: AsyncSession,
    tenant_id: UUID,
) -> None:
    """Check if tenant can add more members."""
    # Seats belong to the billing account; a user shared between linked
    # workspaces is counted once.
    await acquire_plan_limit_lock(db, tenant_id, "seats_max")
    from app.services.usage_service import get_seats_count
    current = await get_seats_count(db, tenant_id)

    # Count pending invites
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
    pending = await db.execute(
        text("SELECT COUNT(*) FROM invites WHERE tenant_id = ANY(:tenant_ids) AND status = 'pending'"),
        {"tenant_ids": [str(item) for item in scope_tenant_ids]},
    )
    pending_count = pending.scalar() or 0

    await require_within_limit(db, tenant_id, "seats_max", current + pending_count, "الأعضاء")


async def check_storage_limit(
    db: AsyncSession,
    tenant_id: UUID,
    current_mb: int,
) -> None:
    """Check if tenant can use more storage."""
    await require_within_limit(db, tenant_id, "storage_mb", current_mb, "التخزين")


async def get_tenant_storage_bytes(db: AsyncSession, tenant_id: UUID) -> int:
    """Sum tracked storage: template assets + non-asset uploads (event covers, etc.)."""
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
    assets_res = await db.execute(
        text("""
            SELECT COALESCE(SUM(ta.file_size), 0)
            FROM template_assets ta
            JOIN invite_templates it ON it.id = ta.template_id
            WHERE it.tenant_id = ANY(:tenant_ids)
        """),
        {"tenant_ids": [str(item) for item in scope_tenant_ids]},
    )
    assets_bytes = int(assets_res.scalar() or 0)

    extra_res = await db.execute(
        text("""
            SELECT COALESCE(SUM(value), 0)
            FROM usage_counters
            WHERE tenant_id = ANY(:tenant_ids) AND key = 'storage_bytes'
              AND period_start = '1970-01-01'::date
        """),
        {"tenant_ids": [str(item) for item in scope_tenant_ids]},
    )
    extra_bytes = int(extra_res.scalar() or 0)
    return assets_bytes + extra_bytes


async def require_storage_for_upload(
    db: AsyncSession,
    tenant_id: UUID,
    file_size_bytes: int,
) -> None:
    """Raise 429 if uploading file_size_bytes would exceed the tenant storage_mb plan limit."""
    await acquire_plan_limit_lock(db, tenant_id, "storage_mb")
    current_bytes = await get_tenant_storage_bytes(db, tenant_id)
    projected_mb = (current_bytes + file_size_bytes + 1024 * 1024 - 1) // (1024 * 1024)
    await check_storage_limit(db, tenant_id, projected_mb)


async def record_non_asset_storage(
    db: AsyncSession,
    tenant_id: UUID,
    file_size_bytes: int,
) -> None:
    """Track storage used by uploads not stored in template_assets (e.g. event covers)."""
    if file_size_bytes <= 0:
        return
    from app.services.entitlement_service import resolve_billing_tenant
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    await db.execute(
        text("""
            INSERT INTO usage_counters (tenant_id, period_start, period_end, key, value)
            VALUES (:tid, '1970-01-01'::date, '2099-12-31'::date, 'storage_bytes', :val)
            ON CONFLICT (tenant_id, period_start, key)
            DO UPDATE SET value = usage_counters.value + :val, updated_at = now()
        """),
        {"tid": str(billing_tenant_id), "val": file_size_bytes},
    )


# Persistent resources whose live count must fit within the target plan
# BEFORE a downgrade is allowed. Monthly counters (events/invitations) reset
# each period, so they are enforced at usage time, not here.
_DOWNGRADE_RESOURCES = {
    "seats_max": ("الأعضاء", "SELECT COUNT(*) FROM memberships WHERE tenant_id = :tid AND status = 'active'"),
    "teams_max": ("الفرق", "SELECT COUNT(*) FROM teams WHERE tenant_id = :tid"),
    "guests_max": ("الضيوف", "SELECT COUNT(*) FROM guests WHERE tenant_id = :tid"),
}


async def check_downgrade_allowed(
    db: AsyncSession,
    tenant_id: UUID,
    target_plan_code: str,
) -> None:
    """
    Block a downgrade when the tenant's existing usage exceeds the target
    plan's persistent limits (seats, teams, guests, storage).

    Raises 409 listing every resource over the new limit. No-op for plans
    that are equal or higher (the target limit will simply be >= usage).
    """
    limits_result = await db.execute(
        text("""
            SELECT pl.key, pl.value AS limit_value
            FROM plan_limits pl
            JOIN plans p ON p.id = pl.plan_id
            WHERE p.code = :code
        """),
        {"code": target_plan_code},
    )
    target_limits = {r["key"]: r["limit_value"] for r in limits_result.mappings().all()}
    if not target_limits:
        return  # Unknown plan: let the caller's own validation handle it.

    violations: list[str] = []

    for key, (label, count_sql) in _DOWNGRADE_RESOURCES.items():
        limit_val = target_limits.get(key)
        if limit_val is None or limit_val == -1:
            continue  # Not limited on the target plan.
        current = (await db.execute(text(count_sql), {"tid": str(tenant_id)})).scalar() or 0
        if current > limit_val:
            violations.append(f"{label}: لديك {current} والحد الجديد {limit_val}")

    # Storage is measured in MB from accumulated bytes, handled separately.
    storage_limit = target_limits.get("storage_mb")
    if storage_limit is not None and storage_limit != -1:
        current_bytes = await get_tenant_storage_bytes(db, tenant_id)
        current_mb = current_bytes // (1024 * 1024)
        if current_mb > storage_limit:
            violations.append(f"التخزين: تستخدم {current_mb}MB والحد الجديد {storage_limit}MB")

    if violations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "لا يمكن التنزيل إلى هذه الباقة لأن استخدامك الحالي يتجاوز حدودها. "
                "قلّل الاستخدام أولاً: " + "؛ ".join(violations)
            ),
        )


async def enforce_monthly_limit(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
    resource_name: str,
    count: int = 1,
) -> None:
    """
    Check a monthly usage counter against plan limit.
    Uses usage_service.check_and_increment to atomically verify and increment.
    Raises 429 if limit exceeded.
    """
    from app.services.usage_service import check_and_increment
    await check_and_increment(db, tenant_id, limit_key, count)


async def enforce_static_limit(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
    current_count: int,
    resource_name: str,
    requested: int = 1,
) -> None:
    """
    Check a static (non-monthly) limit against current count.
    Raises 429 if adding 'requested' items would exceed the plan limit.
    """
    limit_value = await get_plan_limit(db, tenant_id, limit_key)
    if limit_value == -1:
        return  # unlimited
    if current_count + requested > limit_value:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"تم الوصول لحد {resource_name} ({limit_value}). "
                   f"الحالي: {current_count}، المطلوب: {requested}. قم بترقية خطتك.",
        )


async def acquire_plan_limit_lock(
    db: AsyncSession,
    tenant_id: UUID,
    limit_key: str,
    scope_id: str = "global",
) -> None:
    """Serialize a static count/check/write sequence until transaction end."""
    from app.services.entitlement_service import resolve_billing_tenant
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"plan-limit:{billing_tenant_id}:{limit_key}:{scope_id}"},
    )

