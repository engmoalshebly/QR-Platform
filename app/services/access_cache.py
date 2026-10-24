"""Short-lived, in-process cache for the tenant checks run on every request.

TenantResolutionMiddleware looks up the tenant row and the caller's active
membership before each tenant-scoped request.  Each lookup opened its own
database connection, which dominated request latency.  The answers rarely
change, so they are kept for a few seconds:

* tenant rows for TENANT_TTL seconds, so a suspension applies within that time
  even on a path that forgets to invalidate;
* only *positive* membership answers, for MEMBERSHIP_TTL seconds, so a newly
  added member is never refused by a stale entry, and a removed member keeps
  access for at most that long.

Writers that change tenant status or memberships call the invalidate helpers so
the change applies at once in this process.
"""
from __future__ import annotations

import time
from typing import Any

TENANT_TTL = 30.0
MEMBERSHIP_TTL = 15.0
_MAX_ENTRIES = 5000

_tenants: dict[str, tuple[float, dict[str, Any]]] = {}
_members: dict[tuple[str, str], float] = {}


def _trim(store: dict) -> None:
    if len(store) > _MAX_ENTRIES:
        store.clear()


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    hit = _tenants.get(tenant_id)
    if hit and time.monotonic() - hit[0] < TENANT_TTL:
        return dict(hit[1])
    return None


def put_tenant(tenant: dict[str, Any]) -> None:
    _trim(_tenants)
    _tenants[str(tenant["id"])] = (time.monotonic(), dict(tenant))


def is_member(tenant_id: str, user_id: str) -> bool:
    stamp = _members.get((tenant_id, user_id))
    return stamp is not None and time.monotonic() - stamp < MEMBERSHIP_TTL


def put_member(tenant_id: str, user_id: str) -> None:
    _trim(_members)
    _members[(tenant_id, user_id)] = time.monotonic()


def invalidate_tenant(tenant_id: object) -> None:
    """Forget the tenant row and every membership answer for that tenant."""
    key = str(tenant_id)
    _tenants.pop(key, None)
    for member_key in [k for k in _members if k[0] == key]:
        _members.pop(member_key, None)


def clear() -> None:
    _tenants.clear()
    _members.clear()
