BEGIN;
CREATE TABLE generation_storage_objects (
 path text PRIMARY KEY,tenant_id uuid NOT NULL,event_id uuid NOT NULL,operation_id uuid NOT NULL,batch_id uuid NOT NULL,
 lease_owner uuid NOT NULL,byte_size bigint NOT NULL CHECK(byte_size>0),accounted boolean NOT NULL DEFAULT false,published boolean NOT NULL DEFAULT false,
 billing_tenant_id uuid REFERENCES tenants(id),created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,event_id,operation_id) REFERENCES generation_operations(tenant_id,event_id,id),
 FOREIGN KEY(tenant_id,operation_id,batch_id) REFERENCES generation_batches(tenant_id,operation_id,id),
 CHECK(path LIKE tenant_id::text || '/' || event_id::text || '/operations/' || operation_id::text || '/%'),
 CHECK(path !~ '(^|/)\.{1,2}(/|$)'),CHECK(NOT accounted OR billing_tenant_id IS NOT NULL)
);
CREATE INDEX generation_storage_objects_gc ON generation_storage_objects(created_at) WHERE NOT published;
ALTER TABLE generation_storage_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_storage_objects FORCE ROW LEVEL SECURITY;
REVOKE ALL ON generation_storage_objects FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON generation_storage_objects TO qentry_app;
CREATE POLICY generation_storage_objects_own ON generation_storage_objects FOR ALL TO qentry_app
 USING(tenant_id=current_tenant_id()) WITH CHECK(tenant_id=current_tenant_id());
INSERT INTO app_schema_migrations(version,name) VALUES(83,'generation_storage_objects') ON CONFLICT(version) DO NOTHING;
COMMIT;
