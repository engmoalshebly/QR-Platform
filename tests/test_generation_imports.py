"""Bounded import parser and server draft contract."""
import io
import os
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from app.config import get_settings
from app.services.generation_import_parser import normalize_rows,inspect_xlsx
from app.services.generation_workspace_service import workspace,cleanup_abandoned,WorkspaceFull


@pytest.fixture(autouse=True)
def import_settings(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='.p3-import-',dir=os.getcwd()) as directory:
        monkeypatch.setattr(get_settings(),'generation_workspace_dir',directory)
        monkeypatch.setattr(get_settings(),'generation_operations_enabled',True)
        yield Path(directory)


def xlsx(path,formula=False):
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Guests" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>guest_name</t></is></c><c r="B1" t="inlineStr"><is><t>guest_count</t></is></c></row><row r="4"><c r="A4" t="inlineStr"><is><t>ضيف عربي</t></is></c><c r="B4">'+('<f>1+1</f><v>2</v>' if formula else '<v>3</v>')+'</c></row></sheetData></worksheet>')


def test_xlsx_streaming_preserves_sheet_and_original_row(import_settings):
    file=import_settings/'input.xlsx'
    xlsx(file)
    assert inspect_xlsx(file)[0]['name']=='Guests'
    rows=list(normalize_rows(file,'xlsx','Guests'))
    assert len(rows)==1 and rows[0]['row_number']==4
    assert rows[0]['normalized_data']['guest_count']==3
    with pytest.raises(ValueError,match='worksheet'):
        list(normalize_rows(file,'xlsx','Other'))


def test_formula_row_is_visible_error_not_silently_discarded(import_settings):
    file=import_settings/'input.xlsx'
    xlsx(file,formula=True)
    row=next(normalize_rows(file,'xlsx','Guests'))
    assert row['errors'] and row['normalized_data'] is None and not row['excluded']


def test_archive_traversal_and_entity_rejection(import_settings):
    file=import_settings/'input.xlsx'
    xlsx(file)
    with zipfile.ZipFile(file,'a') as archive:
        archive.writestr('../escape.xml','invalid')
    with pytest.raises(ValueError,match='Unsafe'):
        inspect_xlsx(file)
    xlsx(file)
    with zipfile.ZipFile(file,'a') as archive:
        archive.writestr('xl/sharedStrings.xml','<!DOCTYPE a [<!ENTITY x "unsafe">]><sst/>')
    with pytest.raises(ValueError,match='declarations'):
        list(normalize_rows(file,'xlsx','Guests'))


def test_ten_thousand_csv_rows_are_read_incrementally(import_settings):
    file=import_settings/'input.csv'
    with file.open('w') as stream:
        stream.write('guest_name,guest_count\n')
        for index in range(10000):
            stream.write(f'Guest {index},٣\n')
    count=people=0
    for row in normalize_rows(file,'csv'):
        assert not row['errors']
        count+=1
        people+=row['normalized_data']['guest_count']
    assert (count,people)==(10000,30000)
    with file.open('a') as stream:
        stream.write('Overflow,1\n')
    with pytest.raises(ValueError,match='10000'):
        for _ in normalize_rows(file,'csv'):
            pass


def test_workspace_cleanup_respects_live_locks_and_ownership(import_settings):
    with workspace() as active:
        output=active.output('.csv')
        active.write(output,[b'private'])
        assert output.stat().st_mode & 0o777==0o600
        os.utime(active.path,(0,0))
        assert cleanup_abandoned(max_age=1)==0
        with pytest.raises(ValueError,match='inside'):
            active.write(import_settings/'outside.csv',[b'no'])
    abandoned=import_settings/uuid4().hex
    abandoned.mkdir()
    (abandoned/'.active').touch()
    os.utime(abandoned,(0,0))
    assert cleanup_abandoned(max_age=1)==1
    assert not abandoned.exists()


