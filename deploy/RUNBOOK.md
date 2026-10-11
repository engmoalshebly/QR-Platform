# Qentry production runbook

Audience: the engineer on call and whoever performs a release.

## 0. First install on a dedicated server

Prerequisites: Ubuntu 24.04, Docker + compose plugin, DNS A records (Cloudflare,
Proxied, SSL/TLS mode Full (strict)) for the console domain and the Supabase domain
(`dawaa.prideidea.com`, `supabase.prideidea.com`) pointing at this host, ports 80/443 free (no other reverse proxy), the repo at `/opt/qentry`.

1. Harden the host: `sudo deploy/host/harden.sh` (key-only SSH, ufw, fail2ban,
   unattended upgrades).  Open a second SSH session to confirm access before closing the first.
2. Secrets: `sudo scripts/ops/generate_secrets.sh dawaa.prideidea.com supabase.prideidea.com`,
   then fill the `TODO` lines (SMTP in both files, `PLATFORM_SUPERADMIN_EMAILS`).
   Install the Cloudflare Origin CA pair: `sudo install -d -m 700 /etc/qentry/certs`,
   `sudo install -m 600 dawaa-origin.crt /etc/qentry/certs/origin.crt`, same for the key
   as `origin.key`.  The certificate must list both hostnames (or `*.prideidea.com`).
3. Build: `sudo scripts/ops/qentry-compose.sh -f deploy/docker-compose.build.yml build`
   (or set `QENTRY_IMAGE` to a released digest and `pull`).
4. Database: `sudo scripts/ops/bootstrap_database.sh` -- starts db + auth, applies the
   schema and every migration, sets the `qentry_app` password, creates the read-only
   `qentry_backup` role.  It refuses to run on an initialised database.
5. Start: `scripts/ops/qentry-compose.sh up -d`, then **once** `scripts/ops/qentry-compose.sh restart api`
   (on the very first boot the API starts before Caddy is up and cannot create the
   `invitations` storage bucket; the restart does). Verify `https://<domain>/health/ready`.
6. Create the first platform admin: `scripts/bootstrap_platform_admin.py` (run inside the API
   network, see below).  Platform staff must hold an AAL2 session: at first sign-in the console
   sends them to `/auth/mfa`, which enrols a TOTP authenticator (QR) and verifies the code.
   Only then do `/platform/*` calls stop returning 403.  Adding a second device later requires
   an already-verified (AAL2) session.
7. Backups: `sudo cp deploy/systemd/qentry-backup.* /etc/systemd/system/`, create the GPG
   key pair (keep the **private key off this server**), put
   `BACKUP_GPG_RECIPIENT=...` and `BACKUP_OFFSITE_CMD=...` in `/etc/qentry/backup.env`,
   `sudo systemctl enable --now qentry-backup.timer`, run it once by hand and confirm
   the offsite copy arrived.
8. Boot persistence: containers use `restart: unless-stopped`; optionally
   `systemctl enable qentry-compose.service` (`deploy/systemd/`).

Verified end to end on a throwaway copy of this stack (steps 2-5 and 7, backup + restore
drill): config validation passes, readiness is `ok` for database, redis and storage,
Auth admin and Storage calls succeed through the internal route, and the public route
set rejects signup, token, admin and REST requests with 404.

## 0a. Cloudflare

- Both records are Proxied, SSL/TLS mode **Full (strict)**; origin TLS is the Origin CA
  certificate, not Let's Encrypt.
- Caddy trusts `CF-Connecting-IP` only from Cloudflare's published ranges (static list in
  `deploy/Caddyfile`).  Review https://www.cloudflare.com/ips-v4 and `/ips-v6` each
  quarter and update the list; a stale list degrades to the proxy's own address for
  rate limiting, it does not open a spoofing hole.
- Origin CA expires 2041-10-06.  Firewall: allow 443 from anywhere or, stricter, only
  from the Cloudflare ranges.

## 1. Topology

