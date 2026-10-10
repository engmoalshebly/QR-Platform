-- Migration v64: at most one in-flight Link payment per billing tenant.
--
-- app/services/subscription_engine.py correctly makes a single payment_id's
-- confirmation race-safe (SELECT ... FOR UPDATE in _load_pending, then the
-- pending row is deleted before commit, so a concurrent confirm of the SAME
-- payment_id safely sees "not found" instead of activating twice).
--
-- What it never checked: initiate_subscription() and initiate_custom_plan_payment()
-- create a NEW pending_subscriptions row and a NEW Link payment unconditionally,
-- even while an earlier one for the same tenant is still open.  A double-click on
-- "Subscribe", or two browser tabs, sends two OTPs to the same wallet; confirming
-- BOTH charges the wallet twice but activates only the second subscription period
-- (_activate_pending cancels whatever is currently active before inserting the
-- new one), discarding the first period instead of extending it.  Nobody else can
-- trigger this -- it is the tenant paying itself twice, not a cross-tenant issue --
-- but it is a real, user-visible billing bug.
--
-- The application already pre-checks before calling Link (see
-- app/services/subscription_engine.py); this index is the database-level
-- backstop that closes the check-then-insert race between two concurrent
-- requests, consistent with how _load_pending's FOR UPDATE closes the
-- equivalent race on confirmation.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_subscriptions_one_per_tenant
    ON public.pending_subscriptions (tenant_id)
    WHERE provider = 'link';

INSERT INTO app_schema_migrations (version, name)
VALUES (64, 'one_pending_payment_per_tenant')
ON CONFLICT (version) DO NOTHING;

COMMIT;
