-- Phase 8: granular attachment permissions and download audit.
INSERT INTO public.permissions(key, description) VALUES
 ('operations.attachments.view','View operation attachments'),
 ('operations.attachments.upload','Upload operation attachments'),
 ('operations.attachments.delete','Delete operation attachments'),
 ('operations.attachments.download','Download operation attachments')
ON CONFLICT(key) DO NOTHING;
INSERT INTO public.role_permissions(role_id, permission_key)
SELECT r.id,p.key FROM public.roles r CROSS JOIN public.permissions p
WHERE r.name='team_manager' AND p.key IN ('operations.attachments.view','operations.attachments.upload','operations.attachments.delete','operations.attachments.download')
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.event_operation_attachment_downloads(
 id BIGSERIAL PRIMARY KEY, attachment_id UUID NOT NULL REFERENCES public.event_operation_attachments(id) ON DELETE CASCADE,
 operation_id UUID NOT NULL REFERENCES public.event_operations(id) ON DELETE CASCADE,
 user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_attachment_downloads ON public.event_operation_attachment_downloads(attachment_id, created_at DESC);
