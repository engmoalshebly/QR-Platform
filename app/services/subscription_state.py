"""Is this workspace's paid plan still valid?  (read-only mode on expiry)

A workspace is "expired" when its billing account had a paid plan whose period
ended, no paid plan is active now, and staff have not moved it to a free plan
since.  Accounts that were only ever on the free plan are never expired, and
the free plan itself has no read-only state.

Evaluated per request for writes, so results are cached for a few seconds and
dropped explicitly when staff approve a renewal.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.database import AsyncSessionLocal

FREE_PLAN_CODES = ("starter", "free")
_CACHE_TTL_SECONDS = 15.0
_cache: dict[str, tuple[float, "SubscriptionState"]] = {}


@dataclass(frozen=True)
class SubscriptionState:
    expired: bool
    billing_tenant_id: str
    ended_at: datetime | None = None
    plan_name: str | None = None


# Active paid entitlement: a running paid subscription or an activated custom plan.
_ACTIVE_PAID_SQL = """
    SELECT 1
    FROM subscriptions s JOIN plans p ON p.id = s.plan_id
    WHERE s.tenant_id = :b AND s.status IN ('active', 'trialing')
      AND lower(p.code) <> ALL(:free)
      AND (s.current_period_end IS NULL OR s.current_period_end > now())
    UNION ALL
    SELECT 1
    FROM custom_plans cp
    WHERE cp.tenant_id = :b AND cp.status = 'active' AND cp.activated_at IS NOT NULL
      AND (cp.valid_until IS NULL OR cp.valid_until > now())
    LIMIT 1
"""

# The most recent paid period that has already ended.
_LAST_PAID_END_SQL = """
    SELECT end_at, plan_name FROM (
        SELECT s.current_period_end AS end_at, p.name AS plan_name
        FROM subscriptions s JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = :b AND lower(p.code) <> ALL(:free)
          AND s.current_period_end IS NOT NULL AND s.current_period_end <= now()
        UNION ALL
        SELECT cp.valid_until AS end_at, cp.name AS plan_name
        FROM custom_plans cp
        WHERE cp.tenant_id = :b AND cp.activated_at IS NOT NULL
          AND cp.valid_until IS NOT NULL AND cp.valid_until <= now()
    ) x
    ORDER BY end_at DESC LIMIT 1
"""

# Staff may deliberately move an account to the free plan after a paid one ended.
_FREE_AFTER_SQL = """
    SELECT 1 FROM subscriptions s JOIN plans p ON p.id = s.plan_id
    WHERE s.tenant_id = :b AND s.status IN ('active', 'trialing')
      AND lower(p.code) = ANY(:free) AND s.created_at > :ended
    LIMIT 1
"""


async def compute_subscription_state(db, tenant_id: UUID | str) -> SubscriptionState:
    from app.services.entitlement_service import resolve_billing_tenant

    billing = await resolve_billing_tenant(db, UUID(str(tenant_id)))
    params = {"b": str(billing), "free": list(FREE_PLAN_CODES)}

    if (await db.execute(text(_ACTIVE_PAID_SQL), params)).first():
        return SubscriptionState(False, str(billing))

    last = (await db.execute(text(_LAST_PAID_END_SQL), params)).mappings().first()
    if not last:
        return SubscriptionState(False, str(billing))  # never had a paid plan

    moved = (await db.execute(text(_FREE_AFTER_SQL), {**params, "ended": last["end_at"]})).first()
    if moved:
        return SubscriptionState(False, str(billing))

    return SubscriptionState(True, str(billing), last["end_at"], last["plan_name"])


async def get_subscription_state(tenant_id: UUID | str) -> SubscriptionState:
    key = str(tenant_id)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    async with AsyncSessionLocal() as db:
        state = await compute_subscription_state(db, tenant_id)
    _cache[key] = (now, state)
    return state


def invalidate_subscription_state() -> None:
    """Called after a renewal/plan change so the next request sees it at once."""
    _cache.clear()


# ── What a read-only workspace may still write ──────────────────────────────

_ALWAYS_ALLOWED_PREFIXES = (
    "/api/v1/subscriptions/request",   # send a renewal request
    "/api/v1/custom-plans",            # custom plan builder + its renewal request
    "/api/v1/notifications",           # mark notifications as read
    "/api/v1/profile",                 # own profile
)
_CHECKIN_PREFIXES = ("/api/v1/mobile/",)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def write_allowed_when_expired(method: str, path: str, *, allow_checkin: bool = False) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    if path.startswith(_ALWAYS_ALLOWED_PREFIXES):
        return True
    if allow_checkin and path.startswith(_CHECKIN_PREFIXES):
        return True
    return False
