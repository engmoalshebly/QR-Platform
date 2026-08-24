-- Phase 3: explicit booking workflow, transition guardrails and audit history.

ALTER TABLE public.organizer_booking_requests
  DROP CONSTRAINT IF EXISTS organizer_booking_requests_status_check;
ALTER TABLE public.organizer_booking_requests
  ADD CONSTRAINT organizer_booking_requests_status_check
  CHECK (status IN ('pending','needs_information','accepted','in_progress','completed','rejected','cancelled','reopened'));
ALTER TABLE public.organizer_booking_requests ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE public.organizer_booking_requests ADD COLUMN IF NOT EXISTS scheduled_starts_at TIMESTAMPTZ;
ALTER TABLE public.organizer_booking_requests ADD COLUMN IF NOT EXISTS scheduled_ends_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION public.validate_booking_workflow_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed boolean := false;
BEGIN
  IF TG_OP <> 'UPDATE' OR NEW.status = OLD.status THEN RETURN NEW; END IF;
  allowed := CASE OLD.status
    WHEN 'pending' THEN NEW.status IN ('needs_information','accepted','rejected','cancelled')
    WHEN 'needs_information' THEN NEW.status IN ('accepted','rejected','cancelled')
    WHEN 'accepted' THEN NEW.status IN ('in_progress','cancelled','reopened')
    WHEN 'in_progress' THEN NEW.status IN ('completed','cancelled','reopened')
    WHEN 'completed' THEN NEW.status = 'reopened'
    WHEN 'rejected' THEN NEW.status = 'reopened'
    WHEN 'cancelled' THEN NEW.status = 'reopened'
    WHEN 'reopened' THEN NEW.status IN ('needs_information','accepted','in_progress','cancelled')
    ELSE false END;
  IF NOT allowed THEN RAISE EXCEPTION 'Invalid booking status transition: % -> %', OLD.status, NEW.status USING ERRCODE = 'check_violation'; END IF;
  IF NEW.status IN ('rejected','cancelled','needs_information')
     AND NULLIF(trim(COALESCE(NEW.status_reason, NEW.response_note)), '') IS NULL
  THEN RAISE EXCEPTION 'A reason is required for status %', NEW.status USING ERRCODE = 'check_violation'; END IF;
  IF NEW.status IN ('rejected','cancelled','needs_information') AND NULLIF(trim(NEW.status_reason), '') IS NULL
    THEN NEW.status_reason := trim(NEW.response_note); END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validate_booking_workflow ON public.organizer_booking_requests;
CREATE TRIGGER trg_validate_booking_workflow BEFORE UPDATE OF status ON public.organizer_booking_requests
FOR EACH ROW EXECUTE FUNCTION public.validate_booking_workflow_transition();

CREATE OR REPLACE FUNCTION public.audit_booking_workflow_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status OR NEW.starts_at IS DISTINCT FROM OLD.starts_at OR NEW.ends_at IS DISTINCT FROM OLD.ends_at THEN
    INSERT INTO public.event_operation_activity(operation_id, actor_user_id, action, entity_type, entity_id, details)
    SELECT o.id, NEW.responded_by, 'booking.workflow.changed', 'booking', NEW.id::text,
           jsonb_build_object('from_status', OLD.status, 'to_status', NEW.status,
                              'reason', COALESCE(NEW.status_reason, NEW.response_note),
                              'starts_at', NEW.starts_at, 'ends_at', NEW.ends_at)
    FROM public.event_operations o WHERE o.booking_id = NEW.id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_audit_booking_workflow ON public.organizer_booking_requests;
CREATE TRIGGER trg_audit_booking_workflow AFTER UPDATE ON public.organizer_booking_requests
FOR EACH ROW EXECUTE FUNCTION public.audit_booking_workflow_change();

CREATE INDEX IF NOT EXISTS idx_obr_workflow ON public.organizer_booking_requests(provider_tenant_id, status, updated_at DESC);
