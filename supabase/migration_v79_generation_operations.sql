-- Additive operation admission contract. Legacy generation batches stay valid.
BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS generation_events_tenant_key ON events(tenant_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS generation_templates_tenant_key ON invite_templates(tenant_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS generation_invitations_tenant_event_key ON invitations(tenant_id,event_id,id);

CREATE TABLE generation_operations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 event_id uuid NOT NULL, created_by uuid NOT NULL REFERENCES profiles(id),
 idempotency_key varchar(128) NOT NULL, request_sha256 char(64) NOT NULL,
 contract_version integer NOT NULL DEFAULT 1 CHECK(contract_version=1),
 mode text NOT NULL CHECK(mode IN ('quick','designed')),
 source text NOT NULL CHECK(source IN ('count','names','excel')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','partial','failed','cancel_requested','cancelled')),
 cards_count integer NOT NULL CHECK(cards_count BETWEEN 1 AND 10000),
 people_count integer NOT NULL CHECK(people_count>=cards_count AND people_count<=cards_count*100),
 vip_cards integer NOT NULL CHECK(vip_cards>=0), normal_cards integer NOT NULL CHECK(normal_cards>=0),
 vip_people integer NOT NULL CHECK(vip_people>=0), normal_people integer NOT NULL CHECK(normal_people>=0),
 cards_done integer NOT NULL DEFAULT 0 CHECK(cards_done>=0), cards_failed integer NOT NULL DEFAULT 0 CHECK(cards_failed>=0),
 settings_snapshot jsonb NOT NULL, event_snapshot jsonb NOT NULL, templates_snapshot jsonb NOT NULL DEFAULT '{}',
 error_code text, error_message text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,idempotency_key), UNIQUE(tenant_id,id), UNIQUE(tenant_id,event_id,id),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 CHECK(vip_cards+normal_cards=cards_count AND vip_people+normal_people=people_count),
 CHECK(cards_done+cards_failed<=cards_count), CHECK(request_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX generation_operations_feed ON generation_operations(tenant_id,event_id,created_at DESC,id DESC);
CREATE INDEX generation_operations_active ON generation_operations(tenant_id,status,created_at) WHERE status IN ('queued','running','cancel_requested');

CREATE TABLE generation_imports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), event_id uuid NOT NULL,
 operation_id uuid, source text NOT NULL CHECK(source IN ('count','names','excel')),
 original_filename varchar(255), source_sha256 char(64), validation_version integer NOT NULL DEFAULT 1,
 rows_count integer NOT NULL CHECK(rows_count BETWEEN 1 AND 10000), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,id), UNIQUE(tenant_id,operation_id,id),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,event_id,operation_id) REFERENCES generation_operations(tenant_id,event_id,id)
);
CREATE INDEX generation_imports_event ON generation_imports(tenant_id,event_id,created_at DESC);
CREATE TABLE generation_import_rows (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 operation_id uuid NOT NULL, import_id uuid NOT NULL, source_row_number integer NOT NULL CHECK(source_row_number>0),
 normalized_data jsonb NOT NULL, validation_errors jsonb NOT NULL DEFAULT '[]', selected boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,operation_id,id), UNIQUE(tenant_id,operation_id,source_row_number),
 FOREIGN KEY(tenant_id,operation_id) REFERENCES generation_operations(tenant_id,id),
 FOREIGN KEY(tenant_id,operation_id,import_id) REFERENCES generation_imports(tenant_id,operation_id,id)
);
CREATE INDEX generation_import_rows_page ON generation_import_rows(tenant_id,operation_id,source_row_number);

-- Snapshot bytes are deduplicated per tenant, immutable, private and bounded.
-- P3 can move these to immutable private storage without changing the manifest.
CREATE TABLE generation_snapshot_assets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
 sha256 char(64) NOT NULL, kind text NOT NULL CHECK(kind IN ('background','image','font')),
 mime_type text NOT NULL, content bytea NOT NULL CHECK(octet_length(content)>0 AND octet_length(content)<=20971520),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id), UNIQUE(tenant_id,sha256),
 CHECK(sha256=encode(digest(content,'sha256'),'hex'))
);
CREATE TABLE generation_operation_assets (
 tenant_id uuid NOT NULL, operation_id uuid NOT NULL, asset_id uuid NOT NULL,
 asset_key text NOT NULL CHECK(length(asset_key) BETWEEN 1 AND 500),
 PRIMARY KEY(tenant_id,operation_id,asset_key),
 FOREIGN KEY(tenant_id,operation_id) REFERENCES generation_operations(tenant_id,id),
 FOREIGN KEY(tenant_id,asset_id) REFERENCES generation_snapshot_assets(tenant_id,id)
);

