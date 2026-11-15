import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.update(NOTIFY_ADMIN_KEY='a'*40, OPENWA_API_KEY='b'*40,
                  OPENWA_WEBHOOK_SECRET='c'*40, OPENWA_SESSION_ID='0390e1a0-8f42-4ad3-9400-4449cf8ff88d')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi.testclient import TestClient
import main as gateway


async def quiet_worker():
    await asyncio.Event().wait()


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        gateway.DB_PATH = self.tmp.name+'/test.sqlite'
        self.patch = patch.object(gateway, 'worker', quiet_worker)
        self.patch.start()
        self.http = TestClient(gateway.app).__enter__()
        self.admin = {'Authorization': 'Bearer '+'a'*40}
        self.owner = self.make_client('first')
        self.other = self.make_client('second')

    def tearDown(self):
        self.http.__exit__(None, None, None)
        self.patch.stop()
        self.tmp.cleanup()

    def make_client(self, name):
        r = self.http.post('/v1/admin/clients', headers=self.admin, json={'name': name, 'per_minute': 2})
        self.assertEqual(r.status_code, 201)
        return r.json()

    def send(self, key='order-1', body=None):
        return self.http.post('/v1/notifications', headers={'Authorization': 'Bearer '+self.owner['api_key'], 'Idempotency-Key': key},
                              json=body or {'to': '967775451608', 'text': 'test'})

    def test_idempotency_isolation_and_admission(self):
        first = self.send()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.send().json()['id'], first.json()['id'])
        self.assertEqual(self.send(body={'to':'967775451608','text':'changed'}).status_code,409)
        r = self.http.get('/v1/notifications/'+first.json()['id'], headers={'Authorization':'Bearer '+self.other['api_key']})
        self.assertEqual(r.status_code,404)
        self.assertEqual(self.send('order-2').status_code,202)
        self.assertEqual(self.send('order-3').status_code,429)
        self.assertEqual(self.send().status_code,202)

    def test_revocation_cancels_and_blocks(self):
        nid = self.send().json()['id']
        self.assertEqual(self.http.delete('/v1/admin/clients/'+self.owner['id'],headers=self.admin).status_code,200)
        self.assertEqual(self.send('new').status_code,401)
        with gateway.database() as db:
            self.assertEqual(db.execute('SELECT state FROM notifications WHERE id=?',(nid,)).fetchone()[0],'cancelled')

    def test_unknown_not_retried_and_restart_recovers(self):
        nid = self.send().json()['id']
        calls = []
        async def fake(method, suffix, payload=None):
            calls.append(method)
            if method == 'GET': return httpx.Response(200,json={'status':'ready'})
            raise httpx.ReadTimeout('ambiguous')
        with patch.object(gateway,'provider',fake):
            asyncio.run(gateway.dispatch_one())
            asyncio.run(gateway.dispatch_one())
        self.assertEqual(calls,['GET','POST'])
        with gateway.database() as db:
            self.assertEqual(db.execute('SELECT state FROM notifications WHERE id=?',(nid,)).fetchone()[0],'unknown')
            db.execute("UPDATE notifications SET state='sending',attempt_at=0 WHERE id=?",(nid,))
        asyncio.run(gateway.dispatch_one())
        with gateway.database() as db:
            self.assertEqual(db.execute('SELECT error_code FROM notifications WHERE id=?',(nid,)).fetchone()[0],'worker_interrupted')

    def test_early_receipt_signature_and_monotonicity(self):
        nid = self.send().json()['id']
        def ack(number, valid=True):
            raw=json.dumps({'sessionId':gateway.SESSION_ID,'event':'message.ack','data':{'messageId':'mid','ack':number}}).encode()
            signature='sha256='+hmac.new(gateway.WEBHOOK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
            return self.http.post('/v1/provider/webhook',content=raw,headers={'X-OpenWA-Signature':signature if valid else 'invalid'})
        self.assertEqual(ack(3,False).status_code,401)
        self.assertEqual(ack(3).status_code,200)
        async def fake(method,suffix,payload=None):
            return httpx.Response(200,json={'status':'ready'} if method=='GET' else {'messageId':'mid'})
        with patch.object(gateway,'provider',fake): asyncio.run(gateway.dispatch_one())
        ack(2); ack(-1); ack(3)
        with gateway.database() as db:
            self.assertEqual(db.execute('SELECT state FROM notifications WHERE id=?',(nid,)).fetchone()[0],'read')

    def test_validation_admin_and_payload_limit(self):
        self.assertEqual(self.http.get('/v1/admin/clients').status_code,401)
        self.assertEqual(self.send(body={'to':'0775451608','text':' '}).status_code,422)
        self.assertEqual(self.http.post('/v1/provider/webhook',content=b'x'*65537).status_code,413)

if __name__=='__main__': unittest.main()
