"""TOTP multi-factor enrolment and verification for the signed-in user.

Production requires platform staff to hold an AAL2 session
(PLATFORM_ADMIN_REQUIRE_AAL2).  GoTrue issues AAL2 only after a TOTP challenge
is verified, so the API must expose enrol / verify.  The browser never talks to
GoTrue directly; these routes forward to it with the caller's own access token.

Rules enforced here, on top of GoTrue's:
  * a user who already has a verified factor cannot enrol another one from an
    AAL1 session (otherwise a stolen password could add the attacker's device);
  * code attempts are rate limited per user and per address.
"""
import logging
import re
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.database import get_privileged_db
from app.routes.auth import AuthResponse, _deliver_session, _enforce_public_rate_limit
from app.security import get_client_ip
from app.services.audit_service import log_audit

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/auth/mfa", tags=["Authentication"])

_FACTOR_NAME = "DAWAA authenticator"
_ISSUER = "DAWAA"


class MfaStatus(BaseModel):
    aal: Optional[str] = None
    enrolled: bool
    factor_id: Optional[str] = None


class MfaEnrollment(BaseModel):
    factor_id: str
    qr_code: str
    secret: str
    uri: str


class MfaVerifyRequest(BaseModel):
    factor_id: UUID
    code: str = Field(..., pattern=r"^\d{6}$")


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token


async def _gotrue(method: str, path: str, token: str, json: dict | None = None) -> httpx.Response:
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1{path}"
    headers = {"apikey": settings.resolved_anon_key, "Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=settings.external_timeout_seconds) as client:
            return await client.request(method, url, headers=headers, json=json)
    except httpx.HTTPError:
        logger.warning("GoTrue MFA request failed path=%s", path)
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً. حاول لاحقاً.")


async def _factors(token: str) -> list[dict]:
    resp = await _gotrue("GET", "/user", token)
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return [f for f in (resp.json().get("factors") or []) if f.get("factor_type") == "totp"]


@router.get("/status", response_model=MfaStatus)
async def mfa_status(request: Request, user: CurrentUser = Depends(get_current_user)):
    token = _bearer(request)
    verified = [f for f in await _factors(token) if f.get("status") == "verified"]
    return MfaStatus(
        aal=user.aal,
        enrolled=bool(verified),
        factor_id=verified[0]["id"] if verified else None,
    )


@router.post("/enroll", response_model=MfaEnrollment)
async def mfa_enroll(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    await _enforce_public_rate_limit(
        request, action="mfa-enroll", limit=10, window_seconds=3600, subject=str(user.id)
    )
    token = _bearer(request)
    factors = await _factors(token)

    if any(f.get("status") == "verified" for f in factors) and user.aal not in {"aal2", "aal3"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لديك مصادقة ثنائية مفعّلة بالفعل. أدخل الرمز بدل تسجيل جهاز جديد.",
        )

    # Abandoned, never-verified enrolments would otherwise accumulate (and make
    # a later enrol collide on the friendly name).
    for factor in factors:
        if factor.get("status") != "verified":
            await _gotrue("DELETE", f"/factors/{factor['id']}", token)

    resp = await _gotrue(
        "POST", "/factors", token,
        {"factor_type": "totp", "friendly_name": _FACTOR_NAME, "issuer": _ISSUER},
    )
    if resp.status_code not in (200, 201):
        logger.warning("MFA enrol rejected status=%s", resp.status_code)
        raise HTTPException(status_code=400, detail="تعذر بدء تسجيل المصادقة الثنائية.")
    data = resp.json()
    totp = data.get("totp") or {}

    await log_audit(
        db, tenant_id=None, actor_user_id=user.id,
        action="auth.mfa.enroll_started", resource_type="user", resource_id=str(user.id),
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return MfaEnrollment(
        factor_id=data["id"],
        qr_code=totp.get("qr_code", ""),
        secret=totp.get("secret", ""),
        uri=totp.get("uri", ""),
    )


@router.post("/verify", response_model=AuthResponse)
async def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Verify a TOTP code; returns a fresh AAL2 session."""
    await _enforce_public_rate_limit(
        request, action="mfa-verify", limit=10, window_seconds=300, subject=str(user.id)
    )
    token = _bearer(request)
    factor_id = str(body.factor_id)

    # The factor must belong to this user (GoTrue enforces it too; checking here
    # keeps the error uniform and avoids a pointless challenge).
    if factor_id not in {f["id"] for f in await _factors(token)}:
        raise HTTPException(status_code=404, detail="العامل غير موجود.")

    challenge = await _gotrue("POST", f"/factors/{factor_id}/challenge", token)
    if challenge.status_code not in (200, 201):
        raise HTTPException(status_code=400, detail="تعذر بدء التحقق. حاول مرة أخرى.")

    verified = await _gotrue(
        "POST", f"/factors/{factor_id}/verify", token,
        {"challenge_id": challenge.json()["id"], "code": body.code},
    )
    ip = get_client_ip(request)
    if verified.status_code != 200:
        await log_audit(
            db, tenant_id=None, actor_user_id=user.id,
            action="auth.mfa.verify_failed", resource_type="user", resource_id=str(user.id),
            ip_address=ip,
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح أو منتهي.")

    session = verified.json()
    await log_audit(
        db, tenant_id=None, actor_user_id=user.id,
        action="auth.mfa.verified", resource_type="user", resource_id=str(user.id),
        ip_address=ip,
    )
    await db.commit()
    return _deliver_session(request, response, AuthResponse(
        message="تم التحقق بنجاح",
        user_id=str(user.id),
        access_token=session["access_token"],
        refresh_token=session.get("refresh_token"),
    ))
