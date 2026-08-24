"""Baseline: stamp existing schema at migration v52 (RLS enforcement).

This is a no-op migration that marks the Alembic version table with the
current schema state.  All prior schema history lives in:

    supabase/schema_final.sql          -- canonical base DDL
    supabase/migration_v3..v52_*.sql   -- incremental migrations

For a fresh database, run scripts/migrations/ci_migrate.py which applies
all of the above in order.

Revision ID: 0001
Revises:
Create Date: 2026-08-20
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
