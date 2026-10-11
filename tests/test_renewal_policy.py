"""Renewal date rules (pure functions, no database)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services import renewal as r

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


@pytest.mark.unit
def test_same_plan_renewal_keeps_the_remaining_days():
    end = NOW + timedelta(days=10)
    assert r.renewal_valid_until(end, "monthly", same_plan=True, now=NOW) == end + timedelta(days=30)
    assert r.renewal_valid_until(end, "yearly", same_plan=True, now=NOW) == end + timedelta(days=365)


@pytest.mark.unit
@pytest.mark.parametrize("current_end, same_plan", [
    (NOW - timedelta(days=3), True),    # already expired: starts today
    (NOW + timedelta(days=10), False),  # plan change: starts today
    (None, True),                       # first purchase
])
def test_other_cases_start_from_today(current_end, same_plan):
    assert r.renewal_valid_until(current_end, "monthly", same_plan=same_plan, now=NOW) == NOW + timedelta(days=30)


@pytest.mark.unit
def test_window_opens_30_days_before_the_end_and_stays_open_after():
    assert r.is_renewal_open(NOW + timedelta(days=31), NOW) is False
    assert r.is_renewal_open(NOW + timedelta(days=30), NOW) is True
    assert r.is_renewal_open(NOW + timedelta(days=1), NOW) is True
    assert r.is_renewal_open(NOW - timedelta(days=5), NOW) is True
    assert r.is_renewal_open(None, NOW) is False


@pytest.mark.unit
def test_days_left_rounds_up_and_never_goes_negative():
    assert r.days_left(NOW + timedelta(hours=1), NOW) == 1
    assert r.days_left(NOW + timedelta(days=3, minutes=1), NOW) == 4
    assert r.days_left(NOW - timedelta(days=2), NOW) == 0
    assert r.days_left(None, NOW) is None


@pytest.mark.unit
def test_approval_may_not_shorten_a_running_same_plan_period():
    end = NOW + timedelta(days=10)
    with pytest.raises(HTTPException) as caught:
        r.check_same_plan_extension(end, end - timedelta(days=1), same_plan=True, now=NOW)
    assert caught.value.status_code == 422
    r.check_same_plan_extension(end, end + timedelta(days=1), same_plan=True, now=NOW)       # extends: fine
    r.check_same_plan_extension(end, NOW + timedelta(days=5), same_plan=False, now=NOW)      # plan change: fine
    r.check_same_plan_extension(NOW - timedelta(days=1), NOW + timedelta(days=5), same_plan=True, now=NOW)  # expired: fine
