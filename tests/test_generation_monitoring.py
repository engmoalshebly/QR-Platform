import json
import logging
import time
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest
from app.config import get_settings
from app.services import generation_monitoring_service as monitoring


@pytest.fixture
def tmp_path():
    # Production workspaces deliberately reject /tmp, including pytest defaults.
    with tempfile.TemporaryDirectory(prefix='.monitoring-test-', dir=Path.cwd()) as directory:
        yield Path(directory)


@pytest.mark.asyncio
async def test_disabled_monitoring_never_opens_database(monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_worker_enabled', False)
    monkeypatch.setattr(monitoring, 'AsyncSessionLocal', lambda: pytest.fail('DB accessed'))
    assert await monitoring.collect() == {'enabled': 0, 'available': 1}


def test_resource_samples_are_bounded_and_have_no_identifiers(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_workspace_dir', str(tmp_path))
    monitoring.sample_worker()
    data = monitoring.local_snapshot()
    assert data['worker_sample_available'] == 1
    assert data['worker_peak_rss_bytes'] > 0
    assert (tmp_path/'.worker-metrics.json').stat().st_mode & 0o777 == 0o600
    assert 'operation_id' not in json.dumps(data)
    sample = tmp_path/'.worker-metrics.json'
    sample.write_text(json.dumps({'sampled_at': time.time()-301, 'memory_bytes': 123}))
    stale = monitoring.local_snapshot()
    assert stale['worker_sample_available'] == 0
    assert 'worker_memory_bytes' not in stale


def test_structured_log_cannot_include_guest_or_exception(caplog):
    oid = uuid4()
    with caplog.at_level(logging.INFO):
        monitoring.event('started', oid)
    assert json.loads(caplog.records[-1].message) == {'event': 'generation.started', 'operation_id': str(oid)}
    with pytest.raises(ValueError):
        monitoring.event('guest@example.test?token=secret', oid)
    with pytest.raises(ValueError):
        monitoring.event('failed', 'guest@example.test')
    assert 'secret' not in caplog.text and 'guest@example.test' not in caplog.text


@pytest.mark.asyncio
async def test_collection_failure_is_explicit_and_does_not_leak(monkeypatch):
    monkeypatch.setattr(get_settings(), 'generation_worker_enabled', True)
    def broken():
        raise RuntimeError('postgresql://secret:password@private')
    monkeypatch.setattr(monitoring, 'AsyncSessionLocal', broken)
    result = await monitoring.collect()
    assert result['available'] == 0
    assert 'password' not in json.dumps(result)
    assert 'password' not in monitoring.prometheus(result)


@pytest.mark.asyncio
async def test_database_aggregates_use_real_schema(db_session, monkeypatch):
    from sqlalchemy import text
    row = (await db_session.execute(text(monitoring.QUERY))).mappings().one()
    assert set(row) >= {'outbox_pending', 'leases_expired', 'operations_completed', 'recoveries_total'}
    assert all(value is not None and float(value) >= 0 for value in row.values())


def test_workspace_rejects_wrong_owner_before_startup(tmp_path, monkeypatch):
    from app.services import generation_workspace_service as work
    monkeypatch.setattr(get_settings(), 'generation_workspace_dir', str(tmp_path))
    monkeypatch.setattr(work.os, 'getuid', lambda: tmp_path.stat().st_uid+1)
    with pytest.raises(ValueError, match='owned'):
        work.root_directory()


@pytest.mark.asyncio
async def test_metrics_auth_and_prometheus_are_private(monkeypatch):
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    monkeypatch.setattr(get_settings(), 'metrics_access_token', 'monitoring-test-token')
    monkeypatch.setattr(get_settings(), 'generation_worker_enabled', False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        denied = await client.get('/metrics?format=prometheus')
        assert denied.status_code == 404
        headers = {'x-metrics-token': 'monitoring-test-token'}
        result = await client.get('/metrics', headers=headers)
        assert result.status_code == 200
        assert result.json()['generation']['enabled'] == 0
        result = await client.get('/metrics?format=prometheus', headers=headers)
        assert result.status_code == 200
        assert 'qentry_generation_enabled 0.0' in result.text
        assert 'no-store' in result.headers['cache-control']
        assert 'monitoring-test-token' not in result.text


def test_status_latency_has_fixed_buckets_only():
    from app import metrics
    before = metrics.STATE_READ_COUNT
    metrics.observe_request('GET', '/api/v1/generation-operations/{operation_id}', 200, time.perf_counter()-0.2)
    assert metrics.STATE_READ_COUNT == before+1
    assert set(metrics.STATE_READ_BUCKETS) <= {0.05, 0.1, 0.25, 0.5, 1, 2, 5, float('inf')}
    assert 'le="0.25"' in metrics.generation_latency_prometheus()
