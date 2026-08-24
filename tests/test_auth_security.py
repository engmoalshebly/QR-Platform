"""Regression coverage for authentication and platform-admin security."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from jose import jwt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authentication_rejects_hs256_when_no_shared_secret(monkeypatch):
    """An empty configuration value must never become an HMAC signing key."""
    from app import auth

    token = jwt.encode(
        {"sub": str(uuid4()), "aud": "authenticated"},
        "",
        algorithm="HS256",
    )
    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", "")

    with pytest.raises(HTTPException) as exc:
        await auth.decode_supabase_jwt(token)

    assert exc.value.status_code == 401


@pytest.mark.unit
def test_current_user_carries_the_mfa_assurance_level():
    from app.auth import CurrentUser

    assert CurrentUser(id=uuid4(), aal="aal2").aal == "aal2"
