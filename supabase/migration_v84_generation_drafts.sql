BEGIN;
CREATE TABLE generation_drafts (
 tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 created_by uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('quick','designed')),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='array' AND jsonb_array_length(payload)<=1000 AND octet_length(payload::text)<=2097152),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 updated_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
 PRIMARY KEY(tenant_id,event_id,created_by,kind)
);
CREATE INDEX generation_drafts_expiry ON generation_drafts(expires_at);
ALTER TABLE generation_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_drafts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON generation_drafts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON generation_drafts TO qentry_app;
CREATE POLICY generation_drafts_own ON generation_drafts TO qentry_app
 USING(tenant_id=current_tenant_id()) WITH CHECK(tenant_id=current_tenant_id());
INSERT INTO app_schema_migrations(version,name) VALUES(84,'generation_drafts') ON CONFLICT(version) DO NOTHING;
COMMIT;