ALTER TABLE generation_batches ADD COLUMN operation_id uuid, ADD COLUMN part_index integer,
 ADD COLUMN stage text NOT NULL DEFAULT 'generate', ADD COLUMN execution_attempt integer NOT NULL DEFAULT 0,
 ADD COLUMN lease_owner uuid, ADD COLUMN lease_expires_at timestamptz, ADD COLUMN heartbeat_at timestamptz;
ALTER TABLE generation_batches ADD CONSTRAINT generation_batch_operation_fk
 FOREIGN KEY(tenant_id,event_id,operation_id) REFERENCES generation_operations(tenant_id,event_id,id);
ALTER TABLE generation_batches ADD CONSTRAINT generation_batch_operation_part
 CHECK((operation_id IS NULL AND part_index IS NULL) OR (operation_id IS NOT NULL AND part_index>=0));
CREATE UNIQUE INDEX generation_batches_operation_part ON generation_batches(tenant_id,operation_id,part_index,stage) WHERE operation_id IS NOT NULL;
CREATE UNIQUE INDEX generation_batches_operation_key ON generation_batches(tenant_id,operation_id,id);
ALTER TABLE invitations ADD COLUMN generation_operation_id uuid, ADD COLUMN generation_source_row_id uuid;
ALTER TABLE invitations ADD CONSTRAINT invitation_generation_operation_fk
 FOREIGN KEY(tenant_id,event_id,generation_operation_id) REFERENCES generation_operations(tenant_id,event_id,id);
ALTER TABLE invitations ADD CONSTRAINT invitation_generation_source_fk
 FOREIGN KEY(tenant_id,generation_operation_id,generation_source_row_id) REFERENCES generation_import_rows(tenant_id,operation_id,id);
ALTER TABLE invitations ADD CONSTRAINT invitation_generation_both_keys
 CHECK((generation_operation_id IS NULL AND generation_source_row_id IS NULL) OR
       (generation_operation_id IS NOT NULL AND generation_source_row_id IS NOT NULL));
CREATE UNIQUE INDEX invitations_operation_source ON invitations(tenant_id,generation_operation_id,generation_source_row_id) WHERE generation_operation_id IS NOT NULL;
CREATE UNIQUE INDEX invitations_generation_item_key ON invitations(tenant_id,generation_operation_id,generation_source_row_id,id);
CREATE UNIQUE INDEX generation_batches_tenant_key ON generation_batches(tenant_id,id);
ALTER TABLE batch_items ADD COLUMN tenant_id uuid REFERENCES tenants(id);
UPDATE batch_items bi SET tenant_id=b.tenant_id FROM generation_batches b WHERE b.id=bi.batch_id;
ALTER TABLE batch_items ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE batch_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE batch_items FORCE ROW LEVEL SECURITY;
DO $$ DECLARE pol record; BEGIN
 FOR pol IN SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename='batch_items' LOOP
  EXECUTE format('DROP POLICY %I ON batch_items',pol.policyname);
 END LOOP;
END $$;
REVOKE ALL ON batch_items FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON batch_items TO qentry_app;
CREATE POLICY generation_item_access ON batch_items FOR ALL TO qentry_app
 USING(tenant_id=current_tenant_id() OR EXISTS(SELECT 1 FROM generation_batches b WHERE b.id=batch_id AND b.event_id=ANY(current_operated_event_ids())))
 WITH CHECK(tenant_id=current_tenant_id() OR EXISTS(SELECT 1 FROM generation_batches b WHERE b.id=batch_id AND b.event_id=ANY(current_operated_event_ids())));

CREATE FUNCTION generation_item_tenant_default() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE owner_tenant uuid;
BEGIN
 SELECT tenant_id INTO owner_tenant FROM generation_batches WHERE id=NEW.batch_id;
 IF owner_tenant IS NULL OR (NEW.tenant_id IS NOT NULL AND NEW.tenant_id<>owner_tenant) THEN
  RAISE EXCEPTION 'batch item tenant mismatch' USING ERRCODE='23514';
 END IF;
 NEW.tenant_id=owner_tenant;
 RETURN NEW;
END $$;
CREATE TRIGGER generation_item_tenant_guard BEFORE INSERT OR UPDATE OF batch_id,tenant_id ON batch_items
 FOR EACH ROW EXECUTE FUNCTION generation_item_tenant_default();
