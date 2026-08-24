"""Shared authorization rules for field-gate shifts and device sessions.

The web management screens and the future PWA deliberately share this module.
Keeping the decision here prevents a hidden UI tab, a legacy gate assignment, or
an administrator role from becoming an accidental scanning bypass.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Mapping
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def hash_device_session_token(token: str) -> str:
    """Return the stable SHA-256 digest stored for an opaque session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_active_gate_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    event_id: UUID,
    gate_id: UUID,
    device_session_id: UUID | None,
    device_session_token: str | None,
    allow_supervisor_scan: bool = True,
) -> Mapping:
    """Return a valid current session or deny the field action.

    This enforces the complete boundary for a scan: the gate belongs to the
    requested event and remains enabled; the event operation belongs to the
    provider workspace; the member is scheduled for this gate; and the device
    session is active inside its shift window.  No tenant role bypass exists.
    """
    if not device_session_id or not device_session_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="يلزم بدء جلسة جهاز فعّالة لهذه الوردية قبل تسجيل الحضور",
        )

    result = await db.execute(
        text("""
            SELECT ds.id, ds.session_token_hash, ds.shift_id, ds.event_id,
                   ds.gate_id, ds.user_id, ds.status AS device_status,
                   sm.role AS shift_role, s.status AS shift_status,
                   s.starts_at, s.ends_at, o.id AS operation_id
            FROM event_gate_device_sessions ds
            JOIN event_gate_shifts s ON s.id = ds.shift_id
            JOIN event_gate_shift_members sm
              ON sm.shift_id = s.id AND sm.user_id = ds.user_id AND sm.is_active
            JOIN event_gates g ON g.id = s.gate_id
            JOIN event_operations o ON o.id = s.operation_id
            LEFT JOIN event_operation_members om
              ON om.operation_id = o.id AND om.user_id = ds.user_id
            WHERE ds.id = :session_id
              AND ds.user_id = :user_id
              AND ds.event_id = :event_id
              AND ds.gate_id = :gate_id
              AND ds.status = 'active'
              AND s.status = 'active'
              AND now() >= s.starts_at
              AND now() < s.ends_at
              AND g.event_id = :event_id
              AND g.is_active = TRUE
              AND o.provider_tenant_id = :tenant_id
              AND o.status NOT IN ('completed', 'closed', 'cancelled')
              AND (o.project_manager_id = ds.user_id OR om.user_id IS NOT NULL)
            LIMIT 1
        """),
        {
            "session_id": str(device_session_id),
            "user_id": str(user_id),
            "event_id": str(event_id),
            "gate_id": str(gate_id),
            "tenant_id": str(tenant_id),
        },
    )
    session = result.mappings().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="جلسة الجهاز أو وردية البوابة غير صالحة لهذه العملية",
        )
    if session["shift_role"] not in (("scanner", "supervisor") if allow_supervisor_scan else ("scanner",)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="دورك في الوردية لا يتيح مسح الحضور",
        )
    if not hmac.compare_digest(session["session_token_hash"], hash_device_session_token(device_session_token)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="رمز جلسة الجهاز غير صالح",
        )

    await db.execute(
        text("""
            UPDATE event_gate_device_sessions
            SET last_seen_at = now()
            WHERE id = :session_id AND status = 'active'
        """),
        {"session_id": str(device_session_id)},
    )
    return session


async def get_shift_with_provider_access(
    db: AsyncSession,
    *,
    shift_id: UUID,
    tenant_id: UUID,
) -> Mapping | None:
    """Fetch a shift only when it belongs to the selected provider workspace."""
    result = await db.execute(
        text("""
            SELECT s.*, g.name AS gate_name, g.name_ar AS gate_name_ar,
                   o.provider_tenant_id, o.project_manager_id, o.status AS operation_status,
                   e.title AS event_title, e.title_ar AS event_title_ar
            FROM event_gate_shifts s
            JOIN event_gates g ON g.id = s.gate_id
            JOIN event_operations o ON o.id = s.operation_id
            JOIN events e ON e.id = s.event_id
            WHERE s.id = :shift_id AND o.provider_tenant_id = :tenant_id
        """),
        {"shift_id": str(shift_id), "tenant_id": str(tenant_id)},
    )
    return result.mappings().first()
