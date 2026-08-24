"""Destructively reset the local Qentry Supabase database and reapply schema.

This utility deliberately only accepts the local Supabase database exposed by
this workspace (127.0.0.1:5434/postgres).  It clears Qentry application data,
Supabase Auth users, and Supabase Storage metadata, then applies the same
authoritative schema/migrations used by CI.  It never drops Supabase system
schemas, extensions, roles, or Docker volumes.

Usage (PowerShell):
    $env:RESET_LOCAL_DB = 'YES'
    $env:DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:5434/postgres'
    .venv\\Scripts\\python scripts/migrations/reset_local_supabase.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

from ci_migrate import MIGRATION_FILES


ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "supabase"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_PORT = 5434
ALLOWED_DATABASE = "postgres"


def normalise_asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def assert_safe_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("DATABASE_URL must use PostgreSQL.")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise RuntimeError("Refusing to reset a non-local database host.")
    if parsed.port != ALLOWED_PORT:
        raise RuntimeError(f"Refusing to reset a database not on port {ALLOWED_PORT}.")
    if parsed.path.lstrip("/") != ALLOWED_DATABASE:
        raise RuntimeError(f"Refusing to reset a database other than {ALLOWED_DATABASE!r}.")


async def table_exists(conn: asyncpg.Connection, schema: str, table: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = $1 AND table_name = $2
            )
            """,
            schema,
            table,
        )
    )


async def apply_schema(conn: asyncpg.Connection) -> None:
    for name in MIGRATION_FILES:
        path = SQL_DIR / name
        if not path.exists():
            raise FileNotFoundError(path)
        print(f"Applying {name}", flush=True)
        await conn.execute(path.read_text(encoding="utf-8"))


async def main() -> None:
    if os.environ.get("RESET_LOCAL_DB") != "YES":
        raise RuntimeError("Set RESET_LOCAL_DB=YES to confirm this destructive operation.")

    database_url = normalise_asyncpg_url(os.environ["DATABASE_URL"])
    assert_safe_target(database_url)
    conn = await asyncpg.connect(database_url, command_timeout=120)
    try:
        database_name = await conn.fetchval("SELECT current_database()")
        server_port = await conn.fetchval("SELECT inet_server_port()")
        # Docker publishes the approved host port 5434 to PostgreSQL's internal
        # default port 5432.  The URL check above is the authoritative network
        # boundary; this check only validates the expected container mapping.
        if database_name != ALLOWED_DATABASE or server_port != 5432:
            raise RuntimeError("Connected database does not match the approved local reset target.")
        if not await table_exists(conn, "auth", "users"):
            raise RuntimeError("The approved target is not a Supabase Auth database.")

        print("Clearing Qentry application schema, local Auth users, and Storage metadata…", flush=True)
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("GRANT ALL ON SCHEMA public TO postgres")
        await conn.execute("GRANT ALL ON SCHEMA public TO public")

        if await table_exists(conn, "storage", "objects") and await table_exists(conn, "storage", "buckets"):
            await conn.execute("TRUNCATE TABLE storage.objects, storage.buckets CASCADE")
        await conn.execute("TRUNCATE TABLE auth.users CASCADE")

        await apply_schema(conn)
        public_tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        plans = await conn.fetchval("SELECT count(*) FROM public.plans")
        permissions = await conn.fetchval("SELECT count(*) FROM public.permissions")
        print(
            f"Local reset complete: {public_tables} public tables, {plans} plans, {permissions} permissions.",
            flush=True,
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
