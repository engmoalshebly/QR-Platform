-- Mobile gate operations foundation (phases 0–2).
--
-- A gate is never an authorization boundary by itself.  A scanner must be an
-- active operation member, be assigned to a current gate shift and operate
-- through one active device session.  The tables below deliberately preserve
-- the group snapshot used at assignment time; changing a team group later
-- must not silently change people who are already scheduled at a live gate.

BEGIN;

INSERT INTO public.permissions (key, description) VALUES
  ('gate_shifts.view', 'View gate shifts and scanner assignments'),
  ('gate_shifts.manage', 'Create and manage gate shifts and assignments'),
  ('checkin.search', 'Search the minimum invitation details for a gate'),
  ('checkin.supervise', 'Supervise a gate shift and its device sessions'),
  ('checkin.exceptions.manage', 'Resolve documented attendance exceptions'),
  ('checkin.live', 'View live attendance data')
ON CONFLICT (key) DO NOTHING;

-- Team managers administer the operating model.  Scanner roles are still
-- constrained at request time by a shift assignment and an active device
-- session, so a role permission alone cannot scan an event.
INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'gate_shifts.view', 'gate_shifts.manage',
  'checkin.search', 'checkin.supervise', 'checkin.exceptions.manage',
  'checkin.live'
)
WHERE r.name = 'team_manager'
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'gate_shifts.view', 'gate_shifts.manage',
  'checkin.search', 'checkin.supervise', 'checkin.exceptions.manage',
  'checkin.live'
)
WHERE r.name IN ('Admin', 'Owner')
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN ('checkin.search')
WHERE r.name = 'Check-in Staff'
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.event_gate_shifts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    gate_id UUID NOT NULL REFERENCES public.event_gates(id) ON DELETE RESTRICT,
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE RESTRICT,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Riyadh',
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'active', 'completed', 'cancelled')),
    supervisor_user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    created_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    activated_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_gate_shifts_valid_window CHECK (ends_at > starts_at),
    CONSTRAINT event_gate_shifts_cancel_reason CHECK (
      status <> 'cancelled' OR nullif(trim(coalesce(cancellation_reason, '')), '') IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_event_gate_shifts_gate_window
    ON public.event_gate_shifts(gate_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_event_gate_shifts_operation_status
    ON public.event_gate_shifts(operation_id, status, starts_at);
CREATE INDEX IF NOT EXISTS idx_event_gate_shifts_supervisor
    ON public.event_gate_shifts(supervisor_user_id, starts_at);

CREATE TABLE IF NOT EXISTS public.event_gate_shift_group_assignments (
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES public.organizer_team_groups(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('scanner', 'supervisor')),
    assigned_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (shift_id, group_id, role)
);

CREATE INDEX IF NOT EXISTS idx_gate_shift_group_assignments_group
    ON public.event_gate_shift_group_assignments(group_id, created_at DESC);

-- Membership evidence for a group assignment is kept independently from the
-- effective per-person assignment below.  A direct exception can therefore
-- take precedence without erasing the historical group snapshot.
CREATE TABLE IF NOT EXISTS public.event_gate_shift_group_snapshot_members (
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES public.organizer_team_groups(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('scanner', 'supervisor')),
    snapshotted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (shift_id, group_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_gate_shift_group_snapshot_members_user
    ON public.event_gate_shift_group_snapshot_members(user_id, shift_id);

CREATE TABLE IF NOT EXISTS public.event_gate_shift_members (
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('scanner', 'supervisor')),
    assignment_source TEXT NOT NULL DEFAULT 'direct'
        CHECK (assignment_source IN ('direct', 'group_snapshot')),
    source_group_id UUID REFERENCES public.organizer_team_groups(id) ON DELETE SET NULL,
    assigned_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    conflict_override_reason TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (shift_id, user_id),
    CONSTRAINT gate_shift_member_source CHECK (
      (assignment_source = 'direct' AND source_group_id IS NULL)
      OR (assignment_source = 'group_snapshot' AND source_group_id IS NOT NULL)
    ),
    CONSTRAINT gate_shift_member_override_reason CHECK (
      conflict_override_reason IS NULL
      OR nullif(trim(conflict_override_reason), '') IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_gate_shift_members_user
    ON public.event_gate_shift_members(user_id, is_active);

CREATE TABLE IF NOT EXISTS public.event_gate_device_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shift_id UUID NOT NULL REFERENCES public.event_gate_shifts(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    gate_id UUID NOT NULL REFERENCES public.event_gates(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL CHECK (length(trim(device_id)) BETWEEN 8 AND 200),
    device_name TEXT,
    platform TEXT,
    app_version TEXT,
    session_token_hash CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed', 'revoked')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    closure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gate_device_session_closed_at CHECK (
      (status = 'active' AND closed_at IS NULL AND revoked_at IS NULL)
      OR status <> 'active'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_gate_device_session_per_member
    ON public.event_gate_device_sessions(shift_id, user_id)
    WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_gate_device_session_per_device
    ON public.event_gate_device_sessions(shift_id, device_id)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_gate_device_sessions_shift_status
    ON public.event_gate_device_sessions(shift_id, status, last_seen_at DESC);

-- This is intentionally separate from checkins.  It records invalid and
-- rejected attempts too, without retaining raw QR values or guest PII.
CREATE TABLE IF NOT EXISTS public.event_gate_scan_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    gate_id UUID REFERENCES public.event_gates(id) ON DELETE SET NULL,
    shift_id UUID REFERENCES public.event_gate_shifts(id) ON DELETE SET NULL,
    device_session_id UUID REFERENCES public.event_gate_device_sessions(id) ON DELETE SET NULL,
    scanner_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    invitation_id UUID REFERENCES public.invitations(id) ON DELETE SET NULL,
    result TEXT NOT NULL,
    scan_method TEXT NOT NULL DEFAULT 'qr',
    code_fingerprint CHAR(64),
    client_scan_id UUID,
    client_captured_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address INET,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gate_scan_attempt_client_id
    ON public.event_gate_scan_attempts(device_session_id, client_scan_id)
    WHERE device_session_id IS NOT NULL AND client_scan_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gate_scan_attempts_shift_received
    ON public.event_gate_scan_attempts(shift_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_gate_scan_attempts_event_received
    ON public.event_gate_scan_attempts(event_id, received_at DESC);

ALTER TABLE public.checkins
    ADD COLUMN IF NOT EXISTS device_session_id UUID REFERENCES public.event_gate_device_sessions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS client_scan_id UUID,
    ADD COLUMN IF NOT EXISTS client_captured_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS code_fingerprint CHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_device_client_scan
    ON public.checkins(device_session_id, client_scan_id)
    WHERE device_session_id IS NOT NULL AND client_scan_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.validate_event_gate_shift()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_gate_active BOOLEAN;
  v_operation_event UUID;
  v_supervisor_allowed BOOLEAN;
BEGIN
  SELECT is_active INTO v_gate_active
  FROM public.event_gates
  WHERE id = NEW.gate_id AND event_id = NEW.event_id;
  IF COALESCE(v_gate_active, FALSE) = FALSE THEN
    RAISE EXCEPTION 'Gate must exist, belong to the shift event, and be active';
  END IF;

  SELECT event_id INTO v_operation_event
  FROM public.event_operations
  WHERE id = NEW.operation_id;
  IF v_operation_event IS DISTINCT FROM NEW.event_id THEN
    RAISE EXCEPTION 'Gate shift operation must belong to the same event';
  END IF;

  SELECT EXISTS (
    SELECT 1
    FROM public.event_operations o
    LEFT JOIN public.event_operation_members om
      ON om.operation_id = o.id AND om.user_id = NEW.supervisor_user_id
    WHERE o.id = NEW.operation_id
      AND (o.project_manager_id = NEW.supervisor_user_id OR om.user_id IS NOT NULL)
  ) INTO v_supervisor_allowed;
  IF NOT v_supervisor_allowed THEN
    RAISE EXCEPTION 'Shift supervisor must be assigned to the operation';
  END IF;

  -- Moving a live/scheduled shift cannot create an undeclared double booking.
  IF TG_OP = 'UPDATE' AND NEW.status IN ('scheduled', 'active') THEN
    IF EXISTS (
      SELECT 1
      FROM public.event_gate_shift_members current_member
      JOIN public.event_gate_shift_members other_member
        ON other_member.user_id = current_member.user_id
       AND other_member.shift_id <> NEW.id
       AND other_member.is_active
      JOIN public.event_gate_shifts other_shift ON other_shift.id = other_member.shift_id
      WHERE current_member.shift_id = NEW.id
        AND current_member.is_active
        AND current_member.conflict_override_reason IS NULL
        AND other_shift.status IN ('scheduled', 'active')
        AND tstzrange(other_shift.starts_at, other_shift.ends_at, '[)')
            && tstzrange(NEW.starts_at, NEW.ends_at, '[)')
    ) THEN
      RAISE EXCEPTION 'Shift time overlaps an assigned member shift without a documented override'
        USING ERRCODE = '23P01';
    END IF;
  END IF;

  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_event_gate_shift ON public.event_gate_shifts;
CREATE TRIGGER trg_validate_event_gate_shift
BEFORE INSERT OR UPDATE OF event_id, gate_id, operation_id, starts_at, ends_at, status, supervisor_user_id
ON public.event_gate_shifts
FOR EACH ROW EXECUTE FUNCTION public.validate_event_gate_shift();

CREATE OR REPLACE FUNCTION public.validate_event_gate_shift_member()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_operation_id UUID;
  v_member_allowed BOOLEAN;
  v_group_allowed BOOLEAN;
BEGIN
  SELECT operation_id INTO v_operation_id
  FROM public.event_gate_shifts WHERE id = NEW.shift_id;
  IF v_operation_id IS NULL THEN
    RAISE EXCEPTION 'Gate shift does not exist';
  END IF;

  SELECT EXISTS (
    SELECT 1
    FROM public.event_operations o
    LEFT JOIN public.event_operation_members om
      ON om.operation_id = o.id AND om.user_id = NEW.user_id
    WHERE o.id = v_operation_id
      AND (o.project_manager_id = NEW.user_id OR om.user_id IS NOT NULL)
  ) INTO v_member_allowed;
  IF NOT v_member_allowed THEN
    RAISE EXCEPTION 'Shift member must be assigned to the event operation';
  END IF;

  IF NEW.source_group_id IS NOT NULL THEN
    SELECT EXISTS (
      SELECT 1
      FROM public.organizer_team_groups g
      JOIN public.event_operations o ON o.provider_tenant_id = g.tenant_id
      WHERE g.id = NEW.source_group_id AND o.id = v_operation_id
    ) INTO v_group_allowed;
    IF NOT v_group_allowed THEN
      RAISE EXCEPTION 'Shift group must belong to the operation provider team';
    END IF;
  END IF;

  IF NEW.is_active AND NEW.conflict_override_reason IS NULL AND EXISTS (
    SELECT 1
    FROM public.event_gate_shifts current_shift
    JOIN public.event_gate_shift_members other_member
      ON other_member.user_id = NEW.user_id
     AND other_member.shift_id <> NEW.shift_id
     AND other_member.is_active
    JOIN public.event_gate_shifts other_shift ON other_shift.id = other_member.shift_id
    WHERE current_shift.id = NEW.shift_id
      AND current_shift.status IN ('scheduled', 'active')
      AND other_shift.status IN ('scheduled', 'active')
      AND tstzrange(other_shift.starts_at, other_shift.ends_at, '[)')
          && tstzrange(current_shift.starts_at, current_shift.ends_at, '[)')
  ) THEN
    RAISE EXCEPTION 'Member already has an overlapping gate shift; provide a documented override'
      USING ERRCODE = '23P01';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_event_gate_shift_member ON public.event_gate_shift_members;
CREATE TRIGGER trg_validate_event_gate_shift_member
BEFORE INSERT OR UPDATE OF shift_id, user_id, source_group_id, is_active, conflict_override_reason
ON public.event_gate_shift_members
FOR EACH ROW EXECUTE FUNCTION public.validate_event_gate_shift_member();

CREATE OR REPLACE FUNCTION public.validate_gate_device_session()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_shift RECORD;
  v_assigned BOOLEAN;
BEGIN
  SELECT * INTO v_shift FROM public.event_gate_shifts WHERE id = NEW.shift_id;
  IF NOT FOUND
     OR v_shift.event_id <> NEW.event_id
     OR v_shift.gate_id <> NEW.gate_id THEN
    RAISE EXCEPTION 'Device session does not match its gate shift';
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.event_gate_shift_members
    WHERE shift_id = NEW.shift_id AND user_id = NEW.user_id AND is_active
  ) INTO v_assigned;
  IF NOT v_assigned THEN
    RAISE EXCEPTION 'Only an assigned shift member can start a device session';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_gate_device_session ON public.event_gate_device_sessions;
CREATE TRIGGER trg_validate_gate_device_session
BEFORE INSERT OR UPDATE OF shift_id, event_id, gate_id, user_id
ON public.event_gate_device_sessions
FOR EACH ROW EXECUTE FUNCTION public.validate_gate_device_session();

INSERT INTO public.app_schema_migrations(version, name)
VALUES (46, 'mobile_gate_foundation')
ON CONFLICT (version) DO UPDATE SET name = EXCLUDED.name;

COMMIT;
