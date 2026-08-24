"""
Subscription Engine — Internal subscription lifecycle management.

Replaces PayPal's recurring billing with a manual-renewal model
powered by one-shot Link Gateway payments (OTP flow).

Lifecycle:
  1. User selects plan + billing period + wallet provider → initiate_subscription()
  2. User enters OTP → confirm_subscription()
  3. System activates subscription → 30 days (monthly) or 365 days (yearly)
  4. Before expiry → renewal reminders (7d, 3d, 1d) via the task scheduler
  5. User manually renews → initiate_renewal()
  6. If not renewed → downgrade to starter (check_expired_subscriptions)

Failure recovery:
  If the wallet payment succeeds at the gateway but activation fails
  (e.g. a transient DB error), the tenant can call recover_subscription()
  which re-checks the gateway status and completes activation without
  charging again.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.link_payment_service import (
    get_link_payment_service,
    LinkPaymentError,
)

logger = logging.getLogger(__name__)

VALID_PERIODS = ("monthly", "yearly")
PENDING_TTL_HOURS = 24  # OTP sessions at the gateway expire within minutes


class SubscriptionEngineError(Exception):
    """Raised when subscription orchestration fails."""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.detail = detail


class SubscriptionEngine:
    """Orchestrates subscription lifecycle with Link Gateway payments."""

    PERIOD_DAYS = {"monthly": 30, "yearly": 365}

    def __init__(self):
        self.link_service = get_link_payment_service()

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    @staticmethod
    def _period_days(period: str) -> int:
        return SubscriptionEngine.PERIOD_DAYS.get(period, 30)

    @staticmethod
    def _plan_amount(plan: Dict[str, Any], period: str) -> float:
        """Resolve the charge amount for the requested billing period."""
        if period == "yearly":
            yearly = plan["price_yearly"]
            if yearly is None or float(yearly) <= 0:
                raise SubscriptionEngineError("هذه الباقة لا تدعم الاشتراك السنوي")
            return float(yearly)
        return float(plan["price_monthly"])

    # ──────────────────────────────────────────
    # Step 1: Initiate Payment
    # ──────────────────────────────────────────

    async def initiate_subscription(
        self,
        db: AsyncSession,
        tenant_id: str,
        plan_code: str,
        provider_code: str,
        wallet_number: str,
        user_id: str,
        user_email: str,
        period: str = "monthly",
    ) -> Dict[str, Any]:
        """
        Start the subscription payment flow.

        Creates a pending subscription record, then initiates a Link Gateway
        payment which sends an OTP to the user's wallet.

        Returns:
            {
                "payment_id": "uuid",
                "status": "OTP_REQUIRED",
                "fees": 40,
                "total_amount": 2040,
                "expires_at": "...",
                "pending_subscription_id": "uuid"
            }
        """
        if period not in VALID_PERIODS:
            raise SubscriptionEngineError("مدة الاشتراك غير صالحة (monthly أو yearly)")

        # 1. Validate plan exists and get price
        plan_result = await db.execute(
            text("""
                SELECT id, code, name, price_monthly, price_yearly, currency
                FROM plans
                WHERE code = :code AND is_active = true
            """),
            {"code": plan_code},
        )
        plan = plan_result.mappings().first()
        if not plan:
            raise SubscriptionEngineError("الباقة غير موجودة أو غير متاحة")

        amount = self._plan_amount(dict(plan), period)
        if amount <= 0:
            raise SubscriptionEngineError(
                "لا يمكن الاشتراك في باقة مجانية عبر الدفع",
                detail="Use direct plan assignment for free plans",
            )

        # 2. Block downgrade if usage exceeds target plan limits
        from app.services.feature_service import check_downgrade_allowed
        await check_downgrade_allowed(db, tenant_id, plan_code)

        # 3. Generate order ID
        order_id = f"sub_{plan_code}_{period}_{uuid.uuid4().hex[:8]}"

        # 4. Initiate payment via Link Gateway
        try:
            payment_result = self.link_service.initiate_payment(
                order_id=order_id,
                app_id="qentry-platform",
                provider_code=provider_code,
                wallet_number=wallet_number,
                amount=amount,
                currency=plan["currency"],
                metadata={
                    "tenant_id": tenant_id,
                    "plan_code": plan_code,
                    "user_id": user_id,
                    "type": "subscription",
                    "period": period,
                },
            )
            # Handle both sync and async
            if hasattr(payment_result, '__await__'):
                payment_result = await payment_result
        except LinkPaymentError as e:
            raise SubscriptionEngineError(
                f"فشل بدء عملية الدفع: {str(e)}",
                detail=str(e),
            )

        link_payment_id = payment_result.get("paymentId")
        if not link_payment_id:
            raise SubscriptionEngineError("لم يتم إرجاع معرف الدفع من البوابة")

        # 5. Store pending subscription
        pending_result = await db.execute(
            text("""
                INSERT INTO pending_subscriptions
                    (tenant_id, plan_id, provider, provider_agreement_id,
                     payer_email, metadata)
                VALUES
                    (:tid, :plan_id, 'link', :payment_id,
                     :email, CAST(:metadata AS jsonb))
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "plan_id": str(plan["id"]),
                "payment_id": link_payment_id,
                "email": user_email,
                "metadata": json.dumps({
                    "tenant_id": tenant_id,
                    "type": "subscription",
                    "plan_code": plan_code,
                    "provider_code": provider_code,
                    "wallet_number": wallet_number,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": plan["currency"],
                    "period": period,
                    "user_id": user_id,
                }),
            },
        )
        pending_row = pending_result.mappings().first()
        await db.commit()

        return {
            "payment_id": link_payment_id,
            "status": payment_result.get("status", "OTP_REQUIRED"),
            "fees": payment_result.get("fees", 0),
            "total_amount": payment_result.get("totalAmount", amount),
            "expires_at": payment_result.get("expiresAt"),
            "pending_subscription_id": str(pending_row["id"]),
            "period": period,
            "amount": amount,
        }

    # ──────────────────────────────────────────
    # Custom Plan Payment (self-serve)
    # ──────────────────────────────────────────

    async def initiate_custom_plan_payment(
        self,
        db: AsyncSession,
        tenant_id: str,
        custom_plan_id: str,
        provider_code: str,
        wallet_number: str,
        user_id: str,
        user_email: str,
        period: str = "monthly",
    ) -> Dict[str, Any]:
        """
        Start a Link Gateway payment for a draft custom plan.

        Charges the plan's pre-computed price (monthly or yearly) and, once
        the OTP is confirmed, activates the custom plan directly — no staff
        intervention needed.
        """
        if period not in VALID_PERIODS:
            raise SubscriptionEngineError("مدة الاشتراك غير صالحة (monthly أو yearly)")

        cp_result = await db.execute(
            text("""
                SELECT cp.id, cp.name, cp.base_plan_id, cp.status,
                       cp.total_price_monthly, cp.total_price_yearly,
                       p.code AS base_plan_code, p.currency
                FROM custom_plans cp
                LEFT JOIN plans p ON p.id = cp.base_plan_id
                WHERE cp.id = :cpid AND cp.tenant_id = :tid
            """),
            {"cpid": custom_plan_id, "tid": tenant_id},
        )
        custom_plan = cp_result.mappings().first()
        if not custom_plan:
            raise SubscriptionEngineError("الباقة المخصصة غير موجودة")
        if custom_plan["status"] == "active":
            raise SubscriptionEngineError("هذه الباقة المخصصة مفعّلة بالفعل")

        if period == "yearly":
            amount = float(custom_plan["total_price_yearly"] or 0)
            if amount <= 0:
                raise SubscriptionEngineError("هذه الباقة لا تدعم الاشتراك السنوي")
        else:
            amount = float(custom_plan["total_price_monthly"] or 0)
        if amount <= 0:
            raise SubscriptionEngineError("سعر الباقة المخصصة غير صالح")

        currency = custom_plan["currency"] or "YER"
        order_id = f"custom_{custom_plan_id[:8]}_{period}_{uuid.uuid4().hex[:8]}"

        try:
            payment_result = self.link_service.initiate_payment(
                order_id=order_id,
                app_id="qentry-platform",
                provider_code=provider_code,
                wallet_number=wallet_number,
                amount=amount,
                currency=currency,
                metadata={
                    "tenant_id": tenant_id,
                    "custom_plan_id": custom_plan_id,
                    "user_id": user_id,
                    "type": "custom_plan",
                    "period": period,
                },
            )
            if hasattr(payment_result, '__await__'):
                payment_result = await payment_result
        except LinkPaymentError as e:
            raise SubscriptionEngineError(
                f"فشل بدء عملية الدفع: {str(e)}",
                detail=str(e),
            )

        link_payment_id = payment_result.get("paymentId")
        if not link_payment_id:
            raise SubscriptionEngineError("لم يتم إرجاع معرف الدفع من البوابة")

        # plan_id references the base plan — the custom plan itself lives in metadata
        pending_result = await db.execute(
            text("""
                INSERT INTO pending_subscriptions
                    (tenant_id, plan_id, provider, provider_agreement_id,
                     payer_email, metadata)
                VALUES
                    (:tid, :plan_id, 'link', :payment_id,
                     :email, CAST(:metadata AS jsonb))
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "plan_id": str(custom_plan["base_plan_id"]),
                "payment_id": link_payment_id,
                "email": user_email,
                "metadata": json.dumps({
                    "tenant_id": tenant_id,
                    "type": "custom_plan",
                    "custom_plan_id": custom_plan_id,
                    "base_plan_code": custom_plan["base_plan_code"] or "starter",
                    "provider_code": provider_code,
                    "wallet_number": wallet_number,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": currency,
                    "period": period,
                    "user_id": user_id,
                }),
            },
        )
        pending_row = pending_result.mappings().first()

        # Mark the draft as awaiting payment so it cannot be edited mid-flight
        await db.execute(
            text("UPDATE custom_plans SET status = 'pending_payment', updated_at = now() WHERE id = :cpid AND status = 'draft'"),
            {"cpid": custom_plan_id},
        )
        await db.commit()

        return {
            "payment_id": link_payment_id,
            "status": payment_result.get("status", "OTP_REQUIRED"),
            "fees": payment_result.get("fees", 0),
            "total_amount": payment_result.get("totalAmount", amount),
            "expires_at": payment_result.get("expiresAt"),
            "pending_subscription_id": str(pending_row["id"]),
            "custom_plan_id": custom_plan_id,
            "period": period,
            "amount": amount,
        }

    # ──────────────────────────────────────────
    # Shared activation (used by confirm & recover)
    # ──────────────────────────────────────────

    async def _load_pending(
        self,
        db: AsyncSession,
        tenant_id: str,
        payment_id: str,
    ) -> tuple[Any, Dict[str, Any]]:
        """Load the pending subscription row + parsed metadata for a payment."""
        pending_result = await db.execute(
            text("""
                SELECT id, plan_id, metadata
                FROM pending_subscriptions
                WHERE provider_agreement_id = :payment_id
                  AND tenant_id = :tid
                  AND provider = 'link'
                ORDER BY created_at DESC LIMIT 1
                FOR UPDATE
            """),
            {"payment_id": payment_id, "tid": tenant_id},
        )
        pending = pending_result.mappings().first()
        if not pending:
            raise SubscriptionEngineError("لم يتم العثور على عملية دفع معلقة")
        metadata = pending["metadata"] if isinstance(pending["metadata"], dict) else json.loads(pending["metadata"])
        return pending, metadata

    async def _activate_pending(
        self,
        db: AsyncSession,
        tenant_id: str,
        pending: Any,
        metadata: Dict[str, Any],
        payment_id: str,
        transaction_id: str,
        paid_at: Optional[str],
    ) -> Dict[str, Any]:
        """
        Activate a subscription from a confirmed payment.

        Runs as a single transaction: subscription swap, tenant plan update,
        financial record in subscription_payments, and pending cleanup all
        succeed or roll back together.
        """
        plan_code = metadata.get("plan_code") or metadata.get("base_plan_code", "starter")
        period = metadata.get("period", "monthly")

        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=self._period_days(period))

        if metadata.get("type") == "custom_plan":
            return await self._activate_custom_plan(
                db, tenant_id, pending, metadata, payment_id,
                transaction_id, paid_at, now, period_end,
            )

        # A standard subscription replaces any custom entitlement. Without
        # this, resolve_plan would keep returning the older custom plan.
        await db.execute(text("""
            UPDATE custom_plans SET status = 'expired', updated_at = now()
            WHERE tenant_id = :tid AND status = 'active'
        """), {"tid": tenant_id})

        # Deactivate old subscriptions
        await db.execute(
            text("""
                UPDATE subscriptions
                SET status = 'canceled', canceled_at = now()
                WHERE tenant_id = :tid AND status IN ('active', 'trialing')
            """),
            {"tid": tenant_id},
        )

        # Create new subscription
        sub_result = await db.execute(
            text("""
                INSERT INTO subscriptions
                    (tenant_id, plan_id, provider, provider_customer_id,
                     provider_subscription_id, status,
                     current_period_start, current_period_end)
                VALUES
                    (:tid, :plan_id, 'link', :wallet_number,
                     :transaction_id, 'active',
                     :period_start, :period_end)
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "plan_id": str(pending["plan_id"]),
                "wallet_number": metadata.get("wallet_number", ""),
                "transaction_id": transaction_id,
                "period_start": now,
                "period_end": period_end,
            },
        )
        sub_row = sub_result.mappings().first()

        # Update tenant plan
        await db.execute(
            text("UPDATE tenants SET plan = :plan_code, updated_at = now() WHERE id = CAST(:tid AS uuid)"),
            {"plan_code": plan_code, "tid": str(tenant_id)},
        )

        # Record the payment in the financial ledger (subscription_payments).
        # The unique index on link_payment_id makes a retried activation
        # idempotent instead of duplicating the receipt.
        await db.execute(
            text("""
                INSERT INTO subscription_payments
                    (subscription_id, tenant_id, link_payment_id, transaction_id,
                     amount, currency, provider_code, wallet_number,
                     period, status, paid_at)
                VALUES
                    (:sub_id, :tid, :payment_id, :tx_id,
                     :amount, :currency, :provider_code, :wallet,
                     :period, 'success', :paid_at)
                ON CONFLICT (link_payment_id) DO NOTHING
            """),
            {
                "sub_id": str(sub_row["id"]),
                "tid": tenant_id,
                "payment_id": payment_id,
                "tx_id": transaction_id,
                "amount": metadata.get("amount", 0),
                "currency": metadata.get("currency", "YER"),
                "provider_code": metadata.get("provider_code", ""),
                "wallet": metadata.get("wallet_number", ""),
                "period": period,
                "paid_at": paid_at or now.isoformat(),
            },
        )

        # Delete pending subscription
        await db.execute(
            text("DELETE FROM pending_subscriptions WHERE id = :id"),
            {"id": str(pending["id"])},
        )

        await db.commit()

        return {
            "subscription_id": str(sub_row["id"]),
            "plan_code": plan_code,
            "status": "active",
            "period": period,
            "current_period_start": now.isoformat(),
            "current_period_end": period_end.isoformat(),
            "transaction_id": transaction_id,
        }

    async def _activate_custom_plan(
        self,
        db: AsyncSession,
        tenant_id: str,
        pending: Any,
        metadata: Dict[str, Any],
        payment_id: str,
        transaction_id: str,
        paid_at: Optional[str],
        now: datetime,
        period_end: datetime,
    ) -> Dict[str, Any]:
        """Activate a paid custom plan: expire the old one, set validity window,
        record the payment, and align the tenant's cached plan code."""
        custom_plan_id = metadata["custom_plan_id"]
        base_plan_code = metadata.get("base_plan_code", "starter")
        period = metadata.get("period", "monthly")

        # A custom plan replaces the standard subscription for the same
        # billing period; do not leave a paid entitlement silently active
        # underneath it after the custom plan expires.
        await db.execute(text("""
            UPDATE subscriptions
            SET status = 'canceled', canceled_at = now()
            WHERE tenant_id = :tid AND status IN ('active', 'trialing')
        """), {"tid": tenant_id})

        # Expire any currently active custom plan for the tenant
        await db.execute(
            text("""
                UPDATE custom_plans
                SET status = 'expired', updated_at = now()
                WHERE tenant_id = :tid AND status = 'active'
            """),
            {"tid": tenant_id},
        )

        # Activate the paid custom plan
        activate_result = await db.execute(
            text("""
                UPDATE custom_plans
                SET status = 'active', activated_at = :now,
                    activated_by = CAST(:actor AS uuid),
                    payment_reference = :payment_reference,
                    valid_until = :valid_until, updated_at = now()
                WHERE id = :cpid AND tenant_id = :tid
                  AND status IN ('draft', 'pending_payment', 'expired')
                RETURNING id
            """),
            {
                "cpid": custom_plan_id,
                "tid": tenant_id,
                "now": now,
                "actor": metadata.get("user_id"),
                "payment_reference": transaction_id or payment_id,
                "valid_until": period_end,
            },
        )
        if not activate_result.mappings().first():
            raise SubscriptionEngineError("تعذر تفعيل الباقة المخصصة — حالتها لا تسمح بذلك")

        # Align the tenant's cached plan code with the base plan
        await db.execute(
            text("UPDATE tenants SET plan = :plan_code, updated_at = now() WHERE id = CAST(:tid AS uuid)"),
            {"plan_code": base_plan_code, "tid": tenant_id},
        )

        # Record the payment (no subscription row for custom plans)
        await db.execute(
            text("""
                INSERT INTO subscription_payments
                    (subscription_id, tenant_id, link_payment_id, transaction_id,
                     amount, currency, provider_code, wallet_number,
                     period, status, paid_at)
                VALUES
                    (NULL, :tid, :payment_id, :tx_id,
                     :amount, :currency, :provider_code, :wallet,
                     :period, 'success', :paid_at)
                ON CONFLICT (link_payment_id) DO NOTHING
            """),
            {
                "tid": tenant_id,
                "payment_id": payment_id,
                "tx_id": transaction_id,
                "amount": metadata.get("amount", 0),
                "currency": metadata.get("currency", "YER"),
                "provider_code": metadata.get("provider_code", ""),
                "wallet": metadata.get("wallet_number", ""),
                "period": period,
                "paid_at": paid_at or now.isoformat(),
            },
        )

        await db.execute(
            text("DELETE FROM pending_subscriptions WHERE id = :id"),
            {"id": str(pending["id"])},
        )
        await db.commit()

        return {
            "custom_plan_id": custom_plan_id,
            "plan_code": base_plan_code,
            "status": "active",
            "period": period,
            "valid_until": period_end.isoformat(),
            "transaction_id": transaction_id,
        }

    # ──────────────────────────────────────────
    # Step 2: Confirm OTP → Activate Subscription
    # ──────────────────────────────────────────

    async def confirm_subscription(
        self,
        db: AsyncSession,
        tenant_id: str,
        payment_id: str,
        otp: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Confirm OTP payment and activate the subscription.

        Returns:
            {
                "subscription_id": "uuid",
                "plan_code": "pro",
                "status": "active",
                "current_period_end": "...",
                "transaction_id": "..."
            }
        """
        # 1. Find pending subscription
        pending, metadata = await self._load_pending(db, tenant_id, payment_id)

        # 2. Confirm payment with OTP via Link Gateway
        try:
            confirm_result = self.link_service.confirm_payment(payment_id, otp)
            if hasattr(confirm_result, '__await__'):
                confirm_result = await confirm_result
        except LinkPaymentError as e:
            raise SubscriptionEngineError(
                f"فشل تأكيد الدفع: {str(e)}",
                detail=str(e),
            )

        payment_status = confirm_result.get("status", "")
        if payment_status != "SUCCESS":
            raise SubscriptionEngineError(
                f"لم يتم تأكيد الدفع. الحالة: {payment_status}",
                detail=str(confirm_result),
            )

        # 3. Activate the subscription
        return await self._activate_pending(
            db=db,
            tenant_id=tenant_id,
            pending=pending,
            metadata=metadata,
            payment_id=payment_id,
            transaction_id=confirm_result.get("transactionId", ""),
            paid_at=confirm_result.get("paidAt"),
        )

    # ──────────────────────────────────────────
    # Failure Recovery (payment succeeded, activation failed)
    # ──────────────────────────────────────────

    async def recover_subscription(
        self,
        db: AsyncSession,
        tenant_id: str,
        payment_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Complete activation for a payment that already succeeded at the
        gateway but whose activation never finished (e.g. a transient DB
        error after OTP confirmation). Never charges the wallet again.
        """
        # A successful activation may have committed while its HTTP response
        # was lost. In that case the pending row is intentionally gone; return
        # the immutable financial-ledger result instead of reporting failure.
        completed = await db.execute(text("""
            SELECT sp.transaction_id, sp.paid_at, sp.period, sp.subscription_id,
                   s.current_period_start, s.current_period_end, p.code AS plan_code
            FROM subscription_payments sp
            LEFT JOIN subscriptions s ON s.id = sp.subscription_id
            LEFT JOIN plans p ON p.id = s.plan_id
            WHERE sp.tenant_id = :tid AND sp.link_payment_id = :payment_id
              AND sp.status = 'success'
            LIMIT 1
        """), {"tid": tenant_id, "payment_id": payment_id})
        completed_row = completed.mappings().first()
        if completed_row:
            if completed_row["subscription_id"]:
                return {
                    "subscription_id": str(completed_row["subscription_id"]),
                    "plan_code": completed_row["plan_code"],
                    "status": "active",
                    "period": completed_row["period"],
                    "current_period_start": completed_row["current_period_start"].isoformat(),
                    "current_period_end": completed_row["current_period_end"].isoformat(),
                    "transaction_id": completed_row["transaction_id"] or "",
                }
            custom = await db.execute(text("""
                SELECT cp.id, p.code AS plan_code, cp.valid_until
                FROM custom_plans cp JOIN plans p ON p.id = cp.base_plan_id
                WHERE cp.tenant_id = :tid AND cp.status = 'active'
                  AND cp.payment_reference = :tx
                LIMIT 1
            """), {"tid": tenant_id, "tx": completed_row["transaction_id"]})
            custom_row = custom.mappings().first()
            if custom_row:
                return {
                    "custom_plan_id": str(custom_row["id"]),
                    "plan_code": custom_row["plan_code"],
                    "status": "active",
                    "period": completed_row["period"],
                    "valid_until": custom_row["valid_until"].isoformat(),
                    "transaction_id": completed_row["transaction_id"] or "",
                }

        pending, metadata = await self._load_pending(db, tenant_id, payment_id)

        try:
            status_result = self.link_service.get_payment_status(payment_id)
            if hasattr(status_result, '__await__'):
                status_result = await status_result
        except LinkPaymentError as e:
            raise SubscriptionEngineError(
                f"تعذر التحقق من حالة الدفع: {str(e)}",
                detail=str(e),
            )

        payment_status = status_result.get("status", "")
        if payment_status != "SUCCESS":
            raise SubscriptionEngineError(
                f"الدفع لم يكتمل بعد. الحالة الحالية: {payment_status}",
                detail=str(status_result),
            )

        logger.warning(
            "Recovering subscription activation for payment %s (tenant %s)",
            payment_id, tenant_id,
        )
        return await self._activate_pending(
            db=db,
            tenant_id=tenant_id,
            pending=pending,
            metadata=metadata,
            payment_id=payment_id,
            transaction_id=status_result.get("transactionId", ""),
            paid_at=status_result.get("paidAt"),
        )

    # ──────────────────────────────────────────
    # Manual Renewal
    # ──────────────────────────────────────────

    async def initiate_renewal(
        self,
        db: AsyncSession,
        tenant_id: str,
        provider_code: str,
        wallet_number: str,
        user_id: str,
        user_email: str,
        period: str = "monthly",
    ) -> Dict[str, Any]:
        """
        Initiate renewal for the current subscription.

        Finds the current (or recently expired) subscription and
        starts a new payment cycle.
        """
        # Find current or most recent subscription
        sub_result = await db.execute(
            text("""
                SELECT s.id, s.plan_id, p.code AS plan_code, p.price_monthly, p.price_yearly, p.currency
                FROM subscriptions s
                JOIN plans p ON p.id = s.plan_id
                WHERE s.tenant_id = :tid
                  AND s.status IN ('active', 'canceled', 'past_due')
                ORDER BY s.created_at DESC LIMIT 1
            """),
            {"tid": tenant_id},
        )
        sub = sub_result.mappings().first()
        if not sub:
            raise SubscriptionEngineError("لا يوجد اشتراك للتجديد")

        # Re-use initiate_subscription for the same plan
        return await self.initiate_subscription(
            db=db,
            tenant_id=tenant_id,
            plan_code=sub["plan_code"],
            provider_code=provider_code,
            wallet_number=wallet_number,
            user_id=user_id,
            user_email=user_email,
            period=period,
        )

    # ──────────────────────────────────────────
    # Expiry Check (called by scheduler)
    # ──────────────────────────────────────────

    async def check_expired_subscriptions(self, db: AsyncSession) -> list:
        """
        Find expired subscriptions and downgrade them to starter.

        Returns the list of tenant ids that were downgraded (for notifications).
        """
        result = await db.execute(
            text("""
                UPDATE subscriptions
                SET status = 'canceled', canceled_at = now()
                WHERE status = 'active'
                  AND current_period_end IS NOT NULL
                  AND current_period_end < now()
                RETURNING tenant_id
            """)
        )
        expired_tenant_ids = [str(row[0]) for row in result.fetchall()]

        custom_result = await db.execute(text("""
            UPDATE custom_plans
            SET status = 'expired', updated_at = now()
            WHERE status = 'active' AND valid_until IS NOT NULL
              AND valid_until < now()
            RETURNING tenant_id
        """))
        expired_tenant_ids.extend(str(row[0]) for row in custom_result.fetchall())
        expired_tenant_ids = list(dict.fromkeys(expired_tenant_ids))

        for tid in expired_tenant_ids:
            await db.execute(
                text("UPDATE tenants SET plan = 'starter', updated_at = now() WHERE id = :tid"),
                {"tid": tid},
            )
            logger.info("Subscription expired, downgraded tenant %s to starter", tid)

        if expired_tenant_ids:
            await db.commit()

        return expired_tenant_ids

    async def get_expiring_subscriptions(
        self, db: AsyncSession, days_ahead: int = 7
    ) -> list:
        """
        Find subscriptions expiring within the given number of days.
        Used for sending renewal reminders.
        """
        result = await db.execute(
            text("""
                SELECT s.id, s.tenant_id, s.current_period_end,
                       p.code AS plan_code, p.name AS plan_name,
                       p.price_monthly, p.currency
                FROM subscriptions s
                JOIN plans p ON p.id = s.plan_id
                WHERE s.status = 'active'
                  AND s.current_period_end IS NOT NULL
                  AND s.current_period_end BETWEEN now() AND now() + make_interval(days => :days)
            """),
            {"days": days_ahead},
        )
        return [dict(row) for row in result.mappings().all()]

    # ──────────────────────────────────────────
    # Pending Cleanup (called by scheduler)
    # ──────────────────────────────────────────

    async def cleanup_pending_subscriptions(self, db: AsyncSession) -> int:
        """
        Delete abandoned pending subscription rows (OTP never confirmed).
        Gateway OTP sessions expire within minutes, so rows older than
        PENDING_TTL_HOURS can never complete.
        """
        result = await db.execute(
            text("""
                DELETE FROM pending_subscriptions
                WHERE provider = 'link'
                  AND created_at < now() - make_interval(hours => :ttl_hours)
                RETURNING id
            """),
            {"ttl_hours": PENDING_TTL_HOURS},
        )
        deleted = len(result.fetchall())
        if deleted:
            await db.commit()
            logger.info("Cleaned up %d abandoned pending subscriptions", deleted)
        return deleted


# ── Singleton ──
_engine: Optional[SubscriptionEngine] = None


def get_subscription_engine() -> SubscriptionEngine:
    """Get or create the SubscriptionEngine singleton."""
    global _engine
    if _engine is None:
        _engine = SubscriptionEngine()
    return _engine
