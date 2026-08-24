from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum

__all__ = [
    "MembershipRole",
    "MembershipStatus",
    "MembershipRead",
    "MembershipUpdate",
    "MemberWithProfile",
]


class MembershipRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class MembershipStatus(str, Enum):
    active = "active"
    invited = "invited"
    disabled = "disabled"


class MembershipRead(BaseModel):
    tenant_id: UUID
    user_id: UUID
    role: MembershipRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime


class MembershipUpdate(BaseModel):
    role: Optional[MembershipRole] = None
    status: Optional[MembershipStatus] = None


class MemberWithProfile(BaseModel):
    tenant_id: UUID
    user_id: UUID
    role: MembershipRole
    status: MembershipStatus
    full_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
