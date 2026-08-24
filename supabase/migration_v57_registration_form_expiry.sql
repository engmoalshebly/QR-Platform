-- Migration v57: align registration-form storage with the API contract.
-- The API has supported an optional form expiry since the registration form
-- models were introduced, but the original v10 table omitted the column.

ALTER TABLE public.event_registration_forms
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

COMMENT ON COLUMN public.event_registration_forms.expires_at IS
    'Optional instant after which the public registration form stops accepting submissions.';
