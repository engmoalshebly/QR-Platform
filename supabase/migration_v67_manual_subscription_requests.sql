-- Migration v67: manual (staff-approved) subscription requests.
--
-- Link Gateway is disabled for subscriptions and custom plans for now (business
-- decision, not a technical one: real wallet/OTP payments are not being taken
-- today). The replacement flow reuses pending_subscriptions as the request
-- queue, with provider = 'manual' instead of 'link':
--
--   1. A tenant submits a plan request -> INSERT pending_subscriptions
--      (provider='manual', metadata holds plan_code/period/notes).
--   2. A platform staff member reviews it (GET /platform/subscription-requests)
--      and either activates it (verifying payment out of band -- bank
--      transfer, cash, etc.) or rejects it with a reason.
--   3. Activation deletes the pending row and inserts the real `subscriptions`
--      row, exactly like the Link flow's _activate_pending() does today.
--
-- This index is the same race-proof backstop migration_v64 added for
-- provider='link': at most one open request per billing tenant, so a second
-- click or a resubmit-while-pending cannot create a duplicate queue entry.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_subscriptions_one_manual_per_tenant
    ON public.pending_subscriptions (tenant_id)
    WHERE provider = 'manual';

-- A draft custom plan moving to pending_review carries the same two request
-- fields a standard-plan request stores in pending_subscriptions.metadata.
-- Plain columns here (not another jsonb key under `addons`, which is reserved
-- for addon key -> quantity pairs the pricing calculator reconstructs).
ALTER TABLE public.custom_plans
    ADD COLUMN IF NOT EXISTS requested_period TEXT,
    ADD COLUMN IF NOT EXISTS request_notes TEXT;

INSERT INTO app_schema_migrations (version, name)
VALUES (67, 'manual_subscription_requests')
ON CONFLICT (version) DO NOTHING;

COMMIT;
