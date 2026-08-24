-- Explicit Team Manager role for approved organizer/provider tenants.
INSERT INTO public.permissions (key, description) VALUES
    ('operations.tasks.update_own', 'Update tasks assigned to the current user'),
    ('operations.tasks.comment', 'Comment on operation tasks'),
    ('operations.tasks.approve', 'Approve operation tasks')
ON CONFLICT (key) DO NOTHING;

-- Provision one explicit role for every already-approved organizer tenant.
INSERT INTO public.roles (tenant_id, name, description, is_system_role)
SELECT DISTINCT o.created_tenant_id, 'team_manager',
       'مسؤول فريق التشغيل وإدارة الحجوزات والعمليات', true
FROM public.organization_requests o
WHERE o.status = 'approved' AND o.created_tenant_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.roles r
    WHERE r.tenant_id = o.created_tenant_id AND r.name = 'team_manager'
  );

INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'reports.view', 'bookings.view', 'bookings.respond', 'bookings.manage',
  'operations.view', 'operations.manage', 'operations.members',
  'operations.attachments', 'operations.tasks.update_own',
  'operations.tasks.comment', 'operations.tasks.approve', 'notifications.view',
  'events.view', 'guests.view', 'invitations.view', 'gates.view', 'checkin.view'
)
WHERE r.name = 'team_manager'
ON CONFLICT DO NOTHING;

-- The approved applicant is the initial Team Manager when an active membership exists.
INSERT INTO public.membership_roles (tenant_id, user_id, role_id)
SELECT o.created_tenant_id, o.created_user_id, r.id
FROM public.organization_requests o
JOIN public.roles r ON r.tenant_id = o.created_tenant_id AND r.name = 'team_manager'
JOIN public.memberships m ON m.tenant_id = o.created_tenant_id
                         AND m.user_id = o.created_user_id
                         AND m.status = 'active'
WHERE o.status = 'approved' AND o.created_tenant_id IS NOT NULL AND o.created_user_id IS NOT NULL
ON CONFLICT DO NOTHING;
