"""At-least-once outbox transport for the durable generation worker.

The caller owns the transaction and must commit after each dispatch. A broker
ack followed by a database failure can publish twice; the consumer must fence
execution using its database lease. No invitation data or credentials leave DB.
The optional generation dispatcher schedules this only when the worker gate is enabled.
"""
import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings

Publish = Callable[[dict[str, str]], Awaitable[None]]


async def dispatch_one(db: AsyncSession, publish: Publish, *, timeout: float = 5.0) -> str:
    """Lock one eligible event, publish IDs, and record ack or bounded backoff.

    A short broker deadline bounds the row lock. SKIP LOCKED lets concurrent
    publishers progress independently. Cancellation propagates and rolls back;
    the caller must not commit a cancelled transaction.
    """
    if not 0 < timeout <= 10:
        raise ValueError('publish timeout must be within (0, 10] seconds')
    # Fairness: only a bounded window of unfinished work sits in the broker, and the next event
    # comes from the tenant with the fewest unfinished published batches (oldest first on ties).
    # A single statement keeps the row lock and the admission decision consistent.
    inflight = '''FROM generation_outbox y
        JOIN generation_batches b ON b.id=y.batch_id AND b.tenant_id=y.tenant_id
        JOIN generation_operations oo ON oo.id=y.operation_id AND oo.tenant_id=y.tenant_id
        WHERE y.published_at IS NOT NULL AND oo.status IN ('queued','running')
          AND b.status NOT IN ('ready','failed','cancelled')'''
    row = (await db.execute(text(f'''
        SELECT x.id,x.tenant_id,x.operation_id,x.batch_id,x.attempts
        FROM generation_outbox x
        JOIN generation_operations o ON o.id=x.operation_id AND o.tenant_id=x.tenant_id
        WHERE x.published_at IS NULL AND x.available_at<=now()
          AND o.status IN ('queued','running')
          AND (SELECT count(*) {inflight}) < :window
        ORDER BY (SELECT count(*) {inflight} AND y.tenant_id=x.tenant_id),
                 x.available_at,x.created_at,x.id
        LIMIT 1 FOR UPDATE OF x SKIP LOCKED
    '''), {'window': get_settings().generation_dispatch_window})).mappings().first()
    if row is None:
        return 'idle'
    payload = {key: str(UUID(str(row[key]))) for key in
               ('tenant_id', 'operation_id', 'batch_id')}
    try:
        await asyncio.wait_for(publish(payload), timeout=timeout)
    except Exception:
        # Never persist exception text: broker errors may include credentials.
        delay = min(300, 2 ** min(int(row['attempts']) + 1, 9))
        await db.execute(text('''UPDATE generation_outbox
            SET attempts=attempts+1,last_error_code='BROKER_UNAVAILABLE',
                available_at=now()+make_interval(secs=>:delay)
            WHERE id=:id'''), {'id': row['id'], 'delay': delay})
        return 'deferred'
    await db.execute(text('''UPDATE generation_outbox
        SET attempts=attempts+1,published_at=now(),last_error_code=NULL
        WHERE id=:id'''), {'id': row['id']})
    return 'published'
