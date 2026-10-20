"""Run with python -m app.generation_dispatcher_runner. Disabled by default."""
import asyncio
import logging
import time
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.generation_dispatch_service import dispatch_one
from app.services.generation_lifecycle_service import recover_operations

logger=logging.getLogger(__name__)


async def publish(payload):
    from app.worker import execute_generation_batch
    # Publish retries belong to the durable outbox, never an unbounded Celery loop.
    await asyncio.to_thread(execute_generation_batch.apply_async,kwargs=payload,retry=False,
        expires=None,ignore_result=True)


_last_cleanup = float('-inf')


def cleanup_due(now=None):
    """Housekeeping is not on the 5-second publish path; run it on its own cadence."""
    global _last_cleanup
    now = time.monotonic() if now is None else now
    if now - _last_cleanup < get_settings().generation_cleanup_interval_seconds:
        return False
    _last_cleanup = now
    return True


async def run_once(publisher=publish, max_events=20):
    if not get_settings().generation_worker_enabled:
        return {'recovered':0,'published':0}
    cleanup = cleanup_due()
    if cleanup:
        from app.services.generation_object_service import cleanup_orphans
        from app.services.generation_upload_service import cleanup_expired_uploads
        from app.services.generation_workspace_service import cleanup_abandoned
        await asyncio.to_thread(cleanup_abandoned)
    async with AsyncSessionLocal() as db:
        if cleanup:
            await cleanup_expired_uploads(db)
            await cleanup_orphans(db)
        recovered=await recover_operations(db)
        await db.commit()
    published=0
    for _ in range(min(max_events,100)):
        async with AsyncSessionLocal() as db:
            status=await dispatch_one(db,publisher)
            await db.commit()
        if status=='idle':
            break
        published+=status=='published'
    return {'recovered':recovered,'published':published,'cleanup':cleanup}


async def run_forever():
    while True:
        try:
            await run_once()
        except Exception:
            # No exception strings: connection errors can contain credentials.
            logger.error('Generation dispatcher tick failed; pending work remains in PostgreSQL')
        await asyncio.sleep(5)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
