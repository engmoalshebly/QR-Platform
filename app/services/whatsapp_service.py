"""OpenWA transport and durable delivery policy. No browser receives credentials."""
import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text, bindparam

from app.config import get_settings
from app.services.feature_service import require_feature, check_feature_flag, enforce_monthly_limit
from app.services.permission_service import has_permission
from app.services.secret_box import _fernet_from_secret
from app.services import whatsapp_message_service as messages


def configured():
    s = get_settings()
    u = urlparse(s.openwa_base_url)
    return bool(s.openwa_enabled and s.openwa_master_key and len(s.whatsapp_encryption_key) >= 32
                and u.scheme in ('http', 'https') and u.hostname and u.username is None and u.password is None
                and not u.query and not u.fragment)


def crypt(value: str, *, decrypt=False):
    secret = get_settings().whatsapp_encryption_key
    if len(secret) < 32:
        raise HTTPException(503, 'مفتاح حماية اتصال WhatsApp غير مهيأ.')
    box = _fernet_from_secret(secret)
    return (box.decrypt(value.encode()).decode() if decrypt else box.encrypt(value.encode()).decode())


class ProviderError(Exception):
    def __init__(self, status=0):
        self.status = status


async def provider(method, path, *, key=None, payload=None):
    if not configured():
        raise HTTPException(503, 'خدمة WhatsApp غير مهيأة لدى المنصة.')
    s = get_settings()
    # No redirects, retry, or user-supplied host. A POST timeout is ambiguous.
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, s.openwa_base_url.rstrip('/') + '/api/' + path,
                                            headers={'X-API-Key': key or s.openwa_master_key}, json=payload)
    except httpx.HTTPError as exc:
        raise ProviderError() from exc
    if response.status_code >= 300:
        raise ProviderError(response.status_code)
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError() from exc


def normalize_phone(value):
    # Do not infer a country from a local number.
    value = re.sub(r'[\s()\-]', '', str(value or ''))
    if value.startswith('00'):
        value = '+' + value[2:]
    if value.startswith('+'):
        value = value[1:]
    if not re.fullmatch(r'[1-9][0-9]{7,14}', value):
        raise ValueError('رقم دولي غير صالح')
    return value


def eligibility(inv):
    now = datetime.now(timezone.utc)
    if inv.get('deleted_at') or inv.get('event_status') in ('cancelled', 'completed'):
        return None, 'event_unavailable'
    if inv.get('status') in ('revoked', 'expired', 'declined') or inv.get('rsvp_status') == 'declined':
        return None, 'invitation_unavailable'
    if inv.get('expires_at') and inv['expires_at'] <= now:
        return None, 'invitation_expired'
    if inv.get('is_registration'):
        return None, 'registration_only'
    metadata = inv.get('metadata') or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    required = str(metadata.get('require_rsvp')).lower() == 'true' or ('require_rsvp' not in metadata and inv.get('rsvp_status') in ('pending','maybe'))
    return ('rsvp' if required and inv.get('rsvp_status') != 'accepted' else 'ticket'), None


async def connection(db, tenant_id, *, lock=False):
    result = await db.execute(text('SELECT * FROM whatsapp_connections WHERE tenant_id=:tid' +
                                   (' FOR UPDATE' if lock else '')), {'tid': str(tenant_id)})
    return result.mappings().first()


