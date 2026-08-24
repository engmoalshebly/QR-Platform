"""
Middleware for:
1. Tenant Resolution (header → subdomain → custom domain → JWT)
2. Tenant Status Enforcement (suspended/cancelled blocks access)
3. Security Headers
4. Rate Limiting (Redis-backed sliding window, in-memory fallback)
"""
import logging
import time
import uuid
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import text

from app.tenant_context import set_current_tenant, clear_current_tenant
from app.auth import decode_supabase_jwt
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.rate_limiter import rate_limiter
from app.metrics import observe_request
from app.security import get_client_ip, request_path_template

logger = logging.getLogger(__name__)
settings = get_settings()


class ErrorMonitoringMiddleware(BaseHTTPMiddleware):
    """Adds a traceable request id and persists unexpected server failures."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4()
        started = time.perf_counter()
        request.state.request_id = str(request_id)
        try:
            response = await call_next(request)
        except HTTPException as exc:
            observe_request(request.method, request_path_template(request), exc.status_code, started)
            raise
        except Exception as exc:
            route = request_path_template(request)
            if settings.is_production:
                logger.error(
                    "Unhandled request error request_id=%s route=%s error_type=%s",
                    request_id,
                    route,
                    type(exc).__name__,
                )
            else:
                logger.exception("Unhandled request error request_id=%s route=%s", request_id, route)
            try:
                import sentry_sdk
                sentry_sdk.set_tag("request_id", str(request_id))
                sentry_sdk.set_tag("route", route)
                raw_tid = request.headers.get("X-Tenant-ID")
                if raw_tid:
                    sentry_sdk.set_tag("tenant_id", raw_tid)
                sentry_sdk.capture_exception(exc)
            except ImportError:
                pass
            try:
                raw_tenant_id = request.headers.get("X-Tenant-ID")
                tenant_id_uuid = None
                if raw_tenant_id and raw_tenant_id not in ("undefined", "null"):
                    try:
                        tenant_id_uuid = str(uuid.UUID(raw_tenant_id))
                    except ValueError:
                        pass

                async with AsyncSessionLocal() as db:
                    await db.execute(text("""
                        INSERT INTO application_errors
                          (request_id, path, method, status_code, error_type, message, tenant_id)
                        VALUES (:request_id, :path, :method, 500, :error_type, :message, :tenant_id)
                    """), {
                        "request_id": str(request_id), "path": route,
                        "method": request.method, "error_type": type(exc).__name__,
                        "message": type(exc).__name__, "tenant_id": tenant_id_uuid,
                    })
                    await db.commit()
            except Exception:
                logger.exception("Could not persist application error request_id=%s", request_id)
            response = JSONResponse(
                status_code=500,
                content={"detail": "حدث خطأ داخلي غير متوقع", "request_id": str(request_id)},
            )
        observe_request(request.method, request_path_template(request), response.status_code, started)
        response.headers["X-Request-ID"] = str(request_id)
        return response


# Paths that don't require tenant resolution
TENANT_EXEMPT_PATHS = {
    "/field",
    "/health",
    "/health/ready",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/signup",
    "/api/v1/auth/login",
    "/api/v1/auth/org-request",
    "/api/v1/auth/org-request/upload",
    "/api/v1/auth/org-request/",
    "/api/v1/auth/password-reset/send-otp",
    "/api/v1/auth/password-reset/verify-otp",
    "/api/v1/auth/password-reset/confirm-new",
    "/api/v1/auth/refresh",
    "/api/v1/auth/me",
    "/api/v1/plans",
    "/api/v1/addons",
    "/api/v1/custom-plans/calculate",
    "/api/v1/invites/accept",
    "/api/v1/webhooks/stripe",
    "/api/v1/tenants",
    "/api/v1/platform",
    "/api/v1/invitations/view/",
    "/api/v1/invitations/rsvp/",
    "/api/v1/public/events/",
}

# Subdomains to ignore
SYSTEM_SUBDOMAINS = {"www", "api", "app", "admin", "mail", "smtp", "ftp", "localhost"}


class TenantResolutionMiddleware(BaseHTTPMiddleware):
    """
    Resolves the current tenant from each request using multiple strategies:
    Priority 1: X-Tenant-ID or X-Tenant-Slug header
    Priority 2: Subdomain (e.g., amal.system.com → slug=amal)
    Priority 3: Custom domain lookup (e.g., app.amal.com)
    
    After resolution, validates tenant status (active/trial only).
    Stores tenant in contextvars for the duration of the request.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip tenant resolution for exempt paths
        path = request.url.path
        if any(path.startswith(p) for p in TENANT_EXEMPT_PATHS) or path.startswith("/api/v1/templates/fonts/file/"):
            response = await call_next(request)
            return response

        tenant = None
        async with AsyncSessionLocal() as db:
            # Strategy 1: Header (X-Tenant-ID or X-Tenant-Slug)
            tenant_id = request.headers.get("X-Tenant-ID")
            tenant_slug = request.headers.get("X-Tenant-Slug")

            if tenant_id and tenant_id not in ("undefined", "null"):
                try:
                    valid_tenant_uuid = str(uuid.UUID(tenant_id))
                    result = await db.execute(
                        text("SELECT id, slug, name, status, plan FROM tenants WHERE id = :id"),
                        {"id": valid_tenant_uuid},
                    )
                    tenant = result.mappings().first()
                except ValueError:
                    pass

            if not tenant and tenant_slug and tenant_slug not in ("undefined", "null"):
                result = await db.execute(
                    text("SELECT id, slug, name, status, plan FROM tenants WHERE slug = :slug"),
                    {"slug": tenant_slug},
                )
                tenant = result.mappings().first()

            # Strategy 2: Subdomain
            if not tenant:
                host = request.headers.get("host", "")
                parts = host.split(".")
                if len(parts) >= 3:
                    subdomain = parts[0].lower()
                    if subdomain not in SYSTEM_SUBDOMAINS:
                        result = await db.execute(
                            text("SELECT id, slug, name, status, plan FROM tenants WHERE slug = :slug AND status IN ('active', 'trial')"),
                            {"slug": subdomain},
                        )
                        tenant = result.mappings().first()

            # Strategy 3: Custom domain
            if not tenant:
                host = request.headers.get("host", "").split(":")[0]
                if host and host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                    result = await db.execute(
                        text("""
                            SELECT t.id, t.slug, t.name, t.status, t.plan
                            FROM tenant_domains td
                            JOIN tenants t ON t.id = td.tenant_id
                            WHERE td.domain = :domain AND td.is_verified = true
                        """),
                        {"domain": host},
                    )
                    tenant = result.mappings().first()

        # If no tenant found for a tenant-required path
        if not tenant:
            return JSONResponse(
                status_code=400,
                content={"detail": "لم يتم تحديد المستأجر. أرسل X-Tenant-ID أو X-Tenant-Slug في الهيدر."},
            )

        # Enforce tenant status
        tenant_dict = dict(tenant)
        if tenant_dict["status"] not in ("active", "trial"):
            status_messages = {
                "suspended": "حساب المستأجر معلّق. يرجى التواصل مع الدعم.",
                "cancelled": "حساب المستأجر ملغى.",
                "deleted": "حساب المستأجر محذوف.",
            }
            return JSONResponse(
                status_code=403,
                content={"detail": status_messages.get(tenant_dict["status"], "حساب المستأجر غير نشط.")},
            )

        # Tenant selection is not authorization. For authenticated requests,
        # require an active membership before exposing any tenant-scoped route.
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            try:
                claims = await decode_supabase_jwt(authorization[7:].strip())
                user_id = claims.get("sub")
                async with AsyncSessionLocal() as db:
                    member = await db.execute(text("""
                        SELECT 1 FROM memberships
                        WHERE tenant_id = :tenant_id AND user_id = :user_id AND status = 'active'
                    """), {"tenant_id": str(tenant_dict["id"]), "user_id": user_id})
                    if not member.first():
                        return JSONResponse(status_code=403, content={"detail": "User is not an active member of this tenant"})
            except Exception:
                return JSONResponse(status_code=401, content={"detail": "Invalid authorization token"})

        # Set tenant in context
        set_current_tenant(tenant_dict)

        try:
            response = await call_next(request)
            return response
        finally:
            clear_current_tenant()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = settings.content_security_policy or (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
            "object-src 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "manifest-src 'self'"
        )
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Camera access is granted only to the isolated field PWA.  The
        # management dashboard remains explicitly denied.  A header cannot
        # grant camera access to another origin, so production must host the
        # field app on this same dedicated route/origin.
        if request.url.path.startswith("/field"):
            response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        else:
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


