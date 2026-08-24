-- Launch repair: normalize the effective Team Manager permission contract for
-- every existing approved organizer tenant.  This migration is idempotent and
-- deliberately does not grant billing, tenant administration, role management,
-- or destructive event/template permissions.

INSERT INTO public.permissions(key, description) VALUES
  ('operations.tasks.view', 'View operation tasks'),
  ('operations.tasks.create', 'Create operation tasks'),
  ('operations.tasks.update_any', 'Update any task in an operation'),
  ('operations.tasks.delete', 'Delete an incomplete task'),
  ('operations.tasks.delete_completed', 'Delete a completed task'),
  ('operations.tasks.assign', 'Assign operation tasks'),
  ('operations.attachments.view', 'View operation attachments'),
  ('operations.attachments.upload', 'Upload operation attachments'),
  ('operations.attachments.delete', 'Delete operation attachments'),
  ('operations.attachments.download', 'Download operation attachments')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'reports.view', 'bookings.view', 'bookings.respond', 'bookings.manage',
  'operations.view', 'operations.manage', 'operations.members',
  'operations.edit', 'operations.progress.update', 'operations.status.change',
  'operations.escalate', 'operations.close',
  'operations.tasks.view', 'operations.tasks.create', 'operations.tasks.update_own',
  'operations.tasks.update_any', 'operations.tasks.delete',
  'operations.tasks.delete_completed', 'operations.tasks.assign',
  'operations.tasks.approve', 'operations.tasks.comment',
  'operations.attachments', 'operations.attachments.view',
  'operations.attachments.upload', 'operations.attachments.delete',
  'operations.attachments.download',
  'notifications.view', 'events.view', 'guests.view', 'invitations.view',
  'gates.view', 'checkin.view'
)
WHERE r.name = 'team_manager'
ON CONFLICT DO NOTHING;

-- Approved teams created before role provisioning may have an owner/admin
-- membership but no explicit role row.  Keep the explicit role the source of
-- truth and backfill only active managers of the approved provider tenant.
INSERT INTO public.membership_roles(tenant_id, user_id, role_id)
SELECT m.tenant_id, m.user_id, r.id
FROM public.memberships m
JOIN public.organization_requests o
  ON o.created_tenant_id = m.tenant_id AND o.status = 'approved'
JOIN public.roles r ON r.tenant_id = m.tenant_id AND r.name = 'team_manager'
WHERE m.status = 'active' AND m.role IN ('owner', 'admin')
ON CONFLICT DO NOTHING;
