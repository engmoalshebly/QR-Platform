import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from sqlalchemy.util import await_only
from supabase import create_client, Client
from app.config import get_settings
import asyncpg

logger = logging.getLogger(__name__)
settings = get_settings()

# This module is imported before app.main runs its configuration gate, so the
# gate is repeated here.  Otherwise an empty environment fails with an opaque
# SQLAlchemy parse error instead of the list of missing settings.
if settings.is_production:
    _config_problems = settings.validate_for_production()
    if _config_problems:
        raise RuntimeError(
            "Refusing to start in production with invalid configuration: "
            + "; ".join(_config_problems)
        )

# ── Two database roles, two engines ──
#
# privileged (DATABASE_URL): owner role with BYPASSRLS.  Used only by
#   infrastructure that must see across tenants: tenant resolution, membership
#   checks in the middleware, schedulers, workers, startup checks, platform staff
#   and token-scoped public routes.  Each use is listed in app/routes or documented.
#
# application (DATABASE_APP_URL): qentry_app, NOBYPASSRLS.  Used by get_db() for
#   every tenant-scoped request.  Row-level security enforces isolation here even
#   if a query forgets its WHERE tenant_id.
_privileged_url = settings.database_url
_app_url = settings.database_app_url or settings.database_url
if not _privileged_url:
    raise RuntimeError("DATABASE_URL must be set")
if settings.is_production and (not settings.database_app_url or _app_url == _privileged_url):
    raise RuntimeError(
        "DATABASE_APP_URL must name a distinct non-bypass role in production; "
        "without it RLS is not enforced for tenant requests."
    )


def _build_engine(url: str):
    raw_url = url.replace("postgresql+asyncpg://", "postgresql://")

    async def _create_connection():
        """asyncpg connection with statement_cache_size=0 for pgbouncer."""
        connection = await asyncpg.connect(
            raw_url,
            statement_cache_size=0,
            ssl=(
                True
                if settings.is_production and settings.database_ssl.strip().lower() != "disable"
                else None
            ),
        )
        # Billing periods and all date-based SQL use an explicit timezone.
        await connection.execute("SET TIME ZONE 'UTC'")
        return connection

    # NullPool + async_creator: every connection has statement_cache_size=0
    # before any query runs, including SQLAlchemy's internal version probe.
    pool_args: dict = (
        {"pool_size": settings.db_pool_size, "max_overflow": settings.db_pool_max_overflow,
         "pool_pre_ping": True, "pool_recycle": 1800}
        if settings.db_pool_size > 0 else {"poolclass": NullPool}
    )
    built = create_async_engine(
        url,
        echo=settings.db_echo,
        hide_parameters=True,  # guest contacts, snapshot bytes and tokens are never logged by SQLAlchemy
        async_creator=_create_connection,
        **pool_args,
    )
    if settings.db_pool_size > 0:
        event.listen(built.sync_engine, "reset", _reset_session_state)
    return built


def _reset_session_state(dbapi_connection, connection_record, reset_state) -> None:
    """Return a pooled connection with no request state left on it.

    get_db() stores the tenant in a session-level setting
    (app.current_tenant_id) that row-level security reads.  A pooled
    connection outlives the request, so the setting is cleared here, every time
    a connection goes back to the pool.  If clearing fails the error propagates
    and SQLAlchemy discards the connection instead of reusing it.
    """
    connection = dbapi_connection.driver_connection
    await_only(connection.execute("ROLLBACK"))
    await_only(connection.execute("RESET ALL; SET TIME ZONE 'UTC'"))


engine = _build_engine(_privileged_url)
app_engine = _build_engine(_app_url)