| Component | Where | Exposed |
|---|---|---|
| Caddy (TLS, console static files, edge rules) | VPS, `docker-compose.prod.yml` | 80, 443 only |
| API (`app.main:app`) | VPS, container, non-root uid 1000, read-only FS | internal |
| Scheduler, Celery worker | same image, different command | internal |
| Redis (rate limits, Celery broker) | VPS, password-protected | internal |
| Link gateway (payments) | VPS, separate image | internal, never published — **dormant**: subscriptions and custom plans are approved manually today, see §6a |
| PostgreSQL 17 + GoTrue (Auth) + PostgREST + Storage | **Self-hosted Supabase, same compose stack**, named volumes `db_data`, `storage_data` | internal; Auth/Storage reachable publicly only through Caddy's restricted route set on `SUPABASE_DOMAIN` |

Secrets: `/etc/qentry/app.env`, `/etc/qentry/compose.env`, `/etc/qentry/db-roles.env`
(and `link-gateway.env` only if payments are ever enabled), mode 600, root.
Templates: `deploy/env/*.example`; `scripts/ops/generate_secrets.sh` creates them.
Always drive compose through `scripts/ops/qentry-compose.sh` (applies `--env-file`).

Not deployed on purpose: Supabase Studio, Realtime, Edge Functions, Analytics, Kong,
Supavisor.  The API uses only Auth, Storage and direct SQL.  Studio, if ever needed,
is reached over an SSH tunnel, never published.

## 2. Release

1. Tag `vX.Y.Z` on `main` after CI is green. `release.yml` builds, signs and pushes both
   images and prints their digests in the job summary.
2. Verify the signature: `cosign verify ghcr.io/<owner>/qentry-api@sha256:<digest>`.
3. Apply database migrations first (section 3). Schema changes must be backward compatible
   with the currently running version.
4. Put the new digests into `/etc/qentry/compose.env` (`QENTRY_IMAGE`, `LINK_GATEWAY_IMAGE`).
5. `docker compose -f docker-compose.prod.yml up -d`.
6. Check: `curl -fsS https://<domain>/health` returns 200, `/health/ready` returns 200,
   and `https://<domain>/field/` loads.
7. Watch error rate and p95 latency for 30 minutes before closing the release.

## 3. Database migrations (expand / contract)

- Every change is a new numbered file (`supabase/migration_vNN_*.sql`). Never edit an
  applied file.
- Expand first: add columns, tables and indexes that the current version ignores.
- Contract later, in a separate release, once no running version reads the old shape.
- Each migration registers itself in `app_schema_migrations`.
- Open gap: the runner applies the list in `scripts/migrations/ci_migrate.py` to blank
  databases only.  Migrations v52 and v61 through v66 must be applied in order on
  production, in that order, before the RLS-enforced application version is deployed.
  v62 through v66 were found by testing the real `qentry_app` role against every table and, for the highest-risk functions, by calling the real service code (not reimplemented SQL) through the real `get_db()` dependency -- see `tests/test_rls_real_service_functions.py`.
  not by code review alone: v61 missed the two legitimate cross-tenant write paths
  (booking/operation notifications, linked-workspace billing) and the `tenants` table
  itself, and 16 tables never meant to be tenant-scoped still carried schema_final's
  dead legacy policies, which silently blocked ordinary reads (profiles, plans,
  check-ins) for the application role.  `tests/test_rls_enforcement.py` now has a
  standing guardrail (`test_no_table_outside_the_reviewed_set_still_carries_rls`) that
  fails if a future migration re-enables RLS on a table without a reviewed policy. Production migrations are applied by hand, in order, and must be
  recorded. Do not re-run a migration against production unless it is idempotent.

## 4. Rollback

- Application rollback: set `QENTRY_IMAGE` back to the previous digest, `up -d`.
- Database rollback is not automatic. Because of expand/contract, the previous image
  must run against the current schema. If it cannot, restore from backup (section 6)
  and treat it as an incident.

## 5. Secret rotation

Rotate immediately after any suspected exposure, and on a schedule otherwise.

