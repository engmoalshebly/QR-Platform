-- Phase 1 production-readiness: schema reconciliation + event operations.

CREATE TABLE IF NOT EXISTS public.app_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reconcile the event model used by the API with older local databases.
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS capacity INTEGER CHECK (capacity IS NULL OR capacity > 0);
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS vip_capacity INTEGER CHECK (vip_capacity IS NULL OR vip_capacity >= 0);
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS normal_capacity INTEGER CHECK (normal_capacity IS NULL OR normal_capacity >= 0);
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES public.profiles(id);

CREATE TABLE IF NOT EXISTS public.event_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id UUID NOT NULL UNIQUE REFERENCES public.organizer_booking_requests(id) ON DELETE RESTRICT,
    event_id UUID REFERENCES public.events(id) ON DELETE RESTRICT,
    requester_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    provider_tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    project_manager_id UUID NOT NULL REFERENCES public.profiles(id),
    status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning','ready','in_progress','completed','closed','cancelled')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.event_operation_members (
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('manager','lead','member')),
    group_id UUID REFERENCES public.organizer_team_groups(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (operation_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.event_operation_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (length(trim(title)) >= 2),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','blocked','done')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')),
    assigned_to UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    due_at TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES public.profiles(id),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.event_operation_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    task_id UUID REFERENCES public.event_operation_tasks(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    object_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    uploaded_by UUID NOT NULL REFERENCES public.profiles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.event_operation_activity (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.application_errors (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    path TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER NOT NULL DEFAULT 500,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    tenant_id UUID,
    user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operations_provider ON public.event_operations(provider_tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_tasks ON public.event_operation_tasks(operation_id, status, due_at);
CREATE INDEX IF NOT EXISTS idx_operation_activity ON public.event_operation_activity(operation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON public.notifications(tenant_id, user_id, read_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_application_errors_request ON public.application_errors(request_id);

INSERT INTO public.app_schema_migrations(version, name)
VALUES (23, 'phase1_operations') ON CONFLICT (version) DO NOTHING;
