"""Alembic environment configuration.

This project uses raw SQL migrations (supabase/migration_v*.sql) as the
authoritative schema history.  Alembic is configured in --sql / offline
mode to generate new migration stubs that follow the same convention.

For day-to-day development, use:
    alembic revision -m "short description"
    # then write your SQL in the generated file

For CI, the canonical migration runner is scripts/migrations/ci_migrate.py
which applies schema_final.sql + all migration_v*.sql files in order.
"""
import os
from logging.config import fileConfig

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
