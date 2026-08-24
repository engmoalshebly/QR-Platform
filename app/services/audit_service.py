import json
import logging
from uuid import UUID
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from app.security import get_client_ip

logger = logging.getLogger(__name__)


async def log_audit(
    db: AsyncSession,
    *,
    tenant_id: Optional[UUID],
    actor_user_id: UUID,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Write an audit log entry with optional old/new value tracking.
    
    Args:
        old_values: Previous state of the resource (for updates/deletes)
        new_values: New state of the resource (for creates/updates)
    """
    # Never mutate a caller-owned metadata dictionary while enriching it.
    full_metadata = dict(metadata or {})
    if old_values:
        full_metadata["old_values"] = old_values
    if new_values:
        full_metadata["new_values"] = new_values

    try:
        await db.execute(
            text("""
                INSERT INTO audit_logs (tenant_id, actor_user_id, action, resource_type, resource_id, metadata, ip_address, user_agent)
                VALUES (:tenant_id, :actor_user_id, :action, :resource_type, :resource_id, :metadata, :ip_address, :user_agent)
            """),
            {
                "tenant_id": str(tenant_id) if tenant_id else None,
                "actor_user_id": str(actor_user_id),
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "metadata": json.dumps(full_metadata, default=str),
                "ip_address": ip_address,
                "user_agent": user_agent,
            },
        )
    except Exception:
        # Sensitive mutations and their audit event are one transaction.  A
        # successful, unlogged change is worse than a safely failed request.
        logger.exception("Audit log write failed action=%s resource_id=%s", action, resource_id)
        raise


def extract_audit_context(request: Request) -> dict:
    """Extract IP and user_agent from a request for audit logging."""
    return {
        "ip_address": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }
