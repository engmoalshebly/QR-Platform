"""Fast, deterministic security and integration-boundary tests."""
import asyncio
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image

from app.services import barcode_service, storage_service
from app.services.membership_service import verify_membership
from app.resilience import sync_with_retry, with_retry
from app.metrics import observe_request, snapshot


class Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeDB:
    def __init__(self, row):
        self.row = row

    async def execute(self, *_args, **_kwargs):
        return Result(self.row)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authentication_rejects_invalid_token():
    from app.auth import decode_supabase_jwt
    with pytest.raises(HTTPException) as exc:
        await decode_supabase_jwt("not-a-jwt")
    assert exc.value.status_code == 401


@pytest.mark.unit
def test_authorization_rejects_non_member():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_membership(FakeDB(None), uuid4(), uuid4()))
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_authorization_accepts_active_member_and_role():
    row = {"tenant_id": uuid4(), "user_id": uuid4(), "role": "owner", "status": "active"}
    assert asyncio.run(verify_membership(FakeDB(row), row["tenant_id"], row["user_id"], ["owner"])) == row


@pytest.mark.unit
def test_authorization_rejects_wrong_role():
    row = {"tenant_id": uuid4(), "user_id": uuid4(), "role": "member", "status": "active"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_membership(FakeDB(row), row["tenant_id"], row["user_id"], ["owner"]))
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_qr_generation_and_signature_round_trip():
    invite_id, token = str(uuid4()), "invite-token"
    signature = barcode_service.sign_payload(invite_id, token)
    assert len(signature) == 32
    assert barcode_service.verify_signature(invite_id, token, signature)
    assert not barcode_service.verify_signature(invite_id, "other", signature)

    png = barcode_service.generate_qr_png("https://example.test/i/invite-token", size_px=128)
    image = Image.open(io.BytesIO(png))
    assert image.size == (128, 128)
    assert image.format == "PNG"
    assert barcode_service.build_barcode_payload(invite_id, token)["payload"].endswith(token)
    code128 = barcode_service.generate_code128_png("123456789", width_px=160, height_px=80)
    assert Image.open(io.BytesIO(code128)).size == (160, 80)
    badge = barcode_service.add_center_badge_to_png(png, "VIP")
    assert Image.open(io.BytesIO(badge)).size == (128, 128)


@pytest.mark.unit
def test_storage_health_uses_storage_api(monkeypatch):
    called = []
    monkeypatch.setattr(storage_service, "_get_client", lambda: SimpleNamespace(
        storage=SimpleNamespace(list_buckets=lambda: called.append(True) or [])
    ))
    asyncio.run(storage_service.check_health())
    assert called == [True]


@pytest.mark.unit
def test_resilience_retries_then_succeeds():
    state = {"count": 0}
    async def operation():
        state["count"] += 1
        if state["count"] < 2:
            raise RuntimeError("temporary")
        return "ok"
    assert asyncio.run(with_retry(operation, name="test", attempts=2, base_delay=0)) == "ok"
    assert state["count"] == 2

    sync_state = {"count": 0}
    def sync_operation():
        sync_state["count"] += 1
        if sync_state["count"] < 2:
            raise RuntimeError("temporary")
        return "ok"
    assert sync_with_retry(sync_operation, name="test", attempts=2, base_delay=0) == "ok"


@pytest.mark.unit
def test_metrics_snapshot_records_request():
    observe_request("GET", "/test", 200, __import__("time").perf_counter())
    data = snapshot()
    assert data["requests"]["GET|/test|200"] >= 1


@pytest.mark.unit
def test_link_gateway_configuration_fails_closed():
    from app.services.link_payment_service import LinkPaymentService
    service = LinkPaymentService()
    service.base_url = "https://gateway.internal"
    service.api_key = ""
    assert service.is_configured() is False


@pytest.mark.unit
def test_link_gateway_internal_key_is_server_only():
    from app.services.link_payment_service import LinkPaymentService
    service = LinkPaymentService()
    service.api_key = "internal-secret"
    assert service._headers() == {
        "Content-Type": "application/json",
        "X-API-Key": "internal-secret",
    }


@pytest.mark.unit
def test_link_gateway_rejects_placeholder_key():
    from app.services.link_payment_service import LinkPaymentService
    service = LinkPaymentService()
    service.base_url = "https://gateway.internal"
    service.api_key = "your-internal-api-key"
    assert service.is_configured() is False
