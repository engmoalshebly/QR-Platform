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
