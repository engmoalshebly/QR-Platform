"""Canonical invitation-code parsing for the authorised field application.

The gate application accepts several representations while invitations are
migrated.  Every accepted representation becomes one opaque invitation token;
the server never trusts an event, gate, guest, or status embedded in a QR.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import unquote, urlsplit
from uuid import UUID

from app.config import get_settings
from app.services import barcode_service


_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,512}$")
_QENTRY = re.compile(r"^qentry:v1:([0-9a-fA-F-]{36}):([A-Za-z0-9_-]{8,512}):([0-9a-fA-F]{32})$")
_SIGNED_LEGACY = re.compile(r"^([0-9a-fA-F-]{36}):([A-Za-z0-9_-]{8,512}):([0-9a-fA-F]{32})$")


class FieldQRCodeError(ValueError):
    """The input is not an invitation QR/Code128 representation."""


@dataclass(frozen=True)
class ParsedInvitationCode:
    token: str
    invitation_id: UUID | None
    format: str

    @property
    def canonical_code(self) -> str:
        """Opaque code used for fingerprints and the offline queue."""
        return self.token


def _safe_token(value: str) -> str:
    token = value.strip()
    if not _TOKEN.fullmatch(token):
        raise FieldQRCodeError("رمز الدعوة غير صالح")
    return token


def _parse_signed(match: re.Match[str], code_format: str) -> ParsedInvitationCode:
    invitation_id, token, signature = match.groups()
    try:
        parsed_id = UUID(invitation_id)
    except ValueError as error:
        raise FieldQRCodeError("معرّف الدعوة غير صالح") from error
    if not barcode_service.verify_signature(str(parsed_id), token, signature):
        raise FieldQRCodeError("توقيع رمز الدعوة غير صالح")
    return ParsedInvitationCode(token=token, invitation_id=parsed_id, format=code_format)


def _parse_invitation_url(value: str) -> ParsedInvitationCode:
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        raise FieldQRCodeError("رابط الدعوة غير صالح")
    configured_host = urlsplit(get_settings().app_url).hostname
    host = parsed.hostname
    # Public invitation links are issued only from the configured app host.
    # Development explicitly permits localhost so exported test QR images work.
    allowed_hosts = {configured_host, "localhost", "127.0.0.1"}
    if host not in allowed_hosts:
        raise FieldQRCodeError("الرابط ليس رابط دعوة صادر عن المنصة")
    path = unquote(parsed.path).rstrip("/")
    match = re.fullmatch(r"/i/([A-Za-z0-9_-]{8,512})", path)
    if not match:
        raise FieldQRCodeError("الرابط لا يشير إلى دعوة")
    return ParsedInvitationCode(token=_safe_token(match.group(1)), invitation_id=None, format="legacy_url")


def parse_invitation_code(raw_code: str) -> ParsedInvitationCode:
    """Parse a QR or Code128 text payload into a canonical invitation token.

    Supported inputs:
    - ``qentry:v1:<invitation UUID>:<opaque token>:<HMAC>`` (new signed QR)
    - legacy invitation URL ``https://app.example/i/<token>``
    - legacy signed ``<invitation UUID>:<token>:<HMAC>``
    - an old opaque token emitted by early Code128/QR generators.

    Registration and arbitrary URLs are intentionally not accepted here; the
    database check later rejects registration invitations even when a token is
    structurally valid.
    """
    if not isinstance(raw_code, str):
        raise FieldQRCodeError("رمز الدعوة غير صالح")
    value = raw_code.strip()
    if not value or len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise FieldQRCodeError("رمز الدعوة غير صالح")

    signed = _QENTRY.fullmatch(value)
    if signed:
        return _parse_signed(signed, "qentry_v1")
    signed = _SIGNED_LEGACY.fullmatch(value)
    if signed:
        return _parse_signed(signed, "legacy_signed")
    if value.startswith(("http://", "https://")):
        return _parse_invitation_url(value)
    return ParsedInvitationCode(token=_safe_token(value), invitation_id=None, format="legacy_token")