@pytest.mark.asyncio
async def test_import_preview_selection_and_idempotent_generation(db_session,org_world,client_factory):
    tenant=org_world['requester_tenant']
    content='guest_name,guest_count,ticket_class,guest_phone\nأحمد,٣,vip,967700000000\nBad,0,normal,\n,,,\nSecond,1,normal,\n'.encode()
    async with client_factory(org_world['requester_user']) as client:
        headers={'X-Tenant-ID':str(tenant)}
        response=await client.post('/api/v1/generation-imports',params={'event_id':str(org_world['event_id']),'filename':'guests.csv'},content=content,headers={**headers,'Content-Type':'text/csv'})
        assert response.status_code==201,response.text
        uid=response.json()['id']
        url='/api/v1/generation-imports/'+uid
        analyzed=await client.post(url+'/analyze',json={'revision':0},headers=headers)
        assert analyzed.status_code==200,analyzed.text
        assert (analyzed.json()['total'],analyzed.json()['valid'],analyzed.json()['invalid'],analyzed.json()['blank'])==(4,2,1,1)
        rows=await client.get(url+'/rows',params={'state':'invalid','limit':1},headers=headers)
        assert rows.status_code==200,rows.text
        assert rows.json()['items'][0]['row_number']==3
        refused=await client.post(url+'/selection',json={'revision':1},headers=headers)
        assert refused.status_code==409,refused.text
        premature=await client.post(url+'/generate',json={'source_revision':1,'output_formats':[]},headers={**headers,'Idempotency-Key':str(uuid4())})
        assert premature.status_code in (409,422),premature.text
        chosen=await client.post(url+'/selection',json={'revision':1,'acknowledge_exclusions':True},headers=headers)
        assert chosen.status_code==200,chosen.text
        key=str(uuid4())
        body={'source_revision':chosen.json()['revision'],'output_formats':[]}
        generated=await client.post(url+'/generate',json=body,headers={**headers,'Idempotency-Key':key})
        assert generated.status_code==202,generated.text
        assert (generated.json()['cards_count'],generated.json()['people_count'])==(2,4)
        replay=await client.post(url+'/generate',json=body,headers={**headers,'Idempotency-Key':key})
        assert replay.status_code==202,replay.text
        assert replay.json()['id']==generated.json()['id']
        frozen=await client.post(url+'/selection',json={'revision':body['source_revision'],'acknowledge_exclusions':True},headers=headers)
        assert frozen.status_code==409
        errors=await client.get(url+'/errors.csv',headers=headers)
        assert errors.status_code==200,errors.text
        assert 'Bad' in errors.text
    row=(await db_session.execute(text('SELECT status,content FROM generation_uploads WHERE id=:id'),{'id':uid})).one()
    assert tuple(row)==('frozen',None)
    assert (await db_session.execute(text('SELECT source_row_number FROM generation_import_rows WHERE operation_id=:id ORDER BY source_row_number'),{'id':generated.json()['id']})).scalars().all()==[2,5]


@pytest.mark.asyncio
async def test_ten_thousand_selected_rows_are_admitted_by_sql(db_session,org_world,client_factory,monkeypatch):
    from app.services.entitlement_service import resolve_billing_tenant
    tenant=org_world['requester_tenant']
    billing=await resolve_billing_tenant(db_session,tenant)
    plan=uuid4()
    await db_session.execute(text("INSERT INTO plans(id,code,name) VALUES(:id,:code,'P3 isolated capacity')"),{'id':plan,'code':'p3-'+str(plan)})
    for key,value,period in [('invitations_per_event',20000,'none'),('invitations_per_month',20000,'month'),('storage_mb',1024,'none')]:
        await db_session.execute(text('INSERT INTO plan_limits(plan_id,key,value,period) VALUES(:id,:key,:value,CAST(:period AS usage_period))'),{'id':plan,'key':key,'value':value,'period':period})
    await db_session.execute(text('DELETE FROM subscriptions WHERE tenant_id=:tid'),{'tid':billing})
    await db_session.execute(text("INSERT INTO subscriptions(tenant_id,plan_id,status,current_period_end) VALUES(:tid,:id,'active',now()+interval '30 days')"),{'tid':billing,'id':plan})
    await db_session.execute(text('UPDATE events SET normal_quota=20000,vip_quota=20000 WHERE id=:id'),{'id':org_world['event_id']})
    monkeypatch.setattr(get_settings(),'generation_operation_max_cards',10000)
    content=('guest_name,guest_count\n'+''.join(f'Guest {index},1\n' for index in range(10000))).encode()
    async with client_factory(org_world['requester_user']) as client:
        headers={'X-Tenant-ID':str(tenant)}
        upload=await client.post('/api/v1/generation-imports',params={'event_id':str(org_world['event_id']),'filename':'10000.csv'},content=content,headers={**headers,'Content-Type':'text/csv'})
        assert upload.status_code==201,upload.text
        url='/api/v1/generation-imports/'+upload.json()['id']
        checked=await client.post(url+'/analyze',json={'revision':0},headers=headers)
        assert checked.status_code==200,checked.text
        assert checked.json()['valid']==10000
        selected=await client.post(url+'/selection',json={'revision':1},headers=headers)
        assert selected.status_code==200,selected.text
        generated=await client.post(url+'/generate',json={'source_revision':2,'output_formats':[]},headers={**headers,'Idempotency-Key':str(uuid4())})
        assert generated.status_code==202,generated.text
    oid=generated.json()['id']
    assert generated.json()['cards_count']==10000
    counts=(await db_session.execute(text('SELECT count(*),max(count_total),sum(count_total) FROM generation_batches WHERE operation_id=:id'),{'id':oid})).one()
    assert tuple(counts)==(40,250,10000)
    counts=(await db_session.execute(text('SELECT count(*),count(DISTINCT source_row_id) FROM batch_items WHERE operation_id=:id'),{'id':oid})).one()
    assert tuple(counts)==(10000,10000)


