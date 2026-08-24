-- Unified authorization keys for the booking, operations and billing modules.
INSERT INTO public.permissions (key, description) VALUES
    ('bookings.view', 'View organizer bookings'),
    ('bookings.create', 'Create organizer bookings'),
    ('bookings.manage', 'Manage booking groups and completion'),
    ('bookings.respond', 'Accept or reject provider bookings'),
    ('operations.view', 'View event operations'),
    ('operations.manage', 'Manage operation tasks and workflow'),
    ('operations.members', 'Manage operation members'),
    ('operations.attachments', 'Upload operation attachments'),
    ('billing.view', 'View billing and subscription data'),
    ('billing.manage', 'Manage billing and subscriptions'),
    ('notifications.view', 'View and update own notifications')
ON CONFLICT (key) DO NOTHING;

-- Existing system roles receive the new capabilities. Custom roles remain explicit.
INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'bookings.view','bookings.create','bookings.manage','bookings.respond',
  'operations.view','operations.manage','operations.members','operations.attachments',
  'billing.view','billing.manage','notifications.view'
)
WHERE r.is_system_role = true AND r.name IN ('Admin', 'Owner')
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN ('bookings.view','operations.view','notifications.view','billing.view')
WHERE r.is_system_role = true AND r.name IN ('Member', 'Viewer')
ON CONFLICT DO NOTHING;
