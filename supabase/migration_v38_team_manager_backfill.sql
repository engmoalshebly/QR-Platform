-- Ensure every approved organizer tenant has an explicit team_manager role.
INSERT INTO public.roles (tenant_id, name, description, is_system_role)
SELECT DISTINCT o.created_tenant_id, 'team_manager', 'Team Manager', true
FROM public.organization_requests o
WHERE o.status='approved' AND o.created_tenant_id IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id,p.key FROM public.roles r CROSS JOIN public.permissions p
WHERE r.name='team_manager'
  AND p.key IN ('reports.view','bookings.view','bookings.respond','bookings.manage','operations.view','operations.manage','operations.members','operations.attachments','operations.tasks.update_own','operations.tasks.comment','operations.tasks.approve','notifications.view','events.view','guests.view','invitations.view','gates.view','checkin.view','operations.edit','operations.progress.update','operations.status.change','operations.escalate','operations.close','operations.tasks.view','operations.tasks.create','operations.tasks.update_any','operations.tasks.delete','operations.tasks.delete_completed','operations.tasks.assign','operations.tasks.approve','operations.tasks.comment','operations.attachments.view','operations.attachments.upload','operations.attachments.delete','operations.attachments.download')
ON CONFLICT DO NOTHING;

INSERT INTO public.membership_roles(tenant_id,user_id,role_id)
SELECT o.created_tenant_id,o.created_user_id,r.id
FROM organization_requests o JOIN roles r ON r.tenant_id=o.created_tenant_id AND r.name='team_manager'
JOIN memberships m ON m.tenant_id=o.created_tenant_id AND m.user_id=o.created_user_id AND m.status='active'
WHERE o.status='approved' AND o.created_tenant_id IS NOT NULL AND o.created_user_id IS NOT NULL
ON CONFLICT DO NOTHING;
