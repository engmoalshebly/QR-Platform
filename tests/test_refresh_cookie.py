"""Refresh tokens reach browsers only through an HttpOnly cookie.

Supabase is replaced by a fake, so these tests check the transport rules and not
the identity provider:

* browsers get the token in a cookie, never in the JSON body;
* a cookie-based refresh needs the CSRF header that a cross-site form cannot send;
* native clients opt in with X-Refresh-Transport: body;
* a rejected refresh clears the cookie.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

COOKIE_NAME = "qentry_rt"
CSRF = {"X-Requested-With": "qentry"}


def _fake_supabase(refresh_result=None, error: Exception | None = None):
    def refresh_session(token):
        if error:
            raise error
        return refresh_result

    return SimpleNamespace(auth=SimpleNamespace(refresh_session=refresh_session))


def _ok_result(new_refresh: str = "refresh-new"):
    return SimpleNamespace(
        user=SimpleNamespace(id="11111111-1111-1111-1111-111111111111"),
        session=SimpleNamespace(access_token="access-new", refresh_token=new_refresh),
    )


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c


@pytest.mark.asyncio
async def test_refresh_without_any_token_is_unauthorized(client):
    resp = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cookie_refresh_without_csrf_header_is_forbidden(client):
    client.cookies.set(COOKIE_NAME, "refresh-old", path="/api/v1/auth")
    with patch("app.routes.auth.get_supabase_client", return_value=_fake_supabase(_ok_result())):
        resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_browser_refresh_keeps_token_out_of_body_and_rotates_cookie(client):
    client.cookies.set(COOKIE_NAME, "refresh-old", path="/api/v1/auth")
    with patch("app.routes.auth.get_supabase_client", return_value=_fake_supabase(_ok_result())):
        resp = await client.post("/api/v1/auth/refresh", headers=CSRF)

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access-new"
    assert body["refresh_token"] is None

    set_cookie = resp.headers["set-cookie"]
    assert f"{COOKIE_NAME}=refresh-new" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.asyncio
async def test_native_client_receives_token_in_body_when_it_opts_in(client):
    with patch("app.routes.auth.get_supabase_client", return_value=_fake_supabase(_ok_result("refresh-native"))):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "refresh-old"},
            headers={"X-Refresh-Transport": "body"},
        )
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] == "refresh-native"


@pytest.mark.asyncio
async def test_body_token_without_opt_in_is_not_echoed(client):
    with patch("app.routes.auth.get_supabase_client", return_value=_fake_supabase(_ok_result("refresh-x"))):
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-old"})
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] is None
    assert f"{COOKIE_NAME}=refresh-x" in resp.headers["set-cookie"]


@pytest.mark.asyncio
async def test_rejected_refresh_clears_the_cookie(client):
    client.cookies.set(COOKIE_NAME, "refresh-expired", path="/api/v1/auth")
    with patch("app.routes.auth.get_supabase_client",
               return_value=_fake_supabase(error=RuntimeError("expired"))):
        resp = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert resp.status_code == 401
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{COOKIE_NAME}=" in set_cookie and ("Max-Age=0" in set_cookie or "expires=" in set_cookie.lower())
