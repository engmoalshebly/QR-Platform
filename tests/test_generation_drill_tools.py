"""Fail-closed operational tools; fixtures contain no production credentials."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import hashlib
import base64
import hmac
import time
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts/ops'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def fake_gpg(tmp_path,monkeypatch):
    executable=tmp_path/'gpg'
    executable.write_text('#!/bin/sh\nfor arg; do last="$arg"; done\ncat "$last"\n');executable.chmod(0o700)
    monkeypatch.setenv('PATH',str(tmp_path)+':'+os.environ['PATH'])


def archive(path,kind='regular'):
    with tarfile.open(path,'w') as out:
        item=tarfile.TarInfo('../escape' if kind=='traversal' else 'safe/file')
        if kind=='symlink':
            item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';out.addfile(item)
        else:
            item.size=4;out.addfile(item,io.BytesIO(b'data'))
            if kind=='duplicate':out.addfile(item,io.BytesIO(b'data'))


def test_encrypted_archive_file_verification(tmp_path,monkeypatch):
    fake_gpg(tmp_path,monkeypatch);src=tmp_path/'data.tar';archive(src)
    result=module('verify_encrypted_archive').restore(src,tmp_path/'restored')
    assert result['files']==1 and result['all_files_verified']
    assert (tmp_path/'restored/safe/file').stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('kind',['traversal','symlink','duplicate'])
def test_archive_rejects_unsafe_entries(tmp_path,monkeypatch,kind):
    fake_gpg(tmp_path,monkeypatch);src=tmp_path/'data.tar';archive(src,kind)
    with pytest.raises(ValueError):module('verify_encrypted_archive').restore(src,tmp_path/'restored')
    assert not (tmp_path/'escape').exists()


def test_archive_budget_is_enforced(tmp_path,monkeypatch):
    fake_gpg(tmp_path,monkeypatch);src=tmp_path/'data.tar';archive(src)
    with pytest.raises(ValueError,match='budget'):module('verify_encrypted_archive').restore(src,tmp_path/'restored',limit=3)


@pytest.mark.parametrize('host,destination',[('-oProxyCommand=bad','/backups/app'),('backup','/../root'),('backup','/backups;id'),('backup','/.'),('backup','/')])
def test_offsite_rejects_unsafe_target_before_ssh(tmp_path,host,destination):
    file=tmp_path/'archive.gpg';file.write_bytes(b'fixture')
    result=subprocess.run(['bash',str(ROOT/'scripts/ops/offsite_ssh.sh'),str(file)],env={**os.environ,'BACKUP_SSH_HOST':host,'BACKUP_SSH_DIR':destination},capture_output=True)
    assert result.returncode==2


def test_offsite_checksum_mismatch_never_publishes(tmp_path):
    ssh=tmp_path/'ssh';calls=tmp_path/'calls'
    ssh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SSH_TEST_CALLS"\ncat >/dev/null\nprintf "wrongchecksum  file\\n"\n');ssh.chmod(0o700)
    file=tmp_path/'archive.gpg';file.write_bytes(b'fixture')
    result=subprocess.run(['bash',str(ROOT/'scripts/ops/offsite_ssh.sh'),str(file)],env={**os.environ,'PATH':str(tmp_path)+':'+os.environ['PATH'],'SSH_TEST_CALLS':str(calls),'BACKUP_SSH_HOST':'backup','BACKUP_SSH_DIR':'/backups/app'},capture_output=True)
    assert result.returncode!=0
    assert 'StrictHostKeyChecking=yes' in calls.read_text()
    assert 'mv ' not in calls.read_text()


def test_decryption_failure_prevents_restore(tmp_path):
    src=tmp_path/'broken.dump.gpg';src.write_bytes(b'not an encrypted archive')
    result=subprocess.run(['bash',str(ROOT/'scripts/ops/restore_drill.sh')],env={**os.environ,'DRILL_BACKUP_FILE':str(src),'DRILL_WORK_ROOT':str(tmp_path),'DRILL_KEEP_CONTAINER':'1'},capture_output=True,timeout=15)
    assert result.returncode!=0
    assert b'decryption failed' in result.stderr
    assert b'passed' not in result.stdout


def test_staging_tool_refuses_production_database(tmp_path):
    result=subprocess.run([os.sys.executable,str(ROOT/'scripts/ops/generation_staging_drill.py'),'--database-container','qentry-prod-db-1','--output',str(tmp_path/'report'),'--work-root',str(tmp_path/'work')],capture_output=True)
    assert result.returncode!=0
    assert not (tmp_path/'work').exists()


def test_history_current_key_detection_never_returns_token(tmp_path,monkeypatch):
    key='a-test-signing-key'
    enc=lambda value:base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    body=enc({'alg':'HS256'})+'.'+enc({'role':'service_role','exp':time.time()+60})
    token=body+'.'+base64.urlsafe_b64encode(hmac.new(key.encode(),body.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    import types
    tool=module('triage_secret_history')
    monkeypatch.setattr(tool.subprocess,'run',lambda *a,**kw:types.SimpleNamespace(stdout=('token="'+token+'"').encode()))
    record=tool.triage([{'Commit':'a'*40,'File':'example.py','StartLine':1,'EndLine':1,'RuleID':'jwt'}],{'SUPABASE_JWT_SECRET':key})[0]
    assert record['disposition']=='current_credential_requires_rotation_review'
    assert token not in json.dumps(record) and key not in json.dumps(record)
