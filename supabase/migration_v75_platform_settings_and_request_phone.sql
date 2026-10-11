-- Migration v75: staff-editable platform settings (payment instructions) and the
-- contact phone captured with a custom-plan request.
--
-- Standard plan requests keep the phone in pending_subscriptions.metadata
-- (contact_phone); custom_plans has typed columns, so it gets one.
-- platform_settings is written only by platform staff through the privileged
-- connection; tenant sessions may read it (the payment instructions are shown
-- to every workspace) but not change it.  Idempotent.

BEGIN;

INSERT INTO app_schema_migrations (version, name)
VALUES (75, 'platform_settings_and_request_phone')
ON CONFLICT (version) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.platform_settings (
    key         TEXT PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$'),
    value       TEXT NOT NULL DEFAULT '',
    updated_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

REVOKE ALL ON public.platform_settings FROM PUBLIC, anon, authenticated;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qentry_app') THEN
    REVOKE ALL ON public.platform_settings FROM qentry_app;
    GRANT SELECT ON public.platform_settings TO qentry_app;
  END IF;
END $$;

INSERT INTO public.platform_settings (key, value)
VALUES ('payment_instructions', '')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE public.custom_plans
    ADD COLUMN IF NOT EXISTS request_phone TEXT;

COMMIT;
