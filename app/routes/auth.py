from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, BackgroundTasks, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.config import get_settings
from app.database import get_db, get_supabase_admin, get_privileged_db
from app.services.email_service import (
    send_password_changed_email,
    send_otp_email,
    send_signup_otp_email,
    send_org_request_received,
    send_account_already_exists_email,
)
from gotrue.errors import AuthApiError
from app.services.audit_service import log_audit
from app.services.permission_service import get_user_tenants_with_roles, get_user_permissions
from app.services.provisioning_service import (
    ensure_linked_institution_workspace,
    provision_tenant_manual,
)
from app.services import storage_service
from app.services.rate_limiter import rate_limiter
from app.services.secret_box import encrypt_secret
from app.security import get_client_ip, hmac_digest, secure_compare
import asyncio
import io
import re
import secrets
from datetime import datetime, timedelta, timezone
import logging

import fitz
from PIL import Image

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


async def _enforce_public_rate_limit(
    request: Request,
    *,
    action: str,
    limit: int,
    window_seconds: float,
    subject: str | None = None,
) -> None:
    """Apply independent public-endpoint limits without storing PII in Redis."""
    client_ip = get_client_ip(request) or "unknown"
    keys = [f"public:{action}:ip:{client_ip}"]
    if subject:
        keys.append(f"public:{action}:subject:{hmac_digest(subject.lower(), purpose='rate-limit')}")
    try:
        allowed = True
        for key in keys:
            if not await rate_limiter.hit(key, limit, window_seconds):
                allowed = False
                break
    except RuntimeError:
        logger.error("Public rate limiter unavailable action=%s", action)
        raise HTTPException(status_code=503, detail="خدمة الحماية غير متاحة مؤقتاً.")
    if not allowed:
        raise HTTPException(status_code=429, detail="تم تجاوز حد الطلبات. يرجى المحاولة لاحقاً.")


