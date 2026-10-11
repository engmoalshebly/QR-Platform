-- Migration v69: switch plan pricing from YER to USD, at lower price points.
--
-- Plans were seeded in YER by migration_v11 (and touched again by v12/v15).
-- At current exchange rates those numbers (200/500/1200 YER per month) are
-- worth well under $1/month even for the top paid tier -- not a sustainable
-- price for a SaaS product, and YER itself is too volatile/dual-rate (Aden
-- vs Sana'a) to anchor pricing to directly. USD becomes the stored,
-- canonical currency; the frontend displays a YER-equivalent computed from
-- a periodically-updated exchange-rate constant rather than a second stored
-- price, so updating the rate later needs no migration.

BEGIN;

UPDATE public.plans SET price_monthly = 3,  price_yearly = 30,  currency = 'USD' WHERE code = 'basic';
UPDATE public.plans SET price_monthly = 8,  price_yearly = 80,  currency = 'USD' WHERE code = 'pro';
UPDATE public.plans SET price_monthly = 20, price_yearly = 200, currency = 'USD' WHERE code = 'business';
UPDATE public.plans SET currency = 'USD' WHERE code IN ('starter', 'enterprise');

-- Custom-plan addon unit prices were seeded in the same YER scale
-- (migration_v14) and are summed directly onto plans.price_monthly
-- (app/routes/subscriptions.py calculate_custom_plan: base_price + addons_total).
-- Left alone, that sum would mix a $3-20 USD base price with 4-25 YER
-- per-unit addons -- scaled down proportionally to match.
UPDATE public.plan_addons SET price_per_unit = 0.30 WHERE key = 'events_per_month';
UPDATE public.plan_addons SET price_per_unit = 0.08 WHERE key = 'invitations_per_event';
UPDATE public.plan_addons SET price_per_unit = 0.25 WHERE key = 'invitations_per_month';
UPDATE public.plan_addons SET price_per_unit = 0.15 WHERE key = 'gates_per_event';
UPDATE public.plan_addons SET price_per_unit = 0.06 WHERE key = 'guests_max';
UPDATE public.plan_addons SET price_per_unit = 0.25 WHERE key = 'teams_max';
UPDATE public.plan_addons SET price_per_unit = 0.08 WHERE key = 'team_members_per_team';
UPDATE public.plan_addons SET price_per_unit = 0.40 WHERE key = 'seats_max';
UPDATE public.plan_addons SET price_per_unit = 0.15 WHERE key = 'designed_templates';
UPDATE public.plan_addons SET price_per_unit = 0.25 WHERE key = 'registration_forms_max';
UPDATE public.plan_addons SET price_per_unit = 0.08 WHERE key = 'storage_mb';
UPDATE public.plan_addons SET price_per_unit = 0.05 WHERE key = 'messages_per_month';
UPDATE public.plan_addons SET price_per_unit = 0.12 WHERE key = 'ai_requests_per_month';

INSERT INTO app_schema_migrations (version, name)
VALUES (69, 'usd_pricing')
ON CONFLICT (version) DO NOTHING;

COMMIT;
