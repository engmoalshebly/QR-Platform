"""Versioned, asynchronous admission contract; legacy API responses stay unchanged."""
from typing import Any, Literal, Annotated
from datetime import datetime
import json
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.models.batch import LayoutConfig
from app.services.fast_generation_service import _normalize_invitation_row


class CountSource(BaseModel):
    vip_count: int = Field(0, ge=0, le=10000, strict=True)
    normal_count: int = Field(0, ge=0, le=10000, strict=True)
    guest_name_prefix: str = Field('ضيف', min_length=1, max_length=180)


class GenerationOperationCreate(BaseModel):
    contract_version: Literal[1] = 1
    event_id: UUID
    mode: Literal['quick', 'designed'] = 'quick'
    source: Literal['count', 'names', 'excel']
    rows: list[dict[str, Any]] | None = Field(None, max_length=10000)
    count: CountSource | None = None
    source_row_numbers: list[Annotated[int, Field(ge=1, le=2147483647, strict=True)]] | None = Field(None, max_length=10000)
    templates: dict[Literal['vip', 'normal'], UUID] = Field(default_factory=dict)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    output_formats: list[Literal['pdf', 'zip']] = Field(default_factory=lambda: ['pdf', 'zip'])
    require_rsvp: bool = Field(False, strict=True)
    original_filename: str | None = Field(None, max_length=255)
    source_sha256: str | None = Field(None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def normalize_source(self):
        if len(set(self.output_formats)) != len(self.output_formats):
            raise ValueError('صيغ الملفات المطلوبة مكررة')
        if self.source == 'count':
            if self.rows is not None or self.count is None or self.require_rsvp or self.source_row_numbers is not None:
                raise ValueError('التوليد بالعدد يتطلب أعداد الفئات ولا يدعم RSVP أو صفوف الضيوف')
            total = self.count.vip_count + self.count.normal_count
            if not 1 <= total <= 10000:
                raise ValueError('مجموع الدعوات يجب أن يكون من 1 إلى 10000؛ حد التشغيل الحالي يتحقق منه الخادم')
            if not self.count.guest_name_prefix.strip():
                raise ValueError('بادئة اسم الضيف مطلوبة')
            self.count.guest_name_prefix = self.count.guest_name_prefix.strip()
        else:
            if self.count is not None or not self.rows:
                raise ValueError('هذه الطريقة تتطلب صفوف الضيوف ولا تقبل أعدادًا تلقائية')
            normalized = []
            for index, row in enumerate(self.rows):
                metadata = row.get('metadata')
                if metadata is not None and not isinstance(metadata, dict):
                    raise ValueError(f'السطر {index+1}: البيانات الإضافية غير صالحة')
                normalized.append(_normalize_invitation_row({**row, 'require_rsvp': self.require_rsvp,
                    'metadata': {**(metadata or {}), 'require_rsvp': self.require_rsvp}}, index))
            self.rows = normalized
            if self.source_row_numbers is not None and (len(self.source_row_numbers)!=len(normalized) or len(set(self.source_row_numbers))!=len(normalized)):
                raise ValueError('أرقام صفوف المصدر يجب أن تكون فريدة وتطابق عدد الصفوف')
        try:
            json.dumps(self.model_dump(mode='json'), allow_nan=False)
        except ValueError:
            raise ValueError('الحقول الإضافية تحتوي على قيمة غير صالحة مثل NaN أو Infinity')
        classes = {r['ticket_class'] for r in self.normalized_rows()}
        if self.mode == 'designed' and (set(self.templates) != classes):
            raise ValueError('اختر قالبًا لكل فئة موجودة في البيانات دون استبعاد صفوف تلقائيًا')
        if self.mode == 'quick' and self.templates:
            raise ValueError('التوليد السريع لا يتطلب قوالب تصميم')
        return self

    def normalized_rows(self):
        if self.source != 'count':
            return self.rows or []
        rows = []
        for ticket_class, amount in [('vip', self.count.vip_count), ('normal', self.count.normal_count)]:
            for index in range(amount):
                rows.append(_normalize_invitation_row({'guest_name': f'{self.count.guest_name_prefix.strip()} {ticket_class.upper() if ticket_class == "vip" else ""} {index+1}'.replace('  ', ' '),
                    'ticket_class': ticket_class, 'guest_count': 1, 'require_rsvp': False}, len(rows)))
        return rows


class GenerationOperationRead(BaseModel):
    contract_version: Literal[1] = 1
    id: UUID
    event_id: UUID
    mode: Literal['quick','designed']
    source: Literal['count','names','excel']
    status: Literal['queued','running','completed','partial','failed','cancel_requested','cancelled']
    cards_count: int
    people_count: int
    vip_cards: int
    normal_cards: int
    vip_people: int
    normal_people: int
    cards_done: int
    cards_failed: int
    files_done: int = 0
    files_failed: int = 0
    files_expected: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    replayed: bool = False
    status_url: str


class StagedGenerationCreate(BaseModel):
    """Only server-side selection identity and rendering options cross the wire."""
    source_revision: int = Field(ge=1,strict=True)
    mode: Literal['quick','designed'] = 'quick'
    templates: dict[Literal['vip','normal'],UUID] = Field(default_factory=dict)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    output_formats: list[Literal['pdf','zip']] = Field(default_factory=lambda:['pdf','zip'])
    require_rsvp: bool = Field(False,strict=True)

    @model_validator(mode='after')
    def unique_formats(self):
        if len(set(self.output_formats))!=len(self.output_formats):
            raise ValueError('Repeated output formats')
        return self
