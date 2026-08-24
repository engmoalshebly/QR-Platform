-- Sync the explicit team_manager role for active owners of approved organizer tenants.
-- This repairs tenants approved before role provisioning was introduced.
INSERT INTO public.membership_roles(tenant_id,user_id,role_id)
SELECT m.tenant_id,m.user_id,r.id
FROM memberships m
JOIN organization_requests o ON o.created_tenant_id=m.tenant_id AND o.status='approved'
JOIN roles r ON r.tenant_id=m.tenant_id AND r.name='team_manager'
WHERE m.role IN ('owner','admin') AND m.status='active'
ON CONFLICT DO NOTHING;
