-- Migration v73: align tenants.plan across linked workspaces.
--
-- Linked institution/organizer workspaces share one commercial plan held by the
-- billing tenant.  Approving a plan only updated the billing tenant's cached
-- tenants.plan, so the other workspace kept showing "free".  The application
-- now writes the whole billing scope (entitlement_service.sync_plan_cache); this
-- repairs rows approved before that change.  Idempotent.

BEGIN;

INSERT INTO app_schema_migrations (version, name)
VALUES (73, 'sync_linked_plan_cache')
ON CONFLICT (version) DO NOTHING;

UPDATE tenants t
SET plan = b.plan, updated_at = now()
FROM workspace_links wl
JOIN tenants b ON b.id = wl.billing_tenant_id
WHERE wl.status = 'active'
  AND t.id IN (wl.organizer_tenant_id, wl.institution_tenant_id)
  AND t.id <> b.id
  AND t.plan IS DISTINCT FROM b.plan;

COMMIT;
