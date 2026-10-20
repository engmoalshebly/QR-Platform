"""Staged spreadsheet validation. At most 100 normalized records per DB insert."""
import asyncio
import csv
import zipfile
from xml.etree.ElementTree import ParseError
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import text
from app.services.generation_import_parser import normalize_rows,next_chunk
from app.services.generation_workspace_service import workspace


async def get_upload(db,tenant,user,upload_id,lock=False):
    row=(await db.execute(text('''SELECT id,tenant_id,event_id,created_by,filename,kind,byte_size,sha256,sheets,status,
        revision,sheet,delimiter,column_mapping,require_rsvp,summary,acknowledged_exclusions,operation_id,expires_at,
        expires_at<=now() AS expired FROM generation_uploads WHERE tenant_id=:tid AND id=:id'''+(' FOR UPDATE' if lock else '')),
        {'tid':str(tenant),'id':str(upload_id)})).mappings().first()
    if row is None:
        raise HTTPException(404,'ملف الاستيراد غير موجود')
    if row['created_by']!=user:
        from app.services.permission_service import require_permission
        await require_permission(db,tenant,user,'batches.manage')
    if row['expired'] and row['status']!='frozen':
        raise HTTPException(410,'انتهت مدة ملف الاستيراد؛ ارفع الملف مجددًا')
    return dict(row)


async def analyze(db,tenant,user,upload_id,revision,sheet,mapping,require_rsvp,delimiter=","):
    upload=await get_upload(db,tenant,user,upload_id,True)
    if upload['status']=='frozen' or upload['revision']!=revision:
        raise HTTPException(409,'تغيرت نسخة المعاينة أو استُخدمت لإنشاء عملية؛ حدّث الصفحة')
    if require_rsvp:
        from app.services.feature_service import require_feature
        await require_feature(db,tenant,'rsvp')
    content=(await db.execute(text('SELECT content FROM generation_uploads WHERE tenant_id=:tid AND id=:id'),{'tid':str(tenant),'id':str(upload_id)})).scalar_one()
    import hashlib
    if hashlib.sha256(content).hexdigest()!=upload['sha256']:
        raise HTTPException(409,'بصمة ملف المصدر لا تطابق النسخة المحفوظة')
    await db.execute(text('DELETE FROM generation_upload_rows WHERE tenant_id=:tid AND upload_id=:id'),{'tid':str(tenant),'id':str(upload_id)})
    summary={'total':0,'valid':0,'invalid':0,'blank':0,'selected':0,'vip':0,'normal':0,'people':0,'selected_people':0,'selected_vip':0,'selected_normal':0}
    with workspace() as scratch:
        file=scratch.output('.'+upload['kind'])
        await asyncio.to_thread(scratch.write,file,[content])
        del content
        iterator=normalize_rows(file,upload['kind'],sheet,mapping,require_rsvp,delimiter)
        try:
            while True:
                rows=await asyncio.to_thread(next_chunk,iterator)
                if not rows:
                    break
                await db.execute(text('''INSERT INTO generation_upload_rows(tenant_id,upload_id,row_number,raw_data,normalized_data,errors,excluded)
                    SELECT :tid,:id,r.row_number,r.raw_data,r.normalized_data,r.errors,r.excluded
                    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(row_number integer,raw_data jsonb,normalized_data jsonb,errors jsonb,excluded boolean)'''),
                    {'tid':str(tenant),'id':str(upload_id),'rows':json.dumps(rows,ensure_ascii=False)})
                for row in rows:
                    summary['total']+=1
                    if row['excluded']:
                        summary['blank']+=1
                    elif row['errors']:
                        summary['invalid']+=1
                    else:
                        summary['valid']+=1
                        summary[row['normalized_data']['ticket_class']]+=1
                        summary['people']+=row['normalized_data']['guest_count']
        except (ValueError,KeyError,IndexError,UnicodeError,csv.Error,zipfile.BadZipFile,ParseError,OverflowError) as error:
            raise HTTPException(422,str(error)[:500]) from error
        finally:
            iterator.close()
    await db.execute(text('''UPDATE generation_uploads SET status='validated',revision=revision+1,sheet=:sheet,delimiter=:delimiter,
        column_mapping=CAST(:mapping AS jsonb),require_rsvp=:rsvp,summary=CAST(:summary AS jsonb),acknowledged_exclusions=false
        WHERE tenant_id=:tid AND id=:id'''),{'tid':str(tenant),'id':str(upload_id),'sheet':sheet,
        'delimiter':delimiter,'mapping':json.dumps(mapping),'rsvp':require_rsvp,'summary':json.dumps(summary)})
    return {**summary,'revision':revision+1}


