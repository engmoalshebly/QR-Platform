-- Security and integrity hardening for membership workflows.

-- One pending invite per tenant/email. The API also normalizes email to lower
-- case, while this index protects concurrent requests at the database layer.
CREATE UNIQUE INDEX IF NOT EXISTS uq_invites_pending_tenant_email
    ON public.invites (tenant_id, lower(email))
    WHERE status = 'pending';

-- Keep membership identity unique (already present in the canonical schema;
-- this is safe for installations that missed the original constraint).
CREATE UNIQUE INDEX IF NOT EXISTS uq_memberships_tenant_user
    ON public.memberships (tenant_id, user_id);

-- A user can only have one membership row for a team.
CREATE UNIQUE INDEX IF NOT EXISTS uq_team_memberships_team_user
    ON public.team_memberships (team_id, user_id);
