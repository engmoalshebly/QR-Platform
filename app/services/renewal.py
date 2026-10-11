"""Renewal policy for manually approved subscriptions.

Payments are verified out of band, so a renewal is an ordinary plan request that
staff approve.  This module is the single place that answers three questions:

  * when may an owner ask to renew?            -> is_renewal_open()
  * what end date should a renewal get?         -> renewal_valid_until()
  * is a proposed end date acceptable?          -> check_same_plan_extension()

Renewing the SAME plan while it is still running must extend the paid period
(remaining days are kept), never restart it from today.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

# An owner may request a renewal this long before the period ends (and at any
# time after it has ended).  Requests earlier than this are rejected so the
# review queue is not filled with premature renewals.
RENEWAL_WINDOW_DAYS = 30

PERIOD_DAYS = {"monthly": 30, "yearly": 365}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def days_left(period_end: datetime | None, now: datetime | None = None) -> int | None:
    """Whole days until the end (rounded up); 0 once it has passed."""
    if period_end is None:
        return None
    now = now or datetime.now(timezone.utc)
    seconds = (_aware(period_end) - now).total_seconds()
    return max(0, -(-int(seconds) // 86400)) if seconds > 0 else 0


def is_renewal_open(period_end: datetime | None, now: datetime | None = None) -> bool:
    """True from RENEWAL_WINDOW_DAYS before the end, and after it."""
    if period_end is None:
        return False
    now = now or datetime.now(timezone.utc)
    return _aware(period_end) - now <= timedelta(days=RENEWAL_WINDOW_DAYS)


def renewal_valid_until(
    current_end: datetime | None,
    period: str,
    *,
    same_plan: bool,
    now: datetime | None = None,
) -> datetime:
    """Suggested end date for an approval.

    Same plan, still running  -> current end + one period (days kept).
    Anything else (plan change, expired, first purchase) -> now + one period.
    """
    now = now or datetime.now(timezone.utc)
    days = PERIOD_DAYS.get(period, PERIOD_DAYS["monthly"])
    base = now
    if same_plan and current_end is not None and _aware(current_end) > now:
        base = _aware(current_end)
    return base + timedelta(days=days)


def check_same_plan_extension(
    current_end: datetime | None,
    valid_until: datetime,
    *,
    same_plan: bool,
    now: datetime | None = None,
) -> None:
    """Refuse an approval that would SHORTEN a paid, still-running period."""
    now = now or datetime.now(timezone.utc)
    if not same_plan or current_end is None or _aware(current_end) <= now:
        return
    if _aware(valid_until) <= _aware(current_end):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "هذا تجديد لنفس الباقة وهي سارية حتى "
                f"{_aware(current_end).date().isoformat()}؛ يجب أن يتجاوز تاريخ النهاية الجديد "
                "نهاية الفترة الحالية حتى لا يخسر العميل أياماً مدفوعة."
            ),
        )
