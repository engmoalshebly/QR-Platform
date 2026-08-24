-- Migration v59: prevent duplicate self-registration identities per event.
-- Existing invitations are intentionally not rewritten. The application also
-- checks historical phone/email values before insert; these keys provide the
-- final concurrency-safe database guard for new registrations.

ALTER TABLE public.invitations
    ADD COLUMN IF NOT EXISTS registration_phone_key TEXT,
    ADD COLUMN IF NOT EXISTS registration_email_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_phone_per_event
    ON public.invitations(event_id, registration_phone_key)
    WHERE is_registration = TRUE AND registration_phone_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_email_per_event
    ON public.invitations(event_id, registration_email_key)
    WHERE is_registration = TRUE AND registration_email_key IS NOT NULL;

