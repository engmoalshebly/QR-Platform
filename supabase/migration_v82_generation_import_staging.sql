BEGIN;
CREATE TABLE generation_uploads (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES tenants(id),event_id uuid NOT NULL,
 created_by uuid NOT NULL REFERENCES profiles(id),filename text NOT NULL,kind text NOT NULL CHECK(kind IN ('csv','xlsx')),
 content bytea,byte_size integer NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),sha256 char(64) NOT NULL,
 sheets jsonb NOT NULL,status text NOT NULL DEFAULT 'uploaded' CHECK(status IN ('uploaded','validated','frozen')),
 revision integer NOT NULL DEFAULT 0,sheet text,delimiter text NOT NULL DEFAULT ',' CHECK(delimiter IN (',',';',E'\t')),column_mapping jsonb NOT NULL DEFAULT '{}',require_rsvp boolean NOT NULL DEFAULT false,
 summary jsonb NOT NULL DEFAULT '{}',acknowledged_exclusions boolean NOT NULL DEFAULT false,operation_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',
 UNIQUE(tenant_id,id),FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,operation_id) REFERENCES generation_operations(tenant_id,id),
 CHECK((status='frozen' AND operation_id IS NOT NULL AND content IS NULL) OR (status<>'frozen' AND operation_id IS NULL AND octet_length(content)=byte_size))
);
CREATE TABLE generation_upload_rows (
 tenant_id uuid NOT NULL,upload_id uuid NOT NULL,row_number integer NOT NULL,raw_data jsonb NOT NULL,
 normalized_data jsonb,errors jsonb NOT NULL DEFAULT '[]',excluded boolean NOT NULL DEFAULT false,selected boolean NOT NULL DEFAULT false,
 PRIMARY KEY(tenant_id,upload_id,row_number),FOREIGN KEY(tenant_id,upload_id) REFERENCES generation_uploads(tenant_id,id) ON DELETE CASCADE,
 CHECK(NOT selected OR (normalized_data IS NOT NULL AND errors='[]'::jsonb AND NOT excluded))
);
CREATE INDEX generation_uploads_expiry ON generation_uploads(expires_at) WHERE status<>'frozen';
CREATE INDEX generation_upload_rows_selection ON generation_upload_rows(tenant_id,upload_id,selected,row_number);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['generation_uploads','generation_upload_rows'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON %I FROM PUBLIC,anon,authenticated',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO qentry_app',t);
  EXECUTE format('CREATE POLICY generation_upload_own ON %I FOR ALL TO qentry_app USING(tenant_id=current_tenant_id()) WITH CHECK(tenant_id=current_tenant_id())',t);
 END LOOP;
END $$;
CREATE FUNCTION generation_check_upload_capacity(p_tenant uuid,p_bytes integer) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE all_bytes bigint;own_bytes bigint;own_count integer;all_count integer;
BEGIN
 IF p_tenant IS DISTINCT FROM current_tenant_id() THEN RAISE EXCEPTION 'tenant context required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('generation:upload-capacity:v1'));
 SELECT COALESCE(sum(byte_size),0),COALESCE(sum(byte_size) FILTER(WHERE tenant_id=p_tenant),0),count(*) FILTER(WHERE tenant_id=p_tenant),count(*)
 INTO all_bytes,own_bytes,own_count,all_count FROM public.generation_uploads WHERE status<>'frozen';
 RETURN all_count<1000 AND own_count<10 AND own_bytes+p_bytes<=33554432 AND all_bytes+p_bytes<=536870912;
END $$;
REVOKE ALL ON FUNCTION generation_check_upload_capacity(uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION generation_check_upload_capacity(uuid,integer) TO qentry_app;
CREATE FUNCTION generation_protect_upload() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
 IF TG_TABLE_NAME='generation_uploads' THEN
  IF OLD.status='frozen' OR (NEW.id,NEW.tenant_id,NEW.event_id,NEW.created_by,NEW.sha256,NEW.byte_size,NEW.filename,NEW.kind)
    IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.event_id,OLD.created_by,OLD.sha256,OLD.byte_size,OLD.filename,OLD.kind)
    OR (NEW.content IS DISTINCT FROM OLD.content AND NEW.status<>'frozen') THEN
   RAISE EXCEPTION 'upload is immutable' USING ERRCODE='23514';
  END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM generation_uploads WHERE tenant_id=OLD.tenant_id AND id=OLD.upload_id AND status='frozen') THEN
   RAISE EXCEPTION 'selected input is frozen' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER generation_upload_guard BEFORE UPDATE ON generation_uploads FOR EACH ROW EXECUTE FUNCTION generation_protect_upload();
CREATE TRIGGER generation_upload_rows_guard BEFORE UPDATE ON generation_upload_rows FOR EACH ROW EXECUTE FUNCTION generation_protect_upload();
INSERT INTO app_schema_migrations(version,name) VALUES(82,'generation_import_staging') ON CONFLICT(version) DO NOTHING;
COMMIT;
