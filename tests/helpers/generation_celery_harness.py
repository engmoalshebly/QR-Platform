"""Disposable integration worker only. Never imported by the application."""
import os
import time
from pathlib import Path

root=Path(os.environ['P2_WORKER_SCRATCH'])
assert 'pytest-' in str(root), 'Harness requires pytest scratch storage'
from app.services import generation_worker_service as worker
from app.worker import celery_app


def upload(path,content,mime):
    target=root/'objects'/path
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(content)
    return path


worker.storage.upload_disk_file=lambda path,file,mime:upload(path,file.read_bytes(),mime)
def verify(path,size,digest):
    import hashlib
    content=(root/'objects'/path).read_bytes()
    assert len(content)==size and hashlib.sha256(content).hexdigest()==digest
worker.storage.verify_disk_object=verify
worker.storage.upload_file=upload
worker.storage.download_file=lambda path:(root/'objects'/path).read_bytes()
worker.storage.get_signed_url=lambda path,expires:'https://storage.invalid/'+path
original=worker.render.barcode


def slow_once(*args):
    marker=root/'started'
    if not marker.exists():
        marker.write_text(str(os.getpid()))
        deadline=time.monotonic()+45
        while not (root/'release').exists() and time.monotonic()<deadline:
            time.sleep(.05)
    return original(*args)


worker.render.barcode=slow_once
celery_app.conf.worker_enable_remote_control=False
celery_app.worker_main(['worker','--loglevel=WARNING','--concurrency=1','--pool=prefork',
    '--without-gossip','--without-mingle','--without-heartbeat','--queues='+os.environ['P2_WORKER_QUEUE']])
