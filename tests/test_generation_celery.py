"""Optional real Redis + prefork worker crash test in isolated test infrastructure."""
import asyncio
import os
import signal
import subprocess
import sys
from uuid import uuid4
import pytest
from celery import Celery
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.services.generation_dispatch_service import dispatch_one
from app.services.generation_lifecycle_service import recover_operations
from tests.test_generation_operations import committed_world
from tests.test_generation_worker import world,admit,state

pytestmark=pytest.mark.integration


def start_redis_outage():
    """Freeze the disposable Redis container (a real outage). CI's generated service name
    can be passed through P2_TEST_REDIS_CONTAINER. CLIENT PAUSE is not equivalent: the
    prefork worker shuts down on the read timeout instead of reconnecting."""
    container=os.environ.get('P2_TEST_REDIS_CONTAINER','qentry-p2-test-redis')
    subprocess.run(['docker','pause',container],check=True,capture_output=True)
    return lambda: subprocess.run(['docker','unpause',container],check=True,capture_output=True)


async def until(check,timeout=25):
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(.15)


@pytest.mark.asyncio
async def test_real_redis_outage_and_killed_prefork_worker(world,tmp_path):
    broker=os.environ.get('P2_TEST_REDIS_URL')
    if not broker:
        pytest.skip('Set P2_TEST_REDIS_URL to an isolated disposable Redis')
    assert broker.startswith('redis://127.0.0.1:'), 'Never use production Redis'
    queue='p2-'+uuid4().hex
    client=Celery('p2-test',broker=broker)
    client.conf.broker_transport_options={'socket_connect_timeout':1,'socket_timeout':1}
    oid,bid=await admit(world,formats=())
    # Only this operation is visible to the global publisher in this disposable DB.
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE generation_operations SET status='cancelled' WHERE id<>:id AND status IN ('queued','running')"),{'id':oid})
        await db.commit()
    env={**os.environ,'REDIS_URL':broker,'GENERATION_WORKER_ENABLED':'true',
         'GENERATION_WORKSPACE_DIR':__import__('app.config',fromlist=['get_settings']).get_settings().generation_workspace_dir,'P2_WORKER_SCRATCH':str(tmp_path),'P2_WORKER_QUEUE':queue,'PYTHONPATH':os.getcwd()}
    log=open(tmp_path/'worker.log','w')
    process=subprocess.Popen([sys.executable,'tests/helpers/generation_celery_harness.py'],env=env,
                             stdout=log,stderr=log,start_new_session=True)
    async def publish(payload):
        await asyncio.to_thread(client.send_task,'generation.execute_batch',kwargs=payload,queue=queue,retry=False)
    try:
        async with AsyncSessionLocal() as db:
            assert await dispatch_one(db,publish)=='published'
            await db.commit()
        async def started():
            return (tmp_path/'started').exists()
        await until(started)
        # Stop actual Redis while the consumer holds a database lease.
        end_outage=start_redis_outage()
        try:
            os.kill(int((tmp_path/'started').read_text()),signal.SIGKILL)
            # Advance only this lease's deadline; avoids a 120s test sleep.
            async with AsyncSessionLocal() as db:
                await db.execute(text("UPDATE generation_batches SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE tenant_id=:tid AND id=:id"),{'tid':world[0],'id':bid})
                await recover_operations(db)
                await db.commit()
            async with AsyncSessionLocal() as db:
                assert await dispatch_one(db,publish,timeout=2)=='deferred'
                await db.commit()
            data=await state(oid)
            assert data['status']=='running' and data['cards_done']==0
        finally:
            await asyncio.to_thread(end_outage)
        (tmp_path/'release').touch()
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE generation_outbox SET available_at=now()-interval '1 second' WHERE operation_id=:id"),{'id':oid})
            assert await dispatch_one(db,publish)=='published'
            await db.commit()
        async def completed():
            return (await state(oid))['status']=='completed'
        await until(completed,timeout=35)
        await publish({'tenant_id':str(world[0]),'operation_id':str(oid),'batch_id':str(bid)})
        data=await state(oid)
        assert data['cards_done']==2 and data['cards_failed']==0
        async with AsyncSessionLocal() as db:
            assert (await db.execute(text('SELECT count(*) FROM invitations WHERE generation_operation_id=:id'),{'id':oid})).scalar()==2
            assert (await db.execute(text('SELECT execution_attempt FROM generation_batches WHERE id=:id'),{'id':bid})).scalar()==2
    finally:
        os.killpg(process.pid,signal.SIGTERM)
        try:
            await asyncio.to_thread(process.wait,timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            await asyncio.to_thread(process.wait,timeout=5)
        log.close()
        client.close()
