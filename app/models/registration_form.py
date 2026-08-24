from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional, List, Any
from uuid import UUID
from datetime import datetime
from app.models.event import TicketClass

class RegistrationFormField(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    type: Literal["text", "number", "email", "phone", "select", "date", "checkbox"]
    label: str = Field(min_length=1, max_length=120)
    label_en: Optional[str] = Field(None, max_length=120)
    required: bool = False
    system: bool = False  # True for built-in fields like guest_name, guest_phone, guest_email
    options: Optional[List[str]] = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_options(self):
        if self.type == "select" and not self.options:
            raise ValueError("select fields require at least one option")
        if self.options and any(not value.strip() or len(value) > 120 for value in self.options):
            raise ValueError("field options must be non-empty and at most 120 characters")
        return self

class RegistrationFormRead(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: UUID
    is_enabled: bool
    barcode_generation_mode: str
    default_ticket_class: TicketClass
    default_template_id: Optional[UUID] = None
    success_message_ar: Optional[str] = None
    success_message_en: Optional[str] = None
    pending_approval_message_ar: Optional[str] = None
    pending_approval_message_en: Optional[str] = None
    fields: List[RegistrationFormField] = []
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class RegistrationFormCreate(BaseModel):
    is_enabled: bool = False
    barcode_generation_mode: Literal["immediate", "deferred"] = "immediate"
    default_ticket_class: TicketClass = TicketClass.normal
    default_template_id: Optional[UUID] = None
    success_message_ar: Optional[str] = None
    success_message_en: Optional[str] = None
    pending_approval_message_ar: Optional[str] = None
    pending_approval_message_en: Optional[str] = None
    fields: List[RegistrationFormField] = Field(default_factory=list, max_length=50)
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_unique_fields(self):
        ids = [field.id for field in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("registration field ids must be unique")
        return self

class RegistrationFormUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    barcode_generation_mode: Optional[str] = None
    default_ticket_class: Optional[TicketClass] = None
    default_template_id: Optional[UUID] = None
    success_message_ar: Optional[str] = None
    success_message_en: Optional[str] = None
    pending_approval_message_ar: Optional[str] = None
    pending_approval_message_en: Optional[str] = None
    fields: Optional[List[RegistrationFormField]] = None
    expires_at: Optional[datetime] = None

class PublicRegistrationSubmit(BaseModel):
    registration_request_id: UUID
    guest_name: str = Field(..., min_length=1, max_length=255)
    guest_phone: str = Field(..., min_length=8, max_length=40, pattern=r"^\+?[0-9][0-9 ()-]{6,38}$")
    guest_email: Optional[str] = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    custom_answers: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_answers_size(self):
        answers = self.custom_answers or {}
        if len(answers) > 50:
            raise ValueError("too many custom answers")
        for value in answers.values():
            if isinstance(value, str) and len(value) > 2000:
                raise ValueError("custom answer is too long")
            if isinstance(value, list) and len(value) > 100:
                raise ValueError("custom answer contains too many values")
            if isinstance(value, (dict, tuple, set)):
                raise ValueError("unsupported custom answer type")
        return self
