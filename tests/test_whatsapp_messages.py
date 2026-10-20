"""Message authoring and shared image dispatch, on isolated DB with mocked transport."""
import base64
import io
import json
from dataclasses import replace
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import text
from starlette.requests import Request
from app.services import whatsapp_message_service as messages
from app.services import whatsapp_service as svc
from app.routes import whatsapp as routes
from tests.test_whatsapp_delivery import wa_world


def jpeg():
    out=io.BytesIO();Image.new('RGB',(400,240),'navy').save(out,'JPEG');return out.getvalue()


@pytest.mark.parametrize('value',['','{unknown}','bad {guest_name','a'*701,'hello\x00','\ud800'])
def test_template_validation(value):
    with pytest.raises(HTTPException):messages.validate_template(value)


def test_render_uses_arabic_name_one_pass_timezone_and_private_link():
    event={'title':'حفل الاختبار','start_date':datetime(2026,10,13,12,tzinfo=timezone.utc),'timezone':'Asia/Aden','venue_name':'قاعة الحفل'}
    result=messages.render('{guest_name} {event_name} {event_date} {event_location}',{'guest_name':'fallback','guest_name_ar':'{event_name}'},event,'https://example.com/i/personal')
    assert result.startswith('{event_name} حفل الاختبار 2026/10/13، 15:00 قاعة الحفل')
    assert result.endswith('\n\nhttps://example.com/i/personal')


