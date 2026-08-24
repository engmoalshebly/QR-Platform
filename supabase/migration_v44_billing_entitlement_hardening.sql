-- Billing and entitlement hardening.
-- Custom-plan entitlements require staff-verified payment and an expiry date;
-- monthly counters enforce their limit atomically under concurrent requests.

BEGIN;

ALTER TABLE public.custom_plans
    ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS activated_by UUID REFERENCES public.profiles(id),
    ADD COLUMN IF NOT EXISTS payment_reference TEXT,
    ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ;

-- Plans made active by the previous self-service endpoint did not carry
-- payment evidence or an end date. Fail closed and let platform staff review
-- and activate each verified plan through the audited platform API.
UPDATE public.custom_plans
SET status = 'pending_review', updated_at = now()
WHERE status = 'active'
  AND (activated_at IS NULL OR valid_until IS NULL);

CREATE INDEX IF NOT EXISTS idx_custom_plans_active_valid
    ON public.custom_plans (tenant_id, valid_until)
    WHERE status = 'active';

-- Prevent webhook retries from inserting the same provider event repeatedly.
DELETE FROM public.subscription_events older
USING public.subscription_events newer
WHERE older.id > newer.id
  AND older.subscription_id = newer.subscription_id
  AND older.provider_event_id IS NOT NULL
  AND older.provider_event_id = newer.provider_event_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_subscription_events_provider_event
    ON public.subscription_events (subscription_id, provider_event_id)
    WHERE provider_event_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.try_increment_usage(
    p_tenant_id UUID,
    p_key TEXT,
    p_amount BIGINT,
    p_limit BIGINT
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_period_start DATE;
    v_period_end DATE;
    v_new_value BIGINT;
BEGIN
    IF p_amount < 1 THEN
        RAISE EXCEPTION 'Usage increment must be positive';
    END IF;
    IF p_limit <> -1 AND p_amount > p_limit THEN
        RETURN NULL;
    END IF;

    v_period_start := date_trunc('month', CURRENT_DATE)::DATE;
    v_period_end := (date_trunc('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day')::DATE;

    INSERT INTO public.usage_counters AS counter
        (tenant_id, period_start, period_end, key, value)
    VALUES (p_tenant_id, v_period_start, v_period_end, p_key, p_amount)
    ON CONFLICT (tenant_id, period_start, key)
    DO UPDATE SET
        value = counter.value + EXCLUDED.value,
        updated_at = now()
    WHERE p_limit = -1 OR counter.value + EXCLUDED.value <= p_limit
    RETURNING value INTO v_new_value;

    RETURN v_new_value;
END;
$$;

COMMIT;
