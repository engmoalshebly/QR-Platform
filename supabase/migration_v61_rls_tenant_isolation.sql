-- Migration v61: enforce tenant isolation in PostgreSQL for the application role.
--
-- Supersedes the policy set from migration_v52 and the legacy {public} policies
-- from schema_final.sql.  Those legacy policies depend on Supabase's auth.uid()
-- and on get_my_tenant_ids(), which the application role cannot execute, so they
-- are removed rather than OR-ed with the new ones.
--
-- Model
--   * The application connects as qentry_app (NOBYPASSRLS, NOSUPERUSER).
--   * get_db() sets app.current_tenant_id: the tenant the request acts for.
--   * Own rows: every operation is allowed for the current tenant.
--   * Operated events: a provider team may read and write the rows of an event it
--     operates (event_operations links requester and provider).  This is the only
--     cross-tenant path, and it is scoped to that event, never to the other
--     tenant's whole data set.
--   * Missing context means no rows (default deny).
--   * The privileged role (DATABASE_URL) must have BYPASSRLS.  The application
--     checks this at startup and refuses to run in production otherwise.

BEGIN;

-- ── 1. Context helpers ──

CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS UUID
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::UUID;
EXCEPTION WHEN invalid_text_representation THEN
  RETURN NULL;
END;
$$;

-- Events that the current tenant operates, as either requester or provider.
-- SECURITY DEFINER so the lookup does not depend on the caller's policies.  The
-- owner of this function must have BYPASSRLS (checked at startup).
CREATE OR REPLACE FUNCTION public.current_operated_event_ids() RETURNS UUID[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(array_agg(DISTINCT eo.event_id), ARRAY[]::UUID[])
  FROM public.event_operations eo
  WHERE eo.event_id IS NOT NULL
    AND (eo.requester_tenant_id = public.current_tenant_id()
      OR eo.provider_tenant_id  = public.current_tenant_id());
$$;

GRANT EXECUTE ON FUNCTION public.current_tenant_id() TO qentry_app;
GRANT EXECUTE ON FUNCTION public.current_operated_event_ids() TO qentry_app;

-- ── 2. Helper: drop every existing policy on a table ──

CREATE OR REPLACE FUNCTION public._drop_all_policies(p_table TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE pol RECORD;
BEGIN
  FOR pol IN SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = p_table LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol.policyname, p_table);
  END LOOP;
END;
$$;

-- ── 3. Tenant-owned tables ──

DO $$
DECLARE
  tbl TEXT;
  has_event BOOLEAN;
  read_pred TEXT;
  tenant_tables TEXT[] := ARRAY[
    'application_errors', 'audit_logs', 'custom_plans', 'event_categories',
    'event_registration_forms', 'event_team_assignments', 'event_types', 'events',
    'feature_flags', 'generation_batches', 'guests', 'invitations', 'invite_templates',
    'invites', 'membership_roles', 'memberships', 'notifications', 'organizer_team_groups',
    'pending_subscriptions', 'roles', 'subscription_payments', 'subscriptions',
    'team_requests', 'teams', 'tenant_domains', 'tenant_settings', 'usage_counters',
    'batch_items'
  ];
BEGIN
  FOREACH tbl IN ARRAY tenant_tables LOOP
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = tbl AND column_name = 'tenant_id') THEN
      RAISE NOTICE 'skip %: no tenant_id column', tbl;
      CONTINUE;
    END IF;

    PERFORM public._drop_all_policies(tbl);
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);
    -- Supabase grants PostgREST roles table access by default.  Tenant data is
    -- never read that way, so those grants are removed.
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', tbl);

    -- Event-scoped tables let an operating provider reach the event's rows.
    has_event := EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_schema = 'public' AND table_name = tbl AND column_name = 'event_id');
    IF tbl = 'events' THEN
      read_pred := format('(tenant_id = public.current_tenant_id() OR id = ANY(public.current_operated_event_ids()))');
    ELSIF tbl = 'guests' THEN
      -- Guests have no event column; they belong to an event through invitations.
      read_pred := '(tenant_id = public.current_tenant_id() OR id IN (SELECT i.guest_id FROM public.invitations i WHERE i.guest_id IS NOT NULL AND i.event_id = ANY(public.current_operated_event_ids())))';
    ELSIF has_event THEN
      read_pred := format('(tenant_id = public.current_tenant_id() OR event_id = ANY(public.current_operated_event_ids()))');
    ELSE
      read_pred := 'tenant_id = public.current_tenant_id()';
    END IF;

    EXECUTE format('CREATE POLICY tenant_read ON public.%I AS PERMISSIVE FOR SELECT TO qentry_app USING (%s)', tbl, read_pred);
    -- Guests: operating providers read through invitations, but only the owner writes.
    EXECUTE format('CREATE POLICY tenant_insert ON public.%I AS PERMISSIVE FOR INSERT TO qentry_app WITH CHECK (%s)', tbl,
                   CASE WHEN has_event AND tbl NOT IN ('events', 'guests')
                        THEN '(tenant_id = public.current_tenant_id() OR event_id = ANY(public.current_operated_event_ids()))'
                        ELSE 'tenant_id = public.current_tenant_id()' END);
    EXECUTE format('CREATE POLICY tenant_update ON public.%I AS PERMISSIVE FOR UPDATE TO qentry_app USING (%s) WITH CHECK (%s)', tbl,
                   CASE WHEN tbl = 'guests' THEN 'tenant_id = public.current_tenant_id()' ELSE read_pred END,
                   CASE WHEN tbl = 'guests' THEN 'tenant_id = public.current_tenant_id()' ELSE read_pred END);
    -- Deletion stays with the owning tenant, even for operated events.
    EXECUTE format('CREATE POLICY tenant_delete ON public.%I AS PERMISSIVE FOR DELETE TO qentry_app USING (tenant_id = public.current_tenant_id())', tbl);
  END LOOP;
