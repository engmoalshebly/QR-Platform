# Database Schema & Migrations

This directory holds the PostgreSQL schema for the Qentry platform (Supabase).

## Source of truth

The **authoritative** schema is the base consolidated file plus the ordered
migrations applied on top of it:

1. `schema_final.sql` — base SaaS core (tenants, memberships, roles, plans,
   subscriptions, usage, audit, settings, feature flags) + helper functions.
2. The `migration_v3` … `migration_v56` files, applied **in the order listed
   below**.

Apply them with `scripts/migrations/setup_cloud_db.py` (which encodes this exact
order), or via the Supabase CLI.

> The other root files — `schema.sql`, `schema_simple.sql`, and
> `schema_complete.sql` — are **historical bootstrap snapshots** and are NOT
> kept current (they only cover up to ~v4). Do not use them to provision a new
> environment. They are retained for reference only.

## Migration order

| # | File | Adds |
|---|------|------|
| base | `schema_final.sql` | Core SaaS schema, RBAC, plans, usage, audit |
| v3 | `migration_v3_invitations_platform.sql` | events, templates, guests, invitations, checkins, `validate_checkin` |
| v4 | `migration_v4_generation_batches.sql` | generation_batches, batch_items |
| v4 | `migration_v4_event_improvements.sql` | event field additions |
| v5 | `migration_v5_production_hardening.sql` | constraints / hardening |
| v5 | `migration_v5_fix_missing_columns.sql` | column fixups |
| v6 | `migration_v6_constraints_and_governance.sql` | constraints + governance |
| v6 | `migration_v6_platform_limits.sql` | platform limits |
| v7 | `migration_v7_platform_consistency.sql` | platform consistency |
| v8 | `migration_v8_optional_guest_whatsapp.sql` | optional guest whatsapp |
| v8 | `migration_v8_slot_index.sql` | slot index |
| v9 | `migration_v9_event_address.sql` | event address fields |
| v9 | `migration_v9_guest_count_scans.sql` | guest_count-aware `validate_checkin` |
| v10 | `migration_v10_gate_teams_and_users.sql` | gate ↔ teams/users |
| v10 | `migration_v10_registration_forms.sql` | registration_forms |
| v11 | `migration_v11_professional_plans.sql` | professional plan tiers |
| v12 | `migration_v12_custom_plans.sql` | custom plans |
| v13 | `migration_v13_limits_and_features.sql` | limits & features |
| v14 | `migration_v14_addons_pricing.sql` | addon pricing |
| v15 | `migration_v15_standard_plan_limits.sql` | standard plan limits |
| v16 | `migration_v16_paypal_pending_subscriptions.sql` | PayPal pending subs |
| v16 | `migration_v16_ui_permissions.sql` | ui.* permission keys |
| v17 | `migration_v17_team_workflows.sql` | team request + event-assignment workflows |
| v18 | `migration_v18_org_requests.sql` | organizer registration requests |
| v19 | `migration_v19_security_hardening.sql` | RLS / audit / security hardening |
| v20 | `migration_v20_password_reset_otps.sql` | password reset OTP flow |
| v21 | `migration_v21_organizer_booking_marketplace.sql` | organizer booking marketplace |
| v22 | `migration_v22_booking_event_link.sql` | booking ↔ event link |
| v23 | `migration_v23_phase1_operations.sql` | Phase 1 operations (event_operations, tasks, attachments, activity, notifications, app_schema_migrations) |
| v24 | `migration_v24_backfill_event_operations.sql` | backfill event_operations for already-accepted bookings |
| v25 | `migration_v25_phase1_tasks_enhancements.sql` | subtasks, task comments, manager approval, per-type task templates |
| v26–v36 | `migration_v26` … `migration_v36` | operations governance, tasks, teams, attachments and workflow controls |
| v37–v41 | `migration_v37` … `migration_v41` | team-manager limits, permissions, repairs and gate controls |
| v42 | `migration_v42_linked_workspaces.sql` | linked institution/organizer workspaces and shared billing owner |
| v43 | `migration_v43_workspace_permission_matrix.sql` | explicit workspace navigation and operation permissions |
| v44 | `migration_v44_billing_entitlement_hardening.sql` | verified custom-plan activation, webhook idempotency and atomic usage caps |
| v45–v48 | `migration_v45` … `migration_v48` | operation group assignments and mobile/field QR check-in foundations |
| v49 | `migration_v49_security_governance.sql` | hashed reset secrets, ownership invariants, append-only audit, and Supabase surface revocation |
| v50–v54 | `migration_v50` … `migration_v54` | event/field policy, app RLS role, Link payment ledger, YER currency |
| v55 | `migration_v55_plan_entitlements_production.sql` | canonical machine-readable plan features |
| v56 | `migration_v56_event_lifecycle_production.sql` | event lifecycle, registration idempotency, global public slugs |

When two files share a version number, apply them in the order shown above.

## Version tracking

`migration_v23` creates the `app_schema_migrations` table, and v23/v24 record
themselves in it via `INSERT ... ON CONFLICT DO NOTHING`. The backend startup
guard `app/services/schema_guard.py` checks that the required Phase 1 tables
and columns exist and refuses to boot against a stale database. In production
it also enforces the v49 password-reset columns and security functions.

## After provisioning

Run `python seed_plans.py` (from repo root) to seed the 5 plan tiers and their
limits. It requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` env vars —
**never hardcode keys**.