async def queue_deliveries(db, tenant_id, user_id, ids, request_id, *, allow_resend=False, message_versions=None):
    if not configured():
        raise HTTPException(503, 'خدمة WhatsApp غير مهيأة لدى المنصة.')
    await require_feature(db, tenant_id, 'whatsapp_delivery')
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                     {'key': 'whatsapp:' + str(tenant_id)})
    request_payload = {'ids': sorted(set(map(str, ids))), 'resend': allow_resend}
    if message_versions is not None:
        request_payload['message_versions'] = {str(k):v for k,v in message_versions.items()}
    digest = hashlib.sha256(json.dumps(request_payload, sort_keys=True).encode()).hexdigest()
    old = (await db.execute(text('SELECT payload_hash,response FROM whatsapp_delivery_requests WHERE tenant_id=:tid AND client_request_id=:cid'),
                            {'tid': str(tenant_id), 'cid': str(request_id)})).mappings().first()
    if old:
        if old['payload_hash'] != digest:
            raise HTTPException(409, 'معرّف الطلب مستخدم لبيانات مختلفة.')
        return old['response']
    conn = await connection(db, tenant_id)
    if not conn or not conn['enabled'] or not conn['api_key_ciphertext']:
        raise HTTPException(409, 'اربط رقم WhatsApp وفعّل الاتصال أولاً من الإعدادات.')
    expected_versions = {str(k):v for k,v in (message_versions or {}).items()}
    event_ids=(await db.execute(text('SELECT DISTINCT event_id FROM invitations WHERE tenant_id=:tid AND id IN :ids').bindparams(bindparam('ids',expanding=True)),
                               {'tid':str(tenant_id),'ids':list(map(str,ids))})).scalars().all()
    templates={};events={}
    for eid in sorted(event_ids,key=str):
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'whatsapp-template:'+str(tenant_id)+':'+str(eid)})
        templates[str(eid)]=await messages.config(db,tenant_id,eid)
        events[str(eid)]=(await db.execute(text('SELECT * FROM events WHERE tenant_id=:tid AND id=:eid'),{'tid':str(tenant_id),'eid':str(eid)})).mappings().one()
        if message_versions is not None and expected_versions.get(str(eid)) != templates[str(eid)]['version']:
            raise HTTPException(409,{'code':'WHATSAPP_MESSAGE_CHANGED','message':'تغيرت الرسالة بعد المعاينة. افتح نافذة الإرسال مجدداً لمراجعة النسخة الحالية.'})
    request_db_id = str(uuid4())
    result = {'request_id': request_db_id, 'queued': 0, 'skipped': 0, 'items': []}
    # Row created before deliveries for the FK; final response is saved in this transaction.
    await db.execute(text('INSERT INTO whatsapp_delivery_requests(id,tenant_id,client_request_id,payload_hash,response) VALUES(:id,:tid,:cid,:hash,\'{}\')'),
                     {'id': request_db_id, 'tid': str(tenant_id), 'cid': str(request_id), 'hash': digest})
    for inv_id in dict.fromkeys(map(str, ids)):
        inv = (await db.execute(text('''SELECT i.*,e.status event_status,e.deleted_at FROM invitations i
            JOIN events e ON e.id=i.event_id WHERE i.id=:id AND i.tenant_id=:tid AND e.tenant_id=:tid'''),
                                {'id': inv_id, 'tid': str(tenant_id)})).mappings().first()
        purpose, reason = eligibility(inv) if inv else (None, 'not_found')
        phone = ''
        if not reason:
            try:
                phone = normalize_phone(inv.get('guest_whatsapp') or inv.get('guest_phone'))
            except ValueError:
                reason = 'invalid_phone'
        if not reason:
            previous = (await db.execute(text('''SELECT state,purpose FROM whatsapp_deliveries WHERE tenant_id=:tid AND invitation_id=:id
                ORDER BY created_at DESC LIMIT 1'''), {'tid': str(tenant_id), 'id': inv_id})).mappings().first()
            if previous and previous['state'] in ('queued','waiting_connection','sending','unknown'):
                reason = 'already_pending' if previous['state'] != 'unknown' else 'requires_review'
            elif previous and previous['state'] in ('sent','delivered','read') and previous['purpose'] == purpose and not allow_resend:
                reason = 'already_sent'
        message=None;cfg=None
        if not reason:
            cfg=templates[str(inv['event_id'])]
            link=get_settings().app_url.rstrip('/')+'/i/'+quote(str(inv['token']),safe='')
            message=messages.render(cfg[purpose+'_text'],inv,events[str(inv['event_id'])],link)
            if messages.message_length(message)>(1024 if cfg['image_id'] else 4096): reason='message_too_long'
        if reason:
            result['skipped'] += 1
            result['items'].append({'invitation_id': inv_id, 'reason': reason})
            continue
        delivery_id = str(uuid4())
        await db.execute(text('''INSERT INTO whatsapp_deliveries(id,tenant_id,event_id,invitation_id,request_id,created_by,purpose,recipient,message_text,message_image_id,message_version)
            VALUES(:id,:tid,:eid,:iid,:rid,:uid,:purpose,:phone,:message,:image,:version)'''),
            {'id': delivery_id, 'tid': str(tenant_id), 'eid': str(inv['event_id']), 'iid': inv_id,
             'rid': request_db_id, 'uid': str(user_id), 'purpose': purpose, 'phone': phone,'message':message,'image':str(cfg['image_id']) if cfg['image_id'] else None,'version':cfg['version']})
        result['queued'] += 1
        result['items'].append({'invitation_id': inv_id, 'delivery_id': delivery_id, 'state': 'queued', 'purpose': purpose})
    await db.execute(text('UPDATE whatsapp_delivery_requests SET response=CAST(:value AS jsonb) WHERE id=:id AND tenant_id=:tid'),
                     {'value': json.dumps(result), 'id': request_db_id, 'tid': str(tenant_id)})
    return result


async def update_state(db, delivery, state, error=None, message_id=None):
    await db.execute(text('''UPDATE whatsapp_deliveries SET state=:state,error_code=:error,
        wa_message_id=COALESCE(:mid,wa_message_id),updated_at=now() WHERE id=:id AND tenant_id=:tid'''),
        {'id': str(delivery['id']), 'tid': str(delivery['tenant_id']), 'state': state, 'error': error, 'mid': message_id})


