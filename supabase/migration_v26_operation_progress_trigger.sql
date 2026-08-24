-- Migration v26: Automatically calculate and update event operation progress based on tasks.

-- 1) Create or update the function to recalculate progress
CREATE OR REPLACE FUNCTION public.recalculate_operation_progress()
RETURNS TRIGGER AS $$
DECLARE
    v_operation_id UUID;
    v_total INT;
    v_done INT;
    v_progress INT;
    v_status TEXT;
BEGIN
    -- Determine the operation_id to update
    IF TG_OP = 'DELETE' THEN
        v_operation_id := OLD.operation_id;
    ELSE
        v_operation_id := NEW.operation_id;
    END IF;

    IF v_operation_id IS NOT NULL THEN
        -- Check status of the operation
        SELECT status INTO v_status
        FROM public.event_operations
        WHERE id = v_operation_id;

        -- We only automatically recalculate progress for operations that are in active planning/execution status.
        -- Completed, closed, or cancelled operations should retain their final status and progress.
        IF v_status NOT IN ('completed', 'closed', 'cancelled') THEN
            -- Count total tasks and done tasks
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'done')
            INTO v_total, v_done
            FROM public.event_operation_tasks
            WHERE operation_id = v_operation_id;

            -- Calculate progress percentage
            IF v_total > 0 THEN
                v_progress := ROUND((v_done::FLOAT / v_total::FLOAT) * 100);
            ELSE
                v_progress := 0;
            END IF;

            -- Update the event_operations table
            UPDATE public.event_operations
            SET progress = v_progress,
                updated_at = now()
            WHERE id = v_operation_id;
        END IF;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- 2) Create the trigger
DROP TRIGGER IF EXISTS trigger_recalculate_operation_progress ON public.event_operation_tasks;
CREATE TRIGGER trigger_recalculate_operation_progress
AFTER INSERT OR UPDATE OR DELETE ON public.event_operation_tasks
FOR EACH ROW
EXECUTE FUNCTION public.recalculate_operation_progress();

-- 3) Backfill existing active operations' progress
UPDATE public.event_operations o
SET progress = COALESCE(
    (
        SELECT ROUND((COUNT(*) FILTER (WHERE t.status = 'done')::FLOAT / NULLIF(COUNT(*), 0)::FLOAT) * 100)
        FROM public.event_operation_tasks t
        WHERE t.operation_id = o.id
    ),
    0
),
updated_at = now()
WHERE o.status NOT IN ('completed', 'closed', 'cancelled');

-- 4) Register the migration
INSERT INTO public.app_schema_migrations(version, name)
VALUES (26, 'operation_progress_trigger') ON CONFLICT (version) DO NOTHING;
