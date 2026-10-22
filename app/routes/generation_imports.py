"""Server-side import drafts: bounded upload, explicit selection, no browser row dump."""
import asyncio
import csv
import hashlib
import io
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,Header,HTTPException,Query,Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from sqlalchemy import text
from app.auth import CurrentUser,get_current_user,get_tenant_id_from_header
from app.config import get_settings
from app.database import get_db
from app.models.generation_operation import StagedGenerationCreate
from app.routes.generation_operations import preparation_slots
from app.services import generation_upload_service as uploads,generation_operation_service as operations
from app.services.generation_import_parser import MAX_UPLOAD,inspect_xlsx,raw_rows
from app.services.generation_snapshot_service import prepare_snapshot
from app.services.generation_workspace_service import workspace
from app.services.permission_service import require_permission

router=APIRouter(prefix='/generation-imports',tags=['Generation imports'])


@asynccontextmanager
async def slot():
    semaphore=preparation_slots()
    try:
        await asyncio.wait_for(semaphore.acquire(),5)
    except TimeoutError:
        raise HTTPException(429,'تجهيز ملفات أخرى جارٍ؛ أعد المحاولة',headers={'Retry-After':'2'})
    try:
        yield
    finally:
        semaphore.release()


def enabled():
    if not get_settings().generation_operations_enabled:
        raise HTTPException(503,'الاستيراد الجديد غير مفعل بعد')


class AnalyzeImport(BaseModel):
    revision: int=Field(ge=0,strict=True)
    sheet: str|None=Field(None,max_length=100)
    delimiter: Literal[',',';','\t']=','
    mapping: dict[str,str]=Field(default_factory=dict,max_length=128)
    require_rsvp: bool=Field(False,strict=True)


class SelectImport(BaseModel):
    revision: int=Field(ge=1,strict=True)
    row_numbers: list[int]|None=Field(None,max_length=10000)
    # "Every valid row except these": avoids shipping 10,000 row numbers to choose 9,990.
    exclude_row_numbers: list[int]|None=Field(None,max_length=10000)
    acknowledge_exclusions: bool=Field(False,strict=True)


@router.post('',status_code=201)
async def upload_file(request:Request,event_id:UUID,filename:str=Query(min_length=1,max_length=255),
        user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    enabled()
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.create')
    if not (await db.execute(text('SELECT id FROM events WHERE tenant_id=:tid AND id=:id AND deleted_at IS NULL'),{'tid':str(tenant),'id':str(event_id)})).scalar():
        raise HTTPException(404,'المناسبة غير موجودة')
    if Path(filename).name!=filename or '\\' in filename:
        raise HTTPException(422,'اسم الملف غير صالح')
    kind=Path(filename).suffix.lower().lstrip('.')
    if kind not in ('csv','xlsx'):
        raise HTTPException(422,'ارفع ملف CSV أو XLSX فقط')
    allowed={'csv':{'text/csv','text/plain','application/octet-stream'},'xlsx':{'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/octet-stream'}}
    if request.headers.get('content-type','').split(';')[0] not in allowed[kind]:
        raise HTTPException(415,'نوع الملف المرسل لا يطابق صيغة الاستيراد')
    if int(request.headers.get('content-length','0'))>MAX_UPLOAD:
        raise HTTPException(413,'حجم الملف يتجاوز 10MiB')
    async with slot():
        with workspace() as scratch:
            path=scratch.output('.'+kind)
            size=0
            digest=hashlib.sha256()
            with path.open('xb') as output:
                path.chmod(0o600)
                async for block in request.stream():
                    size+=len(block)
                    if size>MAX_UPLOAD:
                        raise HTTPException(413,'حجم الملف يتجاوز 10MiB')
                    digest.update(block)
                    await asyncio.to_thread(output.write,block)
            if not size:
                raise HTTPException(422,'الملف فارغ')
            try:
                if kind=='xlsx':
                    sheets=await asyncio.to_thread(inspect_xlsx,path)
                else:
                    def csv_header():
                        rows=raw_rows(path,kind)
                        try:
                            return next(rows,(0,[]))[1]
                        finally:
                            rows.close()
                    headers=await asyncio.to_thread(csv_header)
                    if not headers or any('\x00' in str(value) for value in headers):
                        raise ValueError('Invalid CSV header')
                    sheets=[{'name':'CSV'}]
            except Exception as error:
                raise HTTPException(422,'ملف غير صالح أو يتجاوز حدود الأمان') from error
            await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,true)"),{'tid':str(tenant)})
            capacity=(await db.execute(text('SELECT generation_check_upload_capacity(:tid,:size)'),{'tid':str(tenant),'size':size})).scalar()
            if not capacity:
                raise HTTPException(429,'مساحة الاستيراد المؤقت ممتلئة؛ انتظر انتهاء الملفات السابقة')
            upload_id=uuid4()
            content=await asyncio.to_thread(path.read_bytes)
            await db.execute(text('''INSERT INTO generation_uploads(id,tenant_id,event_id,created_by,filename,kind,content,byte_size,sha256,sheets)
                VALUES(:id,:tid,:eid,:uid,:name,:kind,:content,:size,:sha,CAST(:sheets AS jsonb))'''),
                {'id':upload_id,'tid':str(tenant),'eid':str(event_id),'uid':str(user.id),'name':filename,'kind':kind,'content':content,'size':size,'sha':digest.hexdigest(),'sheets':json.dumps(sheets)})
            await db.commit()
            return {'id':upload_id,'revision':0,'status':'uploaded','sheets':[s['name'] for s in sheets],'byte_size':size,'sha256':digest.hexdigest()}


