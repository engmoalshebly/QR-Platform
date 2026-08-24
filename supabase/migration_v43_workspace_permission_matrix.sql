-- Explicit organizer navigation and operation-tab permissions.
-- UI visibility is separate from data permissions: hiding a tab never grants
-- access, and every API route keeps enforcing its underlying capability.
BEGIN;

INSERT INTO public.permissions (key, description) VALUES
  ('ui.organizer.nav.home', 'Organizer navigation: home'),
  ('ui.organizer.nav.requests', 'Organizer navigation: booking requests'),
  ('ui.organizer.nav.operations', 'Organizer navigation: events and operations'),
  ('ui.organizer.nav.members', 'Organizer navigation: team members'),
  ('ui.organizer.nav.groups', 'Organizer navigation: operational groups'),
  ('ui.organizer.nav.settings', 'Organizer navigation: workspace settings'),
  ('ui.operation.tab.overview', 'Operation tab: overview'),
  ('ui.operation.tab.tasks', 'Operation tab: tasks'),
  ('ui.operation.tab.team', 'Operation tab: team'),
  ('ui.operation.tab.guests', 'Operation tab: guests and invitations'),
  ('ui.operation.tab.gates', 'Operation tab: gates'),
  ('ui.operation.tab.live', 'Operation tab: live attendance'),
  ('ui.operation.tab.files', 'Operation tab: attachments'),
  ('ui.operation.tab.activity', 'Operation tab: activity log')
ON CONFLICT (key) DO NOTHING;

-- Existing team managers keep their operational workspace after the upgrade.
INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'ui.organizer.nav.home', 'ui.organizer.nav.requests',
  'ui.organizer.nav.operations', 'ui.organizer.nav.members',
  'ui.organizer.nav.groups', 'ui.organizer.nav.settings',
  'ui.operation.tab.overview', 'ui.operation.tab.tasks',
  'ui.operation.tab.team', 'ui.operation.tab.guests',
  'ui.operation.tab.gates', 'ui.operation.tab.live',
  'ui.operation.tab.files', 'ui.operation.tab.activity'
)
WHERE r.name = 'team_manager'
ON CONFLICT DO NOTHING;

-- Tenant administrators retain complete UI administration in every workspace.
INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key LIKE 'ui.organizer.%' OR p.key LIKE 'ui.operation.tab.%'
WHERE r.name = 'Admin'
ON CONFLICT DO NOTHING;

COMMIT;
