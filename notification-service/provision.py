#!/usr/bin/env python3
"""Provision a session-scoped provider credential; store secrets outside Git."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import UUID

session_id = str(UUID(sys.argv[1]))
target = Path(os.getenv('NOTIFY_ENV_FILE', str(Path.home()/'.qentry/notifications.env')))
if target.exists():
    raise SystemExit('Environment already exists; refusing to overwrite secrets')
source = '''import asyncio,json,sys
from app.services import whatsapp_service as svc
async def main():
 sid=sys.argv[1]
 remote=await svc.provider('GET','sessions/'+sid)
 if remote.get('status')!='ready': raise RuntimeError('Sender must be ready')
 key=await svc.provider('POST','auth/api-keys',payload={'name':'notification-gateway','role':'operator','allowedSessions':[sid]})
 print(json.dumps({'key':key['apiKey']}))
asyncio.run(main())
'''
r = subprocess.run(['docker','exec','-i',os.getenv('QENTRY_API_CONTAINER','qentry-prod-api-1'),
                    'python','-c',source,session_id],input='',text=True,capture_output=True)
if r.returncode:
    raise SystemExit('Provider provisioning failed; no environment file written')
key = json.loads(r.stdout)['key']
values = {'NOTIFY_ADMIN_KEY': secrets.token_urlsafe(48), 'OPENWA_BASE_URL': 'http://openwa-api:2785',
          'OPENWA_API_KEY': key, 'OPENWA_SESSION_ID': session_id,
          'OPENWA_WEBHOOK_SECRET': secrets.token_urlsafe(48), 'NOTIFY_INTERVAL_SECONDS': '5'}
target.parent.mkdir(parents=True,exist_ok=True)
fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    for name,value in values.items(): f.write(name+'='+value+'\n')
print('Secrets saved with mode 600:',target)
