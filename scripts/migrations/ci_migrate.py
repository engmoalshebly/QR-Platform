"""Apply the authoritative schema and migrations to a blank PostgreSQL database.

Used by CI only. Supabase normally provides the auth schema; this creates the
minimal compatible auth surface needed for schema/RLS validation.
"""
import asyncio
import os
from pathlib import Path

import asyncpg


ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "supabase"
MIGRATION_FILES = [
    "schema_final.sql", "migration_v3_invitations_platform.sql", "migration_v4_generation_batches.sql",
    "migration_v4_event_improvements.sql", "migration_v5_production_hardening.sql", "migration_v5_fix_missing_columns.sql",
    "migration_v6_constraints_and_governance.sql", "migration_v6_platform_limits.sql", "migration_v7_platform_consistency.sql",
    "migration_v8_optional_guest_whatsapp.sql", "migration_v8_slot_index.sql", "migration_v9_event_address.sql",
    "migration_v9_guest_count_scans.sql", "migration_v10_gate_teams_and_users.sql", "migration_v10_registration_forms.sql",
    "migration_v11_professional_plans.sql", "migration_v12_custom_plans.sql", "migration_v13_limits_and_features.sql",
    "migration_v14_addons_pricing.sql", "migration_v15_standard_plan_limits.sql", "migration_v16_paypal_pending_subscriptions.sql",
    "migration_v16_ui_permissions.sql", "migration_v17_team_workflows.sql", "migration_v18_org_requests.sql",
    "migration_v19_security_hardening.sql", "migration_v20_password_reset_otps.sql", "migration_v21_organizer_booking_marketplace.sql",
    "migration_v22_booking_event_link.sql", "migration_v23_phase1_operations.sql", "migration_v24_backfill_event_operations.sql",
    "migration_v25_phase1_tasks_enhancements.sql", "migration_v26_operation_progress_trigger.sql",
    "migration_v27_unified_authorization.sql", "migration_v28_entitlements_integrity.sql",
    "migration_v29_team_manager_role.sql",
    "migration_v30_operation_governance.sql",
    "migration_v31_operation_audit_triggers.sql",
    "migration_v32_booking_workflow.sql",
    "migration_v33_operations_management.sql",
    "migration_v34_task_permissions.sql",
    "migration_v35_operation_team.sql",
    "migration_v36_operation_attachments.sql",
    "migration_v37_team_manager_limits.sql",
    "migration_v38_team_manager_backfill.sql",
    "migration_v39_team_manager_owner_sync.sql",
    "migration_v40_team_manager_permission_repair.sql",
    "migration_v41_team_gate_controls.sql",
    "migration_v42_linked_workspaces.sql",
    "migration_v43_workspace_permission_matrix.sql",
    "migration_v44_billing_entitlement_hardening.sql",
    "migration_v45_operation_group_assignments.sql",
    "migration_v46_mobile_gate_foundation.sql",
    "migration_v47_field_qr_and_offline.sql",
    "migration_v48_fast_field_checkin.sql",
    "migration_v49_security_governance.sql",
    "migration_v50_event_operation_exclusivity.sql",
    "migration_v51_field_checkin_policy.sql",
    "migration_v52_rls_app_role.sql",
    "migration_v53_subscription_payments.sql",
    "migration_v54_currency_yer.sql",
    "migration_v55_plan_entitlements_production.sql",
    "migration_v56_event_lifecycle_production.sql",
    "migration_v57_registration_form_expiry.sql",
    "migration_v58_public_event_slug_repair.sql",
    "migration_v59_registration_identity_uniqueness.sql",
    "migration_v60_operation_exclusivity_idempotent.sql",
    "migration_v61_rls_tenant_isolation.sql",
    "migration_v62_rls_cross_tenant_write_paths.sql",
    "migration_v63_rls_cleanup_non_tenant_tables.sql",
    "migration_v64_one_pending_payment_per_tenant.sql",
    "migration_v65_rls_pending_subscriptions_linked_tenants.sql",
    "migration_v66_rls_membership_lookup_for_notifications.sql",
    "migration_v67_manual_subscription_requests.sql",
    "migration_v68_one_pending_manual_request_per_tenant.sql",
    "migration_v69_usd_pricing.sql",
    "migration_v70_qentry_app_function_grants.sql",
    "migration_v71_qentry_app_auth_users_access.sql",
    "migration_v72_audit_log_actor_set_null.sql",
    "migration_v73_sync_linked_plan_cache.sql",
    "migration_v74_usage_accounting_utc.sql",
]


async def main() -> None:
    database_url = os.environ["MIGRATION_DATABASE_URL"]
    conn = await asyncpg.connect(database_url)
    try:
        # Supabase provides these roles on every managed project.  Migrations
        # reference them (REVOKE ... FROM anon, authenticated), so a blank CI
        # database must create them before applying any SQL file.
        await conn.execute("""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                CREATE ROLE anon NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                CREATE ROLE authenticated NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                CREATE ROLE service_role NOLOGIN BYPASSRLS;
              END IF;
            END $$;
        """)
        has_supabase_auth = await conn.fetchval(
            "SELECT to_regclass('auth.users') IS NOT NULL"
        )
        if not has_supabase_auth:
            await conn.execute("""
                CREATE SCHEMA IF NOT EXISTS auth;
                CREATE TABLE auth.users (
                    id uuid PRIMARY KEY, email text, aud text, role text,
                    email_confirmed_at timestamptz, instance_id uuid,
                    raw_user_meta_data jsonb NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
                LANGUAGE sql STABLE AS $$ SELECT NULL::uuid $$;
                CREATE OR REPLACE FUNCTION auth.role() RETURNS text
                LANGUAGE sql STABLE AS $$ SELECT 'anon'::text $$;
            """)
        for name in MIGRATION_FILES:
            path = SQL_DIR / name
            if not path.exists():
                raise FileNotFoundError(path)
            print(f"applying {name}", flush=True)
            await conn.execute(path.read_text(encoding="utf-8"))
        # migration_v52 creates qentry_app with a placeholder password.  CI sets the
        # real one from the environment so the RLS-enforced connection can log in.
        app_password = os.environ.get("RLS_APP_PASSWORD", "")
        if app_password:
            if not app_password.isalnum():
                raise ValueError("RLS_APP_PASSWORD must be alphanumeric in CI")
            await conn.execute(f"ALTER ROLE qentry_app PASSWORD '{app_password}'")
        count = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        print(f"migration smoke test passed: {count} public tables", flush=True)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
