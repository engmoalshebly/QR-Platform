#!/usr/bin/env python3
"""Register the dedicated HMAC webhook over the private Docker network."""
import json
import os
from pathlib import Path
import subprocess

path=Path(os.getenv('NOTIFY_ENV_FILE',str(Path.home()/'.qentry/notifications.env')))
values=dict(line.strip().split('=',1) for line in path.read_text().splitlines() if line.strip() and not line.startswith('#'))
# The private network alias resolves only inside Docker; a valid DNS name is
# required by the provider's URL validator. No public DNS is needed for ACKs.
payload={'sid':values['OPENWA_SESSION_ID'],'key':values['OPENWA_API_KEY'],
         'secret':values['OPENWA_WEBHOOK_SECRET'],'url':'http://notification-api.internal:8080/v1/provider/webhook'}
source='''import asyncio,json,sys
from app.services import whatsapp_service as svc
async def main():
 p=json.load(sys.stdin)
 base='sessions/'+p['sid']+'/webhooks'
 hooks=await svc.provider('GET',base,key=p['key'])
 old=next((x for x in hooks if x.get('url')==p['url']),None)
 result=await svc.provider('PUT' if old else 'POST',base+('/'+old['id'] if old else ''),key=p['key'],payload={'url':p['url'],'events':['message.ack'],'secret':p['secret'],'retryCount':5,**({'active':True} if old else {})})
 print('Dedicated provider webhook registered')
asyncio.run(main())
'''
r=subprocess.run(['docker','exec','-i',os.getenv('QENTRY_API_CONTAINER','qentry-prod-api-1'),'python','-c',source],input=json.dumps(payload),text=True,capture_output=True)
if r.returncode: raise SystemExit('Webhook registration failed; inspect provider availability without printing secrets')
print(r.stdout.strip())
