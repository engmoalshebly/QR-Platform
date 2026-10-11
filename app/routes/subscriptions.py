import json
import logging
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from math import ceil
from typing import Literal, Optional

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.config import get_settings
from app.database import get_db, get_privileged_db
from app.models.subscription import SubscriptionRead, SubscriptionWithPlan, PaymentProvider
from app.models.plan import (
    PlanRead, PlanWithLimits, PlanLimitRead,
    PlanAddonRead, CustomPlanRequest, CustomPlanCalculation,
    CustomPlanRead, AddonLineItem,
)
from app.services.membership_service import require_owner
from app.services.permission_service import require_permission
from app.services.audit_service import log_audit
from app.services.entitlement_service import resolve_billing_tenant
from app.security import get_client_ip

logger = logging.getLogger(__name__)

CUSTOM_PLAN_MIN_PRICE = 5.00  # الحد الأدنى للباقة المخصصة ($/شهر، migration_v69)
YEARLY_DISCOUNT_MONTHS = 10     # السنوي = شهري × 10 (خصم شهرين)

settings = get_settings()

router = APIRouter(tags=["Subscriptions & Plans"])


# ── Request/Response Models ──
#
# Payments are not taken online today (Link Gateway is disabled by business
# decision — see app/services/subscription_engine.py and
# app/services/link_payment_service.py, kept intact but unused, for a future
# re-enable). Every plan change is a request that a platform staff member
# approves manually after verifying payment out of band — see
# app/routes/platform.py's subscription-requests endpoints.

BillingPeriod = Literal["monthly", "yearly"]


class SubscriptionRequestBody(BaseModel):
    plan_code: str
    period: BillingPeriod = "monthly"
    notes: Optional[str] = Field(
        default=None, max_length=500,
        description="How payment will be or was made (bank transfer reference, cash receipt, etc.)",
    )


class CustomPlanRequestSubmit(BaseModel):
    period: BillingPeriod = "monthly"
    notes: Optional[str] = Field(default=None, max_length=500)


# ══════════════════════════════════════════════
# PLANS (public)
# ══════════════════════════════════════════════

@router.get("/plans", response_model=list[PlanWithLimits])
async def list_plans(db: AsyncSession = Depends(get_privileged_db)):
    """List all active plans with their limits."""
    try:
        plans_result = await db.execute(
            text("""
                SELECT id, code, name, description, subtitle,
                       price_monthly, price_yearly, currency, is_active, sort_order,
                       badge_color, is_popular, is_customizable, features
                FROM plans
                WHERE is_active = true
                ORDER BY sort_order
            """)
        )
        plans = plans_result.mappings().all()

        result = []
        for plan in plans:
            limits_result = await db.execute(
                text("SELECT id, plan_id, key, value, period FROM plan_limits WHERE plan_id = :pid"),
                {"pid": str(plan["id"])},
            )
            limits = [PlanLimitRead(**dict(l)) for l in limits_result.mappings().all()]
            plan_dict = dict(plan)
            # features is stored as JSONB — ensure it's a list
            features_raw = plan_dict.get("features")
            if features_raw is None:
                plan_dict["features"] = []
            elif isinstance(features_raw, str):
                import json
                plan_dict["features"] = json.loads(features_raw)
            result.append(PlanWithLimits(**plan_dict, limits=limits))
        return result
    except SQLAlchemyError:
        await db.rollback()

    # Local lightweight schema fallback: plans.slug exists, plan_limits may not.
    plans_result = await db.execute(
        text("""
            SELECT
                id,
                slug AS code,
                name,
                price_monthly,
                price_yearly,
                'SAR' AS currency,
                true AS is_active,
                row_number() OVER (ORDER BY price_monthly, name)::int AS sort_order
            FROM plans
            ORDER BY price_monthly, name
        """)
    )
    return [PlanWithLimits(**dict(plan), limits=[]) for plan in plans_result.mappings().all()]


# ══════════════════════════════════════════════
# SUBSCRIPTIONS
# ══════════════════════════════════════════════