# Infrastructure sessions (privileged).
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Tenant-scoped request sessions (RLS-enforced role).
AppSessionLocal = async_sessionmaker(
    app_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Tables that require tenant_id in every query ──
TENANT_SCOPED_TABLES: frozenset[str] = frozenset({
    "audit_logs", "application_errors", "custom_plans", "event_categories",
    "event_operations", "event_registration_forms", "event_team_assignments",
    "event_types", "events", "feature_flags", "generation_batches", "guests",
    "invitations", "invite_templates", "invites", "membership_roles",
    "memberships", "notifications", "organizer_booking_requests",
    "organizer_team_groups", "pending_subscriptions", "roles", "subscriptions",
    "team_requests", "teams", "tenant_domains", "tenant_settings",
    "usage_counters", "workspace_links", "batch_items", "checkins",
    "event_gates", "event_gate_users", "event_gate_shifts",
    "event_gate_shift_members", "event_gate_scan_attempts",
    "event_gate_device_sessions", "event_gate_offline_packs",
    "event_gate_offline_pack_items", "event_gate_shift_group_assignments",
    "event_gate_shift_group_snapshot_members", "event_operation_members",
    "event_operation_tasks", "event_operation_activity",
    "event_operation_attachments", "event_operation_attachment_downloads",
    "event_operation_status_history", "event_operation_task_audit",
    "event_operation_task_comments", "event_operation_member_audit",
    "event_operation_group_assignments", "event_task_templates",
    "invitation_deliveries", "team_memberships", "template_assets",
    "template_elements", "organization_requests",
    "organizer_booking_group_assignments", "organizer_team_group_members",
    "gate_assistance_requests", "whatsapp_message_images", "whatsapp_message_templates", "whatsapp_connections", "whatsapp_deliveries",
    "whatsapp_delivery_requests", "whatsapp_webhook_receipts",
    "generation_operations", "generation_imports", "generation_import_rows",
    "generation_uploads", "generation_upload_rows", "generation_storage_objects",
    "generation_snapshot_assets", "generation_operation_assets", "generation_outbox",
    "generation_artifacts", "generation_artifact_items",
})

# Tables exempt from tenant audit (system-wide or public-facing)
_TENANT_EXEMPT_TABLES: frozenset[str] = frozenset({
    "tenants", "plans", "plan_limits", "plan_addons", "profiles",
    "permissions", "role_permissions", "password_reset_otps",
    "app_schema_migrations",
})


def _audit_tenant_filter(conn, cursor, statement, parameters, context, executemany):
    """SQLAlchemy core event: warn when a tenant-scoped table is queried
    without a tenant_id bind parameter.  Runs only in non-production."""
    if not statement:
        return
    stmt_lower = statement.lower()
    if stmt_lower.startswith("set ") or stmt_lower.startswith("show "):
        return
    for table in TENANT_SCOPED_TABLES:
        if table in stmt_lower:
            params = parameters or {}
            param_keys = set()
            if isinstance(params, dict):
                param_keys = set(params.keys())
            elif isinstance(params, (list, tuple)) and params and isinstance(params[0], dict):
                param_keys = set(params[0].keys())
            has_tenant_param = any(
                "tenant" in k.lower() for k in param_keys
            )
            has_tenant_in_sql = "tenant_id" in stmt_lower
            if not has_tenant_param and not has_tenant_in_sql:
                logger.warning(
                    "TENANT_AUDIT: query on '%s' without tenant_id filter: %.200s",
                    table, statement,
                )
            break


if not settings.is_production:
    event.listen(engine.sync_engine, "before_cursor_execute", _audit_tenant_filter)
    event.listen(app_engine.sync_engine, "before_cursor_execute", _audit_tenant_filter)


async def get_db() -> AsyncSession:
    """Tenant-scoped session on the RLS-enforced role.

    Sets the tenant the request acts for.  Rows of events that tenant operates
    are readable through the policies in migration v61.  Without a tenant
    context every RLS table returns no rows (default deny).

    The setting is session-level; pooled connections are cleared when they
    return to the pool (_reset_session_state) and the value is rewritten at the
    start of every request, so it cannot leak between requests.
    """
    from app.tenant_context import get_current_tenant_id

    async with AppSessionLocal() as session:
        try:
            tenant_id = get_current_tenant_id()
            # Always written, also when empty: a pooled connection must never
            # carry a tenant from an earlier request into this one.
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": str(tenant_id) if tenant_id else ""},
            )
            yield session
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_privileged_db() -> AsyncSession:
    """Cross-tenant session (BYPASSRLS).  Use only where the route cannot be
    scoped to one tenant: platform staff, token-scoped public links, sign-in
    across memberships.  Every such route must check its own authorization and
    is listed in tests/test_database_access_policy.py.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Supabase clients ──
#
# supabase-py rewrites the client's `Authorization` header to the signed-in
# user's access token on every SIGNED_IN / TOKEN_REFRESHED event.  A shared
# client that also performed `sign_in_with_password` or `refresh_session` would
# therefore silently stop using its service-role key: Storage uploads then run
# as that user (RLS violations) and Auth admin calls are rejected -- for every
# later request, until the process restarts.  Two rules prevent that:
#   * the shared clients below never react to auth events (`_freeze`), and
#   * anything that creates a user session uses `new_auth_client()`, a
#     throw-away anon client.
_supabase_admin: Client | None = None


def _freeze(client: Client) -> Client:
    """Stop a shared client from adopting a user session's token."""
    emitters = getattr(client.auth, "_state_change_emitters", None)
    if emitters is not None:
        emitters.clear()
    return client


def get_supabase_admin() -> Client:
    """Shared service-role client: Storage and Auth *admin* operations only."""
    global _supabase_admin
    if _supabase_admin is None:
        _supabase_admin = _freeze(
            create_client(settings.supabase_url, settings.supabase_service_role_key)
        )
    return _supabase_admin


def new_auth_client() -> Client:
    """Fresh anon-key client for one sign-in / refresh / OTP exchange.

    Never shared, so a user's session cannot leak into another request.
    """
    return create_client(settings.supabase_url, settings.resolved_anon_key)


def get_supabase_client() -> Client:
    """Deprecated alias kept for callers that only need an anon client."""
    return new_auth_client()