@router.get('/{upload_id}')
async def get_import(upload_id:UUID,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.create')
    return await uploads.get_upload(db,tenant,user.id,upload_id)


@router.post('/{upload_id}/analyze')
async def analyze_import(upload_id:UUID,body:AnalyzeImport,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    enabled()
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.create')
    async with slot():
        result=await uploads.analyze(db,tenant,user.id,upload_id,body.revision,body.sheet,body.mapping,body.require_rsvp,body.delimiter)
        await db.commit()
        return result


@router.post('/{upload_id}/selection')
async def select_import(upload_id:UUID,body:SelectImport,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    enabled()
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.create')
    if body.row_numbers is not None and body.exclude_row_numbers is not None:
        raise HTTPException(422,'استخدم قائمة اختيار أو قائمة استبعاد، لا الاثنتين معًا')
    for numbers in (body.row_numbers,body.exclude_row_numbers):
        if numbers is not None and (len(set(numbers))!=len(numbers) or any(number<1 for number in numbers)):
            raise HTTPException(422,'أرقام الصفوف يجب أن تكون موجبة وفريدة')
    result=await uploads.select_rows(db,tenant,user.id,upload_id,body.revision,body.row_numbers,body.acknowledge_exclusions,body.exclude_row_numbers)
    await db.commit()
    return result


@router.get('/{upload_id}/rows')
async def import_rows(upload_id:UUID,request:Request,after:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),
        state:Literal['all','valid','invalid','selected','excluded']='all',search:str=Query('',max_length=100),
        ticket_class:Literal['vip','normal']|None=None,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.view')
    await uploads.get_upload(db,tenant,user.id,upload_id)
    filters={'all':'true','valid':"normalized_data IS NOT NULL AND NOT excluded",'invalid':"errors<>'[]'::jsonb",'selected':'selected','excluded':'NOT selected'}
    result=await db.execute(text('''SELECT row_number,raw_data,normalized_data,errors,excluded,selected FROM generation_upload_rows
        WHERE tenant_id=:tid AND upload_id=:id AND row_number>:after AND '''+filters[state]+'''
        AND (CAST(:class AS text) IS NULL OR normalized_data->>'ticket_class'=:class)
        AND (:search='' OR raw_data::text ILIKE :pattern) ORDER BY row_number LIMIT :limit'''),
        {'tid':str(tenant),'id':upload_id,'after':after,'class':ticket_class,'search':search,'pattern':'%'+search.replace('%','\\%').replace('_','\\_')+'%','limit':limit+1})
    rows=[dict(row) for row in result.mappings()]
    return {'items':rows[:limit],'next_row':rows[limit-1]['row_number'] if len(rows)>limit else None}


@router.get('/{upload_id}/errors.csv')
async def error_export(upload_id:UUID,request:Request,user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.export')
    await uploads.get_upload(db,tenant,user.id,upload_id)
    def safe(value):
        value=str(value)
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    async def generate():
        yield '\ufeffrow_number,errors,source_data\r\n'
        after=0
        while True:
            rows=(await db.execute(text("SELECT row_number,errors,raw_data FROM generation_upload_rows WHERE tenant_id=:tid AND upload_id=:id AND row_number>:after AND errors<>'[]'::jsonb ORDER BY row_number LIMIT 100"),{'tid':str(tenant),'id':upload_id,'after':after})).mappings().all()
            if not rows:
                break
            output=io.StringIO()
            writer=csv.writer(output)
            for row in rows:
                writer.writerow([row['row_number'],safe('; '.join(row['errors'])),safe(json.dumps(row['raw_data'],ensure_ascii=False))])
            after=rows[-1]['row_number']
            yield output.getvalue()
    return StreamingResponse(generate(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="import-errors.csv"'})


class StagedBody:
    def __init__(self,options,upload,stats):
        self.options,self.upload,self.stats=options,upload,stats
        self.__dict__.update(options.model_dump())
        self.templates=options.templates
        self.layout=options.layout
        self.event_id=upload['event_id']
        self.source='excel'
        self.original_filename=upload['filename']
        self.source_sha256=upload['sha256']
    def normalized_rows(self):
        return [{'ticket_class':kind,'guest_count':self.stats[kind+'_people']} for kind in ('vip','normal') if self.stats[kind+'_cards']]
    def model_dump(self,mode='json'):
        return {**self.options.model_dump(mode=mode),'event_id':str(self.event_id),'source':'excel','upload_id':str(self.upload['id'])}


async def selected_stats(db,tenant,upload_id):
    result=(await db.execute(text("""SELECT count(*) AS cards,
        count(*) FILTER(WHERE normalized_data->>'ticket_class'='vip') AS vip_cards,
        count(*) FILTER(WHERE normalized_data->>'ticket_class'='normal') AS normal_cards,
        COALESCE(sum((normalized_data->>'guest_count')::integer) FILTER(WHERE normalized_data->>'ticket_class'='vip'),0) AS vip_people,
        COALESCE(sum((normalized_data->>'guest_count')::integer) FILTER(WHERE normalized_data->>'ticket_class'='normal'),0) AS normal_people
        FROM generation_upload_rows WHERE tenant_id=:tid AND upload_id=:id AND selected"""),{'tid':str(tenant),'id':upload_id})).mappings().one()
    return dict(result)


@router.post('/{upload_id}/generate',status_code=202)
async def generate_import(upload_id:UUID,body:StagedGenerationCreate,request:Request,
        idempotency_key:str=Header(...,alias='Idempotency-Key',min_length=8,max_length=128),
        user:CurrentUser=Depends(get_current_user),db=Depends(get_db)):
    enabled()
    if not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}',idempotency_key):
        raise HTTPException(422,'مفتاح الطلب غير صالح')
    tenant=get_tenant_id_from_header(request)
    await require_permission(db,tenant,user.id,'invitations.create')
    async with slot():
        upload=await uploads.get_upload(db,tenant,user.id,upload_id)
        stats=await selected_stats(db,tenant,upload_id)
        adapter=StagedBody(body,upload,stats)
        replay=await operations.find_replay(db,tenant,user.id,idempotency_key,operations.request_fingerprint(adapter))
        if replay:
            return operations.compact_operation(replay,True)
        if upload['status']!='validated' or upload['revision']!=body.source_revision:
            raise HTTPException(409,'اختيار الملف قديم أو مستخدم؛ حدّث المعاينة')
        if not stats['cards']:
            raise HTTPException(422,'اختر صفوفًا صالحة قبل الإنشاء')
        if upload['summary'].get('selected',0)!=stats['cards'] or (
                upload['summary']['total']>stats['cards'] and not upload['acknowledged_exclusions']):
            raise HTTPException(409,'أكّد الصفوف المختارة والمستبعدة قبل الإنشاء')
        if upload['require_rsvp']!=body.require_rsvp:
            raise HTTPException(409,'خيار RSVP تغير؛ أعد فحص الملف بهذا الخيار أولًا')
        classes={kind for kind in ('vip','normal') if stats[kind+'_cards']}
        if (body.mode=='designed' and set(body.templates)!=classes) or (body.mode=='quick' and body.templates):
            raise HTTPException(422,'اختر قالبًا لكل فئة مختارة فقط')
        if stats['cards']>get_settings().generation_operation_max_cards:
            raise operations.max_cards_error(get_settings().generation_operation_max_cards)
        await operations.authorize_admission(db,tenant,user.id,adapter)
        snapshot=await prepare_snapshot(db,tenant,adapter)
        await db.commit()
        await db.execute(text("SELECT set_config('app.current_tenant_id',:tid,false)"),{'tid':str(tenant)})
        current=await uploads.get_upload(db,tenant,user.id,upload_id,True)
        if current['revision']!=body.source_revision or current['status']!='validated':
            replay=await operations.find_replay(db,tenant,user.id,idempotency_key,operations.request_fingerprint(adapter))
            if replay:
                return operations.compact_operation(replay,True)
            raise HTTPException(409,'تغير اختيار الملف أثناء تجهيز الطلب')
        operation,replayed=await operations.admit_operation(db,tenant,user.id,idempotency_key,adapter,snapshot,staged={**stats,'id':upload_id})
        await db.commit()
        return operations.compact_operation(operation,replayed)
