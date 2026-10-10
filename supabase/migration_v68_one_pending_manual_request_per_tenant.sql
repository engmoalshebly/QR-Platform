-- Migration v68: at most one pending *manual* subscription request per tenant.
--
-- migration_v64 added this exact backstop for provider='link', but that index
-- is scoped to `WHERE provider = 'link'` and the Link payment gateway code
-- path has since been removed entirely (subscriptions are now reviewed
-- manually by platform staff, provider='manual'). app/routes/subscriptions.py's
-- request_subscription() has the identical check-then-insert race the v64
-- comment describes: a double-click on "Submit request", or two browser
-- tabs, can both pass the "no existing pending request" check and both
-- INSERT, leaving two pending_subscriptions rows for the same tenant for
-- staff to review. This closes the same race for provider='manual' the way
-- v64 already closes it for provider='link'.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_subscriptions_one_manual_per_tenant
    ON public.pending_subscriptions (tenant_id)
    WHERE provider = 'manual';

INSERT INTO app_schema_migrations (version, name)
VALUES (68, 'one_pending_manual_request_per_tenant')
ON CONFLICT (version) DO NOTHING;

COMMIT;
