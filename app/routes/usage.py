from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.models.usage import UsageCheckResult
from app.services.permission_service import require_any_permission
from app.services.usage_service import check_all_limits

router = APIRouter(prefix="/usage", tags=["Usage & Limits"])


@router.get("", response_model=UsageCheckResult)
async def get_usage_and_limits(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current usage and limits for the tenant."""
    tenant_id = get_tenant_id_from_header(request)
    await require_any_permission(db, tenant_id, user.id, "settings.view", "billing.view", "billing.manage")
    return await check_all_limits(db, tenant_id)
