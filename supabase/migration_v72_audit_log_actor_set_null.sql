-- Migration v72: let an account be deleted without breaking the append-only audit log.
--
-- audit_logs.actor_user_id references profiles(id) ON DELETE SET NULL, and
-- profiles.id cascades from auth.users.  Migration v49 then made every UPDATE
-- and DELETE on audit_logs raise.  Together they mean that deleting an account
-- which ever wrote an audit entry fails with "Audit logs are append-only"
-- (HTTP 500 from GoTrue's admin delete), so no such account can be removed:
-- member removal, rollback of a half-created administrator, and clean-up all
-- hit it.
--
-- The one mutation that must be allowed is the referential action itself:
-- clearing actor_user_id while every other column stays identical.  It is
-- recognised by running nested inside the foreign-key trigger
-- (pg_trigger_depth() > 1), so a direct UPDATE by a person or by application
-- code is still rejected, and DELETE is always rejected.

BEGIN;

INSERT INTO app_schema_migrations (version, name)
VALUES (72, 'audit_log_actor_set_null')
ON CONFLICT (version) DO NOTHING;

CREATE OR REPLACE FUNCTION public.prevent_audit_log_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND pg_trigger_depth() > 1
       AND OLD.actor_user_id IS NOT NULL
       AND NEW.actor_user_id IS NULL
       AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id')
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'Audit logs are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

COMMIT;
