-- Durable worker checkpoints and bounded recovery; no change to legacy jobs.
BEGIN;
ALTER TABLE batch_items ADD COLUMN stage_results jsonb NOT NULL DEFAULT '{}';
ALTER TABLE generation_batches ADD COLUMN last_error_code text,
 ADD COLUMN recovery_count integer NOT NULL DEFAULT 0 CHECK(recovery_count>=0);
ALTER TABLE generation_operations ADD COLUMN files_done integer NOT NULL DEFAULT 0 CHECK(files_done>=0),
 ADD COLUMN files_failed integer NOT NULL DEFAULT 0 CHECK(files_failed>=0);
CREATE INDEX generation_batches_active_lease ON generation_batches(lease_expires_at)
 WHERE operation_id IS NOT NULL AND lease_owner IS NOT NULL;
CREATE INDEX generation_batches_recovery ON generation_batches(updated_at,id)
 WHERE operation_id IS NOT NULL AND status NOT IN ('ready','failed','cancelled');
CREATE OR REPLACE FUNCTION public.enforce_batch_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    valid BOOLEAN := false;
BEGIN
    -- Snapshot-backed jobs resume checkpoints and may request only one export.
    -- Keep the legacy transition contract unchanged for operation_id IS NULL.
    IF OLD.operation_id IS NOT NULL THEN
        IF NEW.status=OLD.status THEN RETURN NEW; END IF;
        IF OLD.status IN ('ready','cancelled') THEN
            RAISE EXCEPTION 'Durable terminal batch cannot transition';
        ELSIF OLD.status='failed' THEN
            IF NEW.status='queued' THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'Failed durable batch must explicitly retry';
        ELSIF NEW.status IN ('queued','generating_barcodes','rendering_images','generating_pdf','generating_zip','ready','failed','cancelled') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Invalid durable batch transition';
    END IF;
    -- Allow any transition if old status is NULL (new row)
    IF OLD.status IS NULL THEN
        RETURN NEW;
    END IF;

    -- Define valid transitions
    CASE OLD.status
        WHEN 'draft' THEN
            valid := NEW.status IN ('queued', 'cancelled');
        WHEN 'queued' THEN
            valid := NEW.status IN ('generating_barcodes', 'cancelled', 'failed');
        WHEN 'generating_barcodes' THEN
            valid := NEW.status IN ('rendering_images', 'generating_pdf', 'cancelled', 'failed');
        WHEN 'rendering_images' THEN
            valid := NEW.status IN ('generating_pdf', 'cancelled', 'failed');
        WHEN 'generating_pdf' THEN
            valid := NEW.status IN ('generating_zip', 'cancelled', 'failed');
        WHEN 'generating_zip' THEN
            valid := NEW.status IN ('ready', 'cancelled', 'failed');
        WHEN 'ready' THEN
            valid := false;  -- terminal state
        WHEN 'failed' THEN
            valid := NEW.status IN ('queued');  -- retry requeues
        WHEN 'cancelled' THEN
            valid := false;  -- terminal state
        ELSE
            valid := false;
    END CASE;

    IF NOT valid THEN
        RAISE EXCEPTION 'Invalid batch status transition: % → %', OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$;


INSERT INTO app_schema_migrations(version,name) VALUES(80,'generation_worker') ON CONFLICT(version) DO NOTHING;
COMMIT;
