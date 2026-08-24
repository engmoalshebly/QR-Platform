-- Complete operation audit trails for member and task mutations.
CREATE OR REPLACE FUNCTION public.audit_operation_member_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO public.event_operation_member_audit(operation_id, user_id, new_role, action)
    VALUES (NEW.operation_id, NEW.user_id, NEW.role, 'added');
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO public.event_operation_member_audit(operation_id, user_id, old_role, new_role, action)
    VALUES (NEW.operation_id, NEW.user_id, OLD.role, NEW.role, 'updated');
    RETURN NEW;
  ELSE
    INSERT INTO public.event_operation_member_audit(operation_id, user_id, old_role, action)
    VALUES (OLD.operation_id, OLD.user_id, OLD.role, 'removed');
    RETURN OLD;
  END IF;
END $$;
DROP TRIGGER IF EXISTS trg_audit_operation_member_change ON public.event_operation_members;
CREATE TRIGGER trg_audit_operation_member_change
AFTER INSERT OR UPDATE OR DELETE ON public.event_operation_members
FOR EACH ROW EXECUTE FUNCTION public.audit_operation_member_change();

CREATE OR REPLACE FUNCTION public.audit_operation_task_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO public.event_operation_task_audit(task_id, operation_id, action, after_data)
    VALUES (NEW.id, NEW.operation_id, 'created', to_jsonb(NEW));
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO public.event_operation_task_audit(task_id, operation_id, action, before_data, after_data)
    VALUES (NEW.id, NEW.operation_id, 'updated', to_jsonb(OLD), to_jsonb(NEW));
    RETURN NEW;
  ELSE
    INSERT INTO public.event_operation_task_audit(task_id, operation_id, action, before_data)
    VALUES (OLD.id, OLD.operation_id, 'deleted', to_jsonb(OLD));
    RETURN OLD;
  END IF;
END $$;
DROP TRIGGER IF EXISTS trg_audit_operation_task_change ON public.event_operation_tasks;
CREATE TRIGGER trg_audit_operation_task_change
AFTER INSERT OR UPDATE OR DELETE ON public.event_operation_tasks
FOR EACH ROW EXECUTE FUNCTION public.audit_operation_task_change();
