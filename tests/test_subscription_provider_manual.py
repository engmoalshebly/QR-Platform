"""Regression: manually approved subscriptions (provider='manual') must serialize."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.subscription import SubscriptionWithPlan


@pytest.mark.unit
def test_manual_provider_row_builds_the_response_model():
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid4(), "tenant_id": uuid4(), "plan_id": uuid4(), "provider": "manual",
        "provider_customer_id": "staff_verified", "provider_subscription_id": "REF-1",
        "status": "active", "current_period_start": now,
        "current_period_end": now + timedelta(days=30), "cancel_at_period_end": False,
        "created_at": now, "updated_at": now,
        "plan_code": "pro", "plan_name": "Pro", "days_left": 30, "renewal_open": True,
    }
    model = SubscriptionWithPlan(**row)
    assert model.provider.value == "manual" and model.days_left == 30 and model.renewal_open is True
