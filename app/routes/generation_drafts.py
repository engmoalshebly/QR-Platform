"""Private, revisioned manual-input drafts. No guest data in browser storage."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from app.auth import CurrentUser, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.permission_service import require_permission

router = APIRouter(prefix='/generation-drafts', tags=['Generation Drafts'])


class DraftGuest(BaseModel):
    guest_name: str = Field(min_length=1, max_length=200, strict=True)
    invitation_count: int = Field(default=1, ge=1, le=100, strict=True)
    ticket_class: Literal['vip', 'normal'] = 'normal'
    custom_fields: dict[str, str] = Field(default_factory=dict, max_length=100)

    @model_validator(mode='after')
    def valid_name_and_fields(self):
        self.guest_name = self.guest_name.strip()
        if not self.guest_name:
            raise ValueError('اسم الضيف مطلوب')
        if len(json.dumps(self.custom_fields, ensure_ascii=False, allow_nan=False).encode()) > 16384:
            raise ValueError('حقول الضيف أكبر من الحد المسموح')
        return self


class DraftWrite(BaseModel):
    revision: int = Field(ge=0, le=2147483646, strict=True)
    rows: list[DraftGuest] = Field(max_length=1000)

    @model_validator(mode='after')
    def bounded(self):
        if len(json.dumps(self.model_dump()['rows'], ensure_ascii=False, allow_nan=False).encode()) > 1024 * 1024:
            raise ValueError('المسودة أكبر من الحد المسموح؛ استخدم استيراد الملف')
        return self


async def scope(db, request, user, event_id, kind):
    tenant = get_tenant_id_from_header(request)
    await require_permission(db, tenant, user.id, 'invitations.create')
    if not (await db.execute(text('SELECT id FROM events WHERE id=:eid AND tenant_id=:tid'),
                             {'eid':event_id,'tid':tenant})).scalar():
        raise HTTPException(404, 'الحدث غير موجود')
    return {'tid':tenant,'eid':event_id,'uid':user.id,'kind':kind}


@router.get('/{event_id}/{kind}')
async def read_draft(event_id:UUID, kind:Literal['quick','designed'], request:Request,
                     user:CurrentUser=Depends(get_current_user), db=Depends(get_db)):
    params = await scope(db,request,user,event_id,kind)
    row=(await db.execute(text('''SELECT payload AS rows,revision,expires_at FROM generation_drafts
        WHERE tenant_id=:tid AND event_id=:eid AND created_by=:uid AND kind=:kind AND expires_at>now()'''),params)).mappings().first()
    return dict(row) if row else {'rows':[], 'revision':0, 'expires_at':None}


@router.put('/{event_id}/{kind}')
async def write_draft(event_id:UUID, kind:Literal['quick','designed'], body:DraftWrite, request:Request,
                      user:CurrentUser=Depends(get_current_user), db=Depends(get_db)):
    params = await scope(db,request,user,event_id,kind)
    # One draft per owner/event/mode; compare-and-swap prevents stale tabs overwriting.
    await db.execute(text('''DELETE FROM generation_drafts WHERE tenant_id=:tid AND event_id=:eid
        AND created_by=:uid AND kind=:kind AND expires_at<=now()'''),params)
    params.update(payload=json.dumps(body.model_dump()['rows'],ensure_ascii=False,allow_nan=False),revision=body.revision)
    row=(await db.execute(text('''INSERT INTO generation_drafts(tenant_id,event_id,created_by,kind,payload)
        SELECT :tid,:eid,:uid,:kind,CAST(:payload AS jsonb) WHERE :revision=0
        ON CONFLICT DO NOTHING RETURNING revision,expires_at'''),params)).mappings().first() if body.revision==0 else None
    if body.revision>0:
        row=(await db.execute(text('''UPDATE generation_drafts SET payload=CAST(:payload AS jsonb),revision=revision+1,
            updated_at=now(),expires_at=now()+interval '7 days' WHERE tenant_id=:tid AND event_id=:eid
            AND created_by=:uid AND kind=:kind AND revision=:revision RETURNING revision,expires_at'''),params)).mappings().first()
    if not row:
        raise HTTPException(409,'تغيرت المسودة في تبويب آخر أو انتهت مدتها. أعد تحميلها قبل المتابعة.')
    await db.commit()
    return dict(row)
