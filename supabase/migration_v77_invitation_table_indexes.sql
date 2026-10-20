-- Ordered, bounded pages and per-invitation latest delivery lookups.
BEGIN;
CREATE INDEX IF NOT EXISTS invitations_tenant_event_page
    ON invitations(tenant_id,event_id,created_at DESC,id DESC)
    WHERE metadata->>'generation_deleted' IS DISTINCT FROM 'true';
CREATE INDEX IF NOT EXISTS whatsapp_invitation_purpose_latest
    ON whatsapp_deliveries(tenant_id,event_id,invitation_id,purpose,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS whatsapp_event_page
    ON whatsapp_deliveries(tenant_id,event_id,created_at DESC,id DESC);
INSERT INTO app_schema_migrations(version,name) VALUES(77,'invitation_table_indexes') ON CONFLICT(version) DO NOTHING;
COMMIT;