ALTER TABLE batch_items ADD CONSTRAINT generation_item_parent_tenant_fk
 FOREIGN KEY(tenant_id,batch_id) REFERENCES generation_batches(tenant_id,id);
ALTER TABLE batch_items ADD COLUMN operation_id uuid, ADD COLUMN source_row_id uuid,
 ADD COLUMN barcode_status text NOT NULL DEFAULT 'pending', ADD COLUMN design_status text NOT NULL DEFAULT 'pending';
ALTER TABLE batch_items ADD CONSTRAINT generation_item_batch_fk
 FOREIGN KEY(tenant_id,operation_id,batch_id) REFERENCES generation_batches(tenant_id,operation_id,id);
ALTER TABLE batch_items ADD CONSTRAINT generation_item_source_fk
 FOREIGN KEY(tenant_id,operation_id,source_row_id) REFERENCES generation_import_rows(tenant_id,operation_id,id);
ALTER TABLE batch_items ADD CONSTRAINT generation_item_invitation_fk
 FOREIGN KEY(tenant_id,operation_id,source_row_id,invitation_id) REFERENCES invitations(tenant_id,generation_operation_id,generation_source_row_id,id);
ALTER TABLE batch_items ADD CONSTRAINT generation_item_both_keys
 CHECK((operation_id IS NULL AND source_row_id IS NULL) OR (operation_id IS NOT NULL AND source_row_id IS NOT NULL));
CREATE UNIQUE INDEX batch_items_operation_source ON batch_items(tenant_id,operation_id,source_row_id) WHERE operation_id IS NOT NULL;

CREATE TABLE generation_outbox (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
 operation_id uuid NOT NULL, batch_id uuid NOT NULL, event_type text NOT NULL DEFAULT 'generation.batch.accepted',
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0), available_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz, last_error_code text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,batch_id,event_type),
 FOREIGN KEY(tenant_id,operation_id) REFERENCES generation_operations(tenant_id,id),
 FOREIGN KEY(tenant_id,operation_id,batch_id) REFERENCES generation_batches(tenant_id,operation_id,id)
);
CREATE INDEX generation_outbox_pending ON generation_outbox(available_at,created_at) WHERE published_at IS NULL;
CREATE INDEX generation_outbox_operations ON generation_outbox(tenant_id,operation_id);
CREATE TABLE generation_artifacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, event_id uuid NOT NULL,
 operation_id uuid NOT NULL, batch_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('pdf','zip','manifest','preview')),
 part_index integer NOT NULL CHECK(part_index>=0), storage_path text NOT NULL,
 byte_size bigint NOT NULL CHECK(byte_size>0), sha256 char(64) NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 manifest_version integer NOT NULL DEFAULT 1, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','verified','invalid')),
 created_at timestamptz NOT NULL DEFAULT now(), verified_at timestamptz,
 UNIQUE(tenant_id,operation_id,kind,part_index), UNIQUE(tenant_id,operation_id,id),
 FOREIGN KEY(tenant_id,event_id,operation_id) REFERENCES generation_operations(tenant_id,event_id,id),
 FOREIGN KEY(tenant_id,operation_id,batch_id) REFERENCES generation_batches(tenant_id,operation_id,id),
 CHECK(storage_path LIKE tenant_id::text || '/' || event_id::text || '/%'),
 CHECK(storage_path !~ '(^|/)\.{1,2}(/|$)'),
 CHECK(status<>'verified' OR verified_at IS NOT NULL)
);
CREATE INDEX generation_artifacts_event ON generation_artifacts(tenant_id,event_id,operation_id,status,part_index);
CREATE TABLE generation_artifact_items (
 tenant_id uuid NOT NULL, operation_id uuid NOT NULL, artifact_id uuid NOT NULL, source_row_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,artifact_id,source_row_id),
 FOREIGN KEY(tenant_id,operation_id,artifact_id) REFERENCES generation_artifacts(tenant_id,operation_id,id),
 FOREIGN KEY(tenant_id,operation_id,source_row_id) REFERENCES generation_import_rows(tenant_id,operation_id,id)
);

