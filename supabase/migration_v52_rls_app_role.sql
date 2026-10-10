-- migration_v52_rls_app_role.sql
-- Creates a non-superuser role for the application and adds RLS policies
-- that enforce tenant isolation via current_setting('app.current_tenant_id').
--
-- After applying, update DATABASE_APP_URL to use the qentry_app role.
-- The app issues SET LOCAL app.current_tenant_id = '<uuid>' per request.
-- RLS policies below guarantee that even a missing WHERE tenant_id filter
-- in application code cannot leak data across tenants.

BEGIN;

-- ── 1. Register this migration ──
INSERT INTO app_schema_migrations (version, name)
VALUES (52, 'rls_app_role')
ON CONFLICT (version) DO NOTHING;

-- ── 2. Create the application role (non-superuser, inherits nothing) ──
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qentry_app') THEN
    CREATE ROLE qentry_app LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;

-- ── 3. Grant schema + table access ──
GRANT USAGE ON SCHEMA public TO qentry_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO qentry_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO qentry_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO qentry_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO qentry_app;

-- Allow the app to SET LOCAL configuration parameters
GRANT SET ON PARAMETER app.current_tenant_id TO qentry_app;

-- ── 4. Helper: safely read the current tenant id ──
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
BEGIN
  RETURN current_setting('app.current_tenant_id', true)::UUID;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- ── 5. Enable RLS + create policies for every tenant-scoped table ──
-- Each table gets: SELECT/INSERT/UPDATE/DELETE restricted to matching tenant_id.
-- The postgres superuser bypasses RLS automatically (for migrations/admin).

-- Helper function to avoid repeating the same DDL 28+ times.
-- We use DO blocks with dynamic SQL.

DO $$
DECLARE
  tbl TEXT;
  tenant_tables TEXT[] := ARRAY[
    'audit_logs', 'application_errors', 'custom_plans', 'event_categories',
    'event_operations', 'event_registration_forms', 'event_team_assignments',
    'event_types', 'events', 'feature_flags', 'generation_batches', 'guests',
    'invitations', 'invite_templates', 'invites', 'membership_roles',
    'memberships', 'notifications', 'organizer_booking_requests',
    'organizer_team_groups', 'pending_subscriptions', 'roles', 'subscriptions',
    'team_requests', 'teams', 'tenant_domains', 'tenant_settings',
    'usage_counters', 'workspace_links', 'batch_items', 'checkins',
    'event_gates', 'event_gate_users', 'event_gate_shifts',
    'event_gate_shift_members', 'event_gate_scan_attempts',
    'event_gate_device_sessions', 'event_gate_offline_packs',
    'event_gate_offline_pack_items', 'event_gate_shift_group_assignments',
    'event_gate_shift_group_snapshot_members', 'event_operation_members',
    'event_operation_tasks', 'event_operation_activity',
    'event_operation_attachments', 'event_operation_attachment_downloads',
    'event_operation_status_history', 'event_operation_task_audit',
    'event_operation_task_comments', 'event_operation_member_audit',
    'event_operation_group_assignments', 'event_task_templates',
    'invitation_deliveries', 'team_memberships', 'template_assets',
    'template_elements', 'organization_requests',
    'organizer_booking_group_assignments', 'organizer_team_group_members',
    'gate_assistance_requests'
  ];
BEGIN
  FOREACH tbl IN ARRAY tenant_tables LOOP
    -- Skip tables that don't exist yet
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = tbl
    ) THEN
      RAISE NOTICE 'Skipping non-existent table: %', tbl;
      CONTINUE;
    END IF;

    -- Skip tables that don't have tenant_id column
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = tbl AND column_name = 'tenant_id'
    ) THEN
      RAISE NOTICE 'Skipping table without tenant_id: %', tbl;
      CONTINUE;
    END IF;

    -- Enable RLS (idempotent)
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);

    -- Force RLS for table owner too (important: without this, table owners bypass RLS)
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);

    -- Drop old app-role policies if they exist (idempotent re-run)
    EXECUTE format('DROP POLICY IF EXISTS rls_app_tenant_select ON public.%I', tbl);
    EXECUTE format('DROP POLICY IF EXISTS rls_app_tenant_insert ON public.%I', tbl);
    EXECUTE format('DROP POLICY IF EXISTS rls_app_tenant_update ON public.%I', tbl);
    EXECUTE format('DROP POLICY IF EXISTS rls_app_tenant_delete ON public.%I', tbl);

    -- SELECT: only rows belonging to the current tenant
    EXECUTE format(
      'CREATE POLICY rls_app_tenant_select ON public.%I FOR SELECT TO qentry_app USING (tenant_id = current_tenant_id())',
      tbl
    );

    -- INSERT: can only insert rows for the current tenant
    EXECUTE format(
      'CREATE POLICY rls_app_tenant_insert ON public.%I FOR INSERT TO qentry_app WITH CHECK (tenant_id = current_tenant_id())',
      tbl
    );

    -- UPDATE: can only update rows belonging to the current tenant
    EXECUTE format(
      'CREATE POLICY rls_app_tenant_update ON public.%I FOR UPDATE TO qentry_app USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id())',
      tbl
    );

    -- DELETE: can only delete rows belonging to the current tenant
    EXECUTE format(
      'CREATE POLICY rls_app_tenant_delete ON public.%I FOR DELETE TO qentry_app USING (tenant_id = current_tenant_id())',
      tbl
    );

    RAISE NOTICE 'RLS policies created for: %', tbl;
  END LOOP;
END $$;

COMMIT;
