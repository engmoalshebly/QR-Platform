import json
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_notification(
    db: AsyncSession,
    tenant_id: UUID | str,
    notification_type: str,
    title: str,
    message: str,
    *,
    user_id: Optional[UUID | str] = None,
    link: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    await db.execute(text("""
        INSERT INTO notifications (tenant_id, user_id, type, title, message, link, metadata)
        VALUES (:tid, :uid, :type, :title, :message, :link, CAST(:metadata AS jsonb))
    """), {
        "tid": str(tenant_id), "uid": str(user_id) if user_id else None,
        "type": notification_type, "title": title, "message": message,
        "link": link, "metadata": json.dumps(metadata or {}),
    })


async def notify_tenant_managers(db: AsyncSession, tenant_id: UUID | str, **kwargs) -> None:
    result = await db.execute(text("""
        SELECT user_id FROM memberships
        WHERE tenant_id = :tid AND status = 'active' AND role IN ('owner','admin')
    """), {"tid": str(tenant_id)})
    for user_id in result.scalars().all():
        await create_notification(db, tenant_id, user_id=user_id, **kwargs)


async def notify_operation_members(
    db: AsyncSession,
    operation_id: UUID | str,
    *,
    exclude_user_id: Optional[UUID | str] = None,
    only_role: Optional[tuple[str, ...]] = None,
    **kwargs,
) -> None:
    """Fan out a notification to members of an operation's provider tenant.

    Uses the event_operation_members join to reach exactly the people working on
    this event. When only_role is given, restricts to those roles (e.g.
    ('manager','lead') for task-approval requests). exclude_user_id avoids
    notifying the actor of their own action.
    """
    params: dict = {"oid": str(operation_id)}
    role_clause = ""
    if only_role:
        role_clause = " AND om.role = ANY(:roles)"
        params["roles"] = list(only_role)
    exclude_clause = ""
    if exclude_user_id:
        exclude_clause = " AND om.user_id <> :excl"
        params["excl"] = str(exclude_user_id)
    result = await db.execute(text(f"""
        SELECT DISTINCT om.user_id, o.provider_tenant_id
        FROM event_operation_members om
        JOIN event_operations o ON o.id = om.operation_id
        WHERE om.operation_id = :oid{role_clause}{exclude_clause}
    """), params)
    rows = result.mappings().all()
    for row in rows:
        await create_notification(db, row["provider_tenant_id"], user_id=row["user_id"], **kwargs)


async def emit(
    db: AsyncSession,
    tenant_id: UUID | str,
    notification_type: str,
    title: str,
    message: str,
    *,
    user_id: Optional[UUID | str] = None,
    link: Optional[str] = None,
    metadata: Optional[dict] = None,
    email_fn=None,
    email_args: Optional[tuple] = None,
) -> None:
    """Unified fan-out: persist an in-app notification and fire an email if given.

    email_fn is called via asyncio.to_thread (fire-and-forget) so email failures
    never break the request. Callers should wrap email sending in a function that
    accepts *email_args.
    """
    await create_notification(
        db, tenant_id, notification_type, title, message,
        user_id=user_id, link=link, metadata=metadata,
    )
    if email_fn and email_args:
        import asyncio
        asyncio.create_task(asyncio.to_thread(email_fn, *email_args))