CREATE FUNCTION generation_protect_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
 IF TG_TABLE_NAME='generation_operations' THEN
  IF (NEW.tenant_id,NEW.event_id,NEW.created_by,NEW.idempotency_key,NEW.request_sha256,NEW.mode,NEW.source,
      NEW.cards_count,NEW.people_count,NEW.vip_cards,NEW.normal_cards,NEW.vip_people,NEW.normal_people,
      NEW.settings_snapshot,NEW.event_snapshot,NEW.templates_snapshot,NEW.contract_version)
     IS DISTINCT FROM
     (OLD.tenant_id,OLD.event_id,OLD.created_by,OLD.idempotency_key,OLD.request_sha256,OLD.mode,OLD.source,
      OLD.cards_count,OLD.people_count,OLD.vip_cards,OLD.normal_cards,OLD.vip_people,OLD.normal_people,
      OLD.settings_snapshot,OLD.event_snapshot,OLD.templates_snapshot,OLD.contract_version) THEN
    RAISE EXCEPTION 'generation admission snapshot is immutable' USING ERRCODE='23514';
  END IF;
 ELSE
  RAISE EXCEPTION 'generation source snapshot is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER generation_operation_snapshot_guard BEFORE UPDATE ON generation_operations FOR EACH ROW EXECUTE FUNCTION generation_protect_snapshot();
CREATE TRIGGER generation_import_snapshot_guard BEFORE UPDATE ON generation_imports FOR EACH ROW EXECUTE FUNCTION generation_protect_snapshot();
CREATE TRIGGER generation_row_snapshot_guard BEFORE UPDATE ON generation_import_rows FOR EACH ROW EXECUTE FUNCTION generation_protect_snapshot();
CREATE TRIGGER generation_asset_snapshot_guard BEFORE UPDATE ON generation_snapshot_assets FOR EACH ROW EXECUTE FUNCTION generation_protect_snapshot();
CREATE TRIGGER generation_manifest_snapshot_guard BEFORE UPDATE ON generation_operation_assets FOR EACH ROW EXECUTE FUNCTION generation_protect_snapshot();

DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['generation_operations','generation_imports','generation_import_rows','generation_snapshot_assets',
 'generation_operation_assets','generation_outbox','generation_artifacts','generation_artifact_items'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('REVOKE ALL ON %I FROM PUBLIC,anon,authenticated',tbl);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE ON %I TO qentry_app',tbl);
  EXECUTE format('CREATE POLICY generation_tenant_isolation ON %I FOR ALL TO qentry_app USING (tenant_id=current_tenant_id()) WITH CHECK(tenant_id=current_tenant_id())',tbl);
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='qentry_backup') THEN
   EXECUTE format('GRANT SELECT ON %I TO qentry_backup',tbl);
  END IF;
 END LOOP;
END $$;
REVOKE UPDATE ON generation_snapshot_assets,generation_import_rows,generation_operation_assets FROM qentry_app;

-- RLS callers cannot see other tenants' queues. A narrowly scoped function
-- counts capacity only and keeps its lock until admission commits or rolls back.
CREATE FUNCTION generation_check_capacity(p_tenant uuid,p_cards integer,p_operations_limit integer,p_cards_limit integer,p_tenant_limit integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE op_count bigint; card_count bigint; tenant_count bigint;
BEGIN
 IF current_tenant_id() IS DISTINCT FROM p_tenant THEN
  RAISE EXCEPTION 'generation capacity requires tenant context' USING ERRCODE='42501';
 END IF;
 IF p_cards<1 OR p_cards>10000 OR p_operations_limit<1 OR p_cards_limit<1 OR p_tenant_limit<1 THEN
  RAISE EXCEPTION 'invalid generation capacity bounds' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('generation-capacity:v1',0));
 SELECT count(*),COALESCE(sum(cards_count),0),count(*) FILTER(WHERE tenant_id=p_tenant)
 INTO op_count,card_count,tenant_count FROM generation_operations WHERE status IN ('queued','running','cancel_requested');
 SELECT op_count+count(*),card_count+COALESCE(sum(count_total),0),tenant_count+count(*) FILTER(WHERE tenant_id=p_tenant)
 INTO op_count,card_count,tenant_count FROM generation_batches
 WHERE operation_id IS NULL AND status IN ('queued','generating_barcodes','rendering_images','generating_pdf','generating_zip');
 RETURN op_count<p_operations_limit AND card_count+p_cards<=p_cards_limit AND tenant_count<p_tenant_limit;
END $$;
REVOKE ALL ON FUNCTION generation_check_capacity(uuid,integer,integer,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION generation_check_capacity(uuid,integer,integer,integer,integer) TO qentry_app;
INSERT INTO app_schema_migrations(version,name) VALUES(79,'generation_operations') ON CONFLICT(version) DO NOTHING;
COMMIT;
