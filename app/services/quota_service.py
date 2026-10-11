"""
Centralized Quota Validation Service.

Provides a single reusable function for checking event invitation quotas
across all creation endpoints (digital_invitations, fast_invitations,
batches, registration_forms).

Design decisions:
- quota = 0  →  unlimited (no validation)
- quota > 0  →  strict enforcement: used + requested <= quota
- Counts only active invitations (excludes 'revoked' and 'expired')
"""
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.services.limit_errors import event_quota_exceeded

logger = logging.getLogger(__name__)


async def check_quota(
    db: AsyncSession,
    tenant_id: str,
    event_id: str,
    ticket_class: str,
    count: int = 1,
) -> dict:
    """
    Check if an event has room for more invitations of a given class.

    Args:
        db: Database session
        tenant_id: Tenant UUID string
        event_id: Event UUID string
        ticket_class: 'vip' or 'normal'
        count: Number of invitations to add

    Returns:
        dict with keys: quota, used, remaining, unlimited

    Raises:
        HTTPException 404 if event not found
        HTTPException 400 if quota would be exceeded
    """
    # All invitation creation and RSVP companion changes for one event share
    # this transaction lock. A read-then-insert quota check without it allows
    # two concurrent requests to both observe the last available place.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"invitation-quota:{event_id}"},
    )

    result = await db.execute(
        text("""
            SELECT
                CASE WHEN CAST(:tc AS ticket_class) = 'vip'::ticket_class
                     THEN e.vip_quota ELSE e.normal_quota END AS quota,
                COALESCE(SUM(COALESCE(i.guest_count, 1)) FILTER (
                    WHERE i.ticket_class = CAST(:tc AS ticket_class)
                      AND i.status NOT IN ('revoked','expired')
                ), 0) AS used
            FROM events e
            LEFT JOIN invitations i ON i.event_id = e.id
            WHERE e.id = :eid AND e.tenant_id = :tid
            GROUP BY e.id
        """),
        {"eid": event_id, "tid": tenant_id, "tc": ticket_class},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الحدث غير موجود")

    quota = row["quota"]
    used = row["used"]

    # quota = 0 means unlimited
    if quota > 0 and (used + count) > quota:
        raise event_quota_exceeded(event_id, ticket_class, used, quota, count)

    return {
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used) if quota > 0 else None,
        "unlimited": quota == 0,
    }


async def check_quota_mixed(
    db: AsyncSession,
    tenant_id: str,
    event_id: str,
    invitations_data: List[Dict[str, Any]],
) -> dict:
    """
    Check quota for a mixed batch of VIP and normal invitations.

    Used by fast_invitations where a single request may contain
    both VIP and normal invitations.

    Args:
        db: Database session
        tenant_id: Tenant UUID string
        event_id: Event UUID string
        invitations_data: List of invitation dicts with 'ticket_class' key

    Returns:
        dict with vip and normal quota info

    Raises:
        HTTPException if any quota would be exceeded
    """
    # Count requested by class
    vip_count = sum(
        max(1, int(inv.get('guest_count') or 1)) for inv in invitations_data
        if inv.get('ticket_class') == 'vip'
    )
    normal_count = sum(
        max(1, int(inv.get('guest_count') or 1)) for inv in invitations_data
        if inv.get('ticket_class', 'normal') == 'normal'
    )

    # Use the same event-level lock as check_quota so a mixed bulk operation
    # cannot race a single invite or an RSVP companion update.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"invitation-quota:{event_id}"},
    )

    # Get current usage and quotas in a single query. Quotas represent people,
    # not invitation rows: a group invitation consumes its guest_count.
    result = await db.execute(
        text("""
            SELECT
                e.vip_quota,
                e.normal_quota,
                COALESCE(SUM(CASE WHEN i.ticket_class = 'vip'
                                  AND i.status NOT IN ('revoked','expired')
                             THEN COALESCE(i.guest_count, 1) ELSE 0 END), 0) as vip_used,
                COALESCE(SUM(CASE WHEN i.ticket_class = 'normal'
                                  AND i.status NOT IN ('revoked','expired')
                             THEN COALESCE(i.guest_count, 1) ELSE 0 END), 0) as normal_used
            FROM events e
            LEFT JOIN invitations i ON i.event_id = e.id
            WHERE e.id = :eid AND e.tenant_id = :tid
            GROUP BY e.id
        """),
        {"eid": event_id, "tid": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الحدث غير موجود")

    vip_quota = row["vip_quota"]
    normal_quota = row["normal_quota"]
    vip_used = row["vip_used"]
    normal_used = row["normal_used"]

    # Check VIP quota (0 = unlimited)
    if vip_quota > 0 and vip_count > 0 and (vip_used + vip_count) > vip_quota:
        raise event_quota_exceeded(event_id, "vip", vip_used, vip_quota, vip_count)

    # Check normal quota (0 = unlimited)
    if normal_quota > 0 and normal_count > 0 and (normal_used + normal_count) > normal_quota:
        raise event_quota_exceeded(event_id, "normal", normal_used, normal_quota, normal_count)

    return {
        "vip": {
            "quota": vip_quota,
            "used": vip_used,
            "remaining": max(0, vip_quota - vip_used) if vip_quota > 0 else None,
            "unlimited": vip_quota == 0,
        },
        "normal": {
            "quota": normal_quota,
            "used": normal_used,
            "remaining": max(0, normal_quota - normal_used) if normal_quota > 0 else None,
            "unlimited": normal_quota == 0,
        },
    }
