"""Private, quota-bounded disk workspaces. Never use the container's /tmp tmpfs."""
import fcntl
import hashlib
import os
import shutil
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4
from app.config import get_settings


class WorkspaceFull(ValueError):
    pass


def root_directory():
    root = Path(get_settings().generation_workspace_dir)
    if not root.is_absolute() or root == Path('/tmp') or Path('/tmp') in root.parents:
        raise ValueError('Generation workspace must be an absolute persistent disk path outside /tmp')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError('Workspace must be owned by the runtime user and cannot be a symlink')
    root.chmod(0o700)
    return root


def disk_usage(root):
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory)/name).is_symlink()]
        for name in files:
            try:
                info = (Path(directory)/name).lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


class Workspace:
    def __init__(self, path, lock):
        self.path, self.lock = path, lock

    def output(self, suffix):
        if suffix not in ('.pdf', '.zip', '.png', '.csv', '.xlsx', '.json'):
            raise ValueError('Unsupported workspace file')
        return self.path/(uuid4().hex+suffix)

    def check(self):
        used = sum(p.stat().st_size for p in self.path.iterdir() if p.is_file() and p.name not in ('.reservation', '.active'))
        if used > get_settings().generation_workspace_job_bytes:
            raise WorkspaceFull('Job disk budget exceeded')

    def write(self, path, chunks):
        path = Path(path)
        if path.parent != self.path:
            raise ValueError('Output must be inside its workspace')
        root = self.path.parent
        # Serialize reservations across API/worker processes sharing this volume.
        with (root/'.quota.lock').open('a+b') as quota:
            fcntl.flock(quota, fcntl.LOCK_EX)
            remaining = get_settings().generation_workspace_max_bytes-disk_usage(root)
            remaining = min(remaining, shutil.disk_usage(root).free-16*1024*1024)
            count = 0
            try:
                with path.open('xb') as stream:
                    path.chmod(0o600)
                    for chunk in chunks:
                        count += len(chunk)
                        if count > remaining:
                            raise WorkspaceFull('Generation workspace capacity exceeded')
                        stream.write(chunk)
                self.check()
                return count
            except BaseException:
                path.unlink(missing_ok=True)
                raise


@contextmanager
def workspace():
    root = root_directory()
    path = root/uuid4().hex
    path.mkdir(mode=0o700)
    lock = (path/'.active').open('xb')
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        budget = get_settings().generation_workspace_job_bytes
        with (root/'.quota.lock').open('a+b') as quota:
            fcntl.flock(quota, fcntl.LOCK_EX)
            if disk_usage(root)+budget > get_settings().generation_workspace_max_bytes or shutil.disk_usage(root).free < disk_usage(root)+budget+16*1024*1024:
                raise WorkspaceFull('Generation workspace reservations exceed capacity')
            with (path/'.reservation').open('xb') as reservation:
                reservation.truncate(budget)
        yield Workspace(path, lock)
    finally:
        shutil.rmtree(path,ignore_errors=True)
        lock.close()


def cleanup_abandoned(max_age=300):
    """Only our UUID directories, with an expired mtime and no live owner."""
    root = root_directory()
    removed = 0
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            UUID(hex=path.name)
        except ValueError:
            continue
        if time.time()-path.stat().st_mtime < max_age:
            continue
        try:
            with (path/'.active').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                shutil.rmtree(path)
                removed += 1
        except (BlockingIOError, FileNotFoundError):
            continue
    return removed


def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()
