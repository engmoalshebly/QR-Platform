from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Optional
from uuid import UUID
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class EventStatus(str, Enum):
    draft = "draft"
    published = "published"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class TicketClass(str, Enum):
    vip = "vip"
    normal = "normal"


# ── Event Categories ──

class EventCategoryRead(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    name: str
    name_ar: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: int = 0
    is_system: bool = False
    created_at: datetime


class EventCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    name_ar: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = "#6366f1"


# ── Event Types ──

class EventTypeRead(BaseModel):
    id: UUID
    category_id: UUID
    tenant_id: Optional[UUID] = None
    name: str
    name_ar: Optional[str] = None
    description: Optional[str] = None
    is_system: bool = False
    created_at: datetime


class EventTypeCreate(BaseModel):
    category_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    name_ar: Optional[str] = None
    description: Optional[str] = None


# ── Events ──

class EventCreate(BaseModel):
    event_type_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    title: str = Field(..., min_length=1, max_length=255)
    title_ar: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=10000)
    start_date: datetime
    end_date: Optional[datetime] = None
    timezone: str = Field("Asia/Riyadh", min_length=1, max_length=64)
    venue_name: Optional[str] = Field(None, max_length=255)
    venue_name_ar: Optional[str] = Field(None, max_length=255)
    venue_address: Optional[str] = Field(None, max_length=1000)
    venue_city: Optional[str] = Field(None, max_length=120)
    venue_country: str = Field("SA", min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    venue_map_url: Optional[str] = Field(None, max_length=2048, pattern=r"^https://")
    venue_lat: Optional[float] = Field(None, ge=-90, le=90)
    venue_lng: Optional[float] = Field(None, ge=-180, le=180)
    vip_quota: int = Field(0, ge=0)
    normal_quota: int = Field(100, ge=0)
    capacity: Optional[int] = Field(None, gt=0)
    vip_capacity: Optional[int] = Field(None, ge=0)
    normal_capacity: Optional[int] = Field(None, ge=0)
    allow_rsvp: bool = False
    allow_plus_one: bool = False
    allow_reentry: bool = False
    require_name: bool = True
    cover_image_url: Optional[str] = Field(None, max_length=2048)
    theme_color: str = Field("#6366f1", pattern=r"^#[0-9A-Fa-f]{6}$")
    team_id: Optional[UUID] = None
    metadata: Optional[dict] = None

    @model_validator(mode="after")
    def validate_schedule_and_capacity(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone")
        if self.end_date is not None and self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date")

        class_capacity = sum(
            value for value in (self.vip_capacity, self.normal_capacity)
            if value is not None
        )
        if self.capacity is not None and class_capacity > self.capacity:
            raise ValueError("VIP and normal capacities cannot exceed total capacity")

        if self.vip_capacity is not None and self.vip_quota > 0 and self.vip_quota > self.vip_capacity:
            raise ValueError("VIP quota cannot exceed VIP capacity")
        if self.normal_capacity is not None and self.normal_quota > 0 and self.normal_quota > self.normal_capacity:
            raise ValueError("normal quota cannot exceed normal capacity")
        return self


class EventRead(BaseModel):
    id: UUID
    tenant_id: UUID
    event_type_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    title: str
    title_ar: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None
    start_date: datetime
    end_date: Optional[datetime] = None
    timezone: str
    venue_name: Optional[str] = None
    venue_name_ar: Optional[str] = None
    venue_address: Optional[str] = None
    venue_city: Optional[str] = None
    venue_country: Optional[str] = None
    venue_map_url: Optional[str] = None
    venue_lat: Optional[float] = None
    venue_lng: Optional[float] = None
    vip_quota: int
    normal_quota: int
    capacity: Optional[int] = None
    vip_capacity: Optional[int] = None
    normal_capacity: Optional[int] = None
    allow_rsvp: bool
    allow_plus_one: bool
    allow_reentry: bool
    require_name: bool
    cover_image_url: Optional[str] = None
    theme_color: Optional[str] = None
    status: str
    published_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[UUID] = None
    created_by: Optional[UUID] = None
    team_id: Optional[UUID] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class EventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    title_ar: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=10000)
    event_type_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    timezone: Optional[str] = Field(None, min_length=1, max_length=64)
    venue_name: Optional[str] = None
    venue_name_ar: Optional[str] = None
    venue_address: Optional[str] = None
    venue_city: Optional[str] = None
    venue_country: Optional[str] = None
    venue_map_url: Optional[str] = Field(None, max_length=2048, pattern=r"^https://")
    venue_lat: Optional[float] = Field(None, ge=-90, le=90)
    venue_lng: Optional[float] = Field(None, ge=-180, le=180)
    vip_quota: Optional[int] = Field(None, ge=0)
    normal_quota: Optional[int] = Field(None, ge=0)
    capacity: Optional[int] = Field(None, gt=0)
    vip_capacity: Optional[int] = Field(None, ge=0)
    normal_capacity: Optional[int] = Field(None, ge=0)
    allow_rsvp: Optional[bool] = None
    allow_plus_one: Optional[bool] = None
    allow_reentry: Optional[bool] = None
    require_name: Optional[bool] = None
    cover_image_url: Optional[str] = None
    theme_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    team_id: Optional[UUID] = None
    metadata: Optional[dict] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("timezone must be a valid IANA timezone")
        return value


# ── Event Gates ──

class EventGateRead(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    name_ar: Optional[str] = None
    allowed_classes: Optional[list] = None
    is_active: bool
    created_at: datetime
    team_id: Optional[UUID] = None
    assigned_users: list[UUID] = []


class EventGateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    name_ar: Optional[str] = None
    allowed_classes: list[str] = ["normal", "vip"]
    team_id: Optional[UUID] = None
    assigned_users: Optional[list[UUID]] = None

    @model_validator(mode="after")
    def validate_gate_scope(self):
        allowed = {"normal", "vip"}
        if not self.allowed_classes or any(item not in allowed for item in self.allowed_classes):
            raise ValueError("allowed_classes may contain only normal and vip")
        if len(self.allowed_classes) != len(set(self.allowed_classes)):
            raise ValueError("allowed_classes cannot contain duplicates")
        if self.assigned_users and len(self.assigned_users) != len(set(self.assigned_users)):
            raise ValueError("assigned_users cannot contain duplicates")
        return self


# ── Event Stats ──

class EventStats(BaseModel):
    vip_quota_used: int = 0
    normal_quota_used: int = 0
    total_invitations: int = 0
    vip_count: int = 0
    normal_count: int = 0
    sent_count: int = 0
    viewed_count: int = 0
    accepted_count: int = 0
    declined_count: int = 0
    checked_in_count: int = 0
    revoked_count: int = 0
    invited_people: int = 0
    accepted_people: int = 0
    checked_in_people: int = 0
    capacity: Optional[int] = None


# ── Event Assets ──

class EventAssetRead(BaseModel):
    id: UUID
    event_id: UUID
    asset_type: str
    file_url: str
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    size: int = 0
    metadata: Optional[dict] = None
    sort_order: int = 0
    created_at: datetime


class EventAssetCreate(BaseModel):
    event_id: UUID
    asset_type: Literal["cover_image", "invitation_design", "logo", "background", "attachment"]
    file_url: str = Field(min_length=1, max_length=2048)
    file_name: Optional[str] = Field(None, max_length=255)
    mime_type: Optional[str] = Field(None, max_length=120)
    size: int = Field(0, ge=0)
    metadata: Optional[dict] = None
    sort_order: int = 0


# ── Event Status Transition ──

class EventStatusTransitionRequest(BaseModel):
    new_status: Literal["published", "active", "completed", "cancelled"]