END $$;

-- ── 4. Shared workflow tables: both parties own each row ──

DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['event_operations', 'organizer_booking_requests'] LOOP
    PERFORM public._drop_all_policies(tbl);
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', tbl);

    EXECUTE format($f$CREATE POLICY party_read ON public.%I AS PERMISSIVE FOR SELECT TO qentry_app
      USING (requester_tenant_id = public.current_tenant_id() OR provider_tenant_id = public.current_tenant_id())$f$, tbl);
    EXECUTE format($f$CREATE POLICY party_insert ON public.%I AS PERMISSIVE FOR INSERT TO qentry_app
      WITH CHECK (requester_tenant_id = public.current_tenant_id() OR provider_tenant_id = public.current_tenant_id())$f$, tbl);
    EXECUTE format($f$CREATE POLICY party_update ON public.%I AS PERMISSIVE FOR UPDATE TO qentry_app
      USING (requester_tenant_id = public.current_tenant_id() OR provider_tenant_id = public.current_tenant_id())
      WITH CHECK (requester_tenant_id = public.current_tenant_id() OR provider_tenant_id = public.current_tenant_id())$f$, tbl);
    EXECUTE format($f$CREATE POLICY party_delete ON public.%I AS PERMISSIVE FOR DELETE TO qentry_app
      USING (requester_tenant_id = public.current_tenant_id())$f$, tbl);
  END LOOP;
END $$;

-- ── 5. Privileges: the application role gets DML on tables, nothing more ──

GRANT USAGE ON SCHEMA public TO qentry_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO qentry_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO qentry_app;

-- ── 6. Documented exceptions (enforced in the application, not by RLS) ──
--   * Tables without a tenant_id column: event_gates, event_gate_*, checkins,
--     event_operation_* children.  They are reached through their tenant
--     parent, and every route checks membership and permission explicitly.
--   * organization_requests, workspace_links: pre-tenant or platform workflow.
--   * Global tables (plans, permissions, profiles, tenants): no tenant column.

INSERT INTO app_schema_migrations (version, name)
VALUES (61, 'rls_tenant_isolation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
