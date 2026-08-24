-- Phase 6: operation team governance.
ALTER TABLE public.event_operation_members DROP CONSTRAINT IF EXISTS event_operation_members_role_check;
ALTER TABLE public.event_operation_members ADD CONSTRAINT event_operation_members_role_check CHECK (role IN ('manager','lead','member','viewer'));

CREATE OR REPLACE FUNCTION public.prevent_last_operation_manager_removal()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.role = 'manager' AND NOT EXISTS (
    SELECT 1 FROM public.event_operation_members
    WHERE operation_id=OLD.operation_id AND role='manager' AND user_id<>OLD.user_id
  ) THEN
    RAISE EXCEPTION 'Cannot remove the last operation manager' USING ERRCODE='check_violation';
  END IF;
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS trg_prevent_last_operation_manager_removal ON public.event_operation_members;
CREATE TRIGGER trg_prevent_last_operation_manager_removal BEFORE DELETE ON public.event_operation_members
FOR EACH ROW EXECUTE FUNCTION public.prevent_last_operation_manager_removal();

CREATE INDEX IF NOT EXISTS idx_operation_member_workload ON public.event_operation_members(operation_id, role, group_id);