def test_image_normalization_limits_size_strips_exif_and_rejects_nonimage():
    out=io.BytesIO();img=Image.new('RGBA',(1800,1200),(10,10,200,80));img.save(out,'PNG')
    result=messages.normalize_image(out.getvalue())
    decoded=Image.open(io.BytesIO(result))
    assert decoded.format=='JPEG' and max(decoded.size)<=1200 and len(result)<=65536 and not decoded.getexif()
    for content in (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',b'fake',b'0'*(messages.MAX_UPLOAD_BYTES+1)):
        with pytest.raises(HTTPException):messages.normalize_image(content)


async def setup_message(db,tid,eid):
    iid=(await db.execute(text('INSERT INTO whatsapp_message_images(tenant_id,event_id,content) VALUES(:tid,:eid,:content) RETURNING id'),{'tid':str(tid),'eid':str(eid),'content':jpeg()})).scalar_one()
    await db.execute(text('''INSERT INTO whatsapp_message_templates(tenant_id,event_id,rsvp_text,ticket_text,image_id)
        VALUES(:tid,:eid,'طلب رد {guest_name}','أهلاً {guest_name} في {event_name}',:iid)'''),{'tid':str(tid),'eid':str(eid),'iid':str(iid)})
    return iid


@pytest.mark.asyncio
async def test_image_dispatch_uses_immutable_snapshot_and_one_provider_post(db_session,wa_world,monkeypatch):
    tid,uid,iid,eid=wa_world;image_id=await setup_message(db_session,tid,eid)
    request=uuid4()
    queued=await svc.queue_deliveries(db_session,tid,uid,[iid],request,message_versions={eid:1})
    original=(await db_session.execute(text('SELECT message_text,message_image_id FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).mappings().one()
    await db_session.execute(text("UPDATE whatsapp_message_templates SET ticket_text='new text',image_id=NULL,version=2 WHERE tenant_id=:tid"),{'tid':str(tid)})
    assert await svc.queue_deliveries(db_session,tid,uid,[iid],request,message_versions={eid:1})==queued
    calls=[]
    async def provider(method,path,**kwargs):
        if method=='GET':return {'status':'ready'}
        calls.append((path,kwargs['payload']));return {'messageId':'image-id'}
    monkeypatch.setattr(svc,'provider',provider)
    assert await svc.dispatch_one(db_session)
    assert len(calls)==1 and calls[0][0].endswith('/send-image')
    assert calls[0][1]['caption']==original['message_text'] and original['message_image_id']==image_id
    assert base64.b64decode(calls[0][1]['base64'])==jpeg() and 'url' not in calls[0][1]
    assert len(json.dumps(calls[0][1]).encode())<100*1024
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()=='sent'


@pytest.mark.asyncio
async def test_stale_preview_is_rejected_before_any_queue_rows(db_session,wa_world):
    tid,uid,iid,eid=wa_world
    await setup_message(db_session,tid,eid)
    with pytest.raises(HTTPException) as error:
        await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4(),message_versions={eid:0})
    assert error.value.status_code==409
    assert (await db_session.execute(text('SELECT count(*) FROM whatsapp_delivery_requests WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()==0


@pytest.mark.asyncio
async def test_image_unknown_result_is_never_retried(db_session,wa_world,monkeypatch):
    tid,uid,iid,eid=wa_world;await setup_message(db_session,tid,eid)
    await svc.queue_deliveries(db_session,tid,uid,[iid],uuid4())
    calls=[]
    async def provider(method,path,**kwargs):
        if method=='GET':return {'status':'ready'}
        calls.append(path);raise svc.ProviderError()
    monkeypatch.setattr(svc,'provider',provider)
    await svc.dispatch_one(db_session);await svc.dispatch_one(db_session)
    assert len(calls)==1
    assert (await db_session.execute(text('SELECT state FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()=='unknown'


@pytest.mark.asyncio
async def test_message_routes_ownership_version_and_preview(db_session,wa_world,monkeypatch):
    tid,uid,iid,eid=wa_world
    for name in ('require_permission','require_any_permission','require_feature'):monkeypatch.setattr(routes,name,AsyncMock())
    request=Request({'type':'http','headers':[(b'x-tenant-id',str(tid).encode())],'client':('127.0.0.1',1)})
    actor=SimpleNamespace(id=uid)
    result=await routes.get_message_config(eid,request,actor,db_session)
    assert result['version']==0 and '{guest_name}' in result['ticket_text']
    image_id=await setup_message(db_session,tid,eid)
    data=routes.MessageConfigUpdate(rsvp_text='دعوة {guest_name}',ticket_text='الحفل {event_name}',image_id=image_id,version=1)
    result=await routes.save_message_config(eid,data,request,actor,db_session)
    assert result['version']==2 and result['image_id']==image_id
    with pytest.raises(HTTPException) as error:await routes.save_message_config(eid,data,request,actor,db_session)
    assert error.value.status_code==409
    preview=await routes.preview_messages(eid,routes.MessagePreviewRequest(invitation_ids=[iid]),request,actor,db_session)
    assert preview['version']==2 and preview['samples'][0]['purpose']=='ticket' and '/i/' in preview['samples'][0]['text']
    with pytest.raises(HTTPException):await messages.image(db_session,uuid4(),eid,image_id)
    with pytest.raises(HTTPException):await messages.image(db_session,tid,uuid4(),image_id)
    with pytest.raises(HTTPException):await routes.preview_messages(eid,routes.MessagePreviewRequest(invitation_ids=[uuid4()]),request,actor,db_session)


@pytest.mark.asyncio
async def test_edit_needs_event_edit_and_whatsapp_send_permission(monkeypatch):
    permission=AsyncMock(side_effect=[None,HTTPException(403,'denied')]);monkeypatch.setattr(routes,'require_permission',permission)
    event=AsyncMock();monkeypatch.setattr(messages,'event_owned',event)
    request=Request({'type':'http','headers':[(b'x-tenant-id',str(uuid4()).encode())]})
    with pytest.raises(HTTPException):await routes.message_access(request,SimpleNamespace(id=uuid4()),object(),uuid4(),edit=True)
    assert permission.call_args.args[-1]=='events.edit';event.assert_not_awaited()

@pytest.mark.asyncio
async def test_hundred_recipients_share_one_image_and_use_own_links(db_session,wa_world):
    tid,uid,_,eid=wa_world;image_id=await setup_message(db_session,tid,eid)
    rows=(await db_session.execute(text('''INSERT INTO invitations(tenant_id,event_id,guest_name,guest_phone,status,rsvp_status,token,metadata)
        SELECT :tid,:eid,'ضيف '||n,'+967700000001','accepted','accepted',gen_random_uuid()::text,jsonb_build_object('require_rsvp',false)
        FROM generate_series(1,100)n RETURNING id,token'''),{'tid':str(tid),'eid':str(eid)})).mappings().all()
    result=await svc.queue_deliveries(db_session,tid,uid,[r['id'] for r in rows],uuid4())
    assert result['queued']==100
    snapshots=(await db_session.execute(text('SELECT message_text,message_image_id FROM whatsapp_deliveries WHERE tenant_id=:tid'),{'tid':str(tid)})).mappings().all()
    assert len({r['message_text'] for r in snapshots})==100
    assert all(r['message_image_id']==image_id for r in snapshots)
    assert (await db_session.execute(text('SELECT count(*) FROM whatsapp_message_images WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()==1


@pytest.mark.asyncio
async def test_upload_reads_bounded_input_and_tracks_storage(db_session,wa_world,monkeypatch):
    tid,uid,_,eid=wa_world
    for name in ('require_permission','require_any_permission','require_feature'):monkeypatch.setattr(routes,name,AsyncMock())
    from app.services import feature_service
    quota=AsyncMock();account=AsyncMock()
    monkeypatch.setattr(feature_service,'require_storage_for_upload',quota)
    monkeypatch.setattr(feature_service,'record_non_asset_storage',account)
    file=SimpleNamespace(read=AsyncMock(return_value=jpeg()))
    request=Request({'type':'http','headers':[(b'x-tenant-id',str(tid).encode())],'client':('127.0.0.1',1)})
    result=await routes.upload_message_image(eid,request,file,SimpleNamespace(id=uid),db_session)
    file.read.assert_awaited_once_with(messages.MAX_UPLOAD_BYTES+1)
    quota.assert_awaited_once_with(db_session,tid,result['size'])
    account.assert_awaited_once_with(db_session,tid,result['size'])
    response=await routes.get_message_image(eid,result['image_id'],request,SimpleNamespace(id=uid),db_session)
    assert response.media_type=='image/jpeg' and response.headers['cache-control']=='private, no-store'


def test_provider_length_matches_utf16():
    assert messages.message_length('😀')==2
    with pytest.raises(HTTPException):messages.validate_template('😀'*351)

@pytest.mark.asyncio
async def test_rls_protects_images_and_templates(db_session,wa_world):
    tid,_,_,eid=wa_world;await setup_message(db_session,tid,eid)
    await db_session.execute(text("SELECT set_config('app.current_tenant_id',:tid,true)"),{'tid':str(uuid4())})
    await db_session.execute(text('SET LOCAL ROLE qentry_app'))
    try:
        for table in ('whatsapp_message_images','whatsapp_message_templates'):
            assert (await db_session.execute(text(f'SELECT count(*) FROM {table} WHERE tenant_id=:tid'),{'tid':str(tid)})).scalar_one()==0
    finally:await db_session.execute(text('RESET ROLE'))


@pytest.mark.asyncio
async def test_http_config_preview_and_input_validation(client_factory,wa_world,org_world,monkeypatch):
    tid,uid,iid,eid=wa_world
    monkeypatch.setattr(routes,'require_feature',AsyncMock())
    headers={'X-Tenant-ID':str(tid)}
    async with client_factory(uid) as client:
        read=await client.get(f'/api/v1/whatsapp/events/{eid}/message',headers=headers)
        assert read.status_code==200 and read.json()['version']==0
        body={'rsvp_text':'مرحباً {guest_name}','ticket_text':'أهلاً {guest_name}','version':0}
        result=await client.put(f'/api/v1/whatsapp/events/{eid}/message',headers=headers,json=body)
        assert result.status_code==200 and result.json()['version']==1
        result=await client.put(f'/api/v1/whatsapp/events/{eid}/message',headers=headers,json=body)
        assert result.status_code==409
        preview=await client.post(f'/api/v1/whatsapp/events/{eid}/message/preview',headers=headers,json={'invitation_ids':[str(iid)]})
        assert preview.status_code==200 and preview.json()['version']==1
        for changed in ({'version':-1},{'ticket_text':'{invalid}','version':1}):
            bad=await client.put(f'/api/v1/whatsapp/events/{eid}/message',headers=headers,json={**body,**changed})
            assert bad.status_code==422
        bad=await client.post('/api/v1/whatsapp/deliveries',headers=headers,json={'invitation_ids':[str(iid)],'client_request_id':str(uuid4()),'message_versions':{str(eid):-1}})
        assert bad.status_code==422
    async with client_factory(org_world['provider_user']) as client:
        bad=await client.put(f'/api/v1/whatsapp/events/{eid}/message',headers=headers,json=body)
        assert bad.status_code==403
