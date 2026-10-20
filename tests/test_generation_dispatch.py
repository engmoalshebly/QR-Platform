"""Outbox transport contract, including cancellation and secret-safe failures."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from app.services.generation_dispatch_service import dispatch_one


def database(attempts=0, empty=False):
    row = {key: uuid4() for key in ('id','tenant_id','operation_id','batch_id')}
    row['attempts'] = attempts
    result = MagicMock()
    result.mappings.return_value.first.return_value = None if empty else row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db, row


@pytest.mark.asyncio
async def test_publish_contains_only_identifiers_and_marks_ack():
    db, row = database()
    publish = AsyncMock()
    assert await dispatch_one(db, publish) == 'published'
    publish.assert_awaited_once_with({key: str(row[key]) for key in
                                   ('tenant_id','operation_id','batch_id')})
    sql = str(db.execute.call_args_list[-1].args[0])
    assert 'published_at=now()' in sql
    assert not db.commit.called


@pytest.mark.asyncio
@pytest.mark.parametrize('attempts,delay', [(0,2),(4,32),(20,300)])
async def test_broker_failure_defers_with_bounded_backoff_without_error_secrets(attempts, delay):
    db, row = database(attempts)
    publish = AsyncMock(side_effect=RuntimeError('redis://secret:password@private'))
    assert await dispatch_one(db, publish) == 'deferred'
    args = db.execute.call_args_list[-1].args
    assert args[1] == {'id': row['id'], 'delay': delay}
    assert 'password' not in str(args)
    assert 'published_at=now()' not in str(args[0])


@pytest.mark.asyncio
async def test_broker_timeout_defers():
    db, _ = database()
    async def blocked(payload):
        await asyncio.Event().wait()
    assert await dispatch_one(db, blocked, timeout=.01) == 'deferred'


@pytest.mark.asyncio
async def test_cancel_propagates_without_recording_ack_or_failure():
    db, _ = database()
    publish = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await dispatch_one(db, publish)
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_idle_does_not_publish_and_selection_skips_locked_cancelled_operations():
    db, _ = database(empty=True)
    publish = AsyncMock()
    assert await dispatch_one(db, publish) == 'idle'
    publish.assert_not_called()
    query = str(db.execute.call_args.args[0])
    assert 'FOR UPDATE OF x SKIP LOCKED' in query
    assert "o.status IN ('queued','running')" in query


@pytest.mark.asyncio
async def test_ack_recording_failure_propagates_for_transaction_rollback():
    db, _ = database()
    result = db.execute.return_value
    db.execute.side_effect = [result, RuntimeError('database disconnected')]
    publish = AsyncMock()
    with pytest.raises(RuntimeError, match='database disconnected'):
        await dispatch_one(db, publish)
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_unbounded_network_lock():
    db, _ = database()
    with pytest.raises(ValueError):
        await dispatch_one(db, AsyncMock(), timeout=30)
    db.execute.assert_not_called()


def test_explicit_legacy_cutover_without_changing_201_contract(monkeypatch):
    from app.config import get_settings
    from app.services.generation_operation_service import guard_legacy_generation_creation
    from fastapi import HTTPException
    monkeypatch.setattr(get_settings(),'generation_operations_enabled',False)
    guard_legacy_generation_creation()
    monkeypatch.setattr(get_settings(),'generation_operations_enabled',True)
    with pytest.raises(HTTPException) as error:
        guard_legacy_generation_creation()
    assert error.value.status_code==409
    assert error.value.detail['code']=='GENERATION_CONTRACT_UPGRADE'


def test_production_legacy_dispatch_never_falls_back_to_api(monkeypatch):
    from app.routes.batches import _dispatch_pipeline
    from app.config import get_settings
    from fastapi import BackgroundTasks,HTTPException
    monkeypatch.setattr(get_settings(),'app_env','production')
    monkeypatch.setattr(get_settings(),'use_worker',False)
    tasks=BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        _dispatch_pipeline(str(uuid4()),tasks)
    assert error.value.status_code==503
    assert not tasks.tasks


def test_production_cannot_accept_operations_with_disabled_worker(monkeypatch):
    from app.config import get_settings
    settings=get_settings()
    monkeypatch.setattr(settings,'app_env','production')
    monkeypatch.setattr(settings,'generation_operations_enabled',True)
    monkeypatch.setattr(settings,'generation_worker_enabled',False)
    assert any('GENERATION_WORKER_ENABLED' in problem for problem in settings.validate_for_production())


def test_frozen_renderer_refuses_hidden_entry_code():
    from app.services.generation_render_service import slots
    with pytest.raises(ValueError,match='visible entry-code'):
        slots({'elements':[{'element_type':'qr_code','is_visible':False}]})
