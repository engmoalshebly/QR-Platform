-- Migration v66: notify_tenant_managers() cannot find who to notify.
--
-- Found by calling the real function (not reimplemented SQL) through the real
-- get_db() role.  app/services/notification_service.py:
--
--   async def notify_tenant_managers(db, tenant_id, **kwargs):
--       result = await db.execute(text(
--           "SELECT user_id FROM memberships WHERE tenant_id = :tid "
--           "AND status = 'active' AND role IN ('owner','admin')"), {"tid": str(tenant_id)})
--       for user_id in result.scalars().all():
--           await create_notification(db, tenant_id, user_id=user_id, **kwargs)
--
-- Migration v62 let the final INSERT into notifications reach a booking or
-- operation counterparty (current_cooperating_tenant_ids()), but memberships'
-- own SELECT policy only covers the *billing* link (current_linked_tenant_ids()).
-- Calling this for a booking counterparty therefore finds zero managers, the
-- loop never runs, and nothing is inserted -- no error, no notification, every
-- time a booking is created or an operation completes.  The v62 test suite
-- missed this because it inserted into notifications directly instead of
-- calling notify_tenant_managers() itself; tests/test_rls_real_service_functions.py
-- now calls the real function and catches it.
--
-- Scope note: this grants read access to a cooperating tenant's membership
-- roster (who the active owners/admins are) for as long as any booking or
-- operation record links the two tenants, regardless of that record's current
-- status.  That is the same mild, name/role-only disclosure a booking
-- negotiation would produce anyway, and matches the scope already granted for
-- the notifications INSERT itself.  It does not touch INSERT/UPDATE/DELETE on
-- memberships, which stay tenant-owned only.

BEGIN;

DROP POLICY IF EXISTS tenant_read ON public.memberships;
CREATE POLICY tenant_read ON public.memberships AS PERMISSIVE FOR SELECT TO qentry_app
  USING (tenant_id = ANY(public.current_linked_tenant_ids())
      OR tenant_id = ANY(public.current_cooperating_tenant_ids()));

INSERT INTO app_schema_migrations (version, name)
VALUES (66, 'rls_membership_lookup_for_notifications')
ON CONFLICT (version) DO NOTHING;

COMMIT;
