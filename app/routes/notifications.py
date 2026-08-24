from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.permission_service import require_permission

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
async def list_notifications(request: Request, unread_only: bool = False,
                             user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "notifications.view")
    query = """
        SELECT * FROM notifications
        WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)
    """
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY created_at DESC LIMIT 100"
    rows = await db.execute(text(query), {"tid": str(tenant_id), "uid": str(user.id)})
    return [dict(row) for row in rows.mappings().all()]


@router.get("/unread-count")
async def unread_count(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "notifications.view")
    result = await db.execute(text("""
        SELECT COUNT(*) FROM notifications
        WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL) AND read_at IS NULL
    """), {"tid": str(tenant_id), "uid": str(user.id)})
    return {"count": result.scalar() or 0}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(notification_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "notifications.view")
    await db.execute(text("""
        UPDATE notifications SET read_at = COALESCE(read_at, now())
        WHERE id = :id AND tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)
    """), {"id": str(notification_id), "tid": str(tenant_id), "uid": str(user.id)})
    await db.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(request: Request, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "notifications.view")
    await db.execute(text("""
        UPDATE notifications SET read_at = COALESCE(read_at, now())
        WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)
    """), {"tid": str(tenant_id), "uid": str(user.id)})
    await db.commit()
