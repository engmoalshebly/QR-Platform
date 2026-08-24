-- Linked workspaces: one identity can own an organizer workspace and a
-- separate institution workspace without duplicating users or credentials.

ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS workspace_type TEXT NOT NULL DEFAULT 'institution';

ALTER TABLE public.tenants
    DROP CONSTRAINT IF EXISTS tenants_workspace_type_check;

ALTER TABLE public.tenants
    ADD CONSTRAINT tenants_workspace_type_check
    CHECK (workspace_type IN ('institution', 'organizer'));

-- Existing approved organizer tenants are the organizer half of the pair.
UPDATE public.tenants t
SET workspace_type = 'organizer'
FROM public.organization_requests r
WHERE r.created_tenant_id = t.id
  AND r.status = 'approved';

CREATE TABLE IF NOT EXISTS public.workspace_links (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organizer_tenant_id     UUID NOT NULL UNIQUE REFERENCES public.tenants(id) ON DELETE CASCADE,
    institution_tenant_id   UUID NOT NULL UNIQUE REFERENCES public.tenants(id) ON DELETE CASCADE,
    owner_user_id           UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    billing_tenant_id       UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    status                  TEXT NOT NULL DEFAULT 'active',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT workspace_links_distinct_tenants CHECK (organizer_tenant_id <> institution_tenant_id),
    CONSTRAINT workspace_links_status_check CHECK (status IN ('active', 'suspended'))
);

CREATE INDEX IF NOT EXISTS idx_workspace_links_owner
    ON public.workspace_links(owner_user_id);

ALTER TABLE public.organization_requests
    ADD COLUMN IF NOT EXISTS institution_tenant_id UUID
    REFERENCES public.tenants(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_org_requests_institution_tenant
    ON public.organization_requests(institution_tenant_id)
    WHERE institution_tenant_id IS NOT NULL;

