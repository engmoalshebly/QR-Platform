-- Production-grade plan feature catalogue and entitlement locking support.
BEGIN;

CREATE TABLE IF NOT EXISTS public.plan_features (
    plan_id UUID NOT NULL REFERENCES public.plans(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL CHECK (feature_key ~ '^[a-z][a-z0-9_]*$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (plan_id, feature_key)
);

ALTER TABLE public.plan_features ENABLE ROW LEVEL SECURITY;

-- Keep customer-facing catalogue promises identical to enforced limits.
UPDATE public.plans SET features = replace(features::text, '3 مستخدمين للوحة التحكم', 'مستخدمان للوحة التحكم')::jsonb
WHERE lower(code) = 'starter';
UPDATE public.plans SET features = replace(replace(features::text,
    '5 أحداث شهرياً', '3 أحداث شهرياً'), '1,000 دعوة شهرياً', '1,500 دعوة شهرياً')::jsonb
WHERE lower(code) = 'basic';
UPDATE public.plans SET features = replace(replace(features::text,
    '20 حدث شهرياً', '10 أحداث شهرياً'), '25 مستخدم للوحة التحكم', '20 مستخدم للوحة التحكم')::jsonb
WHERE lower(code) = 'pro';
UPDATE public.plans SET features = replace(replace(replace(features::text,
    '100 حدث شهرياً', '50 حدثاً شهرياً'), '100 مستخدم للوحة التحكم', '75 مستخدماً للوحة التحكم'),
    '50,000 دعوة شهرياً', '75,000 دعوة شهرياً')::jsonb
WHERE lower(code) = 'business';

DELETE FROM public.pending_subscriptions older
USING public.pending_subscriptions newer
WHERE older.id > newer.id
  AND older.provider = 'link' AND newer.provider = 'link'
  AND older.provider_agreement_id = newer.provider_agreement_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_link_payment
    ON public.pending_subscriptions(provider_agreement_id)
    WHERE provider = 'link';

DELETE FROM public.plan_features pf
USING public.plans p
WHERE pf.plan_id = p.id AND lower(p.code) IN ('starter','basic','pro','business','enterprise');

INSERT INTO public.plan_features (plan_id, feature_key)
SELECT p.id, f.feature_key
FROM public.plans p
JOIN (VALUES
    ('starter', 'email_delivery'),
    ('basic', 'email_delivery'), ('basic', 'rsvp'),
    ('pro', 'email_delivery'), ('pro', 'rsvp'), ('pro', 'pdf_export'), ('pro', 'ai_features'),
    ('business', 'email_delivery'), ('business', 'rsvp'), ('business', 'pdf_export'),
    ('business', 'ai_features'), ('business', 'api_access'), ('business', 'webhooks'),
    ('enterprise', 'email_delivery'), ('enterprise', 'rsvp'), ('enterprise', 'pdf_export'),
    ('enterprise', 'ai_features'), ('enterprise', 'api_access'), ('enterprise', 'webhooks'),
    ('enterprise', 'sso'), ('enterprise', 'white_label')
) AS f(plan_code, feature_key) ON f.plan_code = lower(p.code)
ON CONFLICT DO NOTHING;

-- Entitlement metadata is server-owned; never expose mutations through REST.
REVOKE ALL ON public.plan_features FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON public.plan_features FROM anon;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON public.plan_features FROM authenticated;
  END IF;
END $$;

COMMIT;
