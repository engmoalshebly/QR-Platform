"""Focused regression tests for production security boundaries."""

import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(client_ip: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_ip, 12345),
        }
    )


@pytest.mark.unit
def test_forwarded_ip_is_only_honored_for_trusted_proxies(monkeypatch):
    from app import security

    monkeypatch.setattr(security.settings, "trusted_proxy_ips", "10.0.0.0/8")
    security._trusted_proxy_networks.cache_clear()
    try:
        assert security.get_client_ip(_request("198.51.100.4", "203.0.113.9")) == "198.51.100.4"
        assert security.get_client_ip(_request("10.1.2.3", "203.0.113.9, 10.1.2.3")) == "203.0.113.9"
        assert security.get_client_ip(
            _request("10.1.2.3", "198.51.100.50, 203.0.113.9")
        ) == "203.0.113.9"
    finally:
        security._trusted_proxy_networks.cache_clear()


@pytest.mark.unit
def test_org_request_secret_uses_dedicated_key_with_legacy_decrypt(monkeypatch):
    from app.config import get_settings
    from app.services import secret_box

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "org_request_encryption_key", "dedicated-org-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "legacy-jwt-key")

    encrypted = secret_box.encrypt_secret("new-secret")
    assert secret_box.decrypt_secret(encrypted) == "new-secret"

    legacy = secret_box._fernet_from_secret("legacy-jwt-key").encrypt(b"legacy-secret").decode("utf-8")
    assert secret_box.decrypt_secret(legacy) == "legacy-secret"


@pytest.mark.unit
def test_metrics_series_are_bounded(monkeypatch):
    from app import metrics

    metrics.REQUEST_COUNT.clear()
    metrics.REQUEST_DURATION_MS.clear()
    monkeypatch.setattr(metrics.settings, "metrics_max_series", 2)
    try:
        for index in range(5):
            metrics.observe_request("GET", f"/users/{index}", 200, time.perf_counter())
        assert len(metrics.REQUEST_COUNT) == 2
        assert len(metrics.REQUEST_DURATION_MS) == 2
    finally:
        metrics.REQUEST_COUNT.clear()
        metrics.REQUEST_DURATION_MS.clear()


@pytest.mark.unit
def test_production_config_requires_auth_client_and_strong_secrets():
    from app.config import Settings

    settings = Settings(
        app_env="production",
        app_url="https://app.example.com",
        cors_allowed_origins="https://app.example.com/",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="",
        supabase_key="",
        supabase_service_role_key="service-role",
        database_url="postgresql://database.example.com/app",
        invite_hmac_secret="short",
        otp_hmac_secret="short",
        org_request_encryption_key="short",
        metrics_access_token="short",
        platform_admin_require_aal2=True,
        platform_superadmin_emails="security@example.com",
        smtp_user="mailer@example.com",
        smtp_pass="smtp-secret",
    )

    problems = settings.validate_for_production()

    assert "SUPABASE_ANON_KEY is required for sign-up and sign-in." in problems
    assert any("CORS_ALLOWED_ORIGINS contains an invalid" in problem for problem in problems)
    assert sum("at least 32 bytes" in problem for problem in problems) == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_storage_references_reject_ssrf_and_path_traversal(monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service.settings, "supabase_url", "https://project.supabase.co")

    assert storage_service.is_trusted_storage_url(
        "https://project.supabase.co/storage/v1/object/sign/invitations/tenant/background.png?token=x"
    )
    assert not storage_service.is_trusted_storage_url(
        "https://project.supabase.co.evil.example/storage/v1/object/sign/invitations/background.png"
    )
    assert not storage_service.is_trusted_storage_url("http://127.0.0.1/internal")

    with pytest.raises(ValueError):
        await storage_service.download_reference("tenant/../private-key")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_staff_actions_require_recent_mfa_when_enabled(monkeypatch):
    from app.auth import CurrentUser
    from app.services import staff_service

    async def staff_member(*_args, **_kwargs):
        return True

    monkeypatch.setattr(staff_service, "is_staff_user", staff_member)
    monkeypatch.setattr(staff_service.settings, "platform_admin_require_aal2", True)
    user = CurrentUser(id=uuid4(), email="admin@example.com", aal="aal1")

    with pytest.raises(HTTPException) as exc:
        await staff_service.require_staff(user=user, db=None)
    assert exc.value.status_code == 403

    assert await staff_service.require_staff(
        user=CurrentUser(id=uuid4(), email="admin@example.com", aal="aal2"),
        db=None,
    )
