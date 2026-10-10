"""Migration v64 + SubscriptionEngine: at most one in-flight Link payment per
billing tenant.

Without this, a double-click or two tabs sends two OTPs to the same wallet;
confirming both charges it twice but only the later subscription period
survives (_activate_pending cancels whatever is active before inserting the
new one).  This is a real billing bug: the tenant pays twice for one period.
"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.subscription_engine import SubscriptionEngine, SubscriptionEngineError


async def _insert_tenant(db: AsyncSession, name: str) -> str:
    tid = str(uuid4())
    await db.execute(text("""
        INSERT INTO tenants (id, name, slug, status, plan) VALUES (:id, :name, :slug, 'active', 'starter')
    """), {"id": tid, "name": name, "slug": f"pay-{tid[:8]}"})
    return tid


@pytest_asyncio.fixture
async def engine(db_session: AsyncSession) -> SubscriptionEngine:
    eng = SubscriptionEngine()
    eng.link_service = AsyncMock()
    eng.link_service.initiate_payment = AsyncMock(side_effect=lambda **kw: {
        "paymentId": f"pay_{uuid4().hex[:10]}",
        "status": "OTP_REQUIRED",
        "fees": 0,
        "totalAmount": kw.get("amount"),
        "expiresAt": None,
    })
    return eng


# ── Database-level backstop ──

@pytest.mark.asyncio
async def test_unique_index_blocks_two_pending_link_payments_for_same_tenant(db_session):
    tenant = await _insert_tenant(db_session, "Payer")
    plan_id = (await db_session.execute(text("SELECT id FROM plans WHERE code = 'pro'"))).scalar()
    await db_session.flush()

    await db_session.execute(text("""
        INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id, payer_email, metadata)
        VALUES (:tid, :pid, 'link', :pay1, 'a@test.com', '{}'::jsonb)
    """), {"tid": tenant, "pid": plan_id, "pay1": "pay_1"})
    await db_session.flush()

    with pytest.raises(IntegrityError, match="uq_pending_subscriptions_one_per_tenant"):
        await db_session.execute(text("""
            INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id, payer_email, metadata)
            VALUES (:tid, :pid, 'link', :pay2, 'a@test.com', '{}'::jsonb)
        """), {"tid": tenant, "pid": plan_id, "pay2": "pay_2"})


@pytest.mark.asyncio
async def test_unique_index_allows_pending_rows_for_different_tenants(db_session):
    a = await _insert_tenant(db_session, "Payer A")
    b = await _insert_tenant(db_session, "Payer B")
    plan_id = (await db_session.execute(text("SELECT id FROM plans WHERE code = 'pro'"))).scalar()
    await db_session.flush()

    for tenant, pay in ((a, "pay_a"), (b, "pay_b")):
        await db_session.execute(text("""
            INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id, payer_email, metadata)
            VALUES (:tid, :pid, 'link', :pay, 'x@test.com', '{}'::jsonb)
        """), {"tid": tenant, "pid": plan_id, "pay": pay})
    # no exception: two different tenants may each have one in-flight payment


# ── Application-level guard (fails fast, before calling Link) ──

@pytest.mark.asyncio
async def test_initiate_subscription_rejects_second_payment_while_one_is_pending(db_session, engine):
    tenant = await _insert_tenant(db_session, "Double Clicker")
    await db_session.flush()

    first = await engine.initiate_subscription(
        db=db_session, tenant_id=tenant, plan_code="pro", provider_code="jawali",
        wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
    )
    assert first["payment_id"]
    assert engine.link_service.initiate_payment.await_count == 1

    with pytest.raises(SubscriptionEngineError, match="يوجد طلب دفع معلّق"):
        await engine.initiate_subscription(
            db=db_session, tenant_id=tenant, plan_code="pro", provider_code="jawali",
            wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
        )
    # The guard must reject before ever sending a second OTP to the wallet.
    assert engine.link_service.initiate_payment.await_count == 1


@pytest.mark.asyncio
async def test_initiate_subscription_allowed_again_once_the_first_is_confirmed(db_session, engine):
    """The guard must not block legitimate renewals once the prior payment is
    resolved (confirmed or cleaned up) -- only a genuinely open one."""
    tenant = await _insert_tenant(db_session, "Renewing Tenant")
    await db_session.flush()

    first = await engine.initiate_subscription(
        db=db_session, tenant_id=tenant, plan_code="pro", provider_code="jawali",
        wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
    )

    engine.link_service.confirm_payment = AsyncMock(return_value={
        "status": "SUCCESS", "transactionId": "tx_1", "paidAt": None,
    })
    confirmed = await engine.confirm_subscription(
        db=db_session, tenant_id=tenant, payment_id=first["payment_id"],
        otp="123456", user_id=str(uuid4()),
    )
    assert confirmed["status"] == "active"

    # The pending row is gone; a second payment (e.g. a plan change) may start.
    second = await engine.initiate_subscription(
        db=db_session, tenant_id=tenant, plan_code="business", provider_code="jawali",
        wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
    )
    assert second["payment_id"] != first["payment_id"]
    assert engine.link_service.initiate_payment.await_count == 2


# ── The exact bug: Link's documented paidAt format must store correctly ──

@pytest.mark.asyncio
async def test_confirm_subscription_stores_a_real_gateway_timestamp(db_session, engine):
    """Link documents paidAt as e.g. "2026-08-20T10:16:30.000Z" (link_payment_service.py).
    JSON has no datetime type, so this is always a str -- asyncpg accepts only
    datetime.date/datetime for a timestamptz column, never a str.  This failed on
    every real, successful confirmation before the fix (after the wallet had
    already been charged), rolling back the subscription, tenant plan and
    payment-ledger INSERT together."""
    tenant = await _insert_tenant(db_session, "Real Gateway Timestamp")
    await db_session.flush()

    started = await engine.initiate_subscription(
        db=db_session, tenant_id=tenant, plan_code="pro", provider_code="jawali",
        wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
    )

    engine.link_service.confirm_payment = AsyncMock(return_value={
        "status": "SUCCESS", "transactionId": "tx_real", "paidAt": "2026-08-20T10:16:30.000Z",
    })
    result = await engine.confirm_subscription(
        db=db_session, tenant_id=tenant, payment_id=started["payment_id"],
        otp="123456", user_id=str(uuid4()),
    )
    assert result["status"] == "active"

    stored = (await db_session.execute(text(
        "SELECT paid_at FROM subscription_payments WHERE tenant_id = :tid"
    ), {"tid": tenant})).scalar()
    assert stored is not None and stored.year == 2026 and stored.month == 8 and stored.day == 20


@pytest.mark.asyncio
async def test_recover_subscription_also_stores_a_real_gateway_timestamp(db_session, engine):
    """recover_subscription() calls the same _activate_pending() with
    status_result['paidAt'] -- it had the identical bug, which meant the
    recovery path for a paid-but-unactivated subscription was itself broken."""
    tenant = await _insert_tenant(db_session, "Recovery Path")
    await db_session.flush()

    started = await engine.initiate_subscription(
        db=db_session, tenant_id=tenant, plan_code="pro", provider_code="jawali",
        wallet_number="777000111", user_id=str(uuid4()), user_email="a@test.com", period="monthly",
    )

    engine.link_service.get_payment_status = AsyncMock(return_value={
        "status": "SUCCESS", "transactionId": "tx_recovered", "paidAt": "2026-08-20T10:16:30.000Z",
    })
    result = await engine.recover_subscription(
        db=db_session, tenant_id=tenant, payment_id=started["payment_id"], user_id=str(uuid4()),
    )
    assert result["status"] == "active"
    # confirm_payment (which would re-spend the OTP) must never be called by recovery.
    engine.link_service.confirm_payment.assert_not_called()


@pytest.mark.asyncio
async def test_custom_plan_activation_stores_a_real_gateway_timestamp(db_session, engine):
    tenant = await _insert_tenant(db_session, "Custom Plan Payer")
    base_plan_id = (await db_session.execute(text("SELECT id FROM plans WHERE code = 'pro'"))).scalar()
    custom_plan_id = str(uuid4())
    await db_session.execute(text("""
        INSERT INTO custom_plans (id, tenant_id, base_plan_id, status,
                                   total_price_monthly, total_price_yearly)
        VALUES (:id, :tid, :bpid, 'draft', 600, 6000)
    """), {"id": custom_plan_id, "tid": tenant, "bpid": base_plan_id})
    await db_session.flush()

    actor = str(uuid4())
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
        ON CONFLICT DO NOTHING
    """), {"id": actor, "email": f"actor-{actor[:8]}@test.com"})
    await db_session.execute(text(
        "INSERT INTO profiles (id, full_name) VALUES (:id, 'Actor') ON CONFLICT DO NOTHING"
    ), {"id": actor})

    started = await engine.initiate_custom_plan_payment(
        db=db_session, tenant_id=tenant, custom_plan_id=custom_plan_id,
        provider_code="jawali", wallet_number="777000111",
        user_id=actor, user_email="a@test.com", period="monthly",
    )

    engine.link_service.confirm_payment = AsyncMock(return_value={
        "status": "SUCCESS", "transactionId": "tx_custom", "paidAt": "2026-08-20T10:16:30.000Z",
    })
    result = await engine.confirm_subscription(
        db=db_session, tenant_id=tenant, payment_id=started["payment_id"],
        otp="123456", user_id=str(uuid4()),
    )
    assert result["status"] == "active"
    assert result["custom_plan_id"] == custom_plan_id
