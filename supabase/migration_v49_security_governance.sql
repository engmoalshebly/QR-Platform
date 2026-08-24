-- Security governance hardening.
--
-- This migration makes the API the only public data surface, protects tenant
-- ownership invariants at the database level, and removes dangerous default
-- EXECUTE grants from SECURITY DEFINER functions.

BEGIN;

-- Never keep reset secrets in plaintext. Existing active reset records are
-- deliberately invalidated once because their plaintext values cannot be
-- safely converted without retaining the secret.
ALTER TABLE public.password_reset_otps
    ADD COLUMN IF NOT EXISTS otp_hash TEXT,
    ADD COLUMN IF NOT EXISTS reset_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS user_id UUID,
    ADD COLUMN IF NOT EXISTS request_ip INET,
    ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMPTZ;

UPDATE public.password_reset_otps
SET expires_at = now(), reset_token = NULL
WHERE expires_at > now() OR reset_token IS NOT NULL;

ALTER TABLE public.password_reset_otps
    ALTER COLUMN otp_code DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_password_reset_otps_token_hash
    ON public.password_reset_otps(reset_token_hash)
    WHERE reset_token_hash IS NOT NULL;

-- A tenant must always retain one active owner. The advisory transaction lock
-- closes the race where two concurrent requests each remove a different owner.
CREATE OR REPLACE FUNCTION public.prevent_last_active_tenant_owner_loss()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant_id UUID;
    v_losing_owner BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_tenant_id := OLD.tenant_id;
    ELSE
        v_tenant_id := NEW.tenant_id;
    END IF;

    v_losing_owner := OLD.role = 'owner'
        AND OLD.status = 'active'
        AND (
            TG_OP = 'DELETE'
            OR NEW.role IS DISTINCT FROM 'owner'
            OR NEW.status IS DISTINCT FROM 'active'
        );

    IF v_losing_owner THEN
        PERFORM pg_advisory_xact_lock(hashtext(v_tenant_id::text));
        IF NOT EXISTS (
            SELECT 1
            FROM public.memberships m
            WHERE m.tenant_id = v_tenant_id
              AND m.user_id <> OLD.user_id
              AND m.role = 'owner'
              AND m.status = 'active'
        ) THEN
            RAISE EXCEPTION 'A tenant must retain at least one active owner'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_last_active_tenant_owner_loss ON public.memberships;
CREATE TRIGGER trg_prevent_last_active_tenant_owner_loss
BEFORE UPDATE OF role, status OR DELETE ON public.memberships
FOR EACH ROW EXECUTE FUNCTION public.prevent_last_active_tenant_owner_loss();

-- `membership_roles` has a composite membership FK but historically did not
-- prove that the referenced role belongs to the same tenant.
CREATE OR REPLACE FUNCTION public.validate_membership_role_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.roles r
        WHERE r.id = NEW.role_id AND r.tenant_id = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'Role must belong to the membership tenant'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_membership_role_tenant ON public.membership_roles;
CREATE TRIGGER trg_validate_membership_role_tenant
BEFORE INSERT OR UPDATE OF tenant_id, role_id ON public.membership_roles
FOR EACH ROW EXECUTE FUNCTION public.validate_membership_role_tenant();

-- Ownership is never delegated through an email token. Existing pending owner
-- invitations are revoked rather than silently becoming a privilege grant.
UPDATE public.invites
SET status = 'revoked'
WHERE status = 'pending' AND role = 'owner';

CREATE OR REPLACE FUNCTION public.prevent_owner_invite()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'pending' AND NEW.role = 'owner' THEN
        RAISE EXCEPTION 'Owner invitations are not allowed; use an ownership transfer'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_owner_invite ON public.invites;
CREATE TRIGGER trg_prevent_owner_invite
BEFORE INSERT OR UPDATE OF role, status ON public.invites
FOR EACH ROW EXECUTE FUNCTION public.prevent_owner_invite();

-- Audit records are append-only. Retention jobs must export rather than alter
-- history, and privileged application actions fail if the audit insert fails.
CREATE OR REPLACE FUNCTION public.prevent_audit_log_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_audit_log_mutation ON public.audit_logs;
CREATE TRIGGER trg_prevent_audit_log_mutation
BEFORE UPDATE OR DELETE ON public.audit_logs
FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_log_mutation();

-- The server uses a privileged database connection after authenticating each
-- request itself. Do not expose privileged functions or tables through the
-- Supabase REST/RPC surface. This also removes PostgreSQL's default PUBLIC
-- EXECUTE privilege from every SECURITY DEFINER function.
DO $$
DECLARE
    fn RECORD;
    role_name TEXT;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure AS signature
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
    LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC', fn.signature);
        FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format('REVOKE ALL PRIVILEGES ON FUNCTION %s FROM %I', fn.signature, role_name);
            END IF;
        END LOOP;
    END LOOP;

    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I', role_name);
            EXECUTE format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I', role_name);
        END IF;
    END LOOP;
END;
$$;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

COMMIT;
