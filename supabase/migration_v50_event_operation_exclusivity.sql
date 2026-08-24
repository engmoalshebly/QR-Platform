-- An event has a single operational owner while it is active.  API-level
-- checks make this a friendly 409 response; this trigger is the final
-- integrity boundary for concurrent requests and direct database writes.

BEGIN;

CREATE OR REPLACE FUNCTION public.prevent_parallel_active_event_operations()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Operations without an event are outside this invariant, and terminal
    -- operations deliberately release the event for a subsequent operation.
    IF NEW.event_id IS NULL
       OR NEW.status IN ('completed', 'closed', 'cancelled') THEN
        RETURN NEW;
    END IF;

    -- Match the API lock key so two providers accepting requests for the same
    -- event cannot both pass the existence check at the same time.
    PERFORM pg_advisory_xact_lock(hashtext('event-operation:' || NEW.event_id::text));

    IF EXISTS (
        SELECT 1
        FROM public.event_operations existing
        WHERE existing.event_id = NEW.event_id
          AND existing.id IS DISTINCT FROM NEW.id
          AND existing.status NOT IN ('completed', 'closed', 'cancelled')
    ) THEN
        RAISE EXCEPTION 'An event may have only one active operation'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_parallel_active_event_operations
    ON public.event_operations;
CREATE TRIGGER trg_prevent_parallel_active_event_operations
BEFORE INSERT OR UPDATE OF event_id, status ON public.event_operations
FOR EACH ROW EXECUTE FUNCTION public.prevent_parallel_active_event_operations();

CREATE INDEX IF NOT EXISTS idx_event_operations_active_event
    ON public.event_operations(event_id)
    WHERE event_id IS NOT NULL
      AND status NOT IN ('completed', 'closed', 'cancelled');

INSERT INTO public.app_schema_migrations(version, name)
VALUES (50, 'event_operation_exclusivity')
ON CONFLICT (version) DO NOTHING;

COMMIT;
