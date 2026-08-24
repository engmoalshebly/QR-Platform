-- Field QR, atomic group admission, and offline shift packs (phases 3 and 5).
--
-- The server remains the source of truth.  Offline packs contain only salted
-- code fingerprints and operational attributes; no guest PII is ever copied
-- to a device.  A late sync is recorded for review but cannot become a checkin
-- after its device session, shift, or pack has expired.

BEGIN;

-- Older deployments created registration-form invitations before this marker
-- existed.  Keep it explicit so gate scans can reject them safely.
ALTER TABLE public.invitations
    ADD COLUMN IF NOT EXISTS is_registration BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS public.event_gate_offline_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_session_id UUID NOT NULL REFERENCES public.event_gate_device_sessions(id) ON DELETE CASCADE,
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    gate_id UUID NOT NULL REFERENCES public.event_gates(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    fingerprint_salt TEXT NOT NULL CHECK (length(fingerprint_salt) >= 24),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'revoked')),
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT,
    CHECK (valid_until > valid_from)
);

CREATE INDEX IF NOT EXISTS idx_gate_offline_packs_session_status
    ON public.event_gate_offline_packs(device_session_id, status, valid_until DESC);

CREATE TABLE IF NOT EXISTS public.event_gate_offline_pack_items (
    pack_id UUID NOT NULL REFERENCES public.event_gate_offline_packs(id) ON DELETE CASCADE,
    invitation_id UUID NOT NULL REFERENCES public.invitations(id) ON DELETE CASCADE,
    code_fingerprint CHAR(64) NOT NULL,
    ticket_class ticket_class NOT NULL,
    allowed_count INTEGER NOT NULL CHECK (allowed_count > 0),
    remaining_count INTEGER NOT NULL CHECK (remaining_count >= 0),
    expires_at TIMESTAMPTZ,
    PRIMARY KEY (pack_id, invitation_id),
    UNIQUE (pack_id, code_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_gate_offline_pack_items_fingerprint
    ON public.event_gate_offline_pack_items(pack_id, code_fingerprint);

CREATE TABLE IF NOT EXISTS public.gate_assistance_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_session_id UUID NOT NULL REFERENCES public.event_gate_device_sessions(id) ON DELETE CASCADE,
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    gate_id UUID NOT NULL REFERENCES public.event_gates(id) ON DELETE RESTRICT,
    requested_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    assistance_type TEXT NOT NULL CHECK (assistance_type IN ('duplicate', 'manual_confirmation', 'access', 'device', 'offline_conflict', 'other')),
    note TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved', 'cancelled')),
    resolved_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (note IS NULL OR length(note) <= 500)
);

CREATE INDEX IF NOT EXISTS idx_gate_assistance_shift_status
    ON public.gate_assistance_requests(shift_id, status, created_at DESC);

ALTER TABLE public.checkins
    ADD COLUMN IF NOT EXISTS entry_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS offline_pack_id UUID REFERENCES public.event_gate_offline_packs(id) ON DELETE SET NULL;

ALTER TABLE public.checkins
    DROP CONSTRAINT IF EXISTS checkins_entry_count_positive;
ALTER TABLE public.checkins
    ADD CONSTRAINT checkins_entry_count_positive CHECK (entry_count > 0);

-- Atomic admission for a group invitation.  This deliberately returns TEXT
-- rather than the historical checkin_result enum, allowing the field app to
-- distinguish a full group invitation and a registration QR without changing
-- existing report rows or enum consumers.
CREATE OR REPLACE FUNCTION public.validate_field_checkin(
    p_token TEXT,
    p_event_id UUID,
    p_gate_id UUID,
    p_entry_count INTEGER DEFAULT 1,
    p_expected_invitation_id UUID DEFAULT NULL
)
RETURNS TABLE (
    invitation_id UUID,
    result TEXT,
    guest_name TEXT,
    ticket_class TEXT,
    event_title TEXT,
    checkin_count INTEGER,
    guest_count INTEGER,
    remaining_count INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_inv RECORD;
    v_remaining INTEGER;
BEGIN
    IF p_entry_count IS NULL OR p_entry_count < 1 OR p_entry_count > 10000 THEN
        RETURN QUERY SELECT NULL::UUID, 'invalid_entry_count', NULL::TEXT, NULL::TEXT, NULL::TEXT, 0, 0, 0;
        RETURN;
    END IF;

    SELECT i.*, e.title AS event_title, e.allow_reentry
    INTO v_inv
    FROM public.invitations i
    JOIN public.events e ON e.id = i.event_id
    WHERE i.token = p_token
    FOR UPDATE OF i;

    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::UUID, 'invalid', NULL::TEXT, NULL::TEXT, NULL::TEXT, 0, 0, 0;
        RETURN;
    END IF;

    IF p_expected_invitation_id IS NOT NULL AND v_inv.id <> p_expected_invitation_id THEN
        RETURN QUERY SELECT v_inv.id, 'invalid', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    -- A registration QR is intentionally not a gate invitation.
    IF COALESCE(v_inv.is_registration, FALSE) THEN
        RETURN QUERY SELECT v_inv.id, 'registration_code', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    IF v_inv.event_id <> p_event_id THEN
        RETURN QUERY SELECT v_inv.id, 'wrong_event', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.event_gates g
        WHERE g.id = p_gate_id
          AND g.event_id = p_event_id
          AND g.is_active
          AND v_inv.ticket_class = ANY(g.allowed_classes)
          AND (v_inv.gate_id IS NULL OR v_inv.gate_id = p_gate_id)
    ) THEN
        RETURN QUERY SELECT v_inv.id, 'wrong_gate', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    IF v_inv.status = 'revoked' THEN
        RETURN QUERY SELECT v_inv.id, 'revoked', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    IF v_inv.status = 'declined' THEN
        RETURN QUERY SELECT v_inv.id, 'declined', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    IF v_inv.status = 'expired' OR (v_inv.expires_at IS NOT NULL AND v_inv.expires_at < now()) THEN
        RETURN QUERY SELECT v_inv.id, 'expired', NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count, COALESCE(v_inv.guest_count, 1), GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
        RETURN;
    END IF;

    v_remaining := GREATEST(COALESCE(v_inv.guest_count, 1) - v_inv.checkin_count, 0);
    IF p_entry_count > v_remaining THEN
        RETURN QUERY SELECT v_inv.id,
            CASE WHEN v_remaining = 0 THEN 'already_checked_in' ELSE 'capacity_exceeded' END,
            NULL::TEXT, v_inv.ticket_class::TEXT, v_inv.event_title, v_inv.checkin_count,
            COALESCE(v_inv.guest_count, 1), v_remaining;
        RETURN;
    END IF;

    UPDATE public.invitations AS i SET
        status = 'checked_in',
        checked_in_at = COALESCE(checked_in_at, now()),
        checkin_count = i.checkin_count + p_entry_count,
        updated_at = now()
    WHERE i.id = v_inv.id;

    RETURN QUERY SELECT
        v_inv.id,
        'success',
        v_inv.guest_name,
        v_inv.ticket_class::TEXT,
        v_inv.event_title,
        v_inv.checkin_count + p_entry_count,
        COALESCE(v_inv.guest_count, 1),
        GREATEST(COALESCE(v_inv.guest_count, 1) - (v_inv.checkin_count + p_entry_count), 0);
END;
$$;

-- A shift/device invalidation immediately invalidates its cached offline pack.
CREATE OR REPLACE FUNCTION public.invalidate_gate_offline_packs()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'event_gate_device_sessions' AND NEW.status <> 'active' THEN
        UPDATE public.event_gate_offline_packs
        SET status = 'revoked', revoked_at = now(), revoked_reason = 'device_session_' || NEW.status
        WHERE device_session_id = NEW.id AND status = 'active';
    ELSIF TG_TABLE_NAME = 'event_gate_shifts' AND NEW.status IN ('completed', 'cancelled') THEN
        UPDATE public.event_gate_offline_packs
        SET status = 'revoked', revoked_at = now(), revoked_reason = 'shift_' || NEW.status
        WHERE shift_id = NEW.id AND status = 'active';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_invalidate_gate_offline_packs_from_device ON public.event_gate_device_sessions;
CREATE TRIGGER trg_invalidate_gate_offline_packs_from_device
AFTER UPDATE OF status ON public.event_gate_device_sessions
FOR EACH ROW EXECUTE FUNCTION public.invalidate_gate_offline_packs();

DROP TRIGGER IF EXISTS trg_invalidate_gate_offline_packs_from_shift ON public.event_gate_shifts;
CREATE TRIGGER trg_invalidate_gate_offline_packs_from_shift
AFTER UPDATE OF status ON public.event_gate_shifts
FOR EACH ROW EXECUTE FUNCTION public.invalidate_gate_offline_packs();

INSERT INTO public.app_schema_migrations(version, name)
VALUES (47, 'field_qr_and_offline')
ON CONFLICT (version) DO UPDATE SET name = EXCLUDED.name;

COMMIT;
