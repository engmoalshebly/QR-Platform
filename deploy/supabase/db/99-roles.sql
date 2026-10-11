-- Sets the passwords of the Supabase service roles from POSTGRES_PASSWORD.
-- The upstream roles.sql also touches supabase_functions_admin, which only
-- exists when the Edge Functions webhooks.sql is mounted; that is not deployed
-- here, and a missing role aborts the whole init (ON_ERROR_STOP).  Only roles
-- that exist are altered.
\set pgpass `echo "$POSTGRES_PASSWORD"`

SELECT format('ALTER USER %I WITH PASSWORD %L', rolname, :'pgpass')
FROM pg_roles
WHERE rolname IN ('authenticator', 'pgbouncer', 'supabase_auth_admin',
                  'supabase_storage_admin', 'supabase_functions_admin')
\gexec
