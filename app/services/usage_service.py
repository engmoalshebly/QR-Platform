import logging
from uuid import UUID
from datetime import date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.models.usage import UsageLimitInfo, UsageCheckResult

logger = logging.getLogger(__name__)


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


# Limits that are enforced against a LIVE count of rows, not a monthly counter.
# The usage screen used to read monthly counters for every limit, so these always
# showed 0 however much was actually in use.  Each query mirrors the one the
# enforcing route runs, so "used" on screen equals what the limit check sees.
_STATIC_USAGE_SQL: dict[str, str] = {
    "guests_max": "SELECT COUNT(*) FROM guests WHERE tenant_id = ANY(:tids)",
    "designed_templates": (
        "SELECT COUNT(*) FROM invite_templates "
        "WHERE tenant_id = ANY(:tids) AND template_type = 'designed'"
    ),
    "teams_max": "SELECT COUNT(*) FROM teams WHERE tenant_id = ANY(:tids)",
    "registration_forms_max": (
        "SELECT COUNT(*) FROM event_registration_forms WHERE tenant_id = ANY(:tids) AND is_enabled = true"
    ),
    # Per-event limits: show the busiest event, which is the one that will hit the cap.
    "invitations_per_event": (
        "SELECT COALESCE(MAX(n), 0) FROM ("
        "SELECT COUNT(*) AS n FROM invitations WHERE tenant_id = ANY(:tids) GROUP BY event_id) x"
    ),
    "operations_max": "SELECT COUNT(*) FROM event_operations WHERE provider_tenant_id = ANY(:tids)",
    "operation_groups_max": "SELECT COUNT(*) FROM organizer_team_groups WHERE tenant_id = ANY(:tids)",
    "tasks_per_operation": (
        "SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM event_operation_tasks t "
        "JOIN event_operations o ON o.id = t.operation_id "
        "WHERE o.provider_tenant_id = ANY(:tids) GROUP BY t.operation_id) x"
    ),
    "operation_members_max": (
        "SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM event_operation_members m "
        "JOIN event_operations o ON o.id = m.operation_id "
        "WHERE o.provider_tenant_id = ANY(:tids) GROUP BY m.operation_id) x"
    ),
    "attachments_per_operation": (
        "SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM event_operation_attachments a "
        "JOIN event_operations o ON o.id = a.operation_id "
        "WHERE o.provider_tenant_id = ANY(:tids) GROUP BY a.operation_id) x"
    ),
    "team_members_per_team": (
        "SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM team_memberships tm "
        "JOIN teams t ON t.id = tm.team_id WHERE t.tenant_id = ANY(:tids) GROUP BY tm.team_id) x"
    ),
    "gates_per_event": (
        "SELECT COALESCE(MAX(n), 0) FROM ("
        "SELECT COUNT(*) AS n FROM event_gates g JOIN events e ON e.id = g.event_id "
        "WHERE e.tenant_id = ANY(:tids) AND g.is_active = true GROUP BY g.event_id) x"
    ),
}


async def get_static_usage(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Live consumption of the non-monthly limits, across the billing scope."""
    from app.services.entitlement_service import get_billing_scope_tenant_ids
    from app.services.feature_service import get_tenant_storage_bytes

    scope = [str(t) for t in await get_billing_scope_tenant_ids(db, tenant_id)]
    usage: dict[str, int] = {}

    for key, sql in _STATIC_USAGE_SQL.items():
        try:
            async with db.begin_nested():  # a failed count must not poison the session
                usage[key] = int((await db.execute(text(sql), {"tids": scope})).scalar() or 0)
        except Exception as exc:
            logger.warning("static usage query failed key=%s error=%s", key, type(exc).__name__)

    try:
        pending = (await db.execute(
            text("SELECT COUNT(*) FROM invites WHERE tenant_id = ANY(:tids) AND status = 'pending'"),
            {"tids": scope},
        )).scalar() or 0
        # Same number check_seats_limit compares against the plan: members + pending invites.
        usage["seats_max"] = int(await get_seats_count(db, tenant_id)) + int(pending)
    except Exception as exc:
        logger.warning("seat usage query failed error=%s", type(exc).__name__)

    try:
        stored = await get_tenant_storage_bytes(db, tenant_id)
        usage["storage_mb"] = -(-int(stored) // (1024 * 1024))  # round up
    except Exception as exc:
        logger.warning("storage usage query failed error=%s", type(exc).__name__)

    return usage


async def check_all_limits(db: AsyncSession, tenant_id: UUID) -> UsageCheckResult:
    """Check all usage limits for a tenant."""
    plan_code, limits = await get_tenant_plan_limits(db, tenant_id)
    usage = await get_current_usage(db, tenant_id)
    # Live counts win over the (always-zero) monthly counter for static limits.
    usage.update(await get_static_usage(db, tenant_id))

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
