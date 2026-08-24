-- Organizer team marketplace and booking workflow.

CREATE TABLE IF NOT EXISTS public.organizer_booking_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    provider_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    requested_by UUID NOT NULL REFERENCES public.profiles(id),
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    guest_count INTEGER NOT NULL CHECK (guest_count > 0),
    location TEXT,
    contact_name TEXT NOT NULL,
    contact_phone TEXT NOT NULL,
    contact_email TEXT,
    services TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'needs_information', 'accepted', 'rejected', 'cancelled', 'completed')),
    response_note TEXT,
    responded_by UUID REFERENCES public.profiles(id),
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at),
    CHECK (requester_tenant_id <> provider_tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_obr_requester ON public.organizer_booking_requests(requester_tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_obr_provider ON public.organizer_booking_requests(provider_tenant_id, status, starts_at);

CREATE TABLE IF NOT EXISTS public.organizer_team_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    color TEXT NOT NULL DEFAULT '#C9A96E',
    created_by UUID NOT NULL REFERENCES public.profiles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS public.organizer_team_group_members (
    group_id UUID NOT NULL REFERENCES public.organizer_team_groups(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.organizer_booking_group_assignments (
    booking_id UUID NOT NULL REFERENCES public.organizer_booking_requests(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES public.organizer_team_groups(id) ON DELETE CASCADE,
    assigned_by UUID NOT NULL REFERENCES public.profiles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (booking_id, group_id)
);

