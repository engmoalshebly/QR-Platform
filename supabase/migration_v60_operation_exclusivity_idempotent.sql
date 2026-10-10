-- Migration v60: make the one-active-operation-per-event trigger idempotent.
--
-- migration_v50 compared rows by id only.  The provisioning path retries with
-- INSERT ... ON CONFLICT (booking_id) DO UPDATE; a BEFORE INSERT trigger runs
-- before the conflict check, so the proposed (new) id differed from the row
-- that already belongs to the same booking and the retry was rejected.
--
-- The exclusivity rule is unchanged: a *different* booking still cannot become
-- a second active owner of the same event.  The same booking is now treated as
-- the same operation, matching _assert_event_has_no_other_active_operation().

BEGIN;

CREATE OR REPLACE FUNCTION public.prevent_parallel_active_event_operations()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.event_id IS NULL
       OR NEW.status IN ('completed', 'closed', 'cancelled') THEN
        RETURN NEW;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext('event-operation:' || NEW.event_id::text));

    IF EXISTS (
        SELECT 1
        FROM public.event_operations existing
        WHERE existing.event_id = NEW.event_id
          AND existing.id IS DISTINCT FROM NEW.id
          AND existing.booking_id IS DISTINCT FROM NEW.booking_id
          AND existing.status NOT IN ('completed', 'closed', 'cancelled')
    ) THEN
        RAISE EXCEPTION 'An event may have only one active operation'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

INSERT INTO app_schema_migrations (version, name)
VALUES (60, 'operation_exclusivity_idempotent')
ON CONFLICT (version) DO NOTHING;

COMMIT;
