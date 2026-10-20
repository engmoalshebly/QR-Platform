-- Immutable shared images and per-event message configuration. No sends enabled.
BEGIN;
CREATE TABLE whatsapp_message_images (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 content bytea NOT NULL CHECK(octet_length(content)>0 AND octet_length(content)<=65536),
 mime_type text NOT NULL DEFAULT 'image/jpeg' CHECK(mime_type='image/jpeg'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX whatsapp_message_images_event ON whatsapp_message_images(tenant_id,event_id);
CREATE TABLE whatsapp_message_templates (
 tenant_id uuid NOT NULL REFERENCES tenants(id), event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 rsvp_text text NOT NULL, ticket_text text NOT NULL,
 image_id uuid REFERENCES whatsapp_message_images(id), version integer NOT NULL DEFAULT 1 CHECK(version>0),
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,event_id)
);
ALTER TABLE whatsapp_deliveries ADD COLUMN message_text text,
 ADD COLUMN message_image_id uuid REFERENCES whatsapp_message_images(id), ADD COLUMN message_version integer;
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['whatsapp_message_images','whatsapp_message_templates'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('REVOKE ALL ON %I FROM anon,authenticated',tbl);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO qentry_app',tbl);
  EXECUTE format('CREATE POLICY tenant_isolation ON %I FOR ALL TO qentry_app USING (tenant_id=public.current_tenant_id()) WITH CHECK(tenant_id=public.current_tenant_id())',tbl);
 END LOOP;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='qentry_backup') THEN
  GRANT SELECT ON whatsapp_message_images,whatsapp_message_templates TO qentry_backup;
 END IF;
END $$;
INSERT INTO app_schema_migrations(version,name) VALUES(78,'whatsapp_message_templates') ON CONFLICT(version) DO NOTHING;
COMMIT;
