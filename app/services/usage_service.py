from uuid import UUID
from datetime import date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.models.usage import UsageLimitInfo, UsageCheckResult


async def get_tenant_plan_limits(db: AsyncSession, tenant_id: UUID) -> tuple[str, list[dict]]:
    """Get the active plan and its limits for a tenant."""
    from app.services.entitlement_service import get_limits
    plan, central_limits = await get_limits(db, tenant_id)
    return plan["code"], [{"plan_code": plan["code"], **limit} for limit in central_limits.values()]


async def get_current_usage(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Get current month's usage counters for a tenant."""
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    period_start = date.today().replace(day=1)
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT key, SUM(value) AS value
            FROM usage_counters
            WHERE tenant_id = ANY(:tenant_ids)
              AND period_start = :period_start
            GROUP BY key
        """),
        {"tenant_ids": [str(item) for item in scope_tenant_ids], "period_start": period_start},
    )
    rows = result.mappings().all()
    return {r["key"]: r["value"] for r in rows}


async def check_all_limits(db: AsyncSession, tenant_id: UUID) -> UsageCheckResult:
    """Check all usage limits for a tenant."""
    plan_code, limits = await get_tenant_plan_limits(db, tenant_id)
    usage = await get_current_usage(db, tenant_id)

    limit_infos = []
    any_exceeded = False

    for limit in limits:
        key = limit["key"]
        max_value = limit["value"]
        current = usage.get(key, 0)

        # -1 means unlimited
        if max_value == -1:
            remaining = -1
            is_exceeded = False
        else:
            remaining = max(0, max_value - current)
            is_exceeded = current >= max_value

        if is_exceeded:
            any_exceeded = True

        limit_infos.append(
            UsageLimitInfo(
                key=key,
                limit=max_value,
                current_usage=current,
                remaining=remaining,
                is_exceeded=is_exceeded,
            )
        )

    return UsageCheckResult(
        tenant_id=tenant_id,
        plan_code=plan_code,
        limits=limit_infos,
        any_exceeded=any_exceeded,
    )


async def check_and_increment(
    db: AsyncSession,
    tenant_id: UUID,
    usage_key: str,
    amount: int = 1,
) -> int:
    """
    Check if tenant can consume the resource, then atomically increment.
    Returns the new usage value.
    Raises 429 if limit exceeded.
    """
    plan_code, limits = await get_tenant_plan_limits(db, tenant_id)

    # Find the relevant limit
    limit_value = None
    for limit in limits:
        if limit["key"] == usage_key:
            limit_value = limit["value"]
            break

    if limit_value is None:
        # Missing configuration must fail closed. A new resource must never
        # become unlimited just because its plan limit was not seeded.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Plan limit is not configured: {usage_key}",
        )
    # Enforce and consume in one database statement.  The previous read-then-
    # increment sequence allowed concurrent requests to overrun a plan limit.
    from app.services.entitlement_service import resolve_billing_tenant
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    result = await db.execute(
        text("SELECT public.try_increment_usage(:tenant_id, :key, :amount, :limit_value)"),
        {
            "tenant_id": str(billing_tenant_id),
            "key": usage_key,
            "amount": amount,
            "limit_value": limit_value,
        },
    )
    new_value = result.scalar()
    if new_value is None:
        usage = await get_current_usage(db, tenant_id)
        current = usage.get(usage_key, 0)
        RESOURCE_NAMES_AR = {
            "events_per_month": "الفعاليات شهرياً",
            "invitations_per_month": "الدعوات شهرياً",
            "gates_per_event": "البوابات لكل حدث",
            "teams_max": "فرق العمل",
            "seats_max": "المستخدمين في المنصة",
            "designed_templates": "القوالب المصممة",
            "guests_max": "الضيوف",
            "invitations_per_event": "الدعوات لكل حدث",
            "messages_per_month": "الرسائل الشهرية",
            "registration_forms_max": "نماذج التسجيل النشطة",
            "storage_mb": "التخزين",
        }
        res_name = RESOURCE_NAMES_AR.get(usage_key, usage_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"تم تجاوز الحد الأقصى لـ '{res_name}'. "
                   f"الحالي: {current}، المسموح به: {limit_value}، المطلوب: {amount}.",
        )
    return new_value


async def release_usage(
    db: AsyncSession,
    tenant_id: UUID,
    usage_key: str,
    amount: int,
) -> None:
    """Release an unused reservation inside the caller's transaction."""
    if amount <= 0:
        return
    from app.services.entitlement_service import resolve_billing_tenant
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)
    period_start = date.today().replace(day=1)
    await db.execute(text("""
        UPDATE usage_counters
        SET value = GREATEST(0, value - :amount), updated_at = now()
        WHERE tenant_id = :tid AND key = :key AND period_start = :period_start
    """), {
        "tid": str(billing_tenant_id),
        "key": usage_key,
        "period_start": period_start,
        "amount": amount,
    })


async def get_seats_count(db: AsyncSession, tenant_id: UUID) -> int:
    """Count active members in a tenant."""
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
    result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT user_id) FROM memberships
            WHERE tenant_id = ANY(:tenant_ids) AND status = 'active'
        """),
        {"tenant_ids": [str(item) for item in scope_tenant_ids]},
    )
    return result.scalar() or 0
