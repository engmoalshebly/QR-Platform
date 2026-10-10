from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class TemplateType(str, Enum):
    quick = "quick"
    designed = "designed"


class ElementType(str, Enum):
    guest_name = "guest_name"
    event_title = "event_title"
    event_date = "event_date"
    event_time = "event_time"
    event_location = "event_location"
    event_address = "event_address"
    qr_code = "qr_code"
    barcode = "barcode"
    seat_number = "seat_number"
    gate = "gate"
    hall = "hall"
    table_number = "table_number"
    custom_text = "custom_text"
    dynamic_text = "dynamic_text"
    image = "image"


# ── Templates ──

class TemplateCreate(BaseModel):
    event_id: Optional[UUID] = None
    name: str = Field(..., min_length=1, max_length=255)
    template_type: str = Field("quick", pattern="^(quick|designed)$")
    ticket_class: str = Field("normal", pattern="^(vip|normal)$")
    width_px: int = 1080
    height_px: int = 1920
    orientation: str = "portrait"
    background_url: Optional[str] = None
    background_color: str = "#ffffff"
    quick_style: Optional[dict] = None
    is_default: bool = False
    metadata: Optional[dict] = None


class TemplateRead(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: Optional[UUID] = None
    name: str
    template_type: str
    ticket_class: str
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    orientation: Optional[str] = None
    background_url: Optional[str] = None
    background_color: Optional[str] = None
    quick_style: Optional[dict] = None
    is_default: bool
    is_active: bool
    created_by: Optional[UUID] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    template_type: Optional[str] = Field(None, pattern="^(quick|designed)$")
    ticket_class: Optional[str] = Field(None, pattern="^(vip|normal)$")
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    orientation: Optional[str] = None
    background_url: Optional[str] = None
    background_color: Optional[str] = None
    quick_style: Optional[dict] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    metadata: Optional[dict] = None


# ── Template Elements ──

_ELEMENT_TYPE_PATTERN = "^(" + "|".join(e.value for e in ElementType) + ")$"


class ElementCreate(BaseModel):
    element_type: str = Field(..., pattern=_ELEMENT_TYPE_PATTERN)
    label: Optional[str] = None
    data_key: Optional[str] = None  # e.g. guest.name, invite.barcode_payload, guest.custom_fields.seat
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.5, ge=0, le=1)
    width: float = Field(0.2, ge=0, le=1)
    height: float = Field(0.05, ge=0, le=1)
    rotation: float = 0
    font_family: str = "Cairo"
    font_asset_id: Optional[UUID] = None  # reference to uploaded font in template_assets
    font_size: float = 24
    font_weight: str = "normal"
    font_color: str = "#000000"
    text_align: str = "center"
    text_direction: str = "rtl"
    line_height: float = 1.2
    letter_spacing: float = 0
    qr_size: float = 0.15
    qr_color: str = "#000000"
    qr_bg_color: str = "#ffffff"
    qr_error_level: str = "M"
    maintain_square: bool = True  # ✅ جديد: احفظ النسبة المربعة للـ QR
    static_content: Optional[str] = None
    is_visible: bool = True
    z_index: int = 0
    sort_order: int = 0
    slot_index: Optional[int] = None  # Links dynamic_text to a barcode slot (0, 1, 2...)


class ElementRead(BaseModel):
    id: UUID
    template_id: UUID
    element_type: str
    label: Optional[str] = None
    data_key: Optional[str] = None
    x: float
    y: float
    width: float
    height: float
    rotation: Optional[float] = 0
    font_family: Optional[str] = None
    font_asset_id: Optional[UUID] = None
    font_size: Optional[float] = None
    font_weight: Optional[str] = None
    font_color: Optional[str] = None
    text_align: Optional[str] = None
    text_direction: Optional[str] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    qr_size: Optional[float] = None
    qr_color: Optional[str] = None
    qr_bg_color: Optional[str] = None
    qr_error_level: Optional[str] = None
    maintain_square: Optional[bool] = True  # ✅ جديد
    static_content: Optional[str] = None
    is_visible: bool
    z_index: int
    sort_order: int
    slot_index: Optional[int] = None  # Links dynamic_text to a barcode slot
    created_at: datetime


class ElementUpdate(BaseModel):
    element_type: Optional[str] = Field(None, pattern=_ELEMENT_TYPE_PATTERN)
    label: Optional[str] = None
    data_key: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    rotation: Optional[float] = None
    font_family: Optional[str] = None
    font_asset_id: Optional[UUID] = None
    font_size: Optional[float] = None
    font_weight: Optional[str] = None
    font_color: Optional[str] = None
    text_align: Optional[str] = None
    text_direction: Optional[str] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    qr_size: Optional[float] = None
    qr_color: Optional[str] = None
    qr_bg_color: Optional[str] = None
    qr_error_level: Optional[str] = None
    maintain_square: Optional[bool] = None  # ✅ جديد
    static_content: Optional[str] = None
    is_visible: Optional[bool] = None
    z_index: Optional[int] = None
    sort_order: Optional[int] = None
    slot_index: Optional[int] = None  # Links dynamic_text to a barcode slot


# ── Template Assets ──

class AssetRead(BaseModel):
    id: UUID
    template_id: UUID
    asset_type: str
    file_url: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    metadata: Optional[dict] = None
    sort_order: int = 0
    created_at: datetime