@router.get("/subscriptions/current", response_model=SubscriptionWithPlan)
async def get_current_subscription(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the active subscription for the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.view")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT s.*, p.code AS plan_code, p.name AS plan_name
            FROM subscriptions s
            JOIN plans p ON p.id = s.plan_id
            WHERE s.tenant_id = :tid AND s.status IN ('active', 'trialing')
              AND (s.current_period_end IS NULL OR s.current_period_end > now())
            ORDER BY s.created_at DESC
            LIMIT 1
        """),
        {"tid": str(billing_tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No active subscription")
    return SubscriptionWithPlan(**dict(row))


# ── Request a plan change or renewal (reviewed manually by platform staff) ──
@router.post("/subscriptions/request", status_code=status.HTTP_202_ACCEPTED)
async def request_subscription(
    body: SubscriptionRequestBody,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a plan request for staff review.

    Payments are verified out of band today (bank transfer, cash, etc.), not
    through an online gateway, so this never activates anything by itself. A
    platform staff member approves or rejects it from the admin console —
    see POST /platform/subscription-requests/{id}/approve|reject.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.manage")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    plan_row = (await db.execute(
        text("SELECT id, name FROM plans WHERE code = :code AND is_active = true"),
        {"code": body.plan_code},
    )).mappings().first()
    if not plan_row:
        raise HTTPException(status_code=404, detail="الباقة المطلوبة غير موجودة")

    existing = (await db.execute(
        text("SELECT id FROM pending_subscriptions WHERE tenant_id = :tid AND provider = 'manual'"),
        {"tid": str(billing_tenant_id)},
    )).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="يوجد طلب باقة معلّق بالفعل لهذا الحساب. انتظر مراجعته قبل إرسال طلب جديد.",
        )

    try:
        pending_id = (await db.execute(
            text("""
                INSERT INTO pending_subscriptions
                  (tenant_id, plan_id, provider, provider_agreement_id, metadata)
                VALUES (:tid, :pid, 'manual', :ref, CAST(:metadata AS jsonb))
                RETURNING id
            """),
            {
                "tid": str(billing_tenant_id), "pid": str(plan_row["id"]),
                "ref": f"manual_{uuid4().hex[:16]}",
                "metadata": json.dumps({
                    "plan_code": body.plan_code, "plan_name": plan_row["name"],
                    "period": body.period, "notes": body.notes,
                    "requested_by": str(user.id),
                }),
            },
        )).scalar()
    except IntegrityError as error:
        # The app-level check above is a fast path; this unique index
        # (migration v68) is the race-safe backstop for concurrent requests.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="يوجد طلب باقة معلّق بالفعل لهذا الحساب. انتظر مراجعته قبل إرسال طلب جديد.",
        ) from error

    await log_audit(
        db,
        tenant_id=billing_tenant_id,
        actor_user_id=user.id,
        action="subscription.requested_manual",
        resource_type="pending_subscription",
        resource_id=str(pending_id),
        metadata={"plan_code": body.plan_code, "period": body.period},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return {
        "request_id": str(pending_id),
        "status": "pending_review",
        "message": "تم استلام طلبك وهو قيد مراجعة الإدارة. سيتم تفعيل الباقة بعد التحقق من الدفع.",
    }


# ── Cancel Subscription ──
@router.post("/subscriptions/cancel")
async def cancel_subscription(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the current subscription at period end."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.manage")
    await require_owner(db, tenant_id, user.id)
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT id, provider, provider_subscription_id
            FROM subscriptions
            WHERE tenant_id = :tid AND status IN ('active', 'trialing')
            ORDER BY created_at DESC LIMIT 1
        """),
        {"tid": str(billing_tenant_id)},
    )
    sub = result.mappings().first()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    # Link Gateway payments are one-shot — no external cancellation needed.
    # We just mark the subscription to not renew (cancel_at_period_end).
    # Legacy providers (stripe/paypal) are no longer active.

    await db.execute(
        text("UPDATE subscriptions SET cancel_at_period_end = true WHERE id = :id"),
        {"id": str(sub["id"])},
    )

    await log_audit(
        db,
        tenant_id=billing_tenant_id,
        actor_user_id=user.id,
        action="subscription.cancel",
        resource_type="subscription",
        resource_id=str(sub["id"]),
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return {"message": "الاشتراك سيتم إلغاؤه عند انتهاء الفترة الحالية"}


# ══════════════════════════════════════════════
# CUSTOM PLAN BUILDER
# ══════════════════════════════════════════════

@router.get("/addons", response_model=list[PlanAddonRead])
async def list_addons(db: AsyncSession = Depends(get_privileged_db)):
    """List all available add-on items with pricing."""
    result = await db.execute(
        text("""
            SELECT id, key, label_ar, label_en, unit_ar, unit_en, icon,
                   min_value, max_value, step, price_per_unit,
                   category, sort_order, is_active
            FROM plan_addons
            WHERE is_active = true
            ORDER BY sort_order
        """)
    )
    rows = result.mappings().all()
    return [PlanAddonRead(**dict(r)) for r in rows]


async def _calculate_custom_plan(
    db: AsyncSession,
    body: CustomPlanRequest,
) -> CustomPlanCalculation:
    """
    Core calculation logic for custom plans.
    Takes a base plan + additional items, computes:
      - base price (from the chosen plan)
      - extra add-ons price (only for quantities ABOVE the plan's included limits)
      - final merged limits
    """
    # ── 1. Load base plan + its limits ──
    plan_result = await db.execute(
        text("""
            SELECT id, code, name, price_monthly, price_yearly, currency
            FROM plans
            WHERE code = :code AND is_active = true
        """),
        {"code": body.base_plan_code},
    )
    base_plan = plan_result.mappings().first()
    if not base_plan:
        raise HTTPException(status_code=404, detail="الباقة الأساسية غير موجودة")

    limits_result = await db.execute(
        text("SELECT key, value FROM plan_limits WHERE plan_id = :pid"),
        {"pid": str(base_plan["id"])},
    )
    base_limits = {r["key"]: r["value"] for r in limits_result.mappings().all()}

    # ── 2. Load addon pricing ──
    addons_result = await db.execute(
        text("""SELECT key, label_ar, label_en, icon, price_per_unit, step,
                       min_value, max_value
                FROM plan_addons WHERE is_active = true""")
    )
    addon_pricing = {r["key"]: dict(r) for r in addons_result.mappings().all()}

    # ── 3. Calculate each line item ──
    addon_lines: list[AddonLineItem] = []
    final_limits = dict(base_limits)
    addons_total = 0.0

    for item in body.items:
        if item.key not in addon_pricing:
            raise HTTPException(status_code=422, detail=f"إضافة غير معروفة أو غير متاحة: {item.key}")

        pricing = addon_pricing[item.key]
        base_value = base_limits.get(item.key, 0)
        # -1 means unlimited in base plan — no addon needed
        if base_value == -1:
            final_limits[item.key] = -1
            continue

        desired = item.quantity
        min_value = int(pricing["min_value"])
        max_value = int(pricing["max_value"])
        if desired < min_value or desired > max_value:
            raise HTTPException(
                status_code=422,
                detail=f"قيمة {item.key} يجب أن تكون بين {min_value} و{max_value}",
            )
        if desired <= base_value:
            # No extra needed, base plan already covers it
            final_limits[item.key] = base_value
            continue

        # Calculate extra units above base plan
        extra = desired - base_value
        step = pricing["step"]
        if step > 1 and extra % step != 0:
            raise HTTPException(
                status_code=422,
                detail=f"الزيادة في {item.key} يجب أن تكون بمضاعفات {step}",
            )

        # Price per unit is per-step (e.g., 5 SAR per 100 invitations)
        if step > 1:
            # Round up to nearest step
            extra_steps = ceil(extra / step)
            line_total = round(extra_steps * float(pricing["price_per_unit"]), 2)
        else:
            line_total = round(extra * float(pricing["price_per_unit"]), 2)

        addons_total += line_total
        final_limits[item.key] = desired

        addon_lines.append(AddonLineItem(
            key=item.key,
            label_ar=pricing["label_ar"],
            label_en=pricing["label_en"],
            icon=pricing["icon"],
            base_value=base_value,
            extra_quantity=extra,
            unit_price=float(pricing["price_per_unit"]),
            line_total=line_total,
        ))

    base_price = float(base_plan["price_monthly"])
    total_monthly = round(base_price + addons_total, 2)

    # Enforce minimum price for paid custom plans
    if addons_total > 0 and total_monthly < CUSTOM_PLAN_MIN_PRICE:
        total_monthly = CUSTOM_PLAN_MIN_PRICE

    total_yearly = round(total_monthly * YEARLY_DISCOUNT_MONTHS, 2)

    return CustomPlanCalculation(
        base_plan_code=base_plan["code"],
        base_plan_name=base_plan["name"],
        base_price=base_price,
        addon_lines=addon_lines,
        addons_total=round(addons_total, 2),
        total_monthly=total_monthly,
        total_yearly=total_yearly,
        currency=base_plan["currency"] or "YER",
        final_limits=final_limits,
    )


@router.post("/custom-plans/calculate", response_model=CustomPlanCalculation)
async def calculate_custom_plan(
    body: CustomPlanRequest,
    db: AsyncSession = Depends(get_privileged_db),
):
    """
    Calculate the price for a custom plan without saving it.
    Use this for the live pricing preview in the UI.
    """
    return await _calculate_custom_plan(db, body)


@router.post("/custom-plans", response_model=CustomPlanRead, status_code=status.HTTP_201_CREATED)
async def create_custom_plan(
    body: CustomPlanRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create and save a custom plan for the current tenant.
    This also creates the corresponding plan_limits entries.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.manage")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    # Calculate pricing
    calc = await _calculate_custom_plan(db, body)

    # Get base plan ID
    plan_result = await db.execute(
        text("SELECT id FROM plans WHERE code = :code"),
        {"code": body.base_plan_code},
    )
    base_plan_row = plan_result.mappings().first()

    # Build addons dict for storage
    addons_dict = {item.key: item.quantity for item in body.items}

    # Insert custom plan
    result = await db.execute(
        text("""
            INSERT INTO custom_plans
                (tenant_id, base_plan_id, name, addons, base_price, addons_price,
                 total_price_monthly, total_price_yearly, final_limits, status, created_by)
            VALUES
                (:tid, :base_id, :name, CAST(:addons AS jsonb), :base_price, :addons_price,
                 :total_monthly, :total_yearly, CAST(:final_limits AS jsonb), 'draft', :uid)
            RETURNING id, tenant_id, base_plan_id, name, addons, base_price, addons_price,
                      total_price_monthly, total_price_yearly, final_limits, status,
                      created_at, updated_at
        """),
        {
            "tid": str(billing_tenant_id),
            "base_id": str(base_plan_row["id"]) if base_plan_row else None,
            "name": body.name or "باقتي المخصصة",
            "addons": json.dumps(addons_dict),
            "base_price": calc.base_price,
            "addons_price": calc.addons_total,
            "total_monthly": calc.total_monthly,
            "total_yearly": calc.total_yearly,
            "final_limits": json.dumps(calc.final_limits),
            "uid": str(user.id),
        },
    )
    row = result.mappings().first()

    # Audit log
    await log_audit(
        db,
        tenant_id=billing_tenant_id,
        actor_user_id=user.id,
        action="custom_plan.create",
        resource_type="custom_plan",
        resource_id=str(row["id"]),
        metadata={"base_plan": body.base_plan_code, "total": calc.total_monthly, "status": "draft"},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return CustomPlanRead(**dict(row))


@router.get("/custom-plans", response_model=list[CustomPlanRead])
async def list_custom_plans(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all custom plans for the current tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.view")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT id, tenant_id, base_plan_id, name, addons, base_price, addons_price,
                   total_price_monthly, total_price_yearly, final_limits, status,
                   created_at, updated_at
            FROM custom_plans
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
        """),
        {"tid": str(billing_tenant_id)},
    )
    rows = result.mappings().all()
    return [CustomPlanRead(**dict(r)) for r in rows]


@router.get("/custom-plans/active", response_model=CustomPlanRead)
async def get_active_custom_plan(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the active custom plan for the current tenant (if any)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.view")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT id, tenant_id, base_plan_id, name, addons, base_price, addons_price,
                   total_price_monthly, total_price_yearly, final_limits, status,
                   created_at, updated_at
            FROM custom_plans
            WHERE tenant_id = :tid AND status = 'active'
              AND activated_at IS NOT NULL AND valid_until > now()
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"tid": str(billing_tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="لا توجد باقة مخصصة نشطة")
    return CustomPlanRead(**dict(row))


# ── Submit a draft custom plan for staff review ──
@router.post("/custom-plans/{custom_plan_id}/request", status_code=status.HTTP_202_ACCEPTED)
async def request_custom_plan_activation(
    custom_plan_id: UUID,
    body: CustomPlanRequestSubmit,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move a draft custom plan to pending_review for staff approval.

    A platform staff member activates it after verifying payment out of band —
    see POST /platform/custom-plans/{id}/activate (reject via /reject).
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "billing.manage")
    billing_tenant_id = await resolve_billing_tenant(db, tenant_id)

    cp = (await db.execute(
        text("SELECT id, status FROM custom_plans WHERE id = :cpid AND tenant_id = :tid FOR UPDATE"),
        {"cpid": str(custom_plan_id), "tid": str(billing_tenant_id)},
    )).mappings().first()
    if not cp:
        raise HTTPException(status_code=404, detail="الباقة المخصصة غير موجودة")
    if cp["status"] not in ("draft", "expired"):
        raise HTTPException(status_code=409, detail="هذه الباقة قيد المراجعة أو مفعّلة بالفعل")

    await db.execute(
        text("""
            UPDATE custom_plans
            SET status = 'pending_review', updated_at = now(),
                requested_period = :period, request_notes = :notes
            WHERE id = :cpid
        """),
        {"cpid": str(custom_plan_id), "period": body.period, "notes": body.notes},
    )
    await log_audit(
        db,
        tenant_id=billing_tenant_id,
        actor_user_id=user.id,
        action="custom_plan.requested",
        resource_type="custom_plan",
        resource_id=str(custom_plan_id),
        metadata={"period": body.period},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return {
        "status": "pending_review",
        "message": "تم إرسال الباقة المخصصة للمراجعة. سيتم تفعيلها بعد التحقق من الدفع.",
    }
