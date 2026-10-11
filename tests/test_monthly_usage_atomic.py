"""Real PostgreSQL race/rollback tests on an explicitly isolated test database.

QUOTA_TEST_DATABASE_URL must point to a disposable database; never production.
"""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def quota_db():
    url = os.getenv('QUOTA_TEST_DATABASE_URL')
    if not url:
        pytest.skip('QUOTA_TEST_DATABASE_URL not configured')
    dbname = url.rsplit('/', 1)[-1].split('?')[0].lower()
    if not any(tag in dbname for tag in ('test', 'iso', 'tmp', 'scratch')):
        pytest.fail(f'refusing to TRUNCATE tables in database {dbname!r}: name must contain test/iso/tmp/scratch')
    conn = await asyncpg.connect(url)
    await conn.execute('''
      CREATE TABLE IF NOT EXISTS workspace_links (
        organizer_tenant_id uuid, institution_tenant_id uuid, billing_tenant_id uuid, status text);
      CREATE TABLE IF NOT EXISTS usage_counters (
        tenant_id uuid, period_start date, period_end date, key text, value bigint,
        updated_at timestamptz default now(), UNIQUE(tenant_id,period_start,key));
      -- v74 records itself in the migration ledger.
      CREATE TABLE IF NOT EXISTS app_schema_migrations (
        version integer PRIMARY KEY, name text, applied_at timestamptz DEFAULT now());
      TRUNCATE usage_counters,workspace_links;
      CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS UUID LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('app.current_tenant_id',true),'')::uuid;
      $$;
    ''')
    await conn.execute(Path('supabase/migration_v74_usage_accounting_utc.sql').read_text())
    yield url, conn
    await conn.close()


@pytest.mark.asyncio
async def test_fifty_concurrent_requests_cannot_overrun_last_slot(quota_db):
    url, conn = quota_db
    owner = uuid4()
    async def consume():
        db = await asyncpg.connect(url)
        try:
            async with db.transaction():
                return await db.fetchval('SELECT try_increment_usage($1,$2,1,1)', owner, 'events_per_month')
        finally:
            await db.close()
    results = await asyncio.gather(*(consume() for _ in range(50)))
    assert results.count(1) == 1
    assert results.count(None) == 49
    assert await conn.fetchval('SELECT SUM(value) FROM usage_counters') == 1


@pytest.mark.asyncio
async def test_failed_transaction_releases_usage_and_transaction_lock(quota_db):
    _, db = quota_db
    owner = uuid4()
    with pytest.raises(RuntimeError):
        async with db.transaction():
            assert await db.fetchval('SELECT try_increment_usage($1,$2,1,1)', owner, 'invitations_per_month') == 1
            raise RuntimeError('generation failed before commit')
    assert await db.fetchval('SELECT COUNT(*) FROM usage_counters') == 0
    assert await db.fetchval('SELECT try_increment_usage($1,$2,1,1)', owner, 'invitations_per_month') == 1


@pytest.mark.asyncio
async def test_historical_linked_usage_is_counted_without_rewriting_it(quota_db):
    _, db = quota_db
    owner, linked1, linked2, other = uuid4(), uuid4(), uuid4(), uuid4()
    for linked in (linked1, linked2):
        await db.execute('INSERT INTO workspace_links VALUES($1,$2,$1,\'active\')', owner, linked)
    await db.execute('''INSERT INTO usage_counters(tenant_id,period_start,period_end,key,value)
      VALUES($1,date_trunc('month',now() at time zone 'UTC')::date,current_date,'messages_per_month',2),
            ($2,date_trunc('month',now() at time zone 'UTC')::date,current_date,'messages_per_month',3),
            ($3,date_trunc('month',now() at time zone 'UTC')::date,current_date,'messages_per_month',999)
    ''', linked1, linked2, other)
    assert await db.fetchval('SELECT try_increment_usage($1,$2,1,6)', owner, 'messages_per_month') == 6
    assert await db.fetchval('SELECT try_increment_usage($1,$2,1,6)', owner, 'messages_per_month') is None
    assert await db.fetchval('SELECT value FROM usage_counters WHERE tenant_id=$1', owner) == 1
    assert await db.fetchval('SELECT value FROM usage_counters WHERE tenant_id=$1', linked1) == 2


