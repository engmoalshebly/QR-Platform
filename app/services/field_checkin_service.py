"""Atomic field check-in execution and non-PII scan audit logging."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Mapping
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.field_qr_service import FieldQRCodeError, ParsedInvitationCode, parse_invitation_code
from app.security import get_client_ip


FIELD_MESSAGES = {
    "success": "تم قبول الدعوة وتسجيل الدخول.",
    "already_checked_in": "استُخدمت الدعوة بالكامل سابقاً.",
    "capacity_exceeded": "العدد المطلوب أكبر من المتبقي في هذه الدعوة.",
    "revoked": "الدعوة ملغاة.",
    "expired": "انتهت صلاحية الدعوة.",
    "declined": "تم رفض الحضور لهذه الدعوة.",
    "rsvp_required": "تتطلب هذه الدعوة تأكيد الحضور (RSVP) قبل الدخول.",
    "wrong_event": "هذه الدعوة تخص حفلاً آخر.",
    "wrong_gate": "فئة هذه الدعوة غير مسموحة من هذه البوابة.",
    "registration_code": "هذا رمز تسجيل عام وليس دعوة دخول.",
    "invalid": "تعذر التحقق من رمز الدعوة.",
    "invalid_entry_count": "عدد الداخلين غير صالح.",
    "offline_conflict": "تعارضت هذه الدعوة أثناء المزامنة؛ تم اعتماد المسح الأول فقط.",
    "pack_invalid": "حزمة العمل لم تعد صالحة للمزامنة.",
}


@dataclass
class FieldCheckinResult:
    result: str
    message: str
    invitation_id: str | None = None
    guest_name: str | None = None
    ticket_class: str | None = None
    event_title: str | None = None
    checkin_count: int = 0
    guest_count: int = 0
    remaining_count: int = 0
    entry_count: int = 1
    requires_assistance: bool = False
    code_format: str | None = None
    idempotent: bool = False

    def public_payload(self, *, include_guest_name: bool) -> dict:
        data = asdict(self)
        if not include_guest_name:
            data["guest_name"] = None
        return data


def code_fingerprint(code: str, *, salt: str = "") -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _is_assistance_result(result: str) -> bool:
    return result in {"already_checked_in", "capacity_exceeded", "offline_conflict"}


async def claim_client_scan(
    db: AsyncSession,
    *,
    session: Mapping,
    user_id: UUID,
    client_scan_id: UUID,
    scan_method: str,
    raw_code: str,
    client_captured_at: datetime | None,
    request: Request,
) -> FieldCheckinResult | None:
    """Claim a scan before execution; repeated client ids return prior result."""
    fingerprint = code_fingerprint(raw_code)
    inserted = await db.execute(text("""
        INSERT INTO event_gate_scan_attempts
          (event_id, gate_id, shift_id, device_session_id, scanner_user_id,
           result, scan_method, code_fingerprint, client_scan_id,
           client_captured_at, ip_address)
        VALUES
          (:event_id, :gate_id, :shift_id, :session_id, :user_id,
           'processing', :scan_method, :fingerprint, :client_scan_id,
           :client_captured_at, :ip_address)
        ON CONFLICT (device_session_id, client_scan_id)
        WHERE device_session_id IS NOT NULL AND client_scan_id IS NOT NULL
        DO NOTHING
        RETURNING id
    """), {
        "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]),
        "shift_id": str(session["shift_id"]), "session_id": str(session["id"]),
        "user_id": str(user_id), "scan_method": scan_method, "fingerprint": fingerprint,
        "client_scan_id": str(client_scan_id), "client_captured_at": client_captured_at,
        "ip_address": get_client_ip(request),
    })
    if inserted.first():
        return None
    previous = await db.execute(text("""
        SELECT result, metadata FROM event_gate_scan_attempts
        WHERE device_session_id = :session_id AND client_scan_id = :client_scan_id
    """), {"session_id": str(session["id"]), "client_scan_id": str(client_scan_id)})
    row = previous.mappings().first()
    if not row or row["result"] == "processing":
        return FieldCheckinResult(result="processing", message="تتم معالجة محاولة المسح.", idempotent=True)
    metadata = row["metadata"] or {}
    return FieldCheckinResult(
        result=row["result"], message=FIELD_MESSAGES.get(row["result"], "تمت معالجة محاولة المسح سابقاً."),
        invitation_id=metadata.get("invitation_id"), ticket_class=metadata.get("ticket_class"),
        event_title=metadata.get("event_title"), checkin_count=int(metadata.get("checkin_count") or 0),
        guest_count=int(metadata.get("guest_count") or 0), remaining_count=int(metadata.get("remaining_count") or 0),
        entry_count=int(metadata.get("entry_count") or 1),
        requires_assistance=bool(metadata.get("requires_assistance")), idempotent=True,
    )


async def record_field_attempt(
    db: AsyncSession,
    *,
    session: Mapping,
    user_id: UUID,
    client_scan_id: UUID | None,
    scan_method: str,
    raw_code: str,
    result: FieldCheckinResult,
    client_captured_at: datetime | None,
    request: Request,
    offline_pack_id: UUID | None = None,
) -> None:
    """Finalize or append an immutable non-PII audit record."""
    metadata = {
        "invitation_id": result.invitation_id,
        "ticket_class": result.ticket_class,
        "event_title": result.event_title,
        "checkin_count": result.checkin_count,
        "guest_count": result.guest_count,
        "remaining_count": result.remaining_count,
        "entry_count": result.entry_count,
        "requires_assistance": result.requires_assistance,
        "code_format": result.code_format,
        "offline_pack_id": str(offline_pack_id) if offline_pack_id else None,
    }
    payload = {
        "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]),
        "shift_id": str(session["shift_id"]), "session_id": str(session["id"]),
        "user_id": str(user_id), "invitation_id": result.invitation_id,
        "result": result.result, "scan_method": scan_method,
        "fingerprint": code_fingerprint(raw_code),
        "client_scan_id": str(client_scan_id) if client_scan_id else None,
        "client_captured_at": client_captured_at,
        "ip_address": get_client_ip(request),
        "metadata": json.dumps(metadata, default=str),
    }
    if client_scan_id:
        updated = await db.execute(text("""
            UPDATE event_gate_scan_attempts
            SET invitation_id = :invitation_id, result = :result, scan_method = :scan_method,
                code_fingerprint = :fingerprint, client_captured_at = :client_captured_at,
                ip_address = :ip_address, metadata = CAST(:metadata AS jsonb), received_at = now()
            WHERE device_session_id = :session_id AND client_scan_id = :client_scan_id
              AND scanner_user_id = :user_id
            RETURNING id
        """), payload)
        if updated.first():
            return
    await db.execute(text("""
        INSERT INTO event_gate_scan_attempts
          (event_id, gate_id, shift_id, device_session_id, scanner_user_id,
           invitation_id, result, scan_method, code_fingerprint, client_scan_id,
           client_captured_at, ip_address, metadata)
        VALUES
          (:event_id, :gate_id, :shift_id, :session_id, :user_id,
           :invitation_id, :result, :scan_method, :fingerprint, :client_scan_id,
           :client_captured_at, :ip_address, CAST(:metadata AS jsonb))
    """), payload)


async def process_field_checkin(
    db: AsyncSession,
    *,
    session: Mapping,
    user_id: UUID,
    raw_code: str,
    entry_count: int,
    scan_method: str,
    client_scan_id: UUID | None,
    client_captured_at: datetime | None,
    request: Request,
    expected_invitation_id: UUID | None = None,
    offline_pack_id: UUID | None = None,
    from_offline: bool = False,
    client_scan_already_claimed: bool = False,
) -> FieldCheckinResult:
    """Parse and atomically record a field check-in after session validation.

    Valid scans use a single PostgreSQL transaction for idempotency, invitation
    locking, attendance, and the audit log.  Keeping this hot path to one
    round-trip is important when several gates scan concurrently.
    """
    try:
        parsed: ParsedInvitationCode = parse_invitation_code(raw_code)
    except FieldQRCodeError:
        # Invalid codes are the uncommon path.  Claiming them still prevents a
        # camera retry from flooding the audit log with the same attempt.
        if client_scan_id and not client_scan_already_claimed:
            previous = await claim_client_scan(
                db, session=session, user_id=user_id, client_scan_id=client_scan_id,
                scan_method=scan_method, raw_code=raw_code,
                client_captured_at=client_captured_at, request=request,
            )
            if previous:
                return previous
        result = FieldCheckinResult(result="invalid", message=FIELD_MESSAGES["invalid"], entry_count=entry_count)
        await record_field_attempt(db, session=session, user_id=user_id, client_scan_id=client_scan_id,
                                   scan_method=scan_method, raw_code=raw_code, result=result,
                                   client_captured_at=client_captured_at, request=request, offline_pack_id=offline_pack_id)
        return result

    expected_id = expected_invitation_id or parsed.invitation_id
    row_result = await db.execute(text("""
        SELECT * FROM public.process_field_checkin_fast(
          :token,
          CAST(:event_id AS UUID), CAST(:gate_id AS UUID), CAST(:shift_id AS UUID),
          CAST(:session_id AS UUID), CAST(:user_id AS UUID), CAST(:client_scan_id AS UUID),
          :client_captured_at, :scan_method, :fingerprint, :entry_count,
          CAST(:expected_invitation_id AS UUID), :from_offline,
          CAST(:offline_pack_id AS UUID), :code_format, CAST(:ip_address AS INET), :claim_already
        )
    """), {
        "token": parsed.token,
        "event_id": str(session["event_id"]), "gate_id": str(session["gate_id"]),
        "shift_id": str(session["shift_id"]), "session_id": str(session["id"]),
        "user_id": str(user_id), "client_scan_id": str(client_scan_id) if client_scan_id else None,
        "client_captured_at": client_captured_at, "scan_method": scan_method,
        "fingerprint": code_fingerprint(parsed.canonical_code), "entry_count": entry_count,
        "expected_invitation_id": str(expected_id) if expected_id else None,
        "from_offline": from_offline,
        "offline_pack_id": str(offline_pack_id) if offline_pack_id else None,
        "code_format": parsed.format,
        "ip_address": get_client_ip(request),
        "claim_already": client_scan_already_claimed,
    })
    row = row_result.mappings().first()
    if not row:
        result = FieldCheckinResult(result="invalid", message=FIELD_MESSAGES["invalid"], code_format=parsed.format, entry_count=entry_count)
    else:
        outcome = str(row["result"])
        result = FieldCheckinResult(
            result=outcome, message=FIELD_MESSAGES.get(outcome, FIELD_MESSAGES["invalid"]),
            invitation_id=str(row["invitation_id"]) if row["invitation_id"] else None,
            guest_name=row.get("guest_name"),
            ticket_class=row.get("ticket_class"), event_title=row.get("event_title"),
            checkin_count=int(row.get("checkin_count") or 0), guest_count=int(row.get("guest_count") or 0),
            remaining_count=int(row.get("remaining_count") or 0), entry_count=entry_count,
            requires_assistance=_is_assistance_result(outcome), code_format=parsed.format,
            idempotent=bool(row.get("idempotent")),
        )
    return result
