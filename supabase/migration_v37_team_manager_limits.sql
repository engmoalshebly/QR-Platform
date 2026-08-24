-- Phase 12: explicit operational limits for every plan.
INSERT INTO public.plan_limits(plan_id, key, value, period)
SELECT p.id, x.key,
       CASE x.key
         WHEN 'operations_max' THEN CASE WHEN p.code IN ('enterprise','business') THEN 500 ELSE 50 END
         WHEN 'operation_members_max' THEN CASE WHEN p.code IN ('enterprise','business') THEN 100 ELSE 20 END
         WHEN 'tasks_per_operation' THEN CASE WHEN p.code IN ('enterprise','business') THEN 500 ELSE 100 END
         WHEN 'attachments_per_operation' THEN CASE WHEN p.code IN ('enterprise','business') THEN 200 ELSE 50 END
         WHEN 'operation_groups_max' THEN CASE WHEN p.code IN ('enterprise','business') THEN 100 ELSE 20 END
         WHEN 'storage_mb' THEN CASE WHEN p.code='free' OR p.code='starter' THEN 500 WHEN p.code IN ('enterprise','business') THEN 200000 ELSE 10000 END
         WHEN 'monthly_bookings' THEN CASE WHEN p.code IN ('enterprise','business') THEN -1 ELSE 100 END
       END, 'none'
FROM public.plans p CROSS JOIN (VALUES
 ('operations_max'),('operation_members_max'),('tasks_per_operation'),('attachments_per_operation'),('operation_groups_max'),('storage_mb'),('monthly_bookings')
) x(key)
WHERE NOT EXISTS (SELECT 1 FROM public.plan_limits l WHERE l.plan_id=p.id AND l.key=x.key);
