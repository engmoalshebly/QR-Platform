import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, mfa, tenants, invites, subscriptions, usage, profiles, audit, platform, roles, dashboard
from app.routes import events, digital_invitations, guests, templates, teams, checkin, batches, fast_invitations, registration_forms, bookings, operations, notifications, gate_shifts, mobile
from app.config import get_settings
from app.middleware import TenantResolutionMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware, ErrorMonitoringMiddleware
from app.database import AsyncSessionLocal
from app.resilience import with_retry
from app.metrics import snapshot as metrics_snapshot
from app.security import secure_compare


def _configure_console_encoding() -> None:
    """Avoid cp1252 logging crashes on Windows when Arabic text is emitted."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_console_encoding()
settings = get_settings()

logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Sentry error tracking ──
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            send_default_pii=False,
        )
        logger.info("Sentry initialized env=%s", settings.app_env)
    except ImportError:
        logger.warning("SENTRY_DSN configured but sentry-sdk not installed")

# ── Fail fast on insecure/incomplete production configuration ──
_config_problems = settings.validate_for_production()
if _config_problems:
    for _p in _config_problems:
        logger.critical("Production config error: %s", _p)
    raise RuntimeError(
        "Refusing to start in production with invalid configuration: "
        + "; ".join(_config_problems)
    )

allowed_origins = [
    origin.strip()
    for origin in settings.cors_allowed_origins.split(",")
    if origin.strip()
]

@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("api_start env=%s rate_limit_backend=%s", settings.app_env, _rate_backend())
    from app.services.schema_guard import verify_rls_posture, verify_schema
    await with_retry(verify_schema, name="database.schema", timeout=settings.external_timeout_seconds)
    await with_retry(verify_rls_posture, name="database.rls", timeout=settings.external_timeout_seconds)
    from app.services import storage_service
    try:
        await with_retry(storage_service.ensure_bucket_exists, name="storage.ensure_bucket", timeout=settings.external_timeout_seconds)
    except Exception:
        logger.exception("storage bucket initialization failed; API will remain available")
    scheduler_task = None
    if settings.run_embedded_scheduler:
        # Development-only convenience. Production runs one dedicated
        # scheduler process so API replicas cannot duplicate lifecycle jobs.
        import asyncio as _asyncio
        from app.services.task_scheduler import run_forever as _scheduler_run
        scheduler_task = _asyncio.create_task(_scheduler_run())
    yield
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except _asyncio.CancelledError:
            pass
    logger.info("api_shutdown")


app = FastAPI(
    title="SaaS Core API",
    description="Multi-tenant SaaS backend with Supabase Auth, RBAC, Billing, and Usage Tracking",
    version="2.0.0",
    # Hide interactive API docs in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

# ── Middleware (order matters: last added = first executed) ──
app.add_middleware(TenantResolutionMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=120)
app.add_middleware(ErrorMonitoringMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

# ── Routes ──
app.include_router(auth.router, prefix="/api/v1")
app.include_router(mfa.router, prefix="/api/v1")
app.include_router(profiles.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(invites.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(platform.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")

# ── Digital Invitations Platform ──
app.include_router(events.router, prefix="/api/v1")
app.include_router(digital_invitations.router, prefix="/api/v1")
app.include_router(guests.router, prefix="/api/v1")
app.include_router(templates.router, prefix="/api/v1")
app.include_router(teams.router, prefix="/api/v1")
app.include_router(bookings.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(checkin.router, prefix="/api/v1")
app.include_router(gate_shifts.router, prefix="/api/v1")
app.include_router(mobile.router, prefix="/api/v1")
app.include_router(batches.router, prefix="/api/v1")
app.include_router(fast_invitations.router, prefix="/api/v1")
app.include_router(registration_forms.router, prefix="/api/v1")


# Landing page is now served by the React frontend (same port).
# Old /landing/ routes removed — see frontend/src/features/landing/


# The scanner is intentionally hosted as an isolated application surface.  Its
# production build is served only at /field/, which lets the security middleware
# allow camera access here without allowing it anywhere in the management UI.
_FIELD_PWA_DIST = Path(__file__).resolve().parents[1] / "field-pwa" / "dist"


@app.get("/field", include_in_schema=False)
async def field_pwa_root():
    return RedirectResponse(url="/field/", status_code=307)


@app.get("/field/{asset_path:path}", include_in_schema=False)
async def field_pwa(asset_path: str):
    """Serve the built field PWA with SPA fallback and safe cache semantics."""
    index = _FIELD_PWA_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Field PWA build is not available")

    requested = (_FIELD_PWA_DIST / asset_path).resolve()
    try:
        requested.relative_to(_FIELD_PWA_DIST.resolve())
    except ValueError:
        raise HTTPException(404, "Not found")

    file_to_send = requested if requested.is_file() else index
    response = FileResponse(file_to_send)
    if file_to_send.name in {"index.html", "service-worker.js", "manifest.webmanifest"}:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif "/assets/" in file_to_send.as_posix():
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def _rate_backend() -> str:
    try:
        from app.services.rate_limiter import rate_limiter
        return rate_limiter.backend
    except Exception:
        return "unknown"


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "digital-invitations", "version": "3.0.0"}


@app.get("/health/ready")
async def readiness_check():
    checks: dict[str, dict] = {}
    try:
        async with AsyncSessionLocal() as db:
            await with_retry(lambda: db.execute(text("SELECT 1")), name="database.ping", timeout=settings.external_timeout_seconds)
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        logger.warning("readiness database failed error=%s", type(exc).__name__)
        checks["database"] = {"status": "failed"}
    try:
        from app.services.rate_limiter import rate_limiter
        await with_retry(rate_limiter.ping, name="redis.ping", timeout=settings.external_timeout_seconds)
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        logger.warning("readiness redis failed error=%s", type(exc).__name__)
        checks["redis"] = {"status": "failed"}
    try:
        from app.services.storage_service import check_health as storage_health
        await with_retry(storage_health, name="storage.ping", timeout=settings.external_timeout_seconds)
        checks["storage"] = {"status": "ok"}
    except Exception as exc:
        logger.warning("readiness storage failed error=%s", type(exc).__name__)
        checks["storage"] = {"status": "failed"}
    ready = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse(status_code=200 if ready else 503, content={"status": "ok" if ready else "degraded", "checks": checks})


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    """Expose operational metrics only to a configured private collector."""
    supplied_token = request.headers.get("x-metrics-token", "")
    if not settings.metrics_access_token or not secure_compare(
        supplied_token,
        settings.metrics_access_token,
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(
        content=metrics_snapshot(),
        headers={"Cache-Control": "no-store, private"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": getattr(request.state, "request_id", None)}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed",
            "errors": errors,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
