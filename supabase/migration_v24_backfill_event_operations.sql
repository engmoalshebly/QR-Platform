-- Backfill operational workspaces for bookings accepted before phase 1.
INSERT INTO public.event_operations
  (booking_id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status, progress)
SELECT b.id, b.event_id, b.requester_tenant_id, b.provider_tenant_id,
       COALESCE(b.responded_by, owner_member.user_id),
       CASE WHEN b.status = 'completed' THEN 'completed' ELSE 'planning' END,
       CASE WHEN b.status = 'completed' THEN 100 ELSE 0 END
FROM public.organizer_booking_requests b
LEFT JOIN LATERAL (
    SELECT m.user_id FROM public.memberships m
    WHERE m.tenant_id = b.provider_tenant_id AND m.status = 'active'
      AND m.role IN ('owner', 'admin')
    ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END
    LIMIT 1
) owner_member ON true
WHERE b.status IN ('accepted', 'completed')
  AND COALESCE(b.responded_by, owner_member.user_id) IS NOT NULL
ON CONFLICT (booking_id) DO NOTHING;

INSERT INTO public.event_operation_members(operation_id, user_id, role)
SELECT o.id, o.project_manager_id, 'manager'
FROM public.event_operations o
ON CONFLICT(operation_id, user_id) DO UPDATE SET role = 'manager';

INSERT INTO public.event_operation_activity
  (operation_id, actor_user_id, action, entity_type, entity_id, details)
SELECT o.id, o.project_manager_id, 'operation.backfilled', 'operation', o.id::text,
       jsonb_build_object('booking_id', o.booking_id)
FROM public.event_operations o
WHERE NOT EXISTS (
    SELECT 1 FROM public.event_operation_activity a
    WHERE a.operation_id = o.id AND a.action IN ('operation.created', 'operation.backfilled')
);

INSERT INTO public.app_schema_migrations(version, name)
VALUES (24, 'backfill_event_operations') ON CONFLICT (version) DO NOTHING;