async def select_rows(db,tenant,user,upload_id,revision,row_numbers,acknowledge,exclude=None):
    upload=await get_upload(db,tenant,user,upload_id,True)
    if upload['status']!='validated' or upload['revision']!=revision:
        raise HTTPException(409,'حدّث معاينة الملف قبل تغيير الاختيار')
    p={'tid':str(tenant),'id':str(upload_id)}
    await db.execute(text('UPDATE generation_upload_rows SET selected=false WHERE tenant_id=:tid AND upload_id=:id'),p)
    predicate='' if row_numbers is None else ' AND row_number=ANY(CAST(:numbers AS integer[]))'
    if exclude:
        predicate+=' AND NOT (row_number=ANY(CAST(:exclude AS integer[])))'
    result=await db.execute(text("UPDATE generation_upload_rows SET selected=true WHERE tenant_id=:tid AND upload_id=:id AND normalized_data IS NOT NULL AND errors='[]'::jsonb AND NOT excluded"+predicate),{**p,'numbers':row_numbers,'exclude':exclude or []})
    count=result.rowcount
    if row_numbers is not None and count!=len(row_numbers):
        raise HTTPException(422,'تتضمن قائمة الاختيار صفوفًا غير صالحة أو غير موجودة')
    excluded=upload['summary']['total']-count
    if excluded and not acknowledge:
        raise HTTPException(409,{'code':'EXCLUSIONS_REQUIRE_ACK','selected':count,'excluded':excluded,
            'message':'لن تُولد كل صفوف الملف؛ أكّد عدد الصفوف المستبعدة صراحةً'})
    selected=(await db.execute(text("""SELECT COALESCE(sum((normalized_data->>'guest_count')::integer),0) AS people,
        count(*) FILTER(WHERE normalized_data->>'ticket_class'='vip') AS vip,
        count(*) FILTER(WHERE normalized_data->>'ticket_class'='normal') AS normal
        FROM generation_upload_rows WHERE tenant_id=:tid AND upload_id=:id AND selected"""),p)).mappings().one()
    summary={**upload['summary'],'selected':count,'excluded':excluded,
             'selected_people':selected['people'],'selected_vip':selected['vip'],'selected_normal':selected['normal']}
    await db.execute(text('''UPDATE generation_uploads SET revision=revision+1,summary=CAST(:summary AS jsonb),
        acknowledged_exclusions=:ack WHERE tenant_id=:tid AND id=:id'''),{**p,'summary':json.dumps(summary),'ack':acknowledge})
    return {**summary,'revision':revision+1}


async def cleanup_expired_uploads(db,limit=100):
    if (await db.execute(text("SELECT to_regclass('public.generation_drafts') IS NOT NULL"))).scalar():
        await db.execute(text("""DELETE FROM generation_drafts WHERE (tenant_id,event_id,created_by,kind) IN
            (SELECT tenant_id,event_id,created_by,kind FROM generation_drafts WHERE expires_at<clock_timestamp()
             ORDER BY expires_at LIMIT :limit FOR UPDATE SKIP LOCKED)"""), {'limit':max(1,min(limit,100))})
    result=await db.execute(text('''DELETE FROM generation_uploads WHERE id IN
        (SELECT id FROM generation_uploads WHERE status<>'frozen' AND expires_at<clock_timestamp()
         ORDER BY expires_at LIMIT :limit FOR UPDATE SKIP LOCKED)'''),{'limit':max(1,min(limit,100))})
    return result.rowcount
