-- Enforce the invitation admission policy in the single atomic field scan.
--
-- The field clients already use process_field_checkin_fast.  Keeping these
-- decisions inside that function means online scans, manual confirmation and
-- offline reconciliation all receive the same RSVP, expiry and re-entry
-- rules under the invitation row lock.

BEGIN;

-- Existing packs are intentionally stable during a shift. Remove items whose
-- admission now depends on an online decision before installing the stricter
-- policy, so a pre-deployment pack cannot keep admitting them locally.
DELETE FROM public.event_gate_offline_pack_items item
USING public.invitations i
WHERE item.invitation_id = i.id
  AND (
      COALESCE(i.is_registration, FALSE)
      OR i.status IN ('revoked', 'expired', 'declined')
      OR (i.expires_at IS NOT NULL AND i.expires_at <= now())
      OR LOWER(COALESCE(i.metadata ->> 'require_rsvp', 'false'))
           IN ('true', 't', '1', 'yes', 'on')
  );

CREATE OR REPLACE FUNCTION public.process_field_checkin_fast(
    p_token TEXT,
    p_event_id UUID,
    p_gate_id UUID,
    p_shift_id UUID,
    p_device_session_id UUID,
    p_scanner_user_id UUID,
    p_client_scan_id UUID,
    p_client_captured_at TIMESTAMPTZ,
    p_scan_method TEXT,
    p_code_fingerprint TEXT,
    p_entry_count INTEGER DEFAULT 1,
    p_expected_invitation_id UUID DEFAULT NULL,
    p_from_offline BOOLEAN DEFAULT FALSE,
    p_offline_pack_id UUID DEFAULT NULL,
    p_code_format TEXT DEFAULT NULL,
    p_ip_address INET DEFAULT NULL,
    p_claim_already BOOLEAN DEFAULT FALSE
)
RETURNS TABLE (
    invitation_id UUID,
    result TEXT,
    guest_name TEXT,
    ticket_class TEXT,
    event_title TEXT,
    checkin_count INTEGER,
    guest_count INTEGER,
    remaining_count INTEGER,
    idempotent BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_attempt_id UUID;
    v_previous RECORD;
    v_inv RECORD;
    v_result TEXT := 'invalid';
    v_guest_name TEXT;
    v_ticket_class TEXT;
    v_event_title TEXT;
    v_invitation_id UUID;
    v_checkin_count INTEGER := 0;
    v_guest_count INTEGER := 0;
    v_remaining_count INTEGER := 0;
    v_metadata JSONB;
BEGIN
    -- Claim the scan first. Replays return the completed decision and can
    -- never become an additional admission, including when re-entry is on.
    IF p_client_scan_id IS NOT NULL AND NOT p_claim_already THEN
        INSERT INTO public.event_gate_scan_attempts (
            event_id, gate_id, shift_id, device_session_id, scanner_user_id,
            result, scan_method, code_fingerprint, client_scan_id,
            client_captured_at, ip_address
        ) VALUES (
            p_event_id, p_gate_id, p_shift_id, p_device_session_id, p_scanner_user_id,
            'processing', p_scan_method, p_code_fingerprint, p_client_scan_id,
            p_client_captured_at, p_ip_address
        )
        ON CONFLICT (device_session_id, client_scan_id)
        WHERE device_session_id IS NOT NULL AND client_scan_id IS NOT NULL
        DO NOTHING
        RETURNING id INTO v_attempt_id;

        IF v_attempt_id IS NULL THEN
            SELECT a.result, a.metadata
            INTO v_previous
            FROM public.event_gate_scan_attempts a
            WHERE a.device_session_id = p_device_session_id
              AND a.client_scan_id = p_client_scan_id
            LIMIT 1;

            IF FOUND THEN
                RETURN QUERY SELECT
                    NULLIF(v_previous.metadata ->> 'invitation_id', '')::UUID,
                    v_previous.result,
                    NULL::TEXT,
                    v_previous.metadata ->> 'ticket_class',
                    v_previous.metadata ->> 'event_title',
                    COALESCE((v_previous.metadata ->> 'checkin_count')::INTEGER, 0),
                    COALESCE((v_previous.metadata ->> 'guest_count')::INTEGER, 0),
                    COALESCE((v_previous.metadata ->> 'remaining_count')::INTEGER, 0),
                    TRUE;
                RETURN;
            END IF;
        END IF;
    END IF;

    IF p_entry_count IS NULL OR p_entry_count < 1 OR p_entry_count > 10000 THEN
        v_result := 'invalid_entry_count';
    ELSE
        SELECT i.*, e.title AS resolved_event_title, e.allow_reentry AS allow_reentry
        INTO v_inv
        FROM public.invitations i
        JOIN public.events e ON e.id = i.event_id
        WHERE i.token = p_token
        FOR UPDATE OF i;

        IF NOT FOUND THEN
            v_result := 'invalid';
        ELSE
            v_invitation_id := v_inv.id;
            v_ticket_class := v_inv.ticket_class::TEXT;
            v_event_title := v_inv.resolved_event_title;
            v_checkin_count := COALESCE(v_inv.checkin_count, 0);
            v_guest_count := COALESCE(v_inv.guest_count, 1);
            v_remaining_count := GREATEST(v_guest_count - v_checkin_count, 0);

            IF p_expected_invitation_id IS NOT NULL AND v_inv.id <> p_expected_invitation_id THEN
                v_result := 'invalid';
            -- Registration-form QRs never confer gate admission, regardless
            -- of their RSVP state or which client presents them.
            ELSIF COALESCE(v_inv.is_registration, FALSE) THEN
                v_result := 'registration_code';
            ELSIF v_inv.event_id <> p_event_id THEN
                v_result := 'wrong_event';
            ELSIF NOT EXISTS (
                SELECT 1
                FROM public.event_gates g
                WHERE g.id = p_gate_id
                  AND g.event_id = p_event_id
                  AND g.is_active = TRUE
                  AND v_inv.ticket_class = ANY(g.allowed_classes)
                  AND (v_inv.gate_id IS NULL OR v_inv.gate_id = p_gate_id)
            ) THEN
                v_result := 'wrong_gate';
            ELSIF v_inv.status = 'revoked' THEN
                v_result := 'revoked';
            -- RSVP decline is authoritative even if an older workflow left
            -- invitation.status unchanged.
            ELSIF v_inv.status = 'declined'
               OR COALESCE(v_inv.rsvp_status::TEXT, '') = 'declined' THEN
                v_result := 'declined';
            ELSIF v_inv.status = 'expired'
               OR (v_inv.expires_at IS NOT NULL AND v_inv.expires_at <= now()) THEN
                v_result := 'expired';
            -- require_rsvp may originate from legacy imports as either a JSON
            -- boolean or a string. Only an accepted RSVP may enter.
            ELSIF LOWER(COALESCE(v_inv.metadata ->> 'require_rsvp', 'false'))
                    IN ('true', 't', '1', 'yes', 'on')
               AND COALESCE(v_inv.rsvp_status::TEXT, 'pending') <> 'accepted' THEN
                v_result := 'rsvp_required';
            -- Re-entry permits a previously admitted group to return, but a
            -- single scan can never claim more people than this invitation
            -- represents. This keeps a manipulated entry_count bounded.
            ELSIF p_entry_count > v_guest_count THEN
                v_result := 'capacity_exceeded';
            ELSIF p_entry_count > v_remaining_count
               AND NOT COALESCE(v_inv.allow_reentry, FALSE) THEN
                v_result := CASE WHEN v_remaining_count = 0 THEN 'already_checked_in' ELSE 'capacity_exceeded' END;
            ELSE
                UPDATE public.invitations i
                SET status = 'checked_in',
                    checked_in_at = COALESCE(i.checked_in_at, now()),
                    checked_in_by = p_scanner_user_id,
                    checkin_count = i.checkin_count + p_entry_count,
                    updated_at = now()
                WHERE i.id = v_inv.id;

                v_checkin_count := v_checkin_count + p_entry_count;
                v_remaining_count := GREATEST(v_guest_count - v_checkin_count, 0);
                v_guest_name := v_inv.guest_name;
                v_result := 'success';

                INSERT INTO public.checkins (
                    invitation_id, event_id, gate_id, result, scanned_by, scan_method,
                    device_session_id, client_scan_id, client_captured_at, code_fingerprint,
                    entry_count, offline_pack_id, ip_address
                ) VALUES (
                    v_inv.id, p_event_id, p_gate_id, 'success', p_scanner_user_id, p_scan_method,
                    p_device_session_id, p_client_scan_id, p_client_captured_at, p_code_fingerprint,
                    p_entry_count, p_offline_pack_id, p_ip_address
                ) ON CONFLICT (device_session_id, client_scan_id)
                  WHERE device_session_id IS NOT NULL AND client_scan_id IS NOT NULL
                  DO NOTHING;
            END IF;
        END IF;
    END IF;

    IF p_from_offline AND v_result IN ('already_checked_in', 'capacity_exceeded') THEN
        v_result := 'offline_conflict';
    END IF;

    v_metadata := jsonb_build_object(
        'invitation_id', v_invitation_id,
        'ticket_class', v_ticket_class,
        'event_title', v_event_title,
        'checkin_count', v_checkin_count,
        'guest_count', v_guest_count,
        'remaining_count', v_remaining_count,
        'entry_count', COALESCE(p_entry_count, 1),
        'requires_assistance', v_result IN ('already_checked_in', 'capacity_exceeded', 'offline_conflict'),
        'code_format', p_code_format,
        'offline_pack_id', p_offline_pack_id
    );

    IF p_client_scan_id IS NOT NULL THEN
        UPDATE public.event_gate_scan_attempts a
        SET invitation_id = v_invitation_id,
            result = v_result,
            scan_method = p_scan_method,
            code_fingerprint = p_code_fingerprint,
            client_captured_at = p_client_captured_at,
            ip_address = p_ip_address,
            metadata = v_metadata,
            received_at = now()
        WHERE a.device_session_id = p_device_session_id
          AND a.client_scan_id = p_client_scan_id;
    ELSE
        INSERT INTO public.event_gate_scan_attempts (
            event_id, gate_id, shift_id, device_session_id, scanner_user_id,
            invitation_id, result, scan_method, code_fingerprint,
            client_captured_at, ip_address, metadata
        ) VALUES (
            p_event_id, p_gate_id, p_shift_id, p_device_session_id, p_scanner_user_id,
            v_invitation_id, v_result, p_scan_method, p_code_fingerprint,
            p_client_captured_at, p_ip_address, v_metadata
        );
    END IF;

    RETURN QUERY SELECT
        v_invitation_id,
        v_result,
        CASE WHEN v_result = 'success' AND NOT p_from_offline THEN v_guest_name ELSE NULL END,
        v_ticket_class,
        v_event_title,
        v_checkin_count,
        v_guest_count,
        v_remaining_count,
        FALSE;
END;
$$;

COMMENT ON FUNCTION public.process_field_checkin_fast(
  TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT,
  INTEGER, UUID, BOOLEAN, UUID, TEXT, INET, BOOLEAN
) IS
  'One-transaction, idempotent field scan with RSVP, expiry, registration and re-entry policy.';

INSERT INTO public.app_schema_migrations(version, name)
VALUES (51, 'field_checkin_policy')
ON CONFLICT (version) DO NOTHING;

COMMIT;