@pytest.mark.asyncio
async def test_period_is_utc_even_with_non_utc_session(quota_db):
    _, db = quota_db
    await db.execute("SET TIME ZONE 'Pacific/Kiritimati'")
    owner = uuid4()
    await db.fetchval('SELECT try_increment_usage($1,$2,1,10)', owner, 'events_per_month')
    row = await db.fetchrow('''SELECT period_start,
       date_trunc('month',transaction_timestamp() at time zone 'UTC')::date AS expected
       FROM usage_counters''')
    assert row['period_start'] == row['expected']


@pytest.mark.asyncio
async def test_unused_reservation_can_be_released_in_same_utc_period(quota_db):
    _, db = quota_db
    owner = uuid4()
    async with db.transaction():
        assert await db.fetchval('SELECT try_increment_usage($1,$2,4,4)', owner, 'messages_per_month') == 4
        await db.execute('''UPDATE usage_counters SET value=GREATEST(0,value-3)
          WHERE tenant_id=$1 AND key='messages_per_month'
          AND period_start=date_trunc('month',transaction_timestamp() at time zone 'UTC')::date''', owner)
    assert await db.fetchval('SELECT try_increment_usage($1,$2,3,4)', owner, 'messages_per_month') == 4


@pytest.mark.asyncio
async def test_rls_scope_matches_all_workspaces_in_billing_account(quota_db):
    _, db = quota_db
    owner, linked1, linked2 = uuid4(), uuid4(), uuid4()
    for linked in (linked1, linked2):
        await db.execute("INSERT INTO workspace_links VALUES($1,$2,$1,'active')", owner, linked)
    await db.execute("SELECT set_config('app.current_tenant_id',$1,false)", str(linked1))
    assert set(await db.fetchval('SELECT current_linked_tenant_ids()')) == {owner, linked1, linked2}


@pytest.mark.asyncio
async def test_static_count_check_write_lock_prevents_overrun(quota_db):
    url, conn = quota_db
    await conn.execute('CREATE TABLE IF NOT EXISTS quota_resources(id uuid primary key, tenant_id uuid); TRUNCATE quota_resources;')
    owner = uuid4()
    async def add():
        db = await asyncpg.connect(url)
        try:
            async with db.transaction():
                await db.execute('SELECT pg_advisory_xact_lock(hashtext($1))', f'plan-limit:{owner}:guests_max:global')
                count = await db.fetchval('SELECT COUNT(*) FROM quota_resources WHERE tenant_id=$1', owner)
                if count >= 1:
                    return False
                await db.execute('INSERT INTO quota_resources VALUES($1,$2)', uuid4(), owner)
                return True
        finally:
            await db.close()
    outcomes = await asyncio.gather(*(add() for _ in range(20)))
    assert outcomes.count(True) == 1
    assert await conn.fetchval('SELECT COUNT(*) FROM quota_resources') == 1


@pytest.mark.asyncio
async def test_waiter_gets_lock_not_available_instead_of_hanging(quota_db):
    """A long generation holds the account's reservation lock until commit.  A
    concurrent request must fail fast (SQLSTATE 55P03, mapped to USAGE_BUSY by
    the API) rather than wait for a proxy timeout."""
    url, _ = quota_db
    owner = uuid4()
    holder = await asyncpg.connect(url)
    waiter = await asyncpg.connect(url)
    try:
        tx = holder.transaction()
        await tx.start()
        assert await holder.fetchval('SELECT try_increment_usage($1,$2,1,100)', owner, 'invitations_per_month') == 1
        await waiter.execute("SET lock_timeout = '400ms'")
        started = asyncio.get_running_loop().time()
        with pytest.raises(asyncpg.exceptions.LockNotAvailableError):
            await waiter.fetchval('SELECT try_increment_usage($1,$2,1,100)', owner, 'invitations_per_month')
        assert asyncio.get_running_loop().time() - started < 3
        await tx.commit()
        # Once the holder commits, the waiter is served normally.
        assert await waiter.fetchval('SELECT try_increment_usage($1,$2,1,100)', owner, 'invitations_per_month') == 2
    finally:
        await holder.close()
        await waiter.close()
