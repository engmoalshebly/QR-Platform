"""Bounded operational aggregates. Never export tenant, guest or token labels."""
import asyncio
import json
import logging
import os
import resource
import shutil
import time
import weakref
from pathlib import Path
from sqlalchemy import text
from app.config import get_settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
_cache = weakref.WeakKeyDictionary()

QUERY = """SELECT
 (SELECT count(*) FROM generation_outbox x WHERE published_at IS NULL AND EXISTS(SELECT 1 FROM generation_operations o WHERE o.id=x.operation_id AND o.tenant_id=x.tenant_id AND o.status IN ('queued','running'))) AS outbox_pending,
 (SELECT COALESCE(EXTRACT(epoch FROM clock_timestamp()-min(created_at)),0) FROM generation_outbox x WHERE published_at IS NULL AND EXISTS(SELECT 1 FROM generation_operations o WHERE o.id=x.operation_id AND o.tenant_id=x.tenant_id AND o.status IN ('queued','running'))) AS outbox_oldest_seconds,
 (SELECT count(*) FROM generation_batches WHERE operation_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at<clock_timestamp() AND status NOT IN ('ready','failed','cancelled')) AS leases_expired,
 (SELECT count(*) FROM generation_batches WHERE operation_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at>clock_timestamp()) AS leases_active,
 (SELECT COALESCE(sum(recovery_count),0) FROM generation_batches WHERE operation_id IS NOT NULL) AS recoveries_total,
 (SELECT count(*) FROM generation_batches WHERE operation_id IS NOT NULL AND last_error_code='DISPATCH_STALLED') AS dispatch_stalled,
 (SELECT COALESCE(EXTRACT(epoch FROM clock_timestamp()-min(created_at)),0) FROM generation_operations WHERE status='queued') AS queued_oldest_seconds,
 (SELECT count(*) FROM generation_operations WHERE status='completed') AS operations_completed,
 (SELECT count(*) FROM generation_operations WHERE status='partial') AS operations_partial,
 (SELECT count(*) FROM generation_operations WHERE status='failed') AS operations_failed,
 (SELECT count(*) FROM generation_operations WHERE completed_at>clock_timestamp()-interval '15 minutes' AND status IN ('completed','partial','failed')) AS recent_finished,
 (SELECT count(*) FROM generation_operations WHERE completed_at>clock_timestamp()-interval '15 minutes' AND status IN ('partial','failed')) AS recent_failed"""


def event(name, operation_id):
    # Explicit allowlist; callers cannot accidentally log guest data or exceptions.
    if name not in ('started', 'completed', 'failed', 'ownership_lost'):
        raise ValueError('Unsupported generation log event')
    from uuid import UUID
    logger.info(json.dumps({'event': 'generation.'+name, 'operation_id': str(UUID(str(operation_id)))}, separators=(',', ':')))


def sample_worker():
    """Write process lifetime peak and container memory, shared with API via disk."""
    from app.services.generation_workspace_service import root_directory
    root = root_directory()
    data = {'sampled_at': time.time(), 'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
    for name, source in (('memory_bytes', '/sys/fs/cgroup/memory.current'), ('memory_limit_bytes', '/sys/fs/cgroup/memory.max')):
        try:
            value = Path(source).read_text().strip()
            if value.isdigit():
                data[name] = int(value)
        except OSError:
            pass
    temporary = root/('.worker-metrics-'+str(os.getpid()))
    try:
        with temporary.open('w') as stream:
            temporary.chmod(0o600)
            json.dump(data, stream)
        temporary.replace(root/'.worker-metrics.json')
    finally:
        temporary.unlink(missing_ok=True)


def local_snapshot():
    from app.services.generation_workspace_service import disk_usage
    root = Path(get_settings().generation_workspace_dir)
    if not root.exists() or root.is_symlink():
        return {'workspace_available': 0}
    space = shutil.disk_usage(root)
    result = {'workspace_available': 1, 'workspace_used_bytes': disk_usage(root),
              'workspace_budget_bytes': get_settings().generation_workspace_max_bytes,
              'disk_free_bytes': space.free, 'disk_total_bytes': space.total, 'worker_sample_available': 0}
    path = root/'.worker-metrics.json'
    try:
        if not path.is_symlink() and path.stat().st_size <= 1024:
            sample = json.loads(path.read_text())
            age = max(0, time.time()-float(sample['sampled_at']))
            result['worker_sample_age_seconds'] = age
            if age <= 300:
                for key in ('peak_rss_bytes', 'memory_bytes', 'memory_limit_bytes'):
                    value = sample.get(key)
                    if isinstance(value, (int, float)) and value >= 0:
                        result['worker_'+key] = value
                result['worker_sample_available'] = 1
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return result


async def collect():
    if not get_settings().generation_worker_enabled:
        return {'enabled': 0, 'available': 1}
    loop = asyncio.get_running_loop()
    state = _cache.setdefault(loop, {'lock': asyncio.Lock(), 'expires': 0, 'data': {}})
    async with state['lock']:
        if time.monotonic() < state['expires']:
            return dict(state['data'])
        started = time.monotonic()
        try:
            async with asyncio.timeout(5):
                async with AsyncSessionLocal() as db:
                    # Bound query time independently of HTTP/connection deadlines.
                    await db.execute(text("SET LOCAL statement_timeout='3000ms'"))
                    row = (await db.execute(text(QUERY))).mappings().one()
                data = {key: float(value) for key, value in row.items()}
                data.update(await asyncio.to_thread(local_snapshot))
            data.update(enabled=1, available=1, collected_at=time.time())
        except Exception:
            # Do not show old successful values as fresh or expose exception text.
            data = {'enabled': 1, 'available': 0}
        data['collection_seconds'] = time.monotonic()-started
        state.update(data=data, expires=time.monotonic()+30)
        return dict(data)


def prometheus(data):
    return ''.join(f'# TYPE qentry_generation_{key} gauge\nqentry_generation_{key} {float(value)}\n' for key, value in sorted(data.items()) if isinstance(value, (int, float)))