@pytest.mark.asyncio
async def test_upload_rows_are_hidden_from_other_tenant_and_expire(db_session,org_world,client_factory):
    from app.services.generation_upload_service import cleanup_expired_uploads
    tenant=org_world['requester_tenant']
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-imports',params={'event_id':str(org_world['event_id']),'filename':'guests.csv'},content=b'guest_name\nPrivate\n',headers={'X-Tenant-ID':str(tenant),'Content-Type':'text/csv'})
        assert response.status_code==201,response.text
        uid=response.json()['id']
    async with client_factory(org_world['provider_user']) as client:
        response=await client.get('/api/v1/generation-imports/'+uid,headers={'X-Tenant-ID':str(org_world['provider_tenant'])})
        assert response.status_code==404,response.text
    await db_session.execute(text("UPDATE generation_uploads SET expires_at=now()-interval '1 second' WHERE id=:id"),{'id':uid})
    assert await cleanup_expired_uploads(db_session)==1


@pytest.mark.parametrize('delimiter',[',',';','\t'])
def test_csv_delimiter_is_explicit_and_quoted_values_are_preserved(import_settings,delimiter):
    file=import_settings/'regional.csv'
    file.write_text('guest_name'+delimiter+'guest_count\n"ضيف; عربي"'+delimiter+'٢\n',encoding='utf-8-sig')
    row=next(normalize_rows(file,'csv',delimiter=delimiter))
    assert row['normalized_data']['guest_name']=='ضيف; عربي'
    assert row['normalized_data']['guest_count']==2


def test_null_cells_become_safe_visible_validation_errors(import_settings):
    file=import_settings/'invalid.csv'
    file.write_bytes(b'guest_name\nHidden\x00Name\n')
    row=next(normalize_rows(file,'csv'))
    assert row['errors'] and row['normalized_data'] is None
    assert '\x00' not in str(row['raw_data'])


def test_oversized_rows_have_bounded_previews(import_settings):
    import json
    file=import_settings/'large.csv'
    file.write_text('guest_name,notes\nGuest,'+'x'*20000+'\n')
    row=next(normalize_rows(file,'csv'))
    assert row['errors'] and row['raw_data']['__preview_truncated']
    assert len(json.dumps(row['raw_data']).encode())<16384


@pytest.mark.asyncio
async def test_intake_bounds_chunked_bodies_before_json_parse():
    from fastapi import FastAPI,Request
    from httpx import AsyncClient,ASGITransport
    from app.generation_intake import GenerationIntakeMiddleware
    app=FastAPI()
    app.add_middleware(GenerationIntakeMiddleware,max_bytes=1024)
    @app.post('/api/v1/generation-imports')
    async def read(request:Request):
        return {'size':len(await request.body())}
    async def chunks():
        for _ in range(3):
            yield b'x'*512
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/generation-imports',content=chunks())
    assert response.status_code==413,response.text


@pytest.mark.asyncio
async def test_workspace_backpressure_is_429_not_partial_upload(db_session,org_world,client_factory,monkeypatch):
    monkeypatch.setattr(get_settings(),'generation_workspace_max_bytes',32*1024*1024)
    async with client_factory(org_world['requester_user']) as client:
        response=await client.post('/api/v1/generation-imports',params={'event_id':str(org_world['event_id']),'filename':'guests.csv'},content=b'guest_name\nGuest\n',headers={'X-Tenant-ID':str(org_world['requester_tenant']),'Content-Type':'text/csv'})
    assert response.status_code==429,response.text
    assert response.headers['retry-after']=='5'
    assert (await db_session.execute(text('SELECT count(*) FROM generation_uploads WHERE tenant_id=:tid'),{'tid':org_world['requester_tenant']})).scalar()==0


@pytest.mark.asyncio
async def test_selection_by_exclusion_and_explicit_list_are_exclusive_and_acknowledged(db_session,org_world,client_factory):
    tenant=org_world['requester_tenant']
    content=b'guest_name,guest_count\nA,1\nB,2\nC,3\nD,1\n'  # rows 2..5, all valid
    async with client_factory(org_world['requester_user']) as client:
        headers={'X-Tenant-ID':str(tenant)}
        up=await client.post('/api/v1/generation-imports',params={'event_id':str(org_world['event_id']),'filename':'g.csv'},content=content,headers={**headers,'Content-Type':'text/csv'})
        url='/api/v1/generation-imports/'+up.json()['id']
        assert (await client.post(url+'/analyze',json={'revision':0},headers=headers)).json()['valid']==4
        both=await client.post(url+'/selection',json={'revision':1,'row_numbers':[2],'exclude_row_numbers':[3]},headers=headers)
        assert both.status_code==422
        duplicate=await client.post(url+'/selection',json={'revision':1,'exclude_row_numbers':[3,3]},headers=headers)
        assert duplicate.status_code==422
        unacknowledged=await client.post(url+'/selection',json={'revision':1,'exclude_row_numbers':[3]},headers=headers)
        assert unacknowledged.status_code==409   # excluding a valid row still needs the explicit confirmation
        chosen=await client.post(url+'/selection',json={'revision':1,'exclude_row_numbers':[3,4],'acknowledge_exclusions':True},headers=headers)
        assert chosen.status_code==200,chosen.text
        assert (chosen.json()['selected'],chosen.json()['selected_people'],chosen.json()['excluded'])==(2,2,2)
        selected=await client.get(url+'/rows',params={'state':'selected'},headers=headers)
        assert [r['row_number'] for r in selected.json()['items']]==[2,5]
