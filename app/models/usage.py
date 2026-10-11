from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import date, datetime

__all__ = [
    "UsageCounterRead",
    "UsageCheckResult",
    "UsageLimitInfo",
]


class UsageCounterRead(BaseModel):
    tenant_id: UUID
    period_start: date
    period_end: date
    key: str
    value: int
    updated_at: datetime


class UsageLimitInfo(BaseModel):
    key: str
    limit: int          # -1 = unlimited
    current_usage: int
    remaining: int      # -1 = unlimited
    is_exceeded: bool


class UsageCheckResult(BaseModel):
    tenant_id: UUID
    plan_code: str
    limits: list[UsageLimitInfo]
    any_exceeded: bool
    period_start: date
    resets_at: datetime
    timezone: str
