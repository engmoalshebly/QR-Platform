-- Migration v70: grant EXECUTE on public-schema functions to qentry_app.
--
-- migration_v49_security_governance.sql revoked PostgreSQL's default PUBLIC
-- EXECUTE grant from every SECURITY DEFINER function (correctly -- the goal
-- was keeping them off the anon/authenticated PostgREST surface). v61/v62
-- then explicitly re-granted EXECUTE to qentry_app for exactly four RLS
-- policy helpers (current_tenant_id, current_operated_event_ids,
-- current_linked_tenant_ids, current_cooperating_tenant_ids) and stopped
-- there.
--
-- Nothing ever granted qentry_app EXECUTE on the other ~17 SECURITY DEFINER
-- functions the app actually calls through the RLS-enforced session
-- (get_db/AppSessionLocal) in normal request handling -- most critically
-- user_has_permission(), which almost every require_permission() call in
-- app/services/permission_service.py depends on. A real tenant session hits
-- "permission denied for function user_has_permission" on its very first
-- permission check (confirmed live: GET /api/v1/dashboard/analytics 500).
-- process_field_checkin_fast(), try_increment_usage(), and the tenant/role
-- resolution helpers have the identical gap.
--
-- qentry_app's actual trust boundary is row-level security on tables, not a
-- per-function allowlist -- our FastAPI layer is the only caller of this
-- role (never exposed to PostgREST/anon), and every mutation is already
-- gated by require_permission()/require_owner() in Python before any SQL
-- runs. A blanket grant here matches that boundary and closes this class of
-- bug for every function that exists today; the default-privileges rule
-- closes it for ones created later, regardless of which role creates them.

BEGIN;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO qentry_app;

-- ALTER DEFAULT PRIVILEGES only covers objects created by the role running
-- it. Migrations run as either `postgres` or (when a step needs real
-- superuser, e.g. GRANT SET ON PARAMETER in migration_v52) `supabase_admin`
-- -- cover both so a function created by either one still gets this grant
-- automatically, instead of silently reintroducing this exact bug the next
-- time someone adds a function without remembering this migration exists.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO qentry_app';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin') THEN
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO qentry_app';
  END IF;
END $$;

INSERT INTO app_schema_migrations (version, name)
VALUES (70, 'qentry_app_function_grants')
ON CONFLICT (version) DO NOTHING;

COMMIT;
