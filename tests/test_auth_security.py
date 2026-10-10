"""Regression coverage for authentication and platform-admin security."""

import base64
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _forge_hs256_token_with_empty_secret(claims: dict) -> str:
    """Hand-craft an HS256 JWT signed with an empty-string HMAC secret.

    PyJWT itself refuses to *encode* with an empty key (InvalidKeyError), which
    is correct behavior — but an attacker crafting raw bytes isn't bound by
    that refusal, so the decode path must independently reject this.
    """
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(b"", signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64url(signature)}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authentication_rejects_hs256_when_no_shared_secret(monkeypatch):
    """An empty configuration value must never become an HMAC signing key."""
    from app import auth

    token = _forge_hs256_token_with_empty_secret({"sub": str(uuid4()), "aud": "authenticated"})
    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", "")

    with pytest.raises(HTTPException) as exc:
        await auth.decode_supabase_jwt(token)

    assert exc.value.status_code == 401


@pytest.mark.unit
def test_current_user_carries_the_mfa_assurance_level():
    from app.auth import CurrentUser

    assert CurrentUser(id=uuid4(), aal="aal2").aal == "aal2"
