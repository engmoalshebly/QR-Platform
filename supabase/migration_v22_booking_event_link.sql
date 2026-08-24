-- Link organizer booking requests to the institution's source event.
ALTER TABLE public.organizer_booking_requests
    ADD COLUMN IF NOT EXISTS event_id UUID REFERENCES public.events(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_obr_event
    ON public.organizer_booking_requests(event_id, provider_tenant_id, status);
