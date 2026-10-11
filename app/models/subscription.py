from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum

__all__ = [
    "PaymentProvider",
    "SubscriptionStatus",
    "SubscriptionRead",
    "SubscriptionWithPlan",
]


class PaymentProvider(str, Enum):
    stripe = "stripe"
    paypal = "paypal"
    link = "link"
    link_wallet = "link_wallet"
    mock_bypass = "mock_bypass"
    # Subscriptions approved by platform staff after out-of-band payment.
    manual = "manual"


class SubscriptionStatus(str, Enum):
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"
    incomplete = "incomplete"


class SubscriptionRead(BaseModel):
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    provider: PaymentProvider
    provider_customer_id: Optional[str] = None
    provider_subscription_id: Optional[str] = None
    status: SubscriptionStatus
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    trial_ends_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SubscriptionWithPlan(SubscriptionRead):
    plan_code: str
    plan_name: str
    # Renewal state, computed by the API (app/services/renewal.py).
    days_left: Optional[int] = None
    renewal_open: bool = False