async def dispatch_one(db):
    """Privileged runner only. Row locks serialize workers; no retries after send starts."""
    await db.execute(text("UPDATE whatsapp_deliveries SET state='unknown',error_code='worker_interrupted',updated_at=now() WHERE state='sending' AND attempt_started_at < now()-interval '5 minutes'"))
    await db.commit()
    # Reconcile persisted early receipts, including concurrent commit races.
    await db.execute(text("""UPDATE whatsapp_deliveries d SET
        state=CASE WHEN a.ack>=3 THEN 'read' WHEN a.ack>=2 THEN 'delivered' ELSE 'failed' END,
        error_code=CASE WHEN a.ack<2 AND a.failed THEN 'whatsapp_rejected'
                       WHEN d.error_code='whatsapp_rejected' THEN NULL ELSE d.error_code END,updated_at=now()
        FROM (SELECT tenant_id,wa_message_id,MAX(ack) ack,BOOL_OR(ack=-1) failed
              FROM whatsapp_webhook_receipts GROUP BY tenant_id,wa_message_id) a
        WHERE d.tenant_id=a.tenant_id AND d.wa_message_id=a.wa_message_id
        AND ((d.state='sent' AND (a.ack>=2 OR a.failed)) OR (d.state='delivered' AND a.ack>=3)
             OR (d.state='failed' AND d.error_code='whatsapp_rejected' AND a.ack>=2))"""))
    await db.commit()
    # Connection-before-delivery locking matches disable/review operations and
    # avoids a cycle between a connection lock and an update of queued rows.
    conn = (await db.execute(text("""SELECT c.* FROM whatsapp_connections c
        WHERE c.next_dispatch_at<=now() AND EXISTS(SELECT 1 FROM whatsapp_deliveries d
            WHERE d.tenant_id=c.tenant_id AND d.state IN ('queued','waiting_connection'))
        ORDER BY c.next_dispatch_at,c.tenant_id FOR UPDATE OF c SKIP LOCKED LIMIT 1"""))).mappings().first()
    if not conn:
        await db.rollback()
        return False
    tenant_id = conn['tenant_id']
    delivery = (await db.execute(text("""SELECT * FROM whatsapp_deliveries
        WHERE tenant_id=:tid AND state IN ('queued','waiting_connection')
        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""), {'tid':str(tenant_id)})).mappings().first()
    if not delivery:
        await db.rollback()
        return False
    if not conn['enabled'] or not delivery['created_by'] or not await has_permission(db, tenant_id, delivery['created_by'], 'whatsapp.send') or not await has_permission(db, tenant_id, delivery['created_by'], 'invitations.send') or not await check_feature_flag(db, tenant_id, 'whatsapp_delivery'):
        await update_state(db, delivery, 'cancelled', 'authorization_lost')
        await db.commit()
        return True
    from app.services.subscription_state import compute_subscription_state
    if get_settings().expired_read_only and (await compute_subscription_state(db, tenant_id)).expired:
        await update_state(db, delivery, 'cancelled', 'subscription_expired')
        await db.commit()
        return True
    # Every job rechecks current invitation state and recipient before sending.
    inv = (await db.execute(text('''SELECT i.*,e.status event_status,e.deleted_at,COALESCE(e.title,e.title_ar,'الفعالية') event_title
        FROM invitations i JOIN events e ON e.id=i.event_id WHERE i.id=:id AND i.tenant_id=:tid AND e.tenant_id=:tid'''),
        {'id': str(delivery['invitation_id']), 'tid': str(tenant_id)})).mappings().first()
    purpose, reason = eligibility(inv) if inv else (None, 'not_found')
    try:
        recipient_changed = not inv or normalize_phone(inv.get('guest_whatsapp') or inv.get('guest_phone')) != delivery['recipient']
    except ValueError:
        recipient_changed = True
    if reason or purpose != delivery['purpose'] or recipient_changed:
        await update_state(db, delivery, 'cancelled', reason or 'invitation_changed')
        await db.commit()
        return True
    key = crypt(conn['api_key_ciphertext'], decrypt=True)
    try:
        session = await provider('GET', f"sessions/{conn['session_id']}", key=key)
    except ProviderError:
        session = {'status': 'unavailable'}
    if session.get('status') != 'ready':
        await update_state(db, delivery, 'waiting_connection', 'connection_unavailable')
        await db.execute(text("UPDATE whatsapp_connections SET status=:status,next_dispatch_at=now()+interval '30 seconds',last_checked_at=now() WHERE tenant_id=:tid"),
                         {'tid': str(tenant_id), 'status': session.get('status', 'unavailable')})
        await db.commit()
        return True
    media=None
    if delivery['message_image_id']:
        try:
            media=await messages.image(db,tenant_id,delivery['event_id'],delivery['message_image_id'])
        except HTTPException:
            await update_state(db,delivery,'failed','message_image_unavailable')
            await db.commit()
            return True
    # Feature/plan and quota are checked just before the attempt, not on every poll.
    try:
        await require_feature(db, tenant_id, 'whatsapp_delivery')
        await enforce_monthly_limit(db, tenant_id, 'messages_per_month', 'الرسائل الشهرية', count=1)
    except HTTPException:
        await update_state(db, delivery, 'failed', 'entitlement_or_quota')
        await db.commit()
        return True
    await db.execute(text("UPDATE whatsapp_deliveries SET state='sending',attempt_started_at=now(),error_code=NULL,updated_at=now() WHERE id=:id AND tenant_id=:tid"),
                     {'id': str(delivery['id']), 'tid': str(tenant_id)})
    await db.execute(text("UPDATE whatsapp_connections SET status='ready',last_checked_at=now(),next_dispatch_at=now()+(:seconds * interval '1 second') WHERE tenant_id=:tid"),
                     {'tid': str(tenant_id), 'seconds': max(5, get_settings().whatsapp_dispatch_interval_seconds)})
    await db.commit()  # Durable boundary before any WhatsApp side effect.
    link = get_settings().app_url.rstrip('/') + '/i/' + quote(str(inv['token']), safe='')
    action='يرجى تأكيد حضورك من الرابط:' if purpose=='rsvp' else 'دعوتك ورمز الدخول متاحان من الرابط:'
    legacy_message=f"مرحباً {str(inv.get('guest_name') or '')[:150]}،\nندعوك إلى {str(inv['event_title'])[:200]}.\n{action}\n{link}"
    message=delivery['message_text'] or legacy_message
    try:
        payload={'chatId':delivery['recipient']+'@c.us'}
        if media:
            payload.update({'base64':base64.b64encode(media['content']).decode(),'mimetype':media['mime_type'],'filename':'invitation.jpg','caption':message})
        else: payload['text']=message
        response=await provider('POST',f"sessions/{conn['session_id']}/messages/"+('send-image' if media else 'send-text'),key=key,payload=payload)
        message_id = response.get('messageId')
        if not isinstance(message_id, str) or not message_id:
            raise ProviderError()
        await update_state(db, delivery, 'sent', message_id=message_id)
        await db.execute(text("UPDATE invitations SET status='sent',updated_at=now() WHERE id=:id AND tenant_id=:tid AND status='created'"),
                         {'id': str(delivery['invitation_id']), 'tid': str(tenant_id)})
        await db.execute(text("INSERT INTO invitation_deliveries(invitation_id,channel,recipient,status,provider,provider_id,sent_at) VALUES(:id,'whatsapp',:recipient,'sent','openwa',:mid,now())"),
                         {'id': str(delivery['invitation_id']), 'recipient': delivery['recipient'], 'mid': message_id})
    except ProviderError as exc:
        # Only authentication/validation/rate denial proves that admission to send failed.
        definite = exc.status in (401, 403, 404, 422, 429)
        await update_state(db, delivery, 'failed' if definite else 'unknown', 'provider_rejected' if definite else 'send_result_unknown')
        if definite:
            from app.services.usage_service import release_usage
            await release_usage(db, tenant_id, 'messages_per_month', 1)
    if 'message_id' in locals() and message_id:
        from app.routes.whatsapp import apply_ack
        await apply_ack(db, tenant_id, message_id)
    await db.commit()
    return True


def verify_signature(body, secret, signature):
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(isinstance(signature, str) and re.fullmatch(r'sha256=[0-9a-f]{64}', signature) and hmac.compare_digest(expected, signature))


async def read_summary(db, tid, event_id, ids):
    if not ids:
        return []
    # A paginated history is insufficient for table badges. Return the latest
    # attempt of each message purpose for exactly the requested event and rows.
    statement = text('''SELECT DISTINCT ON (d.invitation_id,d.purpose)
        d.id,d.invitation_id,d.purpose,d.recipient,d.state,d.error_code,d.created_at,d.updated_at,
        COUNT(*) OVER (PARTITION BY d.invitation_id,d.purpose) AS attempt_count
        FROM whatsapp_deliveries d JOIN invitations i ON i.id=d.invitation_id
        WHERE d.tenant_id=:tid AND d.event_id=:eid AND i.tenant_id=:tid AND i.event_id=:eid
          AND d.invitation_id IN :ids
        ORDER BY d.invitation_id,d.purpose,d.created_at DESC,d.id DESC''').bindparams(bindparam('ids', expanding=True))
    rows = await db.execute(statement, {'tid': str(tid), 'eid': str(event_id), 'ids': list(map(str, ids))})
    return [dict(row) for row in rows.mappings().all()]
