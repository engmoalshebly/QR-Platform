"""Short database leases for P2 workers; no long transactions during rendering.

Every result write must acquire ``lock_owned_batch`` in its own transaction,
then perform the result write before committing. A prior heartbeat alone is not
permission to publish. The operation lock serializes result commits with cancel.
"""
from dataclasses import dataclass
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class BatchLease:
    tenant_id: UUID
    operation_id: UUID
    batch_id: UUID
    owner: UUID
    attempt: int

    def params(self):
        return {key: str(value) if isinstance(value, UUID) else value
                for key, value in vars(self).items()}


async def claim_batch(db: AsyncSession, tenant_id: UUID, operation_id: UUID,
                      batch_id: UUID, *, seconds: int = 120) -> BatchLease | None:
    """Claim at most one heavy execution globally, even with multiple replicas.

    Caller commits immediately; expired ownership increments attempt and gets a
    new owner, so an old worker can never resume writes under its old token.
    """
    if not 30 <= seconds <= 600:
        raise ValueError('lease must be between 30 and 600 seconds')
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('generation:heavy-worker:v1'))"))
    params = {'tenant_id': str(tenant_id), 'operation_id': str(operation_id), 'batch_id': str(batch_id)}
    operation = (await db.execute(text('''SELECT status FROM generation_operations
        WHERE tenant_id=:tenant_id AND id=:operation_id FOR UPDATE'''), params)).scalar()
    if operation not in ('queued','running'):
        return None
    active = (await db.execute(text('''SELECT EXISTS(SELECT 1 FROM generation_batches
        WHERE operation_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at>clock_timestamp())'''))).scalar()
    if active:
        return None
    params.update(owner=str(uuid4()), seconds=seconds)
    attempt = (await db.execute(text('''UPDATE generation_batches
        SET lease_owner=:owner,execution_attempt=execution_attempt+1,
            heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+make_interval(secs=>:seconds),
            updated_at=clock_timestamp()
        WHERE tenant_id=:tenant_id AND operation_id=:operation_id AND id=:batch_id
          AND status NOT IN ('ready','failed','cancelled')
          AND (lease_owner IS NULL OR lease_expires_at<=clock_timestamp())
        RETURNING execution_attempt'''), params)).scalar()
    if attempt is None:
        return None
    await db.execute(text("UPDATE generation_operations SET status='running',updated_at=clock_timestamp() WHERE tenant_id=:tenant_id AND id=:operation_id"), params)
    return BatchLease(tenant_id, operation_id, batch_id, UUID(params['owner']), attempt)


async def lock_owned_batch(db: AsyncSession, lease: BatchLease) -> bool:
    """Fence result writes against cancellation, expiration and old attempts."""
    params = lease.params()
    status = (await db.execute(text('''SELECT status FROM generation_operations
        WHERE tenant_id=:tenant_id AND id=:operation_id FOR UPDATE'''), params)).scalar()
    if status != 'running':
        return False
    return bool((await db.execute(text('''SELECT id FROM generation_batches
        WHERE tenant_id=:tenant_id AND operation_id=:operation_id AND id=:batch_id
          AND lease_owner=:owner AND execution_attempt=:attempt
          AND lease_expires_at>clock_timestamp()
          AND status NOT IN ('ready','failed','cancelled') FOR UPDATE'''), params)).scalar())


async def heartbeat(db: AsyncSession, lease: BatchLease, *, seconds: int = 120) -> bool:
    if not 30 <= seconds <= 600:
        raise ValueError('lease must be between 30 and 600 seconds')
    if not await lock_owned_batch(db, lease):
        return False
    await db.execute(text('''UPDATE generation_batches SET heartbeat_at=clock_timestamp(),
        lease_expires_at=clock_timestamp()+make_interval(secs=>:seconds)
        WHERE id=:batch_id AND tenant_id=:tenant_id AND operation_id=:operation_id
          AND lease_owner=:owner AND execution_attempt=:attempt'''), {**lease.params(), 'seconds':seconds})
    return True
