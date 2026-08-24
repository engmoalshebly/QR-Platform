"""Apply event lifecycle migration v56 to an explicitly configured production DB.

Required environment variable:
  MIGRATION_DATABASE_URL=postgresql://...
  PRODUCTION_BACKUP_CONFIRMED=yes

This deliberately refuses local hosts and applies only v56. It performs
read-only preflight checks, executes the migration atomically, and verifies
the exact schema objects needed by the production acceptance test.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import asyncpg


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migration_v56_event_lifecycle_production.sql"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def production_url() -> str:
    if os.environ.get("PRODUCTION_BACKUP_CONFIRMED", "").strip().lower() != "yes":
        raise SystemExit(
            "Set PRODUCTION_BACKUP_CONFIRMED=yes only after confirming a current "
            "restorable production backup"
        )
    value = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    value = value.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise SystemExit("MIGRATION_DATABASE_URL must be a PostgreSQL URL")
    if parsed.hostname.lower() in LOCAL_HOSTS or parsed.hostname.endswith(".local"):
        raise SystemExit("Refusing to run a production migration against a local host")
    return value


async def main() -> None:
    connection = await asyncpg.connect(production_url(), timeout=15)
    try:
        identity = await connection.fetchrow(
            "SELECT current_database() AS database, current_user AS role, "
            "inet_server_addr()::text AS server"
        )
        required = await connection.fetchval("""
            SELECT count(*) = 4
            FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name=ANY($1::text[])
        """, ["events", "invitations", "event_assets", "audit_logs"])
        if not required:
            raise SystemExit("Target is not a compatible QEntry production database")

        print(
            f"Target verified: database={identity['database']} "
            f"role={identity['role']} server={identity['server']}"
        )
        sql = MIGRATION.read_text(encoding="utf-8")
        async with connection.transaction():
            await connection.execute(sql)

        verification = await connection.fetchrow("""
            SELECT
              EXISTS(SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name='invitations'
                       AND column_name='registration_request_id') AS request_id,
              EXISTS(SELECT 1 FROM pg_indexes
                     WHERE schemaname='public' AND indexname='uq_events_public_slug') AS unique_slug,
              EXISTS(SELECT 1 FROM pg_indexes
                     WHERE schemaname='public' AND indexname='uq_registration_request_per_event') AS idempotency
        """)
        if not all(verification.values()):
            raise SystemExit(f"v56 verification failed: {dict(verification)}")
        print("v56 applied and verified successfully")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
