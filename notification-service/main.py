"""Standalone notification API. One dispatcher, durable SQLite WAL, no send retries."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

DB_PATH = os.getenv('NOTIFY_DB', '/data/notifications.sqlite')
ADMIN_KEY = os.getenv('NOTIFY_ADMIN_KEY', '')
PROVIDER_URL = os.getenv('OPENWA_BASE_URL', 'http://openwa-api:2785').rstrip('/')
PROVIDER_KEY = os.getenv('OPENWA_API_KEY', '')
SESSION_ID = os.getenv('OPENWA_SESSION_ID', '')
WEBHOOK_SECRET = os.getenv('OPENWA_WEBHOOK_SECRET', '')
DISPATCH_INTERVAL = max(5, int(os.getenv('NOTIFY_INTERVAL_SECONDS', '5')))
log = logging.getLogger('notifications')
bearer = HTTPBearer(auto_error=False)


@contextmanager
def database():
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    try:
        yield db
    finally:
        if db.in_transaction:
            db.rollback()
        db.close()


def initialize():
    with database() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS clients (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
          active INTEGER NOT NULL DEFAULT 1, daily_limit INTEGER NOT NULL,
          per_minute INTEGER NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications (
          id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
          idem TEXT NOT NULL, digest TEXT NOT NULL, recipient TEXT NOT NULL,
          body TEXT NOT NULL, state TEXT NOT NULL, error_code TEXT, provider_id TEXT,
          created_at REAL NOT NULL, updated_at REAL NOT NULL, attempt_at REAL,
          UNIQUE(client_id,idem));
        CREATE INDEX IF NOT EXISTS notifications_queue ON notifications(state,created_at);
        CREATE INDEX IF NOT EXISTS notifications_client ON notifications(client_id,created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS notifications_provider ON notifications(provider_id);
        CREATE TABLE IF NOT EXISTS receipts (
          provider_id TEXT NOT NULL, ack INTEGER NOT NULL, created_at REAL NOT NULL,
          PRIMARY KEY(provider_id,ack));
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, action TEXT NOT NULL, target TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1),
          heartbeat REAL NOT NULL, next_send REAL NOT NULL);
        INSERT OR IGNORE INTO runtime VALUES(1,0,0);
        ''')


def digest_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def audit(db, action, target, note=''):
    db.execute('INSERT INTO audit(action,target,note,created_at) VALUES(?,?,?,?)',
               (action, target, note, time.time()))


def admin(auth: HTTPAuthorizationCredentials = Depends(bearer)):
    if not auth or not secrets.compare_digest(auth.credentials, ADMIN_KEY):
        raise HTTPException(401, 'Invalid administrator key')


def client(auth: HTTPAuthorizationCredentials = Depends(bearer)):
    if not auth:
        raise HTTPException(401, 'API key required')
    with database() as db:
        row = db.execute('SELECT * FROM clients WHERE key_hash=? AND active=1',
                         (digest_key(auth.credentials),)).fetchone()
    if not row:
        raise HTTPException(401, 'Invalid or revoked API key')
    return dict(row)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ClientCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    daily_limit: int = Field(default=1000, ge=1, le=100000)
    per_minute: int = Field(default=30, ge=1, le=1000)


class Send(Input):
    channel: Literal['whatsapp'] = 'whatsapp'
    to: str = Field(min_length=8, max_length=30)
    text: str = Field(min_length=1, max_length=4096)

    @field_validator('to')
    @classmethod
    def phone(cls, value):
        value = re.sub(r'[\s()\-]', '', value)
        if value.startswith('00'):
            value = value[2:]
        value = value.removeprefix('+')
        if not re.fullmatch(r'[1-9][0-9]{7,14}', value):
            raise ValueError('Use international digits including country code')
        return value

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Text must not be blank')
        return value


class Review(Input):
    outcome: Literal['sent', 'not_sent']
    evidence: str = Field(min_length=20, max_length=500)


def present(row):
    return {k: row[k] for k in ('id', 'state', 'error_code', 'created_at', 'updated_at')}


async def provider(method, suffix, payload=None):
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as http:
        return await http.request(method, PROVIDER_URL + '/api/sessions/' + SESSION_ID + suffix,
                                  headers={'X-API-Key': PROVIDER_KEY}, json=payload)


def apply_receipts(db, message_id):
    a = db.execute('SELECT max(ack),min(ack) FROM receipts WHERE provider_id=?', (message_id,)).fetchone()
    if a[0] is None:
        return
    state = 'read' if a[0] >= 3 else 'delivered' if a[0] >= 2 else 'failed' if a[1] == -1 else None
    if state:
        row = db.execute('SELECT state,error_code FROM notifications WHERE provider_id=?', (message_id,)).fetchone()
        if row and (row['state'] in ('sent', 'unknown') or
                    (row['state'] == 'delivered' and state == 'read') or
                    (row['state'] == 'failed' and row['error_code'] == 'whatsapp_rejected' and state in ('delivered', 'read'))):
            db.execute('UPDATE notifications SET state=?,error_code=?,updated_at=? WHERE provider_id=?',
                       (state, 'whatsapp_rejected' if state == 'failed' else None, time.time(), message_id))


async def dispatch_one():
    now = time.time()
    with database() as db:
        db.execute('UPDATE runtime SET heartbeat=? WHERE id=1', (now,))
        # A stopped process may have sent before losing its response. Never retry it.
        db.execute("UPDATE notifications SET state='unknown',error_code='worker_interrupted',updated_at=? WHERE state='sending' AND attempt_at<?", (now, now-120))
        due = db.execute('SELECT next_send FROM runtime WHERE id=1').fetchone()[0]
        row = db.execute("SELECT * FROM notifications WHERE state IN ('queued','waiting_connection') ORDER BY created_at,id LIMIT 1").fetchone()
        if not row or due > now:
            return
        item = dict(row)
    try:
        response = await provider('GET', '')
        ready = response.status_code == 200 and response.json().get('status') == 'ready'
    except (httpx.HTTPError, ValueError, AttributeError):
        ready = False
    if not ready:
        with database() as db:
            db.execute("UPDATE notifications SET state='waiting_connection',error_code='connection_unavailable',updated_at=? WHERE id=? AND state IN ('queued','waiting_connection')", (now, item['id']))
            db.execute('UPDATE runtime SET next_send=? WHERE id=1', (now+30,))
        return
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        active = db.execute('SELECT active FROM clients WHERE id=?', (item['client_id'],)).fetchone()
        if not active or not active[0]:
            db.execute("UPDATE notifications SET state='cancelled',error_code='key_revoked',updated_at=? WHERE id=? AND state IN ('queued','waiting_connection')", (now, item['id']))
            db.commit()
            return
        claimed = db.execute("UPDATE notifications SET state='sending',attempt_at=?,updated_at=?,error_code=NULL WHERE id=? AND state IN ('queued','waiting_connection')", (now, now, item['id'])).rowcount
        db.execute('UPDATE runtime SET next_send=? WHERE id=1', (now+DISPATCH_INTERVAL,))
        db.commit()  # Durable before external side effect.
    if not claimed:
        return
    state, error, mid = 'unknown', 'send_result_unknown', None
    try:
        response = await provider('POST', '/messages/send-text', {'chatId': item['recipient']+'@c.us', 'text': item['body']})
        if response.status_code in (401, 403, 404, 422, 429):
            state, error = 'failed', 'provider_rejected'
        elif response.is_success:
            candidate = response.json().get('messageId')
            if isinstance(candidate, str) and 0 < len(candidate) <= 512:
                mid, state, error = candidate, 'sent', None
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE notifications SET state=?,error_code=?,provider_id=?,updated_at=? WHERE id=?',
                   (state, error, mid, time.time(), item['id']))
        if mid:
            apply_receipts(db, mid)
        db.commit()


async def worker():
    while True:
        try:
            await dispatch_one()
        except Exception:
            log.error('Dispatch failed; persisted messages retained')
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    if any(len(x) < 32 for x in (ADMIN_KEY, PROVIDER_KEY, WEBHOOK_SECRET)):
        raise RuntimeError('Administrator, provider and webhook secrets must be at least 32 characters')
    UUID(SESSION_ID)
    initialize()
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title='Notification Gateway', version='1.0.0', lifespan=lifespan,
              description='Independent WhatsApp notification API. Times are Unix UTC seconds. Persist the idempotency key before sending.')


@app.middleware('http')
async def limits(request: Request, call_next):
    # Stream limit also covers bodies without Content-Length.
    from starlette.responses import JSONResponse
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 65536:
            return JSONResponse({'detail': 'Payload too large'}, status_code=413)
    request._body = bytes(data)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/health/live', include_in_schema=False)
def live():
    return {'status': 'ok'}


@app.get('/health/ready', include_in_schema=False)
def readiness():
    with database() as db:
        heartbeat = db.execute('SELECT heartbeat FROM runtime WHERE id=1').fetchone()[0]
    if time.time()-heartbeat > 90:
        raise HTTPException(503, 'Dispatcher heartbeat stale')
    return {'status': 'ready'}


@app.post('/v1/admin/clients', dependencies=[Depends(admin)], status_code=201)
def create_client(body: ClientCreate):
    key, cid = 'ntf_'+secrets.token_urlsafe(36), str(uuid4())
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO clients VALUES(?,?,?,?,?,?,?)',
                   (cid, body.name, digest_key(key), 1, body.daily_limit, body.per_minute, time.time()))
        audit(db, 'client.created', cid)
        db.commit()
    return {'id': cid, 'name': body.name, 'api_key': key, 'daily_limit': body.daily_limit, 'per_minute': body.per_minute}


@app.get('/v1/admin/clients', dependencies=[Depends(admin)])
def clients():
    with database() as db:
        return [dict(r) for r in db.execute('SELECT id,name,active,daily_limit,per_minute,created_at FROM clients ORDER BY created_at')]


@app.post('/v1/admin/clients/{client_id}/rotate', dependencies=[Depends(admin)])
def rotate(client_id: UUID):
    key = 'ntf_'+secrets.token_urlsafe(36)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        changed = db.execute('UPDATE clients SET key_hash=? WHERE id=? AND active=1', (digest_key(key), str(client_id))).rowcount
        if not changed:
            raise HTTPException(404, 'Active client not found')
        audit(db, 'client.key_rotated', str(client_id))
        db.commit()
    return {'api_key': key}


@app.delete('/v1/admin/clients/{client_id}', dependencies=[Depends(admin)])
def revoke(client_id: UUID):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('UPDATE clients SET active=0 WHERE id=?', (str(client_id),)).rowcount:
            raise HTTPException(404, 'Client not found')
        db.execute("UPDATE notifications SET state='cancelled',error_code='key_revoked',updated_at=? WHERE client_id=? AND state IN ('queued','waiting_connection')", (time.time(), str(client_id)))
        audit(db, 'client.revoked', str(client_id))
        db.commit()
    return {'revoked': True}


@app.get('/v1/admin/connection', dependencies=[Depends(admin)])
async def connection():
    try:
        r = await provider('GET', '')
        r.raise_for_status()
        data = r.json()
        return {'status': data.get('status'), 'phone': data.get('phone')}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Provider unavailable')


@app.post('/v1/notifications', status_code=202)
def enqueue(body: Send, idempotency_key: str = Header(min_length=1, max_length=128), owner=Depends(client)):
    if not re.fullmatch(r'[A-Za-z0-9_.:\-]{1,128}', idempotency_key):
        raise HTTPException(422, 'Invalid Idempotency-Key')
    digest = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    now, nid = time.time(), str(uuid4())
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        # Recheck revocation under the same lock as admission.
        if not db.execute('SELECT 1 FROM clients WHERE id=? AND active=1', (owner['id'],)).fetchone():
            raise HTTPException(401, 'API key revoked')
        old = db.execute('SELECT * FROM notifications WHERE client_id=? AND idem=?', (owner['id'], idempotency_key)).fetchone()
        if old:
            if old['digest'] != digest:
                raise HTTPException(409, 'Idempotency key already used with different content')
            return present(old)
        daily = db.execute('SELECT count(*) FROM notifications WHERE client_id=? AND created_at>=?', (owner['id'], now//86400*86400)).fetchone()[0]
        minute = db.execute('SELECT count(*) FROM notifications WHERE client_id=? AND created_at>?', (owner['id'], now-60)).fetchone()[0]
        if daily >= owner['daily_limit'] or minute >= owner['per_minute']:
            raise HTTPException(429, 'Client admission limit exceeded', headers={'Retry-After': '60'})
        db.execute('INSERT INTO notifications(id,client_id,idem,digest,recipient,body,state,created_at,updated_at) VALUES(?,?,?,?,?,?,\'queued\',?,?)',
                   (nid, owner['id'], idempotency_key, digest, body.to, body.text, now, now))
        row = db.execute('SELECT * FROM notifications WHERE id=?', (nid,)).fetchone()
        db.commit()
        return present(row)


@app.get('/v1/notifications')
def listing(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), owner=Depends(client)):
    with database() as db:
        rows = db.execute('SELECT * FROM notifications WHERE client_id=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (owner['id'], limit, offset)).fetchall()
        return {'items': [present(r) for r in rows], 'limit': limit, 'offset': offset}


@app.get('/v1/notifications/{notification_id}')
def get_one(notification_id: UUID, owner=Depends(client)):
    with database() as db:
        row = db.execute('SELECT * FROM notifications WHERE id=? AND client_id=?', (str(notification_id), owner['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Notification not found')
        return present(row)


@app.post('/v1/notifications/{notification_id}/cancel')
def cancel(notification_id: UUID, owner=Depends(client)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM notifications WHERE id=? AND client_id=?', (str(notification_id), owner['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Notification not found')
        if row['state'] not in ('queued', 'waiting_connection'):
            raise HTTPException(409, 'Notification already started or completed')
        db.execute("UPDATE notifications SET state='cancelled',error_code=NULL,updated_at=? WHERE id=?", (time.time(), str(notification_id)))
        db.commit()
    return {'cancelled': True}


@app.post('/v1/admin/notifications/{notification_id}/review', dependencies=[Depends(admin)])
def review(notification_id: UUID, body: Review):
    if len(body.evidence.strip()) < 20:
        raise HTTPException(422, 'Evidence is required')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        changed = db.execute("UPDATE notifications SET state=?,error_code='manually_reviewed',updated_at=? WHERE id=? AND state='unknown'", ('sent' if body.outcome == 'sent' else 'failed', time.time(), str(notification_id))).rowcount
        if not changed:
            raise HTTPException(409, 'Only unknown results can be reviewed')
        audit(db, 'notification.reviewed', str(notification_id), body.outcome+': '+body.evidence.strip())
        db.commit()
    return {'reviewed': True}


@app.post('/v1/provider/webhook', include_in_schema=False)
async def webhook(request: Request):
    raw = await request.body()
    expected = 'sha256='+hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(expected, request.headers.get('X-OpenWA-Signature', '')):
        raise HTTPException(401, 'Invalid signature')
    try:
        event = json.loads(raw)
        if not isinstance(event, dict) or event.get('sessionId') != SESSION_ID:
            raise ValueError()
        if event.get('event') != 'message.ack':
            return {'accepted': True}
        data = event['data']
        mid, ack = data['messageId'], data['ack']
        if not isinstance(mid, str) or not 0 < len(mid) <= 512 or type(ack) is not int or ack not in (-1,0,1,2,3,4):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, 'Invalid event')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?)', (mid, ack, time.time()))
        apply_receipts(db, mid)
        db.commit()
    return {'accepted': True}


@app.get('/v1/admin/notifications', dependencies=[Depends(admin)])
def admin_notifications(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                        state: Literal['queued','waiting_connection','sending','sent','delivered','read','failed','unknown','cancelled'] | None = None):
    with database() as db:
        rows = db.execute('SELECT * FROM notifications WHERE (? IS NULL OR state=?) ORDER BY created_at DESC,id LIMIT ? OFFSET ?',
                          (state, state, limit, offset)).fetchall()
        return {'items': [{**present(r), 'client_id': r['client_id']} for r in rows], 'limit': limit, 'offset': offset}


@app.get('/v1/admin/audit', dependencies=[Depends(admin)])
def audit_listing(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with database() as db:
        return {'items': [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset))]}
