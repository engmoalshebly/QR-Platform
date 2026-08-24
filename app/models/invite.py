from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum
from app.models.membership import MembershipRole

__all__ = [
    "InviteStatus",
    "InviteCreate",
    "InviteRead",
]


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    expired = "expired"
    revoked = "revoked"


class InviteMembershipRole(str, Enum):
    """Roles that may be granted through the self-service invite flow.

    Ownership transfer is intentionally excluded: it requires an explicit
    owner-controlled handover rather than an email token.
    """

    admin = "admin"
    member = "member"
    viewer = "viewer"


class InviteCreate(BaseModel):
    email: EmailStr
    role: InviteMembershipRole = InviteMembershipRole.member


class InviteRead(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    role: MembershipRole
    status: InviteStatus
    invited_by: UUID
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    created_at: datetime
