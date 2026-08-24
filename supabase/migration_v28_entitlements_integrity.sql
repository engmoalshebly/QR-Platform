-- Entitlement integrity: one effective subscription/custom plan per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_subscription_per_tenant
    ON public.subscriptions (tenant_id)
    WHERE status IN ('active', 'trialing');

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_custom_plan_per_tenant
    ON public.custom_plans (tenant_id)
    WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_limit_key
    ON public.plan_limits (plan_id, key);

-- Plan codes are the canonical identifiers used by API and billing.
UPDATE public.plans SET code = lower(trim(code)) WHERE code IS NOT NULL;
