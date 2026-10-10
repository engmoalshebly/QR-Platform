"""Platform staff access checks with production MFA and break-glass controls."""
from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, CurrentUser
from app.config import get_settings
from app.database import get_privileged_db

settings = get_settings()


async def is_staff_user(db: AsyncSession, user_id) -> bool:
    result = await db.execute(
        text("SELECT is_staff FROM profiles WHERE id = :uid"),
        {"uid": str(user_id)},
    )
    row = result.mappings().first()
    return bool(row and row["is_staff"])


async def require_staff(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
) -> CurrentUser:
    """Ensure the user is an authenticated platform administrator."""
    if not await is_staff_user(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذا الإجراء مخصص لمشرفي المنصة فقط",
        )
    if settings.platform_admin_require_aal2 and user.aal not in {"aal2", "aal3"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="يتطلب هذا الإجراء مصادقة متعددة العوامل حديثة.",
        )
    return user


async def require_platform_superadmin(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
) -> CurrentUser:
    """Gate staff promotion and revocation behind named break-glass accounts.

    Normal platform staff retain their operational access, while only explicitly
    configured super-admin accounts can change the platform trust boundary.
    Production validation requires this allowlist to be configured.
    """
    await require_staff(user=user, db=db)
    allowed_emails = settings.platform_superadmin_email_set
    if settings.is_production and (not user.email or user.email.lower() not in allowed_emails):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="تعديل مشرفي المنصة مخصص لحسابات الطوارئ المعتمدة فقط.",
        )
    return user
