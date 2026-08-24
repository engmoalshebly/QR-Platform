-- Phase 4: operation management fields and dedicated permissions.
INSERT INTO public.permissions(key, description) VALUES
 ('operations.edit','Edit operation details'),
 ('operations.progress.update','Update operation progress'),
 ('operations.status.change','Change operation status'),
 ('operations.escalate','Escalate an operation'),
 ('operations.close','Close and reopen an operation')
ON CONFLICT(key) DO NOTHING;

ALTER TABLE public.event_operations ALTER COLUMN booking_id DROP NOT NULL;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS internal_notes TEXT;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ;
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS escalated_by UUID REFERENCES public.profiles(id);
ALTER TABLE public.event_operations ADD COLUMN IF NOT EXISTS escalation_reason TEXT;
ALTER TABLE public.event_operations DROP CONSTRAINT IF EXISTS event_operations_progress_check;
ALTER TABLE public.event_operations ADD CONSTRAINT event_operations_progress_check CHECK (progress BETWEEN 0 AND 100);
CREATE INDEX IF NOT EXISTS idx_operations_deadline ON public.event_operations(provider_tenant_id, deadline_at, status);

INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id, p.key FROM public.roles r CROSS JOIN public.permissions p
WHERE r.name='team_manager' AND p.key IN ('operations.edit','operations.progress.update','operations.status.change','operations.escalate','operations.close')
ON CONFLICT DO NOTHING;
