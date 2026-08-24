-- A group assignment is an operational decision in its own right.  Keep it
-- independently from the people currently in the group so it remains visible
-- when members are added, removed, or the group is temporarily empty.
CREATE TABLE IF NOT EXISTS public.event_operation_group_assignments (
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES public.organizer_team_groups(id) ON DELETE CASCADE,
    assigned_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (operation_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_operation_group_assignments_group
    ON public.event_operation_group_assignments(group_id, created_at DESC);
