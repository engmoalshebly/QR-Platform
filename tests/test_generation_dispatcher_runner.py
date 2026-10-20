"""Dispatcher loop: disabled by default, housekeeping off the publish path, secret-safe failures."""
import logging
from unittest.mock import AsyncMock
import pytest
from app import generation_dispatcher_runner as runner
from app.config import get_settings


@pytest.fixture(autouse=True)
def fresh_clock(monkeypatch):
    monkeypatch.setattr(runner,'_last_cleanup',float('-inf'))
    monkeypatch.setattr(get_settings(),'generation_cleanup_interval_seconds',60)


def test_cleanup_runs_on_its_own_cadence():
    assert runner.cleanup_due(now=1000.0) is True
    assert runner.cleanup_due(now=1030.0) is False   # inside the interval
    assert runner.cleanup_due(now=1060.0) is True


@pytest.mark.asyncio
async def test_disabled_worker_does_nothing(monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_worker_enabled',False)
    sweep=AsyncMock()
    monkeypatch.setattr(runner,'recover_operations',sweep)
    assert await runner.run_once()=={'recovered':0,'published':0}
    sweep.assert_not_awaited()


@pytest.mark.asyncio
async def test_housekeeping_skipped_between_intervals_but_publishing_continues(monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_worker_enabled',True)
    monkeypatch.setattr(runner,'recover_operations',AsyncMock(return_value=0))
    statuses=iter(['published','published','idle'])
    monkeypatch.setattr(runner,'dispatch_one',AsyncMock(side_effect=lambda *a,**k: next(statuses)))
    cleaned=AsyncMock(return_value=0)
    monkeypatch.setattr('app.services.generation_workspace_service.cleanup_abandoned',lambda: cleaned())
    monkeypatch.setattr('app.services.generation_upload_service.cleanup_expired_uploads',cleaned)
    monkeypatch.setattr('app.services.generation_object_service.cleanup_orphans',cleaned)
    first=await runner.run_once(publisher=AsyncMock())
    assert first['cleanup'] is True and first['published']==2
    statuses=iter(['idle'])
    second=await runner.run_once(publisher=AsyncMock())
    assert second['cleanup'] is False   # not due yet, publish path unaffected


@pytest.mark.asyncio
async def test_tick_failure_is_logged_without_exception_text(monkeypatch,caplog):
    calls={'n':0}
    async def boom():
        calls['n']+=1
        raise RuntimeError('postgresql://user:secret@db/private')
    async def stop(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(runner,'run_once',boom)
    monkeypatch.setattr(runner.asyncio,'sleep',stop)
    with caplog.at_level(logging.ERROR), pytest.raises(KeyboardInterrupt):
        await runner.run_forever()
    assert calls['n']==1
    assert 'secret' not in caplog.text and 'Generation dispatcher tick failed' in caplog.text
