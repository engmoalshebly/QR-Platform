import asyncio
from unittest.mock import AsyncMock

from app.worker import run_pipeline_task


def test_worker_runs_repeated_jobs_without_a_preexisting_loop(monkeypatch):
    import app.database
    import app.services.batch_pipeline

    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    loops = []
    async def pipeline(db, batch_id):
        loops.append(asyncio.get_running_loop())
        return {'status': 'completed'}

    monkeypatch.setattr(app.database, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(app.services.batch_pipeline, 'run_batch_pipeline', pipeline)
    asyncio.set_event_loop(None)
    try:
        for _ in range(2):
            assert run_pipeline_task.run('11111111-1111-4111-8111-111111111111')['status'] == 'completed'
        assert loops[0] is loops[1]
        assert not loops[0].is_closed()
    finally:
        if loops:
            loops[0].close()
        asyncio.set_event_loop(None)
