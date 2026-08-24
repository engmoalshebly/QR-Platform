"""Database-level protection for an event's active operational owner."""
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_database_blocks_parallel_active_operations(db_session, org_world):
    """The constraint must hold even when a caller bypasses the API preflight."""
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migration_v50_event_operation_exclusivity.sql"
    ).read_text(encoding="utf-8")
    # The fixture deliberately owns the outer transaction. DDL is
    # transactional in PostgreSQL, so install the function and trigger within
    # it and let fixture teardown roll the changes back without touching the
    # developer DB. asyncpg prepares one SQL command at a time, hence the
    # deliberate separation of the PL/pgSQL function from the trigger DDL.
    function_sql = migration.split("DROP TRIGGER IF EXISTS", 1)[0].replace("BEGIN;", "", 1)
    await db_session.execute(text(function_sql))
    await db_session.execute(text("""
        DROP TRIGGER IF EXISTS trg_prevent_parallel_active_event_operations
        ON public.event_operations
    """))
    await db_session.execute(text("""
        CREATE TRIGGER trg_prevent_parallel_active_event_operations
        BEFORE INSERT OR UPDATE OF event_id, status ON public.event_operations
        FOR EACH ROW EXECUTE FUNCTION public.prevent_parallel_active_event_operations()
    """))

    values = {
        "event_id": str(org_world["event_id"]),
        "requester_tenant_id": str(org_world["requester_tenant"]),
        "provider_tenant_id": str(org_world["provider_tenant"]),
        "project_manager_id": str(org_world["provider_user"]),
    }
    await db_session.execute(text("""
        INSERT INTO event_operations (
            event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status
        ) VALUES (
            :event_id, :requester_tenant_id, :provider_tenant_id, :project_manager_id, 'planning'
        )
    """), values)

    with pytest.raises(DBAPIError, match="only one active operation"):
        async with db_session.begin_nested():
            await db_session.execute(text("""
                INSERT INTO event_operations (
                    event_id, requester_tenant_id, provider_tenant_id, project_manager_id, status
                ) VALUES (
                    :event_id, :requester_tenant_id, :provider_tenant_id, :project_manager_id, 'ready'
                )
            """), values)
