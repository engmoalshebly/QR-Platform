-- Migration v65: pending_subscriptions must follow the same linked-workspace
-- scope as subscriptions, custom_plans and usage_counters (migration v62).
--
-- Missed in v62 because the billing-tenant resolution happens one layer above
-- subscription_engine.py: app/routes/subscriptions.py resolves
-- resolve_billing_tenant() and passes the RESULT into SubscriptionEngine as a
-- plain `tenant_id` parameter, so a grep for `billing_tenant_id` inside
-- subscription_engine.py itself finds nothing.  The engine's own queries are
-- real, direct SQL against pending_subscriptions, keyed by whatever tenant_id
-- it was given -- the organizer's linked institution, when billing is
-- delegated:
--
--   * initiate_subscription() / initiate_custom_plan_payment(): INSERT a new
--     pending_subscriptions row for the billing tenant.
--   * _load_pending(): SELECT ... WHERE tenant_id = :tid FOR UPDATE, to
--     confirm an OTP.
--   * confirm_subscription() / confirm_custom_plan_payment(): DELETE ... WHERE
--     id = :id once activated -- no tenant_id in that WHERE clause at all, so
--     today it silently deletes zero rows for a linked organizer (RLS hides
--     the row; the DELETE does not error, it just never cleans up).
--
-- Net effect before this migration: an organizer workspace billing through a
-- linked institution gets "لم يتم العثور على عملية دفع معلقة" on every
-- confirm, and any pending row that is INSERTed under v61's own-tenant-only
-- policy fails outright.  Unlike subscriptions/custom_plans/usage_counters,
-- DELETE must also cross the link here -- nothing else deletes this row.

BEGIN;

DO $$
BEGIN
  PERFORM public._drop_all_policies('pending_subscriptions');
  ALTER TABLE public.pending_subscriptions ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.pending_subscriptions FORCE ROW LEVEL SECURITY;
  REVOKE ALL ON public.pending_subscriptions FROM anon, authenticated;

  CREATE POLICY tenant_read ON public.pending_subscriptions AS PERMISSIVE FOR SELECT TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_insert ON public.pending_subscriptions AS PERMISSIVE FOR INSERT TO qentry_app
    WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_update ON public.pending_subscriptions AS PERMISSIVE FOR UPDATE TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()))
    WITH CHECK (tenant_id = ANY(public.current_linked_tenant_ids()));
  CREATE POLICY tenant_delete ON public.pending_subscriptions AS PERMISSIVE FOR DELETE TO qentry_app
    USING (tenant_id = ANY(public.current_linked_tenant_ids()));
END $$;

INSERT INTO app_schema_migrations (version, name)
VALUES (65, 'rls_pending_subscriptions_linked_tenants')
ON CONFLICT (version) DO NOTHING;

COMMIT;
