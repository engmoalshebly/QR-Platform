import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from supabase import create_client, Client
from app.config import get_settings
import asyncpg

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Parse DB URL for asyncpg (strip the +asyncpg dialect) ──
# Prefer the non-superuser connection when configured (RLS enforcement).
_db_url = settings.database_app_url or settings.database_url
_raw_url = _db_url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_connection():
    """Create an asyncpg connection with statement_cache_size=0 for pgbouncer."""
    return await asyncpg.connect(
        _raw_url,
        statement_cache_size=0,
        ssl=True if settings.is_production else None,
    )


# ── SQLAlchemy Async Engine (for direct DB operations) ──
# Use NullPool + async_creator: ensures every connection has
# statement_cache_size=0 BEFORE any queries run (including
# SQLAlchemy's internal `select pg_catalog.version()`).
engine = create_async_engine(
    _db_url,
    echo=settings.db_echo,
    poolclass=NullPool,
    async_creator=_create_connection,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
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
    "gate_assistance_requests",
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


async def get_db() -> AsyncSession:
    """Yield a DB session with automatic tenant context for RLS enforcement.

    Uses session-scoped SET (not SET LOCAL) so the tenant variable persists
    across commit boundaries within the same request.  Safe because NullPool
    guarantees each request gets its own connection — the variable cannot
    leak to another request.
    """
    from app.tenant_context import get_current_tenant_id

    async with AsyncSessionLocal() as session:
        try:
            tenant_id = get_current_tenant_id()
            if tenant_id:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": str(tenant_id)},
                )
            yield session
        finally:
            await session.close()


# ── Supabase Client singletons (reused across requests) ──
_supabase_admin: Client | None = None
_supabase_client: Client | None = None


def get_supabase_admin() -> Client:
    global _supabase_admin
    if _supabase_admin is None:
        _supabase_admin = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _supabase_admin


def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.resolved_anon_key)
    return _supabase_client
