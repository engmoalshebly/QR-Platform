-- Gate setup and attendance are operational work.  They are available only
-- to Team Managers through an active event operation, never to the event
-- owner workspace.  Existing team-manager roles receive the required keys.

INSERT INTO public.permissions(key, description) VALUES
  ('gates.manage', 'Manage operational event gates'),
  ('checkin.scan', 'Scan guest QR codes'),
  ('checkin.manual', 'Record manual check-in')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id, p.key
FROM public.roles r
JOIN public.permissions p ON p.key IN (
  'gates.view', 'gates.manage', 'checkin.view', 'checkin.scan', 'checkin.manual'
)
WHERE r.name = 'team_manager'
ON CONFLICT DO NOTHING;