| Secret | How |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` | Rotate in Supabase, update `app.env`, restart API, worker, scheduler. |
| `SUPABASE_JWT_SECRET` | Rotate in Supabase. This invalidates all sessions. Announce first. |
| `INVITE_HMAC_SECRET` | Move the current value to `INVITE_HMAC_SECRET_PREV`, set the new one, restart. Remove `_PREV` after `HMAC_ROTATION_DAYS` (90). |
| `OTP_HMAC_SECRET`, `ORG_REQUEST_ENCRYPTION_KEY`, `METRICS_ACCESS_TOKEN` | Rotate and restart. OTP rotation invalidates pending resets. Encrypted org-request documents need re-encryption before the old key is removed. |
| `DATABASE_APP_URL` role password (`qentry_app`) | `ALTER ROLE qentry_app PASSWORD '...'`, update `app.env`, restart. Migration v52 ships a placeholder: rotate it before the first production start. Startup refuses to run if the role can bypass RLS. |
| `REDIS_PASSWORD` | Update `compose.env` and Redis together; restart in one window. |
| Link credentials | Rotate with Link, update `link-gateway.env`, restart the gateway. |

## 6. Backups and restore

Self-hosted means **this server is the only copy unless backups leave it**.

- Every 6 hours (`qentry-backup.timer`): `scripts/ops/backup_postgres.sh` dumps through
  the read-only `qentry_backup` role (BYPASSRLS, read-only), encrypts with GPG, verifies
  the archive is readable, then runs `BACKUP_OFFSITE_CMD`.  Local retention 14 days.
  Without `BACKUP_OFFSITE_CMD` the script warns on every run: treat that as an incident.
- **Targets: RPO 6 hours, RTO 2 hours.**  WAL archiving / PITR is not enabled; if an RPO
  under 6 hours is required, add `archive_mode` with an offsite WAL target (pgBackRest or
  WAL-G) -- it is a deliberate, separate project.
- Uploaded files live in the `storage_data` volume and are **not** in the dump.  Back them
  up as well (offsite rsync/rclone of the volume path, `docker volume inspect
  qentry-prod_storage_data`), together with `/etc/qentry` (store separately, encrypted).
- Restore drill, quarterly and before major releases: `scripts/ops/restore_drill.sh`
  restores the newest backup into a throwaway container and prints the schema version,
  table count and elapsed time (record it in the release notes).  Last verified result
  on the test stack: schema v71, 73 tables, 8 s.
- Real restore: stop api/worker/scheduler, restore into a fresh `db` volume with
  `pg_restore --no-owner`, re-run nothing from `bootstrap_database.sh` except role
  passwords, start the stack, check `/health/ready`.

## 6a. Billing: manual approval (Link Gateway disabled)

- Business decision, not a technical limitation: no online wallet payment is taken
  today. `subscription_engine.py` / `link_payment_service.py` are kept intact,
  unused, for a future re-enable — nothing currently imports or calls them.
- Flow: a tenant submits a plan or custom-plan request from the billing page
  (`POST /subscriptions/request`, `POST /custom-plans/{id}/request`). It sits in
  `pending_subscriptions` (provider='manual') or `custom_plans.status='pending_review'`
  until staff act on it. Nothing is activated automatically.
- Staff review in the admin console (`Subscriptions` tab → **طلبات قيد المراجعة**):
  `GET /platform/subscription-requests`, `GET /platform/custom-plans/pending`.
  Approve only after verifying payment out of band (bank transfer, cash, etc.);
  `payment_reference` is free text kept for bookkeeping, not verified by the app.
- Approve: `POST /platform/subscription-requests/{id}/approve` or
  `.../custom-plans/{id}/activate`, both requiring `payment_reference` and
  `valid_until`. Reject: the `/reject` counterpart with a `note` — the tenant can
  resubmit immediately afterward (the one-request-per-tenant unique index is gone
  once the row is removed).
- Every decision is audited (`subscription.requested_manual`, `.activated_manual`,
  `.rejected_manual`, `custom_plan.requested`, `.activate_verified`, `.rejected`)
  and notifies the tenant's active owner in-app and by email.
- **Known gap:** nothing pages staff when a new request arrives — the queue is
  polled by opening the tab, exactly like the pre-existing org-request and
  team-request queues. Acceptable for low volume; revisit if request volume grows.

## 6b. Verifying plan limits (after changing plans, limits or the scheduler)

1. Clone production into a throw-away container: `pg_dump -Fc` from `qentry-prod-db-1`,
   start `public.ecr.aws/supabase/postgres` on the `qentry-prod_app` network, create role
   `qentry_app`, `pg_restore --no-owner`.
2. Run `scripts/ops/verify_plan_limits.py` in the API image with `DATABASE_URL` /
   `DATABASE_APP_URL` pointing at the clone (and `PYTHONPATH=/app`).  It checks: a monthly
   limit refuses at the cap, static limits use live counts, a new month starts a new counter,
   linked workspaces share one counter, an expired subscription falls back to `starter`
   immediately and is downgraded + notified by the scheduler, renewal reminders at 7/3/1 days
   are sent once.  Last run: 17/17.
3. Remove the container.

## 7. Incidents

1. Declare the incident, name an owner, open a channel.
2. Stabilise first: roll back the image (section 4) or stop the failing component.
3. Preserve evidence: request IDs from the `X-Request-ID` header, the `application_errors`
   table and Sentry events. Do not copy tokens or personal data into tickets.
4. If tenant data may have been exposed, rotate the secrets involved (section 5), notify
   the security contact in `SECURITY.md`, and keep an audit trail of the investigation.
5. Write a post-incident review within five working days. Each action item gets an owner.

## 7a. Tenant isolation (RLS)

- **Payments:** migration v64 adds a unique index so at most one Link payment can
  be in flight per billing tenant -- a database-level backstop, not just an
  app-level check, against a double-click or two tabs charging the same wallet
  twice for one subscription period.  Verified with
  `tests/test_subscription_payment_idempotency.py`, which also covers the
  real bug this review found: Link's `paidAt` is a JSON string, and the
  asyncpg driver refuses a string for a `timestamptz` column outright, so
  every real payment confirmation rolled back its own activation -- after the
  wallet had already been charged -- until `_parse_paid_at()` was added.

- The application connects as `qentry_app` for tenant requests.  Infrastructure
  (middleware, scheduler, worker, platform staff, token-scoped public links) uses the
  privileged role explicitly.
- A new tenant table needs `tenant_id`, and migration v61's policy loop (or a later
  migration of the same shape) must cover it.  `tests/test_rls_enforcement.py` fails
  when any tenant table lacks forced RLS.
- Operating providers see events they operate, not other tenant data.  Any new
  cross-tenant path needs a migration, a test and a review.
- **Two more legitimate cross-tenant paths exist, fixed in migration v62** after
  verifying real call sites, not by inspection alone:
  - **Booking/operation notifications** (`notification_service.notify_tenant_managers`,
    `notify_operation_members`): a tenant may INSERT a notification for the
    counterparty of an active booking or operation (`current_cooperating_tenant_ids()`).
    Every other operation on `notifications` stays own-tenant only.
  - **Linked workspaces** (`entitlement_service.resolve_billing_tenant`,
    `get_billing_scope_tenant_ids`): an organizer workspace and its linked
    institution workspace (`workspace_links`) bill as one account.
    `current_linked_tenant_ids()` extends `usage_counters`, `subscriptions` and
    `custom_plans` to full read/write across the pair, and `memberships` /
    `invites` to read-only (seat and pending-invite counting).  Writes to
    memberships/invites stay own-tenant only.
  - `tenants` itself was missed by v61's audit (its own identity column is `id`,
    not `tenant_id`) and still carried schema_final's `auth.uid()`-based
    policies, which `qentry_app` cannot satisfy even for its own row — breaking
    `GET/PATCH /api/v1/tenants/current`.  v62 replaces them: a tenant reads its
    own row, its linked billing partner's and a cooperating counterparty's; it
    updates only its own row and its billing partner's.
  - Found by running the real `qentry_app` role against the actual call sites
    (`SET LOCAL ROLE qentry_app` in a rolled-back transaction), not by code
    review alone — `app/services/notification_service.py` and
    `app/services/entitlement_service.py` are the two places that manufacture a
    tenant id different from the caller's own; both are now covered and tested
    in `tests/test_rls_enforcement.py`.  `try_increment_usage()` and
    `increment_usage()` were already `SECURITY DEFINER` and needed no change.

- **v62's own audit still missed two things, caught only by calling the real
  Python functions — not reimplemented SQL — through the real `get_db()` on the
  real role** (`tests/test_rls_real_service_functions.py`):
  - **`pending_subscriptions` (migration v65).** `resolve_billing_tenant()` is
    called one layer above `subscription_engine.py`, in
    `app/routes/subscriptions.py`, so a grep for `billing_tenant_id` inside the
    engine itself found nothing. The engine's own
    `INSERT`/`SELECT ... FOR UPDATE`/`DELETE` on `pending_subscriptions` are
    real, direct SQL keyed by whatever `tenant_id` it was handed — the
    organizer's linked institution when billing is delegated. Before this fix,
    confirming an OTP for a linked organizer workspace failed with "لم يتم
    العثور على عملية دفع معلقة" every time, and the cleanup `DELETE ... WHERE
    id = :id` (no tenant filter in the SQL at all) silently removed nothing.
    Unlike `subscriptions`/`custom_plans`, `DELETE` here also needed the linked
    scope, not just the tenant's own.
  - **`memberships` read for `notify_tenant_managers()` (migration v66).**
    v62 let the final `INSERT INTO notifications` reach a booking/operation
    counterparty, but `notify_tenant_managers()` first runs
    `SELECT user_id FROM memberships WHERE tenant_id = :tid AND
    status='active' AND role IN ('owner','admin')` to find who to notify — and
    that read was still scoped to the *billing* link only. Calling the real
    function (not its final INSERT in isolation) found zero managers for a
    booking counterparty, so the loop ran zero times: no error, no
    notification, on every real booking creation and operation completion.
    `memberships`' read policy now also covers `current_cooperating_tenant_ids()`.
  - `notify_operation_members()` needed no change: it joins
    `event_operation_members` (no `tenant_id`, not RLS-scoped) to
    `event_operations`, which v62's party policies already cover for both
    sides. Verified the same way, not assumed.
  - **Lesson for the next cross-tenant change:** a policy fix is not done until
    something has called the real Python function end to end as the real role.
    SQL copied from reading the source can still miss a nested query inside a
    shared helper.

## 8. Operational procedures

- **Suspend a tenant:** platform console, or `POST /api/v1/platform/tenants/{id}/suspend`.
  Suspension blocks every tenant-scoped route, including `/api/v1/tenants/current/*`, and
  removes all permissions. Reactivate with `/activate`.
- **Platform staff:** grant or revoke through `/api/v1/platform/staff`. Only the break-glass
  superadmin emails in `PLATFORM_SUPERADMIN_EMAILS` may change staff. Staff require AAL2.
- **Payments stuck in PENDING:** the status endpoint resolves them. If one stays PENDING
  beyond the alert threshold, reconcile against the Link statement before any manual action.
  Never mark a payment successful by hand.

## 9. Monitoring and alerts (required before go-live)

| Signal | Source | Alert when |
|---|---|---|
| Uptime of `/health/ready` | external probe | fails 2 consecutive checks |
| 5xx rate | Caddy JSON logs, `application_errors` | above 1% for 5 minutes |
| p95 latency | Caddy logs | above 1 s for 10 minutes |
| Scheduler and worker liveness | container health and logs | container restarting or no heartbeat for 15 minutes |
| Payments in PENDING | reconciliation query | any older than the agreed threshold |
| Redis / DB errors | `/health/ready` checks | any failure |
| Disk and backup age | host | disk above 80%, newest backup older than 26 hours |

Sentry is enabled by `SENTRY_DSN`. `send_default_pii` is off.

## 10. Go-live gate

- CI green on `main`, release tag built and signed.
- Restore drill passed within the last 90 days.
- Billing runs on manual staff approval today (§6a) — no Link acceptance checklist
  gate applies while that stays the case. If Link is ever re-enabled,
  `link-gateway-service/PRODUCTION_CHECKLIST_AR.md` items 5–9 must pass with
  production credentials before any real payment is accepted again.
- External penetration test completed with no open critical or high findings.
- Monitoring alerts in section 9 fire in a test.
