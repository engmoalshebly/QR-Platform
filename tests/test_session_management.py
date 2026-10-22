"""Logout, password change and login hardening: behaviour around GoTrue, no live services."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.database import get_privileged_db
from app.routes import auth as auth_routes

USER = CurrentUser(id="22222222-2222-2222-2222-222222222222", email="a@b.c", aal="aal1")
H = {"Authorization": "Bearer access-jwt"}


class _FakeDb:
    async def commit(self):
        return None


class _Admin:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail
        self.auth = SimpleNamespace(admin=SimpleNamespace(
            sign_out=self._sign_out,
            update_user_by_id=lambda *a, **k: None,
        ))

    def _sign_out(self, jwt, scope="global"):
        self.calls.append((jwt, scope))
        if self.fail:
            raise RuntimeError("gotrue down")


def _client(monkeypatch, admin, audits=None):
    async def noop(*a, **k):
        return None

    async def audit(db, **kw):
        if audits is not None:
            audits.append(kw)

    monkeypatch.setattr(auth_routes, "get_supabase_admin", lambda: admin)
    monkeypatch.setattr(auth_routes, "log_audit", audit)
    monkeypatch.setattr(auth_routes, "_enforce_public_rate_limit", noop)
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_privileged_db] = lambda: _FakeDb()
    return TestClient(app)


def test_logout_revokes_current_session_with_the_callers_jwt(monkeypatch):
    admin, audits = _Admin(), []
    res = _client(monkeypatch, admin, audits).post("/api/v1/auth/logout", headers=H)
    assert res.status_code == 200
    assert admin.calls == [("access-jwt", "local")]
    assert audits[0]["action"] == "auth.logout" and audits[0]["metadata"]["server_revoked"] is True
    assert "qentry_rt=" in res.headers["set-cookie"]


def test_logout_all_uses_global_scope(monkeypatch):
    admin = _Admin()
    res = _client(monkeypatch, admin).post("/api/v1/auth/logout-all", headers=H)
    assert res.status_code == 200 and admin.calls == [("access-jwt", "global")]


def test_logout_reports_a_failed_server_revocation(monkeypatch):
    admin, audits = _Admin(fail=True), []
    res = _client(monkeypatch, admin, audits).post("/api/v1/auth/logout", headers=H)
    assert res.status_code == 200
    assert "تعذر إلغاء الجلسة" in res.json()["message"]
    assert audits[0]["metadata"]["server_revoked"] is False
    assert "qentry_rt=" in res.headers["set-cookie"]  # the browser is still signed out


def test_change_password_revokes_other_sessions_and_the_verification_session(monkeypatch):
    admin = _Admin()
    verification = SimpleNamespace(session=SimpleNamespace(access_token="throwaway-jwt"))
    anon = SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=lambda creds: verification))
    monkeypatch.setattr(auth_routes, "get_supabase_client", lambda: anon)
    monkeypatch.setattr(auth_routes, "send_password_changed_email", lambda *a, **k: None)
    res = _client(monkeypatch, admin).post(
        "/api/v1/auth/change-password", headers=H,
        json={"current_password": "old-password-123", "new_password": "N3w-password-Strong!"},
    )
    assert res.status_code == 200, res.text
    assert ("throwaway-jwt", "local") in admin.calls
    assert ("access-jwt", "others") in admin.calls


@pytest.mark.parametrize("status,code", [(400, 401), (401, 401), (429, 429), (500, 503), (None, 503)])
def test_login_failure_separates_bad_credentials_from_outage(status, code):
    exc = SimpleNamespace(status=status)
    error = auth_routes._login_failure(exc)  # type: ignore[arg-type]
    assert isinstance(error, HTTPException) and error.status_code == code
