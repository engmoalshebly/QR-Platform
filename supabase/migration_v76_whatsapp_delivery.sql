-- Durable, tenant-isolated WhatsApp delivery. No transport is enabled here.
BEGIN;
INSERT INTO permissions (key,description) VALUES
 ('whatsapp.manage','إدارة اتصال WhatsApp للمؤسسة'),
 ('whatsapp.send','إرسال الدعوات عبر WhatsApp'),
 ('whatsapp.view','عرض سجل إرسال WhatsApp') ON CONFLICT (key) DO NOTHING;
INSERT INTO role_permissions(role_id,permission_key)
 SELECT r.id,p.key FROM roles r CROSS JOIN permissions p
 WHERE lower(r.name) IN ('admin','owner') AND p.key IN ('whatsapp.manage','whatsapp.send','whatsapp.view')
 ON CONFLICT DO NOTHING;
CREATE TABLE whatsapp_connections (
 tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
 session_id uuid UNIQUE, api_key_ciphertext text, webhook_secret_ciphertext text,
 webhook_id uuid, enabled boolean NOT NULL DEFAULT false,
 status text NOT NULL DEFAULT 'not_connected', phone text,
 next_dispatch_at timestamptz NOT NULL DEFAULT now(), last_checked_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE whatsapp_delivery_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 client_request_id uuid NOT NULL, payload_hash text NOT NULL, response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,client_request_id)
);
CREATE TABLE whatsapp_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 event_id uuid NOT NULL REFERENCES events(id), invitation_id uuid NOT NULL REFERENCES invitations(id),
 request_id uuid NOT NULL REFERENCES whatsapp_delivery_requests(id),
 created_by uuid REFERENCES profiles(id) ON DELETE SET NULL,
 purpose text NOT NULL CHECK(purpose IN ('rsvp','ticket')), recipient text NOT NULL,
 state text NOT NULL DEFAULT 'queued' CHECK(state IN
 ('queued','waiting_connection','sending','sent','delivered','read','failed','unknown','cancelled')),
 wa_message_id text, error_code text, attempt_started_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX whatsapp_due ON whatsapp_deliveries(created_at) WHERE state IN ('queued','waiting_connection');
CREATE INDEX whatsapp_event_history ON whatsapp_deliveries(tenant_id,event_id,created_at DESC);
CREATE UNIQUE INDEX whatsapp_active_invitation ON whatsapp_deliveries(tenant_id,invitation_id)
 WHERE state IN ('queued','waiting_connection','sending','unknown');
CREATE UNIQUE INDEX whatsapp_message_identity ON whatsapp_deliveries(tenant_id,wa_message_id) WHERE wa_message_id IS NOT NULL;
CREATE TABLE whatsapp_webhook_receipts (
 tenant_id uuid NOT NULL REFERENCES tenants(id), event_id text NOT NULL, wa_message_id text NOT NULL, ack integer NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,event_id)
);
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['whatsapp_connections','whatsapp_delivery_requests','whatsapp_deliveries','whatsapp_webhook_receipts'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('REVOKE ALL ON %I FROM anon, authenticated',tbl);
  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO qentry_app',tbl);
  EXECUTE format('CREATE POLICY tenant_isolation ON %I FOR ALL TO qentry_app USING (tenant_id=public.current_tenant_id()) WITH CHECK (tenant_id=public.current_tenant_id())',tbl);
 END LOOP;
END $$;
INSERT INTO app_schema_migrations(version,name) VALUES(76,'whatsapp_delivery') ON CONFLICT(version) DO NOTHING;
COMMIT;
