import logging

from sqlalchemy import text

from app.config import get_settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

REQUIRED_TABLES = {
    "organizer_booking_requests", "event_operations", "event_operation_members",
    "event_operation_tasks", "event_operation_attachments", "event_operation_activity",
    "event_operation_task_comments", "event_task_templates",
    "notifications", "application_errors", "app_schema_migrations",
    "event_gate_shifts", "event_gate_shift_group_assignments", "event_gate_shift_group_snapshot_members",
    "event_gate_shift_members", "event_gate_device_sessions",
    "event_gate_scan_attempts",
    "plan_features",
    "event_gate_offline_packs", "event_gate_offline_pack_items", "gate_assistance_requests",
}
REQUIRED_EVENT_COLUMNS = {"capacity", "deleted_at", "deleted_by"}
REQUIRED_TASK_COLUMNS = {"parent_task_id", "start_at", "approval_required", "approved_by", "approved_at"}
REQUIRED_INVITATION_COLUMNS = {
    "is_registration", "guest_count", "checkin_count", "registration_request_id",
    "registration_phone_key", "registration_email_key",
}
REQUIRED_REGISTRATION_FORM_COLUMNS = {"expires_at"}
REQUIRED_PASSWORD_RESET_COLUMNS = {"otp_hash", "reset_token_hash", "user_id", "consumed_at"}
REQUIRED_SECURITY_FUNCTIONS = {
    "prevent_last_active_tenant_owner_loss",
    "validate_membership_role_tenant",
    "prevent_owner_invite",
    "prevent_audit_log_mutation",
}


async def verify_schema() -> None:
    """Fail startup when the runtime schema is older than the application contract."""
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        table_result = await db.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY(:tables)
        """), {"tables": sorted(REQUIRED_TABLES)})
        found_tables = set(table_result.scalars().all())
        column_result = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'events'
              AND column_name = ANY(:columns)
        """), {"columns": sorted(REQUIRED_EVENT_COLUMNS)})
        found_columns = set(column_result.scalars().all())
        task_column_result = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'event_operation_tasks'
              AND column_name = ANY(:columns)
        """), {"columns": sorted(REQUIRED_TASK_COLUMNS)})
        found_task_columns = set(task_column_result.scalars().all())
        invitation_column_result = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'invitations'
              AND column_name = ANY(:columns)
        """), {"columns": sorted(REQUIRED_INVITATION_COLUMNS)})
        found_invitation_columns = set(invitation_column_result.scalars().all())
        registration_form_column_result = await db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'event_registration_forms'
              AND column_name = ANY(:columns)
        """), {"columns": sorted(REQUIRED_REGISTRATION_FORM_COLUMNS)})
        found_registration_form_columns = set(registration_form_column_result.scalars().all())

        found_password_reset_columns = set()
        found_security_functions = set()
        if settings.is_production:
            password_reset_column_result = await db.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'password_reset_otps'
                  AND column_name = ANY(:columns)
            """), {"columns": sorted(REQUIRED_PASSWORD_RESET_COLUMNS)})
            found_password_reset_columns = set(password_reset_column_result.scalars().all())
            security_function_result = await db.execute(text("""
                SELECT p.proname
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = ANY(:functions)
            """), {"functions": sorted(REQUIRED_SECURITY_FUNCTIONS)})
            found_security_functions = set(security_function_result.scalars().all())

    missing = sorted(
        (REQUIRED_TABLES - found_tables)
        | {f"events.{c}" for c in REQUIRED_EVENT_COLUMNS - found_columns}
        | {f"event_operation_tasks.{c}" for c in REQUIRED_TASK_COLUMNS - found_task_columns}
        | {f"invitations.{c}" for c in REQUIRED_INVITATION_COLUMNS - found_invitation_columns}
        | {f"event_registration_forms.{c}" for c in REQUIRED_REGISTRATION_FORM_COLUMNS - found_registration_form_columns}
    )
    if settings.is_production:
        missing.extend(
            sorted(
                {f"password_reset_otps.{column}" for column in REQUIRED_PASSWORD_RESET_COLUMNS - found_password_reset_columns}
                | {f"public.{function}()" for function in REQUIRED_SECURITY_FUNCTIONS - found_security_functions}
            )
        )
    if missing:
        raise RuntimeError("Database schema is out of date. Missing: " + ", ".join(missing))
    logger.info("Database schema contract verified (phase 1)")
