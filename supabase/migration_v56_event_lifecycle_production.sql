-- Event lifecycle production hardening.

ALTER TABLE public.invitations
    ADD COLUMN IF NOT EXISTS registration_request_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS uq_registration_request_per_event
    ON public.invitations(event_id, registration_request_id)
    WHERE registration_request_id IS NOT NULL;

-- Public registration slugs are resolved without a tenant header and must be
-- globally unique. Repair historical collisions deterministically first.
WITH ranked AS (
    SELECT id, slug, row_number() OVER (PARTITION BY slug ORDER BY created_at, id) AS position
    FROM public.events
    WHERE slug IS NOT NULL
)
UPDATE public.events e
SET slug = e.slug || '-' || left(e.id::text, 8)
FROM ranked r
WHERE e.id=r.id AND r.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_events_public_slug
    ON public.events(slug)
    WHERE slug IS NOT NULL;

DO $$ BEGIN
    ALTER TABLE public.event_assets
      ADD CONSTRAINT event_assets_type_check
      CHECK (asset_type IN ('cover_image','invitation_design','logo','background','attachment'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- The legacy SECURITY DEFINER transition function bypasses tenant checks and
-- is no longer a public API. The application performs the locked transition.
REVOKE ALL ON FUNCTION public.transition_event_status(UUID, event_status, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.transition_event_status(UUID, event_status, UUID) FROM anon, authenticated;
