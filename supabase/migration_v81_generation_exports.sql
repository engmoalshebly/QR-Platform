BEGIN;
ALTER TABLE generation_batches ADD COLUMN output_manifest jsonb;
ALTER TABLE generation_artifacts ADD COLUMN file_part integer NOT NULL DEFAULT 0 CHECK(file_part>=0);
CREATE UNIQUE INDEX generation_artifacts_file_part ON generation_artifacts(tenant_id,batch_id,kind,file_part);
INSERT INTO app_schema_migrations(version,name) VALUES(81,'generation_exports') ON CONFLICT(version) DO NOTHING;
COMMIT;
