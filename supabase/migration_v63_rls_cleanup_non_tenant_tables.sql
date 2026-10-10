-- Migration v63: remove stale RLS from tables that were never tenant-scoped.
--
-- A systematic sweep (SET ROLE qentry_app; SELECT ... on every table) found 16
-- tables with schema_final.sql's legacy RLS still enabled (relrowsecurity = true)
-- and no corresponding v61/v62 policy, because they have no tenant_id column:
--
--   * Global reference data: plans, plan_limits, plan_addons, plan_features,
--     permissions, role_permissions, profiles.
--   * Operational children reached only through their parent
--     (event/template/team/batch/invitation/subscription), already documented in
--     migration_v61 as app-layer-enforced, matching ADR-0001: batch_items,
--     checkins, event_assets, event_gates, invitation_deliveries,
--     subscription_events, team_memberships, template_assets, template_elements.
--
-- PostgreSQL applies RLS to every role except the table owner and superusers,
-- REGARDLESS of FORCE ROW LEVEL SECURITY (FORCE only changes the owner's
-- behaviour).  So qentry_app was already subject to these legacy policies, not
-- protected from them by their missing FORCE flag.  Confirmed by direct test:
--
--   SET ROLE qentry_app; SELECT count(*) FROM profiles;
--   ERROR:  permission denied for function get_my_tenant_ids
--
-- That breaks a profile lookup on nearly every authenticated request, and
-- check-in/gate/template reads and writes throughout the field and design
-- flows.  These tables were never meant to carry a tenant_id-based policy (v61's
-- own loop skips any table without one); the fix is to remove the dead policies
-- and leave isolation where the application already enforces it: by joining
-- through the owning event, template, team, batch or invitation and checking
-- membership/permission, exactly as ADR-0001 describes for this class of table.
--
-- Disabling RLS does not change qentry_app's privileges: migration_v52 already
-- granted it SELECT/INSERT/UPDATE/DELETE on every table.  REVOKE FROM anon,
-- authenticated matches the pattern in v61/v62 and closes the unused PostgREST
-- path (no client code queries Supabase tables directly; verified by search).

BEGIN;

DO $$
DECLARE
  tbl TEXT;
  cleanup_tables TEXT[] := ARRAY[
    'plans', 'plan_limits', 'plan_addons', 'plan_features', 'permissions', 'role_permissions', 'profiles',
    'batch_items', 'checkins', 'event_assets', 'event_gates', 'invitation_deliveries',
    'subscription_events', 'team_memberships', 'template_assets', 'template_elements'
  ];
BEGIN
  FOREACH tbl IN ARRAY cleanup_tables LOOP
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
      RAISE NOTICE 'skip %: table does not exist', tbl;
      CONTINUE;
    END IF;
    PERFORM public._drop_all_policies(tbl);
    EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', tbl);
  END LOOP;
END $$;

INSERT INTO app_schema_migrations (version, name)
VALUES (63, 'rls_cleanup_non_tenant_tables')
ON CONFLICT (version) DO NOTHING;

COMMIT;