async def _read_limited_upload(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while chunk := await file.read(64 * 1024):
        if len(content) + len(chunk) > max_bytes:
            raise HTTPException(413, "حجم الملف غير صالح")
        content.extend(chunk)
    if not content:
        raise HTTPException(400, "الملف فارغ")
    return bytes(content)


def _validate_org_request_upload(content: bytes, content_type: str | None) -> tuple[str, str]:
    allowed = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
    signatures = (
        ("application/pdf", content.startswith(b"%PDF-")),
        ("image/jpeg", content.startswith(b"\xff\xd8\xff")),
        ("image/png", content.startswith(b"\x89PNG\r\n\x1a\n")),
        ("image/webp", content.startswith(b"RIFF") and content[8:12] == b"WEBP"),
    )
    detected = next((mime for mime, matches in signatures if matches), None)
    if content_type not in allowed or detected != content_type:
        raise HTTPException(400, "نوع الملف غير صالح أو لا يطابق محتواه")

    try:
        if detected == "application/pdf":
            document = fitz.open(stream=content, filetype="pdf")
            try:
                if document.page_count < 1 or document.page_count > 20:
                    raise ValueError("page count")
            finally:
                document.close()
        else:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("image dimensions")
    except Exception:
        raise HTTPException(400, "الملف تالف أو يتجاوز حدود المعالجة الآمنة")

    suffix = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[detected]
    return detected, suffix


@router.post("/org-request/upload")
async def upload_org_request_document(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload a bounded, parsed document and return a server-owned reference."""
    await _enforce_public_rate_limit(
        request,
        action="org-request-upload",
        limit=8,
        window_seconds=3600,
    )
    declared_size = request.headers.get("content-length")
    if declared_size and declared_size.isdigit() and int(declared_size) > settings.org_request_upload_max_bytes + 128 * 1024:
        raise HTTPException(413, "حجم الملف غير صالح")

    content = await _read_limited_upload(file, settings.org_request_upload_max_bytes)
    detected, suffix = _validate_org_request_upload(content, file.content_type)
    path = f"public-org-requests/{secrets.token_urlsafe(24)}{suffix}"
    await storage_service.upload_bytes(path, content, detected)
    return {"file_key": path, "file_name": file.filename or suffix[1:]}


# ══════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    organization_name: Optional[str] = None  # Auto-generated if not provided


class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)


class OrgRequestCreate(BaseModel):
    # Applicant
    full_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    # Organization
    org_name: str
    org_type: Optional[str] = None
    description: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    contact_handle: Optional[str] = None
    # Expected activity size
    expected_events_per_month: Optional[int] = None
    expected_attendees: Optional[int] = None
    requested_plan_code: Optional[str] = None
    # Proof / documents
    proof_url: Optional[str] = None
    documents_url: Optional[str] = None
    notes: Optional[str] = None


class OrgRequestPublicResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[str] = None  # Optional: select tenant on login


class SelectTenantRequest(BaseModel):
    tenant_id: str


class SendOtpRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., pattern=r"^\d{6}$")


class ConfirmNewPasswordRequest(BaseModel):
    reset_token: str = Field(..., min_length=32, max_length=256)
    new_password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class TenantInfo(BaseModel):
    tenant_id: UUID
    slug: str
    name: str
    tenant_status: str
    plan: str
    role: str
    membership_status: str
    workspace_type: str = "institution"
    linked_tenant_id: Optional[UUID] = None


class AuthResponse(BaseModel):
    message: str
    user_id: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    tenants: Optional[list[TenantInfo]] = None
    requires_tenant_selection: bool = False


# ── Refresh-token transport ──
# Browsers receive the refresh token only as an HttpOnly cookie, so page scripts
# (and any XSS payload) cannot read it.  Native clients that cannot hold a cookie
# opt in per request with `X-Refresh-Transport: body` and receive it in JSON.
REFRESH_COOKIE = "qentry_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
REFRESH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "qentry"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=REFRESH_COOKIE_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite="strict",
    )


def _deliver_session(request: Request, response: Response, payload: "AuthResponse") -> "AuthResponse":
    """Move the refresh token into the cookie and keep it out of the JSON body
    unless the caller explicitly asked for body transport."""
    if payload.refresh_token:
        _set_refresh_cookie(response, payload.refresh_token)
        if request.headers.get("x-refresh-transport") != "body":
            payload.refresh_token = None
    return payload


class OtpResponse(BaseModel):
    message: str
    email: Optional[str] = None
    reset_token: Optional[str] = None
    remaining_attempts: Optional[int] = None
    blocked_until: Optional[str] = None


# ══════════════════════════════════════════════
# SIGNUP
# ══════════════════════════════════════════════

async def _ensure_initial_workspace(
    db: AsyncSession,
    *,
    user_id: UUID,
    email: str,
    full_name: str,
    organization_name: str | None,
) -> None:
    """Provision a personal workspace only after a confirmed successful login."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:user_id))"),
        {"user_id": str(user_id)},
    )
    existing = await db.execute(
        text("SELECT 1 FROM memberships WHERE user_id = :user_id LIMIT 1"),
        {"user_id": str(user_id)},
    )
    if existing.first():
        return

    staff = await db.execute(
        text("SELECT COALESCE(is_staff, false) FROM profiles WHERE id = :user_id"),
        {"user_id": str(user_id)},
    )
    if staff.scalar():
        return

    await db.execute(
        text("""
            INSERT INTO profiles (id, full_name, avatar_url)
            VALUES (:user_id, :full_name, '')
            ON CONFLICT (id) DO UPDATE
            SET full_name = COALESCE(NULLIF(profiles.full_name, ''), EXCLUDED.full_name)
        """),
        {"user_id": str(user_id), "full_name": full_name},
    )
    workspace_name = organization_name or f"{full_name or email.split('@')[0]}'s Workspace"
    base_slug = re.sub(r"[^a-z0-9]+", "-", workspace_name.lower()).strip("-") or "workspace"
    slug = f"{base_slug[:40]}-{secrets.token_hex(3)}"
    tenant_result = await db.execute(
        text("""
            INSERT INTO tenants (slug, name, created_by, metadata)
            VALUES (:slug, :name, :created_by, '{}'::jsonb)
            RETURNING id
        """),
        {"slug": slug, "name": workspace_name, "created_by": str(user_id)},
    )
    tenant_id = tenant_result.scalar_one()
    await db.execute(
        text("""
            INSERT INTO memberships (tenant_id, user_id, role, status)
            VALUES (:tenant_id, :user_id, 'owner', 'active')
        """),
        {"tenant_id": str(tenant_id), "user_id": str(user_id)},
    )
    await db.execute(
        text("""
            INSERT INTO subscriptions (tenant_id, plan_id, status,
                current_period_start, current_period_end, trial_ends_at)
            VALUES (
                :tenant_id,
                (SELECT id FROM plans WHERE code = 'starter'),
                'active', now(), now() + INTERVAL '30 days', now() + INTERVAL '14 days'
            )
        """),
        {"tenant_id": str(tenant_id)},
    )
    await provision_tenant_manual(db, tenant_id, user_id)
    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="tenant.create_after_verified_login",
        resource_type="tenant",
        resource_id=str(tenant_id),
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_202_ACCEPTED)
async def signup(
    body: SignupRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Start signup without revealing account existence or creating resources."""
    _validate_password_strength(body.password)
    await _enforce_public_rate_limit(
        request,
        action="signup",
        limit=5,
        window_seconds=3600,
        subject=str(body.email),
    )
    email = str(body.email).lower().strip()
    admin = get_supabase_admin()

    try:
        res = await asyncio.to_thread(
            admin.auth.admin.generate_link,
            {
                "type": "signup",
                "email": email,
                "password": body.password,
                "options": {
                    "data": {
                        "full_name": body.full_name or "",
                        "organization_name": body.organization_name or "",
                    }
                },
            },
        )
        otp_code = getattr(getattr(res, "properties", None), "email_otp", None)
        if otp_code:
            background_tasks.add_task(
                send_signup_otp_email,
                to_email=email,
                otp_code=str(otp_code),
                full_name=body.full_name or "",
                organization_name=body.organization_name or "",
            )
    except AuthApiError as exc:
        logger.info("Signup request rejected by identity provider error=%s", type(exc).__name__)
        if exc.code == "email_exists":
            # The API response below must stay generic either way (an
            # external prober must not learn account existence from it),
            # but the real inbox owner deserves to know why no code is
            # coming instead of retrying a code that will never exist.
            background_tasks.add_task(send_account_already_exists_email, to_email=email)
    except Exception as exc:
        logger.info("Signup request rejected by identity provider error=%s", type(exc).__name__)

    return AuthResponse(
        message="إذا كان البريد صالحاً، ستصلك رسالة تحتوي على رمز تحقق مكوّن من 6 أرقام لتأكيد حسابك.",
    )


class VerifySignupOtpRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., pattern=r"^\d{6}$")


@router.post("/verify-signup-otp", response_model=AuthResponse)
async def verify_signup_otp(
    body: VerifySignupOtpRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Confirm a new account with the emailed OTP and log the user straight in.

    Verifying via a 6-digit code (rather than the emailed link) sidesteps GoTrue's
    local-dev confirmation link always pointing at 127.0.0.1 in this deployment.
    """
    email = str(body.email).lower().strip()
    await _enforce_public_rate_limit(
        request,
        action="verify-signup-otp",
        limit=8,
        window_seconds=3600,
        subject=email,
    )
    from app.database import get_supabase_client
    supabase = get_supabase_client()

    try:
        result = await asyncio.to_thread(
            supabase.auth.verify_otp,
            {"email": email, "token": body.otp_code, "type": "signup"},
        )
    except Exception:
        raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح أو منتهي الصلاحية")

    if not result.session or not result.user:
        raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح أو منتهي الصلاحية")

    user_id = str(result.user.id)
    identity_metadata = getattr(result.user, "user_metadata", None) or {}
    if not isinstance(identity_metadata, dict):
        identity_metadata = {}

    try:
        await _ensure_initial_workspace(
            db,
            user_id=UUID(user_id),
            email=str(getattr(result.user, "email", None) or email).lower(),
            full_name=str(identity_metadata.get("full_name") or ""),
            organization_name=identity_metadata.get("organization_name") or None,
        )
        await db.execute(
            text("UPDATE profiles SET last_login_at = now() WHERE id = :uid"),
            {"uid": user_id},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("Could not prepare the verified workspace for %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="تعذر تجهيز مساحة العمل. يرجى المحاولة لاحقاً.",
        ) from e

    try:
        tenants = await get_user_tenants_with_roles(db, UUID(user_id))
        active_tenants = [t for t in tenants if t["tenant_status"] in ("active", "trial")]
    except Exception as e:
        logger.warning("Could not load tenants for %s: %s", user_id, e)
        active_tenants = []

    return _deliver_session(request, response, AuthResponse(
        message="تم تأكيد الحساب وتسجيل الدخول بنجاح",
        user_id=user_id,
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
        tenants=[TenantInfo(**t) for t in active_tenants] if active_tenants else None,
    ))


@router.post("/resend-signup-otp", status_code=status.HTTP_202_ACCEPTED)
async def resend_signup_otp(
    body: SendOtpRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Resend the signup confirmation OTP without revealing account existence."""
    email = str(body.email).lower().strip()
    await _enforce_public_rate_limit(
        request,
        action="resend-signup-otp",
        limit=5,
        window_seconds=3600,
        subject=email,
    )
    admin = get_supabase_admin()

    try:
        res = await asyncio.to_thread(
            admin.auth.admin.generate_link,
            {
                "type": "signup",
                "email": email,
            },
        )
        otp_code = getattr(getattr(res, "properties", None), "email_otp", None)
        user_meta = getattr(getattr(res, "user", None), "user_metadata", {}) or {}
        full_name = str(user_meta.get("full_name") or "")
        org_name = str(user_meta.get("organization_name") or "")
        if otp_code:
            background_tasks.add_task(
                send_signup_otp_email,
                to_email=email,
                otp_code=str(otp_code),
                full_name=full_name,
                organization_name=org_name,
            )
    except AuthApiError as exc:
        logger.info("Resend signup OTP rejected error=%s", type(exc).__name__)
        if exc.code == "email_exists":
            background_tasks.add_task(send_account_already_exists_email, to_email=email)
    except Exception as exc:
        logger.info("Resend signup OTP rejected error=%s", type(exc).__name__)

    return {"message": "إذا كان البريد بانتظار التأكيد، سيصلك رمز جديد."}


# ══════════════════════════════════════════════
# ORGANIZER-TEAM REGISTRATION REQUEST (public, awaits platform approval)
# ══════════════════════════════════════════════

def _validate_password_strength(password: str) -> None:
    """Enforce one server-side password policy for every credential flow."""
    if (
        len(password) < settings.password_min_length
        or len(password) > 256
        or not re.search(r"[a-z]", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r"[0-9]", password)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"كلمة المرور يجب أن تكون {settings.password_min_length} حرفاً على الأقل "
                "وتحتوي على حرف كبير وصغير ورقم"
            ),
        )


def _validate_org_document_reference(value: str | None) -> str | None:
    if not value:
        return None
    if not re.fullmatch(r"public-org-requests/[A-Za-z0-9_-]{20,96}\.(pdf|jpg|png|webp)", value):
        raise HTTPException(status_code=400, detail="مرجع المستند غير صالح")
    return value


@router.post("/org-request", response_model=OrgRequestPublicResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_org_request(
    body: OrgRequestCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Record a review request without creating a live account or tenant."""
    email = body.email.lower().strip()
    if body.phone:
        body.phone = body.phone.strip()
    _validate_password_strength(body.password)
    await _enforce_public_rate_limit(
        request,
        action="org-request",
        limit=3,
        window_seconds=24 * 3600,
        subject=email,
    )
    proof_key = _validate_org_document_reference(body.proof_url)
    documents_key = _validate_org_document_reference(body.documents_url)
    generic_response = OrgRequestPublicResponse(
        message="تم استلام الطلب. إذا كان مؤهلاً ستصلك رسالة من فريق المنصة.",
    )

    try:
        existing_user = await db.execute(
            text("SELECT 1 FROM auth.users WHERE lower(email) = :email"),
            {"email": email},
        )
        pending = await db.execute(
            text("SELECT 1 FROM organization_requests WHERE lower(email) = :email AND status = 'pending'"),
            {"email": email},
        )
    except Exception:
        logger.exception("Could not validate organization request email")
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً. حاول لاحقاً.")

    if existing_user.first() or pending.first():
        return generic_response

    try:
        await db.execute(
            text("""
                INSERT INTO organization_requests (
                    full_name, email, phone, password_encrypted,
                    org_name, org_type, description, city, country, website, contact_handle,
                    expected_events_per_month, expected_attendees, requested_plan_code,
                    proof_url, documents_url, notes
                ) VALUES (
                    :full_name, :email, :phone, :password_encrypted,
                    :org_name, :org_type, :description, :city, :country, :website, :contact_handle,
                    :eepm, :attendees, :plan,
                    :proof_url, :documents_url, :notes
                )
            """),
            {
                "full_name": body.full_name, "email": email, "phone": body.phone,
                "password_encrypted": encrypt_secret(body.password),
                "org_name": body.org_name, "org_type": body.org_type,
                "description": body.description, "city": body.city, "country": body.country,
                "website": body.website, "contact_handle": body.contact_handle,
                "eepm": body.expected_events_per_month, "attendees": body.expected_attendees,
                "plan": body.requested_plan_code,
                "proof_url": proof_key, "documents_url": documents_key, "notes": body.notes,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Could not save organization request")
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً. حاول لاحقاً.")

    background_tasks.add_task(send_org_request_received, email, body.full_name, body.org_name)

    return generic_response


# ══════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════

@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_privileged_db),
):
    """
    Login with email and password via Supabase Auth.
    If user belongs to multiple tenants, returns tenant list for selection.
    """
    from app.database import get_supabase_client
    supabase = get_supabase_client()  # Use anon key for sign_in

    try:
        result = await asyncio.to_thread(
            supabase.auth.sign_in_with_password,
            {"email": body.email, "password": body.password},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="بيانات الدخول غير صحيحة",
        )

    user_id = str(result.user.id)
    identity_metadata = getattr(result.user, "user_metadata", None) or {}
    if not isinstance(identity_metadata, dict):
        identity_metadata = {}

    try:
        await _ensure_initial_workspace(
            db,
            user_id=UUID(user_id),
            email=str(getattr(result.user, "email", None) or body.email).lower(),
            full_name=str(identity_metadata.get("full_name") or ""),
            organization_name=identity_metadata.get("organization_name") or None,
        )
        await db.execute(
            text("UPDATE profiles SET last_login_at = now() WHERE id = :uid"),
            {"uid": user_id},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("Could not prepare the verified workspace for %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="تعذر تجهيز مساحة العمل. يرجى المحاولة لاحقاً.",
        ) from e

    # Organizer owners from before linked workspaces were introduced receive
    # their institution workspace lazily on their next successful login.
    try:
        tenants = await get_user_tenants_with_roles(db, UUID(user_id))
        for tenant in tenants:
            if tenant.get("workspace_type") == "organizer" and tenant.get("role") == "owner":
                await ensure_linked_institution_workspace(
                    db,
                    UUID(str(tenant["tenant_id"])),
                    UUID(user_id),
                    str(tenant["name"]),
                )
        await db.commit()
        tenants = await get_user_tenants_with_roles(db, UUID(user_id))
        active_tenants = [t for t in tenants if t["tenant_status"] in ("active", "trial")]
    except Exception as e:
        await db.rollback()
        logger.warning("Could not load tenants for %s: %s", user_id, e)
        active_tenants = []

    if len(active_tenants) > 1 and not body.tenant_id:
        # Multiple tenants — require selection
        return _deliver_session(request, response, AuthResponse(
            message="يرجى اختيار المستأجر",
            user_id=user_id,
            access_token=result.session.access_token,
            refresh_token=result.session.refresh_token,
            tenants=[TenantInfo(**t) for t in active_tenants],
            requires_tenant_selection=True,
        ))

    return _deliver_session(request, response, AuthResponse(
        message="تم تسجيل الدخول بنجاح",
        user_id=user_id,
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
        tenants=[TenantInfo(**t) for t in active_tenants] if active_tenants else None,
    ))


# ══════════════════════════════════════════════
# PASSWORD RESET — STEP 1: SEND OTP
# ══════════════════════════════════════════════

def _generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure, zero-padded numeric OTP."""
    return f"{secrets.randbelow(10 ** length):0{length}d}"


@router.post(
    "/password-reset/send-otp",
    response_model=OtpResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_otp(
    body: SendOtpRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Issue a short-lived reset OTP without disclosing account existence."""
    email = body.email.lower().strip()
    await _enforce_public_rate_limit(
        request,
        action="password-reset-send",
        limit=5,
        window_seconds=3600,
        subject=email,
    )
    generic_response = OtpResponse(
        message="إذا كان البريد مسجلاً، فسيصلك رمز التحقق خلال دقائق.",
    )

    try:
        user_result = await db.execute(
            text("SELECT id FROM auth.users WHERE lower(email) = :email LIMIT 1"),
            {"email": email},
        )
        user_id = user_result.scalar()
    except Exception:
        await db.rollback()
        logger.exception("Could not look up password-reset identity")
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً. حاول لاحقاً.")

    if not user_id:
        return generic_response

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:email))"),
        {"email": email},
    )
    block_result = await db.execute(
        text("""
            SELECT blocked_until FROM password_reset_otps
            WHERE email = :email
              AND blocked_until IS NOT NULL
              AND blocked_until > now()
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"email": email},
    )
    block_row = block_result.mappings().first()
    if block_row:
        await db.commit()
        return generic_response

    await db.execute(
        text("""
            UPDATE password_reset_otps
            SET expires_at = now(), consumed_at = COALESCE(consumed_at, now()),
                reset_token_hash = NULL
            WHERE email = :email
              AND consumed_at IS NULL
              AND expires_at > now()
        """),
        {"email": email},
    )

    otp_code = _generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await db.execute(
        text("""
            INSERT INTO password_reset_otps (
                email, user_id, otp_hash, request_ip, expires_at
            ) VALUES (
                :email, :user_id, :otp_hash, :request_ip, :expires_at
            )
        """),
        {
            "email": email,
            "user_id": str(user_id),
            "otp_hash": hmac_digest(otp_code, purpose=f"password-reset-otp:{email}"),
            "request_ip": get_client_ip(request),
            "expires_at": expires_at,
        },
    )
    await db.commit()

    background_tasks.add_task(send_otp_email, email, otp_code)
    return generic_response


# ══════════════════════════════════════════════
# PASSWORD RESET — STEP 2: VERIFY OTP
# ══════════════════════════════════════════════

@router.post("/password-reset/verify-otp", response_model=OtpResponse)
async def verify_otp(
    body: VerifyOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Atomically verify a hashed OTP and issue a one-time reset token."""
    email = body.email.lower().strip()
    await _enforce_public_rate_limit(
        request,
        action="password-reset-verify",
        limit=10,
        window_seconds=15 * 60,
        subject=email,
    )
    otp_hash = hmac_digest(body.otp_code, purpose=f"password-reset-otp:{email}")
    invalid_detail = "رمز التحقق غير صالح أو منتهي الصلاحية. يرجى إعادة العملية."

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:email))"),
        {"email": email},
    )
    block_result = await db.execute(
        text("""
            SELECT blocked_until FROM password_reset_otps
            WHERE email = :email
              AND blocked_until IS NOT NULL
              AND blocked_until > now()
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"email": email},
    )
    if block_result.mappings().first():
        await db.commit()
        raise HTTPException(status_code=400, detail=invalid_detail)

    otp_result = await db.execute(
        text("""
            SELECT id, otp_hash, attempts, max_attempts
            FROM password_reset_otps
            WHERE email = :email
              AND is_verified = FALSE
              AND consumed_at IS NULL
              AND expires_at > now()
              AND blocked_until IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
        """),
        {"email": email},
    )
    otp_row = otp_result.mappings().first()

    if not otp_row:
        await db.commit()
        raise HTTPException(status_code=400, detail=invalid_detail)

    if not secure_compare(str(otp_row["otp_hash"] or ""), otp_hash):
        attempts = int(otp_row["attempts"] or 0) + 1
        max_attempts = int(otp_row["max_attempts"] or 3)
        blocked_until = (
            datetime.now(timezone.utc) + timedelta(minutes=15)
            if attempts >= max_attempts
            else None
        )
        await db.execute(
            text("""
                UPDATE password_reset_otps
                SET attempts = :attempts,
                    blocked_until = :blocked_until,
                    expires_at = CASE WHEN :blocked_until IS NULL THEN expires_at ELSE now() END
                WHERE id = :id
            """),
            {
                "attempts": attempts,
                "blocked_until": blocked_until,
                "id": otp_row["id"],
            },
        )
        await db.commit()
        raise HTTPException(status_code=400, detail=invalid_detail)

    reset_token = secrets.token_urlsafe(48)

    await db.execute(
        text("""
            UPDATE password_reset_otps
            SET is_verified = TRUE,
                otp_hash = NULL,
                otp_code = NULL,
                reset_token_hash = :reset_token_hash
            WHERE id = :id
        """),
        {
            "reset_token_hash": hmac_digest(reset_token, purpose="password-reset-token"),
            "id": otp_row["id"],
        },
    )
    await db.commit()

    return OtpResponse(
        message="تم التحقق بنجاح",
        reset_token=reset_token,
    )


# ══════════════════════════════════════════════
# PASSWORD RESET — STEP 3: SET NEW PASSWORD
# ══════════════════════════════════════════════

@router.post("/password-reset/confirm-new", response_model=OtpResponse)
async def confirm_new_password(
    body: ConfirmNewPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Consume a one-time hashed reset token and set a compliant password."""
    _validate_password_strength(body.new_password)
    await _enforce_public_rate_limit(
        request,
        action="password-reset-confirm",
        limit=8,
        window_seconds=3600,
        subject=body.reset_token,
    )
    supabase = get_supabase_admin()

    token_result = await db.execute(
        text("""
            SELECT id, email, user_id FROM password_reset_otps
            WHERE reset_token_hash = :reset_token_hash
              AND is_verified = TRUE
              AND consumed_at IS NULL
              AND expires_at > now()
            LIMIT 1
            FOR UPDATE
        """),
        {"reset_token_hash": hmac_digest(body.reset_token, purpose="password-reset-token")},
    )
    token_row = token_result.mappings().first()

    if not token_row:
        raise HTTPException(
            status_code=400,
            detail="رمز غير صالح أو منتهي الصلاحية. يرجى إعادة العملية.",
        )

    email = token_row["email"]
    user_id = str(token_row["user_id"]) if token_row["user_id"] else None
    if not user_id:
        user_result = await db.execute(
            text("SELECT id FROM auth.users WHERE lower(email) = :email LIMIT 1"),
            {"email": email.lower()},
        )
        legacy_user_id = user_result.scalar()
        user_id = str(legacy_user_id) if legacy_user_id else None
    if not user_id:
        await db.rollback()
        raise HTTPException(status_code=400, detail="رمز غير صالح أو منتهي الصلاحية. يرجى إعادة العملية.")

    try:
        await asyncio.to_thread(
            supabase.auth.admin.update_user_by_id,
            user_id,
            # Successfully consuming a mailed OTP already proves control of
            # this inbox -- exactly what email confirmation exists to prove.
            # Without this, an account left unconfirmed (e.g. a previous
            # signup attempt that was never completed) gets a real new
            # password here but still can't log in: GoTrue refuses password
            # grants for an unconfirmed email and reports it as the same
            # generic "invalid credentials" as a wrong password, silently
            # stranding the user after what looked like a successful reset.
            {"password": body.new_password, "email_confirm": True},
        )
    except Exception:
        await db.rollback()
        logger.exception("Could not update password through identity provider")
        raise HTTPException(
            status_code=503,
            detail="فشل تغيير كلمة المرور. يرجى المحاولة مرة أخرى.",
        )

    await db.execute(
        text("""
            UPDATE password_reset_otps
            SET expires_at = now(), consumed_at = COALESCE(consumed_at, now()),
                reset_token_hash = NULL
            WHERE user_id = :user_id
               OR (user_id IS NULL AND email = :email)
        """),
        {"email": email, "user_id": user_id},
    )

    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=UUID(user_id),
        action="auth.password_reset_otp",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )
    await db.commit()

    background_tasks.add_task(send_password_changed_email, email)

    return OtpResponse(
        message="تم تغيير كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن.",
    )


# ══════════════════════════════════════════════
# CHANGE PASSWORD (authenticated user)
# ══════════════════════════════════════════════

@router.post("/change-password", response_model=AuthResponse)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Change password for the currently authenticated user."""
    supabase = get_supabase_client()  # fresh anon client: sign-in must not touch the shared admin client
    admin = get_supabase_admin()
    _validate_password_strength(body.new_password)

    # Verify current password by attempting sign-in
    if not user.email:
        raise HTTPException(status_code=400, detail="لا يمكن تحديد البريد الإلكتروني من التوكن")

    try:
        await asyncio.to_thread(
            supabase.auth.sign_in_with_password,
            {"email": user.email, "password": body.current_password},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="كلمة المرور الحالية غير صحيحة",
        )

    # Update password
    try:
        await asyncio.to_thread(
            admin.auth.admin.update_user_by_id,
            str(user.id),
            {"password": body.new_password},
        )
    except Exception:
        logger.exception("Could not change password for authenticated user %s", user.id)
        raise HTTPException(status_code=503, detail="فشل تغيير كلمة المرور. يرجى المحاولة مرة أخرى.")

    # Send confirmation email
    background_tasks.add_task(send_password_changed_email, user.email)

    # Audit log
    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=user.id,
        action="auth.password_change",
        resource_type="user",
        resource_id=str(user.id),
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return AuthResponse(
        message="تم تغيير كلمة المرور بنجاح",
        user_id=str(user.id),
    )


# ══════════════════════════════════════════════
# REFRESH TOKEN
# ══════════════════════════════════════════════

class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(
    request: Request,
    response: Response,
    body: Optional[RefreshRequest] = None,
):
    """Refresh the access token.

    The refresh token comes from the HttpOnly cookie for browsers, or from the
    JSON body for native clients.  Cookie-based refresh changes server state, so it
    requires a custom header that a cross-site form cannot send.
    """
    from_body = bool(body and body.refresh_token)
    token = body.refresh_token if from_body else request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="رمز التحديث غير موجود",
        )
    if not from_body and request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="طلب التحديث غير مصرّح به",
        )

    supabase = get_supabase_client()  # fresh anon client (never the shared admin one)
    try:
        result = await asyncio.to_thread(supabase.auth.refresh_session, token)
    except Exception:
        # Cookies set on the injected Response are dropped when an HTTPException
        # is raised, so the rejection is returned directly with the cookie cleared.
        rejected = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "رمز التحديث غير صالح أو منتهي الصلاحية"},
        )
        _clear_refresh_cookie(rejected)
        return rejected

    return _deliver_session(request, response, AuthResponse(
        message="تم تحديث التوكن بنجاح",
        user_id=str(result.user.id),
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    ))


# ══════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════

@router.post("/logout", response_model=AuthResponse)
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Logout — sign out from Supabase (invalidates refresh token)."""
    supabase = get_supabase_admin()

    try:
        # Sign out via admin API
        await asyncio.to_thread(supabase.auth.admin.sign_out, str(user.id))
    except Exception:
        pass  # Best effort — token will expire naturally

    await log_audit(
        db, tenant_id=None, actor_user_id=user.id,
        action="auth.logout", resource_type="user", resource_id=str(user.id),
        ip_address=get_client_ip(request),
    )
    await db.commit()
    _clear_refresh_cookie(response)

    return AuthResponse(message="تم تسجيل الخروج بنجاح")


# ══════════════════════════════════════════════
# GET CURRENT USER INFO (enhanced)
# ══════════════════════════════════════════════

@router.get("/me")
async def get_me(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """
    Get current user info + profile + list of tenants with roles.
    When X-Tenant-ID header is set, includes permissions for that tenant.
    This is the main endpoint the frontend calls after login.
    """
    # Get profile (graceful fallback if DB unavailable)
    profile = None
    try:
        profile_result = await db.execute(
            text("""
                SELECT full_name, avatar_url, phone, is_staff, status,
                       email_verified_at::text, last_login_at::text,
                       created_at::text
                FROM profiles WHERE id = :uid
            """),
            {"uid": str(user.id)},
        )
        profile = profile_result.mappings().first()
    except Exception:
        pass  # DB unavailable, use JWT data only

    # Get tenants with roles (graceful fallback if not set up)
    tenants = []
    try:
        tenants = await get_user_tenants_with_roles(db, user.id)
    except Exception:
        pass  # No tenants if schema not ready

    permissions: list[str] = []
    try:
        tenant_id = get_tenant_id_from_header(request)
        permissions = await get_user_permissions(db, tenant_id, user.id)
    except Exception:
        pass

    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": profile["full_name"] if profile else None,
        "avatar_url": profile["avatar_url"] if profile else None,
        "phone": profile["phone"] if profile else None,
        "is_staff": profile["is_staff"] if profile else False,
        "status": profile["status"] if profile else "active",
        "email_verified_at": profile["email_verified_at"] if profile else None,
        "last_login_at": profile["last_login_at"] if profile else None,
        "created_at": profile["created_at"] if profile else None,
        "tenants": [TenantInfo(**t) for t in tenants],
        "permissions": permissions,
    }


@router.patch("/me")
async def update_me(
    body: ProfileUpdateRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Update the signed-in user's own profile only."""
    full_name = body.full_name.strip()
    phone = body.phone.strip() if body.phone else None
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="يجب أن يتكون الاسم من حرفين على الأقل")
    if phone and not re.fullmatch(r"[+0-9()\-\s]{7,32}", phone):
        raise HTTPException(status_code=422, detail="رقم الهاتف غير صالح")

    result = await db.execute(
        text("""
            UPDATE profiles
            SET full_name=:full_name, phone=:phone, updated_at=now()
            WHERE id=:uid
            RETURNING full_name, avatar_url, phone, status,
                      email_verified_at::text, last_login_at::text, created_at::text
        """),
        {"uid": str(user.id), "full_name": full_name, "phone": phone},
    )
    profile = result.mappings().first()
    if not profile:
        raise HTTPException(status_code=404, detail="تعذر العثور على الملف الشخصي")
    await log_audit(
        db, tenant_id=None, actor_user_id=user.id,
        action="profile.update", resource_type="profile", resource_id=str(user.id),
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"user_id": str(user.id), "email": user.email, **dict(profile)}
