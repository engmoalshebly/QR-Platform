-- Migration v71: grant qentry_app read access to auth.users (id, email only).
--
-- `auth` is a Supabase-managed schema, outside every migration before this
-- one -- qentry_app (created in migration_v52) was never granted USAGE on
-- it, let alone SELECT on auth.users. Several tenant-facing routes running
-- on the RLS-enforced session join auth.users to show a member's email
-- (tenants.py list_members, bookings.py group member listings, invites.py,
-- operations.py member listings, platform.py staff views, and others) --
-- every one of them hits "permission denied for schema auth" on first use.
--
-- Column-level GRANT, not the whole table: refresh tokens, password hashes,
-- confirmation tokens and MFA state live in the same table and must stay
-- out of reach of the application-level role. qentry_app can SELECT id and
-- email only; selecting any other column still fails with a privilege
-- error, so this can't silently widen if a future query adds a column by
-- mistake. Existing queries already only ever select `email` (and join on
-- `id`), so no application code changes are needed.

BEGIN;

GRANT USAGE ON SCHEMA auth TO qentry_app;
GRANT SELECT (id, email) ON auth.users TO qentry_app;

-- auth.users has row-level security enabled (Supabase default) with zero
-- policies defined. Without a policy, the column grant above is necessary
-- but not sufficient: every row is still silently filtered out for any
-- role that isn't the table owner or BYPASSRLS, so the join returns NULL
-- for every email instead of erroring -- the same fail-closed-but-silent
-- trap this project's own schema_guard.verify_rls_posture check exists to
-- catch on our own tables. qentry_app is never reachable except through
-- our own backend (never exposed to PostgREST/anon), so a permissive
-- policy scoped to just this one role is the RLS-enabled equivalent of
-- the column grant already restricting what it can see.
DROP POLICY IF EXISTS qentry_app_can_read ON auth.users;
CREATE POLICY qentry_app_can_read ON auth.users
    FOR SELECT
    TO qentry_app
    USING (true);

INSERT INTO app_schema_migrations (version, name)
VALUES (71, 'qentry_app_auth_users_access')
ON CONFLICT (version) DO NOTHING;

COMMIT;
