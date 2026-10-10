-- Migration v62: the two legitimate cross-tenant paths that migration v61 missed.
--
-- v61 scoped cross-tenant access to "events a provider operates".  Verifying the
-- rest of the codebase against real qentry_app traffic found two more patterns,
-- both pre-existing application behaviour, not new features:
--
-- 1. Booking/operation notifications (app/services/notification_service.py).
--    notify_tenant_managers() and notify_operation_members() write a
--    notification row into the COUNTERPARTY tenant: the organizer notifies the
--    provider's managers on booking.created, the provider notifies the
--    organizer on event.completed, operation members on either side notify
--    each other.  Every such call is reachable by either party acting as
--    itself, so a plain "own tenant only" INSERT policy on notifications
--    blocks real traffic the first time a booking or operation fires one.
--
-- 2. Linked workspaces share one commercial entitlement
--    (app/services/entitlement_service.py: resolve_billing_tenant,
--    get_billing_scope_tenant_ids).  An organizer workspace and its linked
--    institution workspace (migration_v42, workspace_links) bill as one
--    account.  Several call sites run raw SQL against the *billing* tenant
--    or the full linked scope while the session's own tenant is the other
--    side of the link:
--      - usage_service.release_usage() / get_current_usage(),
--        feature_service.track_storage_upload(): raw read/write on
--        usage_counters keyed by billing_tenant_id.
--      - usage_service.get_seats_count(): raw SELECT on memberships across
--        the linked scope.
--      - feature_service.check_seats_limit(): raw SELECT on invites across
--        the linked scope.
--      - app/routes/subscriptions.py: subscriptions and custom_plans are read
--        and written keyed by billing_tenant_id; log_audit() there logs under
--        billing_tenant_id too.
--    (try_increment_usage() and increment_usage() are already SECURITY DEFINER
--    and were not affected; this migration does not touch them.)
--
-- Both patterns are existing, intentional relationships backed by a real table
-- (event_operations / organizer_booking_requests for cooperation,
-- workspace_links for billing), never by a client-supplied value.
--
-- 3. The `tenants` table itself was never covered by migration v61's audit: the
--    loop there only picked up tables with a `tenant_id` column, and this one's
--    own identity column is `id`.  It still carries schema_final.sql's legacy
--    policies (`get_my_tenant_ids()`, `is_admin_of()`, `auth.uid()`), which
--    qentry_app cannot satisfy -- not even for its OWN row.  That breaks
--    GET/PATCH /api/v1/tenants/current (app/routes/tenants.py) and the plan
--    update in app/routes/subscriptions.py for every tenant, confirmed by
--    testing against the real qentry_app role rather than assumed.  Booking and
--    operation detail views (app/routes/bookings.py, operations.py) also read
--    both parties' tenant rows in one query.

BEGIN;

