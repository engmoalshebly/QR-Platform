#!/usr/bin/env python3
"""Local administrator helper; credentials never go into shell arguments."""
import argparse
import json
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
sub=parser.add_subparsers(dest='action',required=True)
p=sub.add_parser('create-client')
p.add_argument('name'); p.add_argument('--output',required=True)
p.add_argument('--daily-limit',type=int,default=1000)
p.add_argument('--per-minute',type=int,default=30)
sub.add_parser('connection')
sub.add_parser('clients')
args=parser.parse_args()
if args.action=='create-client':
    output=Path(args.output).expanduser()
    if output.exists(): raise SystemExit('Output already exists; refusing to overwrite credentials')
    method,path,body='POST','/v1/admin/clients',{'name':args.name,'daily_limit':args.daily_limit,'per_minute':args.per_minute}
else:
    method,path,body='GET','/v1/admin/'+args.action,None
source='''import json,os,sys,httpx
p=json.load(sys.stdin)
r=httpx.request(p['method'],'http://127.0.0.1:8080'+p['path'],json=p['body'],headers={'Authorization':'Bearer '+os.environ['NOTIFY_ADMIN_KEY']},trust_env=False)
r.raise_for_status()
print(r.text)
'''
r=subprocess.run(['docker','exec','-i','notification-gateway-notification-api-1','python','-c',source],input=json.dumps({'method':method,'path':path,'body':body}),text=True,capture_output=True)
if r.returncode: raise SystemExit('Administrator request failed; verify service health')
if args.action=='create-client':
    payload=json.loads(r.stdout)
    payload['base_url']='https://notify.prideidea.com'
    output.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump(payload,f,ensure_ascii=False,indent=2);f.write('\n')
    print('Client credentials saved with mode 600:',output)
else:
    print(r.stdout.strip())
