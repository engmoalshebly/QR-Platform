"""The shared service-role client must never adopt a user's session token."""
import types

import pytest

from app import database


# supabase-py validates that keys look like JWTs.
SERVICE_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2VydmljZS1zaWduYXR1cmU"
ANON_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.YW5vbi1zaWduYXR1cmU"


class _Session:
    access_token = "USER-ACCESS-TOKEN"


@pytest.mark.unit
def test_shared_admin_client_keeps_its_service_key_after_a_user_signs_in(monkeypatch):
    monkeypatch.setattr(database, "_supabase_admin", None)
    monkeypatch.setattr(database.settings, "supabase_url", "https://example.invalid")
    monkeypatch.setattr(database.settings, "supabase_service_role_key", SERVICE_KEY)

    admin = database.get_supabase_admin()
    before = admin.options.headers["Authorization"]
    assert before == f"Bearer {SERVICE_KEY}"

    # What gotrue does after sign_in_with_password / refresh_session.
    admin.auth._notify_all_subscribers("SIGNED_IN", _Session())
    admin.auth._notify_all_subscribers("TOKEN_REFRESHED", _Session())

    assert admin.options.headers["Authorization"] == before
    assert "USER-ACCESS-TOKEN" not in admin.options.headers["Authorization"]


@pytest.mark.unit
def test_auth_clients_are_never_shared_between_requests(monkeypatch):
    monkeypatch.setattr(database.settings, "supabase_url", "https://example.invalid")
    monkeypatch.setattr(database.settings, "supabase_anon_key", ANON_KEY)
    first, second = database.new_auth_client(), database.get_supabase_client()
    assert first is not second
    assert first is not database.get_supabase_admin()


class _AuthStub:
    def __init__(self):
        self.refreshed = None

    def refresh_session(self, token):
        self.refreshed = token
        session = types.SimpleNamespace(access_token="NEW-ACCESS", refresh_token="NEW-REFRESH")
        return types.SimpleNamespace(user=types.SimpleNamespace(id="u-1"), session=session)


@pytest.mark.unit
def test_refresh_endpoint_uses_a_fresh_auth_client_not_the_shared_admin(monkeypatch):
    """Regression: /auth/refresh once ran on the shared admin client (and a later
    edit referenced an unimported helper, giving HTTP 500)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import auth as auth_routes

    stub = types.SimpleNamespace(auth=_AuthStub())
    monkeypatch.setattr(auth_routes, "get_supabase_client", lambda: stub)
    monkeypatch.setattr(auth_routes, "get_supabase_admin",
                        lambda: (_ for _ in ()).throw(AssertionError("admin client used for a refresh")))
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/api/v1")

    r = TestClient(app).post("/api/v1/auth/refresh", json={"refresh_token": "RT-1"})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"] == "NEW-ACCESS"
    assert stub.auth.refreshed == "RT-1"
