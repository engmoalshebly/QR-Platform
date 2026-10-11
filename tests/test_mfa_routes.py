"""TOTP enrolment/verification routes: behaviour around GoTrue, no live services."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.database import get_privileged_db
from app.routes import mfa

FACTOR = "11111111-1111-1111-1111-111111111111"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload = status_code, payload or {}

    def json(self):
        return self._payload


class _FakeDb:
    async def commit(self):
        return None


def _client(monkeypatch, *, aal="aal1", factors=(), gotrue=None):
    calls = []

    async def fake_gotrue(method, path, token, json=None):
        calls.append((method, path))
        if path == "/user":
            return _Resp(200, {"factors": list(factors)})
        return (gotrue or {}).get((method, path.split("/")[-1] if "/factors/" in path else path)) \
            or _Resp(200, {})

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(mfa, "_gotrue", fake_gotrue)
    monkeypatch.setattr(mfa, "_enforce_public_rate_limit", noop)
    monkeypatch.setattr(mfa, "log_audit", noop)
    app = FastAPI()
    app.include_router(mfa.router, prefix="/api/v1")
    user = CurrentUser(id="22222222-2222-2222-2222-222222222222", email="a@b.c", aal=aal)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_privileged_db] = lambda: _FakeDb()
    return TestClient(app), calls


H = {"Authorization": "Bearer t"}


@pytest.mark.unit
def test_enrol_refused_from_aal1_when_a_factor_is_already_verified(monkeypatch):
    client, calls = _client(monkeypatch, aal="aal1",
                            factors=[{"id": FACTOR, "factor_type": "totp", "status": "verified"}])
    r = client.post("/api/v1/auth/mfa/enroll", headers=H)
    assert r.status_code == 403
    assert ("POST", "/factors") not in calls  # nothing was created


@pytest.mark.unit
def test_enrol_returns_secret_and_clears_abandoned_factors(monkeypatch):
    stale = "33333333-3333-3333-3333-333333333333"
    client, calls = _client(
        monkeypatch, factors=[{"id": stale, "factor_type": "totp", "status": "unverified"}],
        gotrue={("POST", "/factors"): _Resp(200, {"id": FACTOR, "totp": {
            "qr_code": "data:image/svg+xml;utf-8,<svg/>", "secret": "ABC", "uri": "otpauth://x"}})},
    )
    r = client.post("/api/v1/auth/mfa/enroll", headers=H)
    assert r.status_code == 200
    assert r.json()["factor_id"] == FACTOR and r.json()["secret"] == "ABC"
    assert ("DELETE", f"/factors/{stale}") in calls


@pytest.mark.unit
def test_verify_rejects_a_factor_that_is_not_the_callers(monkeypatch):
    client, _ = _client(monkeypatch, factors=[])
    r = client.post("/api/v1/auth/mfa/verify", headers=H, json={"factor_id": FACTOR, "code": "123456"})
    assert r.status_code == 404


@pytest.mark.unit
def test_verify_wrong_code_is_400_without_a_session(monkeypatch):
    client, _ = _client(
        monkeypatch, factors=[{"id": FACTOR, "factor_type": "totp", "status": "verified"}],
        gotrue={("POST", "challenge"): _Resp(200, {"id": "c1"}),
                ("POST", "verify"): _Resp(400, {"msg": "invalid"})},
    )
    r = client.post("/api/v1/auth/mfa/verify", headers=H, json={"factor_id": FACTOR, "code": "000000"})
    assert r.status_code == 400
    assert "qentry_rt" not in r.headers.get("set-cookie", "")


@pytest.mark.unit
def test_verify_success_returns_new_token_and_sets_the_refresh_cookie(monkeypatch):
    client, _ = _client(
        monkeypatch, factors=[{"id": FACTOR, "factor_type": "totp", "status": "verified"}],
        gotrue={("POST", "challenge"): _Resp(200, {"id": "c1"}),
                ("POST", "verify"): _Resp(200, {"access_token": "AAL2TOKEN", "refresh_token": "RT"})},
    )
    r = client.post("/api/v1/auth/mfa/verify", headers=H, json={"factor_id": FACTOR, "code": "123456"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "AAL2TOKEN"
    assert r.json().get("refresh_token") is None          # cookie transport only
    assert "qentry_rt=RT" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


@pytest.mark.unit
@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", ""])
def test_verify_rejects_malformed_codes(monkeypatch, code):
    client, _ = _client(monkeypatch)
    r = client.post("/api/v1/auth/mfa/verify", headers=H, json={"factor_id": FACTOR, "code": code})
    assert r.status_code == 422
