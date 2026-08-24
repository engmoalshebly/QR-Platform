-- Phase 5: granular operation-task authorization.
INSERT INTO public.permissions(key, description) VALUES
 ('operations.tasks.view','View operation tasks'),
 ('operations.tasks.create','Create operation tasks'),
 ('operations.tasks.update_any','Update any task in an operation'),
 ('operations.tasks.delete','Delete an incomplete task'),
 ('operations.tasks.delete_completed','Delete a completed task'),
 ('operations.tasks.assign','Assign operation tasks'),
 ('operations.tasks.approve','Approve operation tasks'),
 ('operations.tasks.comment','Comment on operation tasks'),
 ('operations.tasks.update_own','Update tasks assigned to the current user')
ON CONFLICT(key) DO NOTHING;
INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id,p.key FROM public.roles r CROSS JOIN public.permissions p
WHERE r.name='team_manager' AND p.key IN ('operations.tasks.view','operations.tasks.create','operations.tasks.update_any','operations.tasks.delete','operations.tasks.delete_completed','operations.tasks.assign','operations.tasks.approve','operations.tasks.comment','operations.tasks.update_own')
ON CONFLICT DO NOTHING;