# Sensitive routes get stricter per-IP limits (requests/minute).
_STRICT_RATE_LIMITS: dict[str, int] = {
    "/api/v1/auth/login": 10,
    "/api/v1/auth/signup": 5,
    "/api/v1/auth/password-reset/send-otp": 5,
    "/api/v1/auth/password-reset/verify-otp": 10,
    "/api/v1/auth/password-reset/confirm-new": 10,
    "/api/v1/auth/org-request": 5,
    "/api/v1/auth/refresh": 30,
}

# Per-tenant global limit (requests/minute across all IPs for one tenant).
_TENANT_RATE_LIMIT = 600


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Multi-tier sliding-window limiter that fails closed in production.

    Layer 1: per-IP global (120/min default)
    Layer 2: per-IP strict for auth routes (5–30/min)
    Layer 3: per-tenant aggregate (600/min)
    """

    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path == "/health" or path == "/health/ready":
            return await call_next(request)

        client_ip = get_client_ip(request) or "unknown"

        try:
            # Layer 1: per-IP global limit
            if not await rate_limiter.hit(f"ip:{client_ip}", self.requests_per_minute, 60.0):
                return self._too_many(self.requests_per_minute)

            # Layer 2: strict limit for sensitive auth routes
            strict_limit = _STRICT_RATE_LIMITS.get(path)
            if (
                strict_limit is None
                and request.method == "POST"
                and path.startswith("/api/v1/public/events/")
                and path.endswith("/register")
            ):
                strict_limit = 10
            if strict_limit is not None:
                if not await rate_limiter.hit(f"ip:{client_ip}:{path}", strict_limit, 60.0):
                    return self._too_many(strict_limit)

            # Layer 3: per-tenant aggregate limit
            raw_tenant = request.headers.get("X-Tenant-ID")
            if raw_tenant and raw_tenant not in ("undefined", "null"):
                if not await rate_limiter.hit(f"tenant:{raw_tenant}", _TENANT_RATE_LIMIT, 60.0):
                    return self._too_many(_TENANT_RATE_LIMIT)

        except RuntimeError:
            logger.error("Rate limiter unavailable in production")
            return JSONResponse(
                status_code=503,
                content={"detail": "خدمة الحماية من الإساءة غير متاحة مؤقتاً."},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(
            strict_limit if strict_limit is not None else self.requests_per_minute
        )
        return response

    @staticmethod
    def _too_many(limit: int) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": "تم تجاوز حد الطلبات المسموح به. يرجى المحاولة لاحقاً."},
            headers={"Retry-After": "60", "X-RateLimit-Limit": str(limit)},
        )
