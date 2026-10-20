#!/usr/bin/env python3
"""Isolated real-worker/Redis/Prometheus drill; filesystem object-store adapter only.
Requires an already restored/upgraded disposable database. No production endpoints.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def verify_completed(database, report_path):
    """Resume final verification after the live phase, without rerunning jobs."""
    import hashlib
    report=json.loads(report_path.read_text())
    if report['database_container']!=database or report.get('stage')!='completed':
        raise ValueError('Only a completed disposable drill can be verified')
    identifiers=[str(uuid.UUID(r['id'])) for r in report['operations']]
    values=','.join("'"+x+"'" for x in identifiers)
    def sql(query):
        result=subprocess.run(['docker','exec','-i','-e','PGPASSWORD=drill',database,'psql','-X','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-U','supabase_admin','-d','restore','-tA'],input=query,text=True,capture_output=True,check=True)
        return result.stdout.strip()
    assert int(sql(f"SELECT count(*) FROM generation_operations WHERE id IN ({values}) AND status='completed'"))==2
    objects=Path(report['work_directory'])/'objects'
    records=json.loads(sql(f"SELECT json_agg(r) FROM (SELECT storage_path,byte_size,sha256 FROM generation_artifacts WHERE operation_id IN ({values}) AND status='verified') r"))
    for record in records:
        path=objects/record['storage_path']
        assert objects.resolve() in path.resolve().parents
        assert path.stat().st_size==record['byte_size'] and hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==record['sha256']
    report['invitations']=int(sql(f"SELECT count(*) FROM invitations WHERE generation_operation_id IN ({values})"))
    report['monthly_usage']=int(sql(f"SELECT COALESCE(sum(value),0)::bigint FROM usage_counters WHERE key='invitations_per_month' AND tenant_id IN (SELECT tenant_id FROM generation_operations WHERE id IN ({values}))"))
    report['verified_artifacts']=len(records)
    assert report['invitations']==report['monthly_usage']==report['verified_artifacts']==4
    report.update(result='passed',final_verification_resumed=True)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


def main():
    p=argparse.ArgumentParser();p.add_argument('--database-container',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--work-root',type=Path,required=True);p.add_argument('--resume-verification',action='store_true')
    a=p.parse_args()
    if not a.database_container.startswith('qentry-restore-drill-'):
        raise ValueError('Only a disposable restore container is permitted')
    if a.resume_verification:
        return verify_completed(a.database_container,a.output)
    a.work_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='runtime-',dir=a.work_root));root.chmod(0o700)
    prefix='qentry-fault-'+uuid.uuid4().hex[:8];network=prefix+'-net';names=[]
    repo=Path(__file__).resolve().parents[2]
    def command(args,**kw):
        result=subprocess.run(args,capture_output=True,text=True,**kw)
        if result.returncode:
            (root/'failure.log').write_text(result.stderr)
            raise RuntimeError('Isolated drill command failed; see private work directory')
        return result.stdout.strip()
    def start(kind,image,args=(),options=()):
        name=prefix+'-'+kind
        command(['docker','run','-d','--name',name,'--network',network,'--network-alias',kind,*options,image,*args]);names.append(name);return name
    def api_python(code):
        output=command(['docker','exec','-i',api,'python','-'],input=code)
        return json.loads(output.splitlines()[-1])
    def wait(check,timeout):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if check():return
            time.sleep(5)
        raise TimeoutError('Isolated drill condition did not converge')
    report={'production_modified':False,'database_container':a.database_container,'work_directory':str(root),'object_store':'isolated filesystem adapter; not Supabase HTTP','worker_limits':{'cpus':1,'memory_mib':768}}
    try:
        command(['docker','network','create','--internal',network])
        command(['docker','network','disconnect','none',a.database_container])
        command(['docker','network','connect','--alias','db',network,a.database_container])
        (root/'workspace').mkdir(mode=0o700);(root/'objects').mkdir(mode=0o700)
        bootstrap='''import os,hashlib
from pathlib import Path
from app.services import storage_service as storage
root=Path('/drill/objects')
def upload(path,content,mime):
 target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content);return path
storage.upload_file=upload
storage.upload_disk_file=lambda path,file,mime:upload(path,file.read_bytes(),mime)
storage.download_file=lambda path:(root/path).read_bytes()
def verify(path,size,digest):
 file=root/path
 assert file.stat().st_size==size and hashlib.file_digest(file.open('rb'),'sha256').hexdigest()==digest
storage.verify_disk_object=verify
storage.get_signed_url=lambda path,expires:'https://isolated.invalid/'+path
storage.ensure_bucket_exists=lambda:None
'''
        (root/'bootstrap.py').write_text(bootstrap)
        (root/'api.py').write_text("import bootstrap\nimport uvicorn\nuvicorn.run('app.main:app',host='0.0.0.0',port=9000,log_level='warning')\n")
        (root/'worker.py').write_text('''import bootstrap,os,time
from pathlib import Path
from app.services import generation_worker_service as worker
from app.worker import celery_app
original=worker.render.barcode
def barrier(*args):
 marker=Path('/drill/started')
 if not marker.exists():
  marker.write_text(str(os.getpid()))
  until=time.monotonic()+600
  while not Path('/drill/release').exists() and time.monotonic()<until:time.sleep(.1)
 return original(*args)
worker.render.barcode=barrier
celery_app.worker_main(['worker','--loglevel=WARNING','--concurrency=1','--pool=prefork','--without-gossip','--without-mingle','--without-heartbeat'])
''')
        env={'APP_ENV':'test','DATABASE_URL':'postgresql+asyncpg://supabase_admin:drill@db:5432/restore','DATABASE_APP_URL':'postgresql+asyncpg://qentry_app:drillapp@db:5432/restore','SUPABASE_URL':'http://127.0.0.1:55999','SUPABASE_ANON_KEY':'isolated-only','SUPABASE_SERVICE_ROLE_KEY':'isolated-only','SUPABASE_JWT_SECRET':'test-jwt-secret','INVITE_HMAC_SECRET':'test-hmac-secret','REDIS_URL':'redis://redis:6379/0','GENERATION_OPERATIONS_ENABLED':'true','GENERATION_WORKER_ENABLED':'true','GENERATION_WORKSPACE_DIR':'/var/lib/qentry/generation','METRICS_ACCESS_TOKEN':'metrics-test-token','OPENWA_ENABLED':'false','SMTP_HOST':'','SMTP_USER':'','SMTP_PASS':'','PYTHONPATH':'/drill:/app','RUN_EMBEDDED_SCHEDULER':'false'}
        (root/'app.env').write_text(''.join(k+'='+v+'\n' for k,v in env.items()));(root/'app.env').chmod(0o600)
        common=['--env-file',str(root/'app.env'),'-v',str(root)+':/drill','-v',str(root/'workspace')+':/var/lib/qentry/generation','--read-only','--tmpfs','/tmp']
        redis=start('redis','redis:7-alpine',['redis-server','--save','','--appendonly','no'])
        api=start('api','qentry-api:readiness-integration',['python','/drill/api.py'],common)
        def api_ready():
            try:return api_python("import urllib.request,json\nr=urllib.request.Request('http://127.0.0.1:9000/metrics',headers={'x-metrics-token':'metrics-test-token'})\nprint(json.dumps({'status':urllib.request.urlopen(r,timeout=5).status}))")['status']==200
            except (RuntimeError,ValueError):return False
        wait(api_ready,90)
        seed='''import asyncio,json
from uuid import uuid4
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.models.generation_operation import GenerationOperationCreate
from app.services.generation_snapshot_service import prepare_snapshot
from app.services.generation_operation_service import admit_operation
async def run():
 tid,uid,eid=uuid4(),uuid4(),uuid4()
 async with AsyncSessionLocal() as db:
  await db.execute(text("INSERT INTO auth.users(id,email,aud,role,email_confirmed_at,instance_id) VALUES(:id,:email,'authenticated','authenticated',now(),'00000000-0000-0000-0000-000000000000')"),{'id':uid,'email':str(uid)+'@example.invalid'})
  await db.execute(text("INSERT INTO profiles(id,full_name) VALUES(:id,'Synthetic staging actor') ON CONFLICT(id) DO NOTHING"),{'id':uid})
  await db.execute(text("INSERT INTO tenants(id,name,slug,status) VALUES(:id,'Synthetic fault drill',:slug,'active')"),{'id':tid,'slug':'drill-'+str(tid)})
  await db.execute(text("INSERT INTO memberships(tenant_id,user_id,role,status) VALUES(:tid,:uid,'owner','active')"),{'tid':tid,'uid':uid})
  await db.execute(text("INSERT INTO events(id,tenant_id,title,start_date,status) VALUES(:id,:tid,'Synthetic fault drill',now()+interval '7 days','draft')"),{'id':eid,'tid':tid})
  await db.execute(text("INSERT INTO feature_flags(tenant_id,flag_key,enabled) VALUES(:tid,'pdf_export',true)"),{'tid':tid})
  await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"),{'tid':str(tid)})
  body=GenerationOperationCreate(event_id=eid,mode='quick',source='count',count={'normal_count':2},output_formats=['pdf','zip'])
  snapshot=await prepare_snapshot(db,tid,body)
  op,_=await admit_operation(db,tid,uid,str(uuid4()),body,snapshot)
  await db.commit()
  print(json.dumps({'tenant':str(tid),'user':str(uid),'event':str(eid),'operation':str(op['id'])}))
asyncio.run(run())
'''
        first=api_python(seed)
        (root/'intents.json').write_text(json.dumps([first]))
        worker=start('worker','qentry-api:readiness-integration',['python','/drill/worker.py'],[*common,'--cpus','1','--memory','768m','--restart','unless-stopped','--health-cmd','celery -A app.worker inspect ping -d celery@$HOSTNAME --timeout 5 | grep -q pong','--health-interval','60s','--health-timeout','15s','--health-retries','3'])
        publisher="import asyncio,json\nfrom app.generation_dispatcher_runner import run_once\nprint(json.dumps(asyncio.run(run_once())))"
        api_python(publisher)
        wait(lambda:(root/'started').exists(),60)
        # Prometheus delivers to a private Alertmanager and local evidence receiver.
        (root/'receiver.py').write_text('''from http.server import BaseHTTPRequestHandler,HTTPServer
import json,time
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  path=Path('/drill/alerts.json');data=json.loads(path.read_text()) if path.exists() else []
  data.extend({'name':a['labels'].get('alertname'),'status':a['status'],'received_at':time.time()} for a in payload.get('alerts',[]))
  path.write_text(json.dumps(data));self.send_response(200);self.end_headers()
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
''')
        start('receiver','qentry-api:readiness-integration',['python','/drill/receiver.py'],['--no-healthcheck','-v',str(root)+':/drill'])
        (root/'alertmanager.yml').write_text("route:\n  receiver: local\n  group_wait: 0s\n  group_interval: 5s\n  repeat_interval: 1h\nreceivers:\n  - name: local\n    webhook_configs:\n      - url: http://receiver:8080/alerts\n        send_resolved: true\n")
        start('alertmanager','prom/alertmanager:v0.28.1',['--config.file=/config/alertmanager.yml','--storage.path=/tmp/alertmanager'],['--user','1000:1000','--tmpfs','/tmp','-v',str(root)+':/config:ro'])
        (root/'prometheus.yml').write_text("global:\n  scrape_interval: 5s\n  evaluation_interval: 5s\nrule_files: ['/rules/generation-alerts.yml']\nalerting:\n  alertmanagers:\n    - static_configs:\n        - targets: ['alertmanager:9093']\nscrape_configs:\n  - job_name: generation\n    metrics_path: /metrics\n    params: {format: [prometheus]}\n    http_headers:\n      x-metrics-token:\n        values: [metrics-test-token]\n    static_configs:\n      - targets: ['api:9000']\n")
        prom=start('prometheus','prom/prometheus:v3.2.1',['--config.file=/config/prometheus.yml','--storage.tsdb.path=/tmp/prometheus'],['--user','1000:1000','--tmpfs','/tmp','-v',str(root)+':/config:ro','-v',str(repo/'deploy/monitoring')+':/rules:ro'])
        def monitoring_ready():
            try:return api_python("import json,urllib.request;print(json.dumps({'ok':urllib.request.urlopen('http://prometheus:9090/-/ready',timeout=3).status==200}))")['ok']
            except RuntimeError:return False
        wait(monitoring_ready,60)
        command(['docker','pause',redis]);fault=time.monotonic()
        command(['docker','exec',worker,'python','-c','import os,signal;os.kill('+str(int((root/'started').read_text()))+',signal.SIGKILL)'])
        # Second unpublished synthetic intent drives the durable outbox alert.
        second=api_python(seed)
        (root/'intents.json').write_text(json.dumps([first,second]))
        def alerted():
            if not (root/'alerts.json').exists():return False
            names={x['name'] for x in json.loads((root/'alerts.json').read_text()) if x['status']=='firing'}
            return {'GenerationLeaseExpired','GenerationDispatchDelayed'}<=names
        wait(alerted,300)
        report['faulted_resources']=['Redis paused','prefork child killed','publisher held until alerts']
        report['lease_clock_advanced']=False
        report['alert_detection_seconds']=round(time.monotonic()-fault,2)
        report['alerts_received']=sorted({x['name'] for x in json.loads((root/'alerts.json').read_text()) if x['status']=='firing'})
        report['stage']='alerts_received';a.output.write_text(json.dumps(report,indent=2)+'\n')
        command(['docker','unpause',redis]);(root/'release').touch();recovery=time.monotonic()
        code="""import asyncio,json
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def run():
 async with AsyncSessionLocal() as db:
  rows=(await db.execute(text(\"SELECT id,status,cards_count,cards_done,files_done FROM generation_operations WHERE id IN ('%s','%s')\"))).mappings().all()
  print(json.dumps([dict(r,id=str(r['id'])) for r in rows]))
asyncio.run(run())
"""%(first['operation'],second['operation'])
        def completed():
            api_python(publisher)
            return all(r['status']=='completed' for r in api_python(code))
        wait(completed,150)
        report['recovery_seconds']=round(time.monotonic()-recovery,2)
        report['end_to_end_seconds']=round(time.monotonic()-fault,2)
        report['operations']=api_python(code)
        report['stage']='completed';a.output.write_text(json.dumps(report,indent=2)+'\n')
        for row in report['operations']:
            assert row['cards_count']==row['cards_done']==2 and row['files_done']==2
        verify="""import asyncio,json,hashlib
from pathlib import Path
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def run():
 async with AsyncSessionLocal() as db:
  p={'ids':['%s','%s']}
  rows=(await db.execute(text(\"SELECT storage_path AS path,byte_size,sha256 FROM generation_artifacts WHERE operation_id=ANY(CAST(:ids AS uuid[]))\"),p)).mappings().all()
  for r in rows:
   f=Path('/drill/objects')/r['path'];assert f.stat().st_size==r['byte_size'] and hashlib.file_digest(f.open('rb'),'sha256').hexdigest()==r['sha256']
  count=(await db.execute(text(\"SELECT count(*) FROM invitations WHERE generation_operation_id=ANY(CAST(:ids AS uuid[]))\"),p)).scalar()
  print(json.dumps({'verified_artifacts':len(rows),'invitations':count,'monthly_usage':int((await db.execute(text("SELECT sum(value) FROM usage_counters WHERE key='invitations_per_month' AND tenant_id IN (SELECT tenant_id FROM generation_operations WHERE id=ANY(CAST(:ids AS uuid[])))"),p)).scalar())}))
asyncio.run(run())
"""%(first['operation'],second['operation'])
        report.update(api_python(verify));assert report['invitations']==4 and report['verified_artifacts']==4 and report['monthly_usage']==4
        report['lease_clock_advanced']=False;report['result']='passed';report['work_directory']=str(root)
        a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally:
        if 'redis' in locals():subprocess.run(['docker','unpause',redis],capture_output=True)
        for name in reversed(names):
            logs=subprocess.run(['docker','logs',name],capture_output=True,text=True)
            (root/(name+'.log')).write_text(logs.stdout+logs.stderr)
            subprocess.run(['docker','rm','-f',name],capture_output=True)
        subprocess.run(['docker','network','disconnect',network,a.database_container],capture_output=True)
        subprocess.run(['docker','network','connect','none',a.database_container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