-- ── Counterparty of an active booking or operation ──
CREATE OR REPLACE FUNCTION public.current_cooperating_tenant_ids() RETURNS UUID[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(array_agg(DISTINCT t), ARRAY[]::UUID[])
  FROM (
    SELECT requester_tenant_id AS t FROM public.event_operations WHERE provider_tenant_id = public.current_tenant_id()
    UNION SELECT provider_tenant_id FROM public.event_operations WHERE requester_tenant_id = public.current_tenant_id()
    UNION SELECT requester_tenant_id FROM public.organizer_booking_requests WHERE provider_tenant_id = public.current_tenant_id()
    UNION SELECT provider_tenant_id FROM public.organizer_booking_requests WHERE requester_tenant_id = public.current_tenant_id()
  ) s
  WHERE t IS NOT NULL;
$$;

-- ── Own tenant plus its linked billing counterpart, if any ──
CREATE OR REPLACE FUNCTION public.current_linked_tenant_ids() RETURNS UUID[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(array_agg(DISTINCT t), ARRAY[]::UUID[])
  FROM (
    SELECT public.current_tenant_id() AS t
    UNION SELECT organizer_tenant_id FROM public.workspace_links
      WHERE status = 'active'
        AND (organizer_tenant_id = public.current_tenant_id() OR institution_tenant_id = public.current_tenant_id())
    UNION SELECT institution_tenant_id FROM public.workspace_links
      WHERE status = 'active'
        AND (organizer_tenant_id = public.current_tenant_id() OR institution_tenant_id = public.current_tenant_id())
  ) s
  WHERE t IS NOT NULL;
$$;

GRANT EXECUTE ON FUNCTION public.current_cooperating_tenant_ids() TO qentry_app;
GRANT EXECUTE ON FUNCTION public.current_linked_tenant_ids() TO qentry_app;

DO $$
BEGIN
  -- notifications: a tenant may notify an active booking/operation counterpart,
  -- but only ever reads, updates (mark-read) or deletes its own notifications.
  PERFORM public._drop_all_policies('notifications');
  ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.notifications FROM anon, authenticated;

  CREATE POLICY tenant_read ON public.notifications AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_insert ON public.notifications AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = public.current_tenant_id()
             OR tenant_id = ANY(public.current_cooperating_tenant_ids()));
  CREATE POLICY tenant_update ON public.notifications AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = public.current_tenant_id()) WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_delete ON public.notifications AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  -- usage_counters, subscriptions, custom_plans: linked workspaces are one
  -- billing unit.  Delete stays with the owning tenant; nothing deletes these
  -- rows cross-tenant today.
  PERFORM public._drop_all_policies('usage_counters');
  ALTER TABLE public.usage_counters ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.usage_counters FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.usage_counters FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.usage_counters AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.usage_counters AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_update ON public.usage_counters AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids())) WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_delete ON public.usage_counters AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  PERFORM public._drop_all_policies('subscriptions');
  ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.subscriptions FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.subscriptions FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.subscriptions AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.subscriptions AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_update ON public.subscriptions AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids())) WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_delete ON public.subscriptions AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  PERFORM public._drop_all_policies('custom_plans');
  ALTER TABLE public.custom_plans ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.custom_plans FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.custom_plans FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.custom_plans AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.custom_plans AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_update ON public.custom_plans AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids())) WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_delete ON public.custom_plans AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  -- memberships, invites: read across the linked pair to count seats and
  -- pending invites against one shared seats_max.  Every write (inviting,
  -- joining, role changes) stays scoped to the acting tenant only.
  PERFORM public._drop_all_policies('memberships');
  ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.memberships FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.memberships FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.memberships AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.memberships AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_update ON public.memberships AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = public.current_tenant_id()) WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_delete ON public.memberships AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  PERFORM public._drop_all_policies('invites');
  ALTER TABLE public.invites ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.invites FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.invites FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.invites AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.invites AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_update ON public.invites AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = public.current_tenant_id()) WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_delete ON public.invites AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  -- audit_logs: billing actions taken under the linked counterpart (e.g. a
  -- subscription purchase resolved to the institution's billing tenant) may
  -- log there.  Reading another tenant's audit trail is never allowed, and
  -- trigger prevent_audit_log_mutation already blocks UPDATE/DELETE outright.
  PERFORM public._drop_all_policies('audit_logs');
  ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.audit_logs FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.audit_logs FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.audit_logs AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_insert ON public.audit_logs AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = public.current_tenant_id()
             OR tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_update ON public.audit_logs AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = public.current_tenant_id()) WITH CHECK (tenant_id = public.current_tenant_id());
  CREATE POLICY tenant_delete ON public.audit_logs AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = public.current_tenant_id());

  -- tenants: replace schema_final's auth.uid()-based policies, which qentry_app
  -- cannot satisfy even for its own row.  A tenant reads its own row, its
  -- linked billing partner's, and a booking/operation counterparty's (to show
  -- both names in a shared view).  Only its own row and its billing partner's
  -- may be updated (e.g. subscriptions.py changing the billing tenant's plan).
  -- INSERT and DELETE are not granted here: creation and deletion stay on the
  -- privileged connection.
  PERFORM public._drop_all_policies('tenants');
  ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.tenants FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.tenants FROM anon, authenticated;
  CREATE POLICY tenant_read ON public.tenants AS PERMISSIVE FOR SELECT TO qentry_app
    USING (id = public.current_tenant_id()
        OR id = ANY(public.current_linked_tenant_ids())
        OR id = ANY(public.current_cooperating_tenant_ids()));
  CREATE POLICY tenant_update ON public.tenants AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (id = public.current_tenant_id() OR id = ANY(public.current_linked_tenant_ids()))
    WITH CHECK (id = public.current_tenant_id() OR id = ANY(public.current_linked_tenant_ids()));
END $$;

INSERT INTO app_schema_migrations (version, name)
VALUES (62, 'rls_cross_tenant_write_paths')
ON CONFLICT (version) DO NOTHING;

COMMIT;
