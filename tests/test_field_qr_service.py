from uuid import uuid4

import pytest

from app.services import barcode_service
from app.services.field_qr_service import FieldQRCodeError, parse_invitation_code


def test_qentry_v1_code_round_trip_is_signed_and_opaque():
    invitation_id = str(uuid4())
    token = "opaque-token-for-field-12345"
    payload = barcode_service.build_barcode_payload(invitation_id, token)

    assert payload["field_payload"].startswith(f"qentry:v1:{invitation_id}:")
    assert "guest" not in payload["field_payload"].lower()
    parsed = parse_invitation_code(payload["field_payload"])
    assert parsed.token == token
    assert str(parsed.invitation_id) == invitation_id
    assert parsed.format == "qentry_v1"


def test_previous_hmac_key_is_accepted_during_rotation(monkeypatch):
    invitation_id = str(uuid4())
    token = "rotated-key-token-12345"
    previous = b"previous-test-hmac-key"
    signature = barcode_service._sign_with_key(invitation_id, token, previous)
    monkeypatch.setattr(barcode_service, "_get_prev_hmac_key", lambda: previous)

    parsed = parse_invitation_code(f"qentry:v1:{invitation_id}:{token}:{signature}")
    assert parsed.token == token


def test_legacy_formats_remain_compatible_but_signature_is_checked():
    invitation_id = str(uuid4())
    token = "legacy-code128-token-12345"
    signature = barcode_service.sign_payload(invitation_id, token)

    assert parse_invitation_code(f"{invitation_id}:{token}:{signature}").token == token
    assert parse_invitation_code(f"http://localhost:9000/i/{token}").token == token
    assert parse_invitation_code(token).format == "legacy_token"

    with pytest.raises(FieldQRCodeError):
        parse_invitation_code(f"{invitation_id}:{token}:00000000000000000000000000000000")


@pytest.mark.parametrize("value", [
    "https://attacker.example/i/opaque-token-for-field-12345",
    "https://localhost:9000/register/opaque-token-for-field-12345",
    "qentry:v1:not-a-uuid:opaque-token-for-field-12345:00000000000000000000000000000000",
    "not a valid raw invitation code",
])
def test_non_invitation_codes_are_rejected(value):
    with pytest.raises(FieldQRCodeError):
        parse_invitation_code(value)
