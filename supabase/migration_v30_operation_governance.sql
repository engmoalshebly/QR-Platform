-- Phase 2: operation governance, ownership, SLA and integrity constraints.

ALTER TABLE public.roles ADD COLUMN IF NOT EXISTS role_scope TEXT NOT NULL DEFAULT 'tenant';
ALTER TABLE public.roles DROP CONSTRAINT IF EXISTS roles_role_scope_check;
ALTER TABLE public.roles ADD CONSTRAINT roles_role_scope_check CHECK (role_scope IN ('tenant','team','operation'));
UPDATE public.roles SET role_scope = 'team' WHERE name = 'team_manager';

ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS status_change_reason TEXT;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS response_due_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS reopened_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS last_modified_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS last_modified_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE public.event_operations DROP CONSTRAINT IF EXISTS event_operations_priority_check;
ALTER TABLE public.event_operations ADD CONSTRAINT event_operations_priority_check CHECK (priority IN ('low','medium','high','urgent'));

-- Every operation has exactly one primary manager represented by project_manager_id
-- and one manager membership row.
INSERT INTO public.event_operation_members(operation_id, user_id, role)
SELECT o.id, o.project_manager_id, 'manager'
FROM public.event_operations o
WHERE NOT EXISTS (
  SELECT 1 FROM public.event_operation_members m
  WHERE m.operation_id = o.id AND m.user_id = o.project_manager_id
)
ON CONFLICT (operation_id, user_id) DO UPDATE SET role = 'manager';

CREATE UNIQUE INDEX IF NOT EXISTS uq_operation_primary_manager
    ON public.event_operation_members(operation_id) WHERE role = 'manager';

CREATE TABLE IF NOT EXISTS public.event_operation_status_history (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT,
    changed_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.event_operation_member_audit (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    old_role TEXT,
    new_role TEXT,
    action TEXT NOT NULL CHECK (action IN ('added','updated','removed')),
    changed_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.event_operation_task_audit (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES public.event_operation_tasks(id) ON DELETE CASCADE,
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    changed_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    before_data JSONB,
    after_data JSONB,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.validate_operation_member_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE provider_id UUID;
BEGIN
  SELECT provider_tenant_id INTO provider_id FROM public.event_operations WHERE id = NEW.operation_id;
  IF NOT EXISTS (SELECT 1 FROM public.memberships WHERE tenant_id = provider_id AND user_id = NEW.user_id AND status = 'active') THEN
    RAISE EXCEPTION 'Operation member must be an active member of the provider tenant';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validate_operation_member_tenant ON public.event_operation_members;
CREATE TRIGGER trg_validate_operation_member_tenant BEFORE INSERT OR UPDATE ON public.event_operation_members
FOR EACH ROW EXECUTE FUNCTION public.validate_operation_member_tenant();

CREATE OR REPLACE FUNCTION public.validate_operation_task_operation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_task_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.event_operation_tasks p WHERE p.id = NEW.parent_task_id AND p.operation_id = NEW.operation_id
  ) THEN RAISE EXCEPTION 'Parent task must belong to the same operation'; END IF;
  IF NEW.assigned_to IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.event_operation_members m WHERE m.operation_id = NEW.operation_id AND m.user_id = NEW.assigned_to
  ) THEN RAISE EXCEPTION 'Assigned user must belong to the same operation'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validate_operation_task_operation ON public.event_operation_tasks;
CREATE TRIGGER trg_validate_operation_task_operation BEFORE INSERT OR UPDATE ON public.event_operation_tasks
FOR EACH ROW EXECUTE FUNCTION public.validate_operation_task_operation();

CREATE OR REPLACE FUNCTION public.validate_operation_attachment_operation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.task_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.event_operation_tasks t WHERE t.id = NEW.task_id AND t.operation_id = NEW.operation_id
  ) THEN RAISE EXCEPTION 'Attachment task must belong to the same operation'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_validate_operation_attachment_operation ON public.event_operation_attachments;
CREATE TRIGGER trg_validate_operation_attachment_operation BEFORE INSERT OR UPDATE ON public.event_operation_attachments
FOR EACH ROW EXECUTE FUNCTION public.validate_operation_attachment_operation();

CREATE OR REPLACE FUNCTION public.touch_operation_governance()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.last_modified_at = now();
  IF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
    NEW.closed_at = CASE WHEN NEW.status IN ('completed','closed','cancelled') THEN COALESCE(NEW.closed_at, now()) ELSE NEW.closed_at END;
    NEW.reopened_at = CASE WHEN OLD.status IN ('completed','closed','cancelled') AND NEW.status NOT IN ('completed','closed','cancelled') THEN now() ELSE NEW.reopened_at END;
    INSERT INTO public.event_operation_status_history(operation_id, from_status, to_status, reason, changed_by)
    VALUES (NEW.id, OLD.status, NEW.status, NEW.status_change_reason, NEW.last_modified_by);
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_touch_operation_governance ON public.event_operations;
CREATE TRIGGER trg_touch_operation_governance BEFORE UPDATE ON public.event_operations
FOR EACH ROW EXECUTE FUNCTION public.touch_operation_governance();

CREATE INDEX IF NOT EXISTS idx_operation_sla ON public.event_operations(provider_tenant_id, sla_due_at, status);
CREATE INDEX IF NOT EXISTS idx_operation_status_history ON public.event_operation_status_history(operation_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_member_audit ON public.event_operation_member_audit(operation_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_task_audit ON public.event_operation_task_audit(operation_id, changed_at DESC);
