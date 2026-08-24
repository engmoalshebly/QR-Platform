"""Create the first Qentry platform administrator safely.

This command is deliberately local/operational tooling, not a public API.  It
creates an Auth account without a tenant and marks its profile as platform
staff.  It refuses to run if a platform administrator already exists, so it
cannot be used to silently escalate another account.

Run from the repository root:
    $env:BOOTSTRAP_PLATFORM_ADMIN = 'YES'
    & .venv\\Scripts\\python.exe scripts\\bootstrap_platform_admin.py --email owner@example.com --full-name "Platform Owner"
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

# Running a script by path makes Python place ``scripts/`` (rather than the
# repository root) on sys.path.  Resolve the application package explicitly
# so this command works from PowerShell as documented.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal, get_supabase_admin


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the first Qentry platform administrator.")
    parser.add_argument("--email", required=True, type=str.lower)
    parser.add_argument("--full-name", required=True)
    return parser.parse_args()


def validate_password(password: str) -> None:
    if len(password) < 12 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must be at least 12 characters and include upper/lowercase letters and a number.")


async def _create_auth_user(email: str, password: str, full_name: str) -> Any:
    admin = get_supabase_admin()
    return await asyncio.to_thread(
        admin.auth.admin.create_user,
        {"email": email, "password": password, "email_confirm": True, "user_metadata": {"full_name": full_name}},
    )


async def main() -> None:
    if os.environ.get("BOOTSTRAP_PLATFORM_ADMIN") != "YES":
        raise RuntimeError("Set BOOTSTRAP_PLATFORM_ADMIN=YES to confirm first-admin creation.")

    args = parse_args()
    # Automation may run without an interactive terminal.  The value is read
    # once and immediately removed from this process environment; interactive
    # use remains the default and never places a password on the command line.
    password = os.environ.pop("PLATFORM_BOOTSTRAP_PASSWORD", "")
    if password:
        confirmation = password
    else:
        password = getpass.getpass("Platform administrator password: ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    validate_password(password)

    async with AsyncSessionLocal() as db:
        # Serialise concurrent bootstrap invocations before checking the count.
        await db.execute(text("SELECT pg_advisory_xact_lock(918247631)"))
        existing_staff = await db.scalar(text("SELECT count(*) FROM profiles WHERE is_staff = true"))
        if existing_staff:
            raise RuntimeError("A platform administrator already exists. Use the Platform Admin dashboard to manage staff.")

        existing_user = await db.scalar(text("SELECT id FROM auth.users WHERE lower(email) = :email"), {"email": args.email})
        if existing_user:
            raise RuntimeError("This email already has an account. Use a new email for the first platform administrator.")

        created_user_id: str | None = None
        try:
            response = await _create_auth_user(args.email, password, args.full_name.strip())
            created_user_id = str(response.user.id)
            await db.execute(text("""
                INSERT INTO profiles (id, full_name, is_staff, status)
                VALUES (:id, :name, true, 'active')
                ON CONFLICT (id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    is_staff = true,
                    status = 'active',
                    updated_at = now()
            """), {"id": created_user_id, "name": args.full_name.strip()})
            await db.execute(text("""
                INSERT INTO audit_logs (tenant_id, actor_user_id, action, resource_type, resource_id, metadata)
                VALUES (NULL, :actor_id, 'platform.staff.bootstrap', 'profile', :resource_id, CAST(:metadata AS jsonb))
            """), {
                "actor_id": created_user_id,
                "resource_id": created_user_id,
                "metadata": '{"source":"local_bootstrap"}',
            })
            await db.commit()
        except Exception:
            await db.rollback()
            if created_user_id:
                try:
                    await asyncio.to_thread(get_supabase_admin().auth.admin.delete_user, created_user_id)
                except Exception:
                    pass
            raise

    print(f"Platform administrator created for {args.email}. Sign in at the Platform Admin dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
