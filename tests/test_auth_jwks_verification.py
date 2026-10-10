"""Coverage for the RS256/ES256 JWKS verification path in app/auth.py.

This path was migrated from python-jose to PyJWT this session (python-jose
had an unpatched CVE in its HMAC/asymmetric-key handling, CVE-2026-85394, and
pulled in a second unpatched CVE via its `ecdsa` dependency). The HS256 path
already had test coverage; this path — Supabase's asymmetric signing keys via
JWKS — had none, despite being a real production configuration, so it is
exercised directly here against real generated keypairs rather than assumed
to work from the HS256 tests alone."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

pytestmark = pytest.mark.unit


def _claims(sub=None):
    from app.config import get_settings
    now = datetime.now(timezone.utc)
    return {
        "sub": str(sub or uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "email": "jwks-test@example.com",
        "iss": get_settings().resolved_jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-rsa-kid-1"
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk_dict["kid"] = kid
    jwk_dict["alg"] = "RS256"
    return private_key, kid, jwk_dict


@pytest.fixture
def ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    kid = "test-ec-kid-1"
    jwk_dict = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    jwk_dict["kid"] = kid
    jwk_dict["alg"] = "ES256"
    return private_key, kid, jwk_dict


@pytest.mark.asyncio
async def test_valid_rs256_token_is_accepted_via_jwks(monkeypatch, rsa_keypair):
    from app import auth
    private_key, kid, jwk_dict = rsa_keypair
    monkeypatch.setattr(auth, "get_supabase_jwks", _async_return({kid: jwk_dict}))

    user_id = uuid4()
    token = jwt.encode(_claims(user_id), private_key, algorithm="RS256", headers={"kid": kid})

    payload = await auth.decode_supabase_jwt(token)
    assert payload["sub"] == str(user_id)


@pytest.mark.asyncio
async def test_valid_es256_token_is_accepted_via_jwks(monkeypatch, ec_keypair):
    from app import auth
    private_key, kid, jwk_dict = ec_keypair
    monkeypatch.setattr(auth, "get_supabase_jwks", _async_return({kid: jwk_dict}))

    user_id = uuid4()
    token = jwt.encode(_claims(user_id), private_key, algorithm="ES256", headers={"kid": kid})

    payload = await auth.decode_supabase_jwt(token)
    assert payload["sub"] == str(user_id)


@pytest.mark.asyncio
async def test_rs256_token_signed_by_a_different_key_is_rejected(monkeypatch, rsa_keypair):
    """A token claiming our known kid but signed with an attacker's own key must fail."""
    from app import auth
    _, kid, jwk_dict = rsa_keypair
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, "get_supabase_jwks", _async_return({kid: jwk_dict}))

    token = jwt.encode(_claims(), attacker_key, algorithm="RS256", headers={"kid": kid})

    with pytest.raises(HTTPException) as exc:
        await auth.decode_supabase_jwt(token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rs256_token_with_unknown_kid_is_rejected(monkeypatch, rsa_keypair):
    from app import auth
    private_key, _, jwk_dict = rsa_keypair
    monkeypatch.setattr(auth, "get_supabase_jwks", _async_return({"some-other-kid": jwk_dict}))

    token = jwt.encode(_claims(), private_key, algorithm="RS256", headers={"kid": "unknown-kid"})

    with pytest.raises(HTTPException) as exc:
        await auth.decode_supabase_jwt(token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_token_with_disallowed_algorithm_is_rejected(monkeypatch):
    from app import auth
    token = jwt.encode(_claims(), "irrelevant", algorithm="HS384")

    with pytest.raises(HTTPException) as exc:
        await auth.decode_supabase_jwt(token)
    assert exc.value.status_code == 401


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner
