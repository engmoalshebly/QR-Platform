"""Digital Invitations API: create (quick/designed/bulk), send, revoke, RSVP."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, Literal
from datetime import datetime, timezone
import json
import logging
import asyncio
from urllib.parse import quote

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db, get_privileged_db
from app.models.invitation import (
    InvitationCreate, InvitationRead, InvitationUpdate,
    QuickInviteCreate, BulkInviteFromGuests, InvitationSend,
    RsvpRequest, DeliveryChannel, RsvpStatus,
)
from app.services.permission_service import require_permission, has_permission
from app.services import invitation_table_service as tables
import csv
import tempfile
from zoneinfo import ZoneInfo
from app.services.audit_service import log_audit
from app.security import get_client_ip
from app.services import barcode_service, storage_service
from app.services.quota_service import check_quota as _quota_check_single, check_quota_mixed
from app.config import get_settings
from app.services.email_service import (
    is_email_delivery_configured,
    send_event_invitation_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invitations", tags=["Invitations"])
settings = get_settings()


def _delivery_recipient(invitation: dict, channel: DeliveryChannel) -> str:
    """Return the requested channel's address, never another contact method."""
    if channel == DeliveryChannel.email:
        return (invitation.get("guest_email") or "").strip()
    if channel == DeliveryChannel.sms:
        return (invitation.get("guest_phone") or "").strip()
    if channel == DeliveryChannel.whatsapp:
        return (invitation.get("guest_whatsapp") or "").strip()
    # A public link is useful context in a failed audit row, but it is not
    # itself evidence that a guest was notified.
    token = str(invitation.get("token") or "")
    return f"{settings.app_url.rstrip('/')}/i/{quote(token, safe='')}"


async def _record_invitation_delivery(
    db: AsyncSession,
    *,
    invitation_id: UUID | str,
    channel: DeliveryChannel,
    recipient: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Persist one outcome without inventing a delivery success."""
    await db.execute(
        text("""
            INSERT INTO invitation_deliveries
                (invitation_id, channel, recipient, status, provider, sent_at, error_message)
            VALUES
                (:iid, :channel, :recipient, :status, :provider,
                 CASE WHEN :status = 'sent' THEN now() ELSE NULL END,
                 :error_message)
        """),
        {
            "iid": str(invitation_id),
            "channel": channel.value,
            # invitation_deliveries.recipient is NOT NULL. Keep absent contact
            # data visible rather than substituting another private channel.
            "recipient": recipient or "(missing recipient)",
            "status": status,
            "provider": "smtp" if channel == DeliveryChannel.email else None,
            "error_message": error_message,
        },
    )


async def _reject_expired_public_invitation(
    db: AsyncSession,
    invitation: dict,
) -> None:
    """Fail closed when an invitation's timestamp has elapsed.

    Older rows may still have a non-expired lifecycle status even though
    ``expires_at`` is in the past. Public view and RSVP must not rely on a
    background job having updated that status first.
    """
    expires_at = invitation.get("expires_at")
    if not expires_at:
        return

    now = datetime.now(timezone.utc)
    if getattr(expires_at, "tzinfo", None) is None:
        is_expired = expires_at <= now.replace(tzinfo=None)
    else:
        is_expired = expires_at <= now
    if not is_expired:
        return

    if invitation.get("status") != "expired":
        await db.execute(
            text("""
                UPDATE invitations
                SET status = 'expired', updated_at = now()
                WHERE id = :id AND status NOT IN ('revoked', 'expired')
            """),
            {"id": str(invitation["id"])},
        )
        await db.commit()
    raise HTTPException(410, "انتهت صلاحية هذه الدعوة")


# ══════════════════════════════════════════════
# LIST / GET
# ══════════════════════════════════════════════

@router.get("", response_model=list[InvitationRead])
async def list_invitations(
    request: Request,
    event_id: Optional[UUID] = None,
    ticket_class: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.view")

    query = """
        SELECT * FROM invitations
        WHERE tenant_id = :tid
          AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
    """
    params: dict = {"tid": str(tenant_id)}

    if event_id:
        query += " AND event_id = :eid"
        params["eid"] = str(event_id)
    if ticket_class:
        query += " AND ticket_class = :tc"
        params["tc"] = ticket_class
    if status_filter:
        query += " AND status = :st"
        params["st"] = status_filter

    query += " ORDER BY created_at DESC LIMIT :lim OFFSET :off"
    params["lim"] = limit
    params["off"] = offset

    result = await db.execute(text(query), params)
    from app.routes.fast_invitations import redact_generation_files
    rows = await redact_generation_files(db, tenant_id, user.id, result.mappings().all())
    return [InvitationRead(**row) for row in rows]


def table_filters(
    event_id: UUID, tab: Literal['rsvp','final'] = 'rsvp',
    search: str = Query('', max_length=200),
    ticket_class: Literal['all','normal','vip'] = 'all',
    rsvp_status: Literal['all','pending','maybe','accepted','declined'] = 'all',
    checkin: Literal['all','checked_in','not_checked_in'] = 'all',
    whatsapp_state: Literal['all','not_sent','sent','delivered','read','pending','failed','unknown','cancelled'] = 'all',
):
    return tables.TableFilters(event_id, tab, search, ticket_class, rsvp_status, checkin, whatsapp_state)


async def authorize_table(request, user, db, filters):
    tid = get_tenant_id_from_header(request)
    await require_permission(db, tid, user.id, 'invitations.view')
    can_view = await has_permission(db, tid, user.id, 'whatsapp.view')
    if filters.whatsapp_state != 'all' and not can_view:
        raise HTTPException(403, 'تصفية حالات WhatsApp تحتاج صلاحية عرض السجل.')
    return tid, can_view


@router.get('/table')
async def invitation_table(request: Request, filters: tables.TableFilters = Depends(table_filters),
                           limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                           user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tid, can_view = await authorize_table(request, user, db, filters)
    return await tables.page(db, tid, filters, limit, offset, can_view)


@router.get('/table/export')
async def export_invitation_table(request: Request, filters: tables.TableFilters = Depends(table_filters),
                                  user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tid, can_view = await authorize_table(request, user, db, filters)
    await require_permission(db, tid, user.id, 'ui.rsvp.action.export' if filters.tab == 'rsvp' else 'ui.invitations.action.export')
    join, where, params = tables.filtered_query(tid, filters)
    if can_view and not join:
        join = f''' LEFT JOIN LATERAL (SELECT d.state FROM whatsapp_deliveries d
            WHERE d.tenant_id=:tid AND d.event_id=:eid AND d.invitation_id=i.id AND d.purpose=({tables.PURPOSE_SQL})
            ORDER BY d.created_at DESC,d.id DESC LIMIT 1) latest ON true'''
    selection = ",COALESCE(latest.state,'not_sent') wa_state" if can_view else ''
    query = f'''SELECT i.guest_name,i.guest_name_ar,i.guest_phone,i.guest_whatsapp,i.ticket_class,
        i.rsvp_status,i.plus_one_count,i.rsvp_at,i.rsvp_message,i.checkin_count,i.guest_count,i.gate_id,i.updated_at,
        ({tables.PURPOSE_SQL}) purpose {selection} FROM invitations i {join} WHERE {where}
        ORDER BY i.created_at DESC,i.id DESC'''
    # One database cursor provides the full matching export. Spool to disk
    # above 1MB; the browser and API never build a giant invitation JSON array.
    spool = tempfile.SpooledTemporaryFile(max_size=1024*1024, mode='w+', encoding='utf-8', newline='')
    states = {'not_sent':'لم تُرسل','queued':'بانتظار التنفيذ','waiting_connection':'بانتظار الاتصال','sending':'جارٍ الإرسال',
              'sent':'تم الإرسال','delivered':'تم التسليم','read':'تمت القراءة','failed':'فشل الإرسال','unknown':'تحتاج مراجعة','cancelled':'أُلغي الإرسال'}
    def cell(value):
        value = str(value if value is not None else '')
        return "'" + value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
    count = 0
    result = None
    try:
        writer = csv.writer(spool)
        headers = ['الاسم','الهاتف','الفئة','حالة تأكيد الحضور','المرافقين','تاريخ الرد (عدن)','رسالة الضيف','مرات الدخول','عدد الأشخاص']
        if filters.tab == 'final':
            headers = ['الاسم','الهاتف','الفئة','حالة الدخول','مرات الدخول','بوابة الدخول','آخر تحديث (عدن)','عدد الأشخاص']
        if can_view: headers += ['حالة إرسال WhatsApp','نوع الرسالة']
        writer.writerow(headers)
        result = await db.stream(text(query).execution_options(yield_per=1000), params)
        async for partition in result.mappings().partitions(1000):
            for row in partition:
                values = [row['guest_name_ar'] or row['guest_name'], row['guest_whatsapp'] or row['guest_phone'],
                          'VIP' if row['ticket_class']=='vip' else 'عادي',
                          {'accepted':'مؤكد','declined':'معتذر'}.get(row['rsvp_status'],'بانتظار الرد'), row['plus_one_count'],
                          row['rsvp_at'].astimezone(ZoneInfo('Asia/Aden')).strftime('%Y-%m-%d %H:%M') if row['rsvp_at'] else '',
                          row['rsvp_message'],row['checkin_count'],row['guest_count']]
                if filters.tab == 'final':
                    values = [row['guest_name_ar'] or row['guest_name'], row['guest_whatsapp'] or row['guest_phone'],
                              'VIP' if row['ticket_class']=='vip' else 'عادي', 'تم الدخول' if row['checkin_count'] else 'لم يحضر بعد',
                              row['checkin_count'], row['gate_id'] or 'تلقائي',
                              row['updated_at'].astimezone(ZoneInfo('Asia/Aden')).strftime('%Y-%m-%d %H:%M') if row['updated_at'] else '',
                              row['guest_count']]
                if can_view: values += [states[row['wa_state']], 'طلب تأكيد الحضور' if row['purpose']=='rsvp' else 'رابط الدعوة']
                writer.writerow(map(cell, values)); count += 1
        await result.close(); result = None
        spool.seek(0)
        await log_audit(db, tenant_id=tid, actor_user_id=user.id, action='invitations.export', resource_type='event',
                        resource_id=str(filters.event_id), metadata={'tab':filters.tab,'rows':count}, ip_address=get_client_ip(request))
        await db.commit()
    except BaseException:
        spool.close()
        if result is not None: await result.close()
        raise
    def chunks():
        try:
            yield '\ufeff'
            while chunk := spool.read(65536): yield chunk
        finally:
            spool.close()
    filename = quote(('تأكيد_الحضور' if filters.tab=='rsvp' else 'الدعوات_النهائية') + '.csv')
    return StreamingResponse(chunks(), media_type='text/csv', background=BackgroundTask(spool.close),
                             headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}",'Cache-Control':'no-store'})


@router.get("/{invitation_id}", response_model=InvitationRead)
async def get_invitation(
    invitation_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.view")

    result = await db.execute(
        text("SELECT * FROM invitations WHERE id = :id AND tenant_id = :tid"),
        {"id": str(invitation_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدعوة غير موجودة")
    from app.routes.fast_invitations import redact_generation_files
    values = await redact_generation_files(db, tenant_id, user.id, [row])
    return InvitationRead(**values[0])


# ══════════════════════════════════════════════
# CREATE SINGLE INVITATION
# ══════════════════════════════════════════════

@router.post("", response_model=InvitationRead, status_code=201)
async def create_invitation(
    body: InvitationCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.create")

    # Check RSVP feature flag
    if body.require_rsvp:
        from app.services.feature_service import require_feature
        await require_feature(db, tenant_id, "rsvp")

    # Acquire the event-level quota lock before both quota systems inspect
    # current invitation usage. All creation paths use this lock order.
    await _quota_check_single(
        db, str(tenant_id), str(body.event_id), body.ticket_class,
        count=body.guest_count or 1,
    )

    # ── Plan limits ──
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    inv_count = body.guest_count or 1
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=inv_count)
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(body.event_id), "tid": str(tenant_id)},
    )
    # A group invitation is one persisted record; its people consume the
    # monthly issuance units and the event's class quota separately.
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل مناسبة", requested=1)

    status_val = "created"
    rsvp_status_val = "pending"
    if not body.require_rsvp:
        status_val = "accepted"
        rsvp_status_val = "accepted"

    result = await db.execute(
        text("""
            INSERT INTO invitations (
                tenant_id, event_id, template_id, guest_id, ticket_class,
                guest_name, guest_name_ar, guest_phone, guest_whatsapp, guest_email,
                seat_number, table_number, gate_id, hall, zone,
                notes, metadata, created_by, status, rsvp_status, guest_count
            ) VALUES (
                :tid, :eid, :tmpl, :gid, CAST(:tc AS ticket_class),
                :gname, :gname_ar, :gphone, :gwhatsapp, :gemail,
                :seat, :tbl, :gate, :hall, :zone,
                :notes, CAST(:meta AS jsonb), :uid, :status, :rsvp_status, :guest_count
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id), "eid": str(body.event_id),
            "tmpl": str(body.template_id) if body.template_id else None,
            "gid": str(body.guest_id) if body.guest_id else None,
            "tc": body.ticket_class,
            "gname": body.guest_name, "gname_ar": body.guest_name_ar,
            "gphone": body.guest_phone, "gwhatsapp": body.guest_whatsapp, "gemail": body.guest_email,
            "seat": body.seat_number, "tbl": body.table_number,
            "gate": str(body.gate_id) if body.gate_id else None,
            "hall": body.hall, "zone": body.zone,
            "notes": body.notes,
            "meta": json.dumps({**(body.metadata or {}), "require_rsvp": body.require_rsvp}, default=str),
            "uid": str(user.id),
            "status": status_val,
            "rsvp_status": rsvp_status_val,
            "guest_count": inv_count,
        },
    )
    row = result.mappings().first()

    # Generate barcode inline
    await _generate_barcode_for_row(db, tenant_id, body.event_id, dict(row))

    await db.commit()
    # Re-fetch to get updated barcode URLs
    updated = await db.execute(
        text("SELECT * FROM invitations WHERE id = :id"),
        {"id": str(row["id"])},
    )
    return InvitationRead(**dict(updated.mappings().first()))


# ══════════════════════════════════════════════
# QUICK INVITES (بدون تصميم — بالعدد أو بالأسماء)
# ══════════════════════════════════════════════

@router.post("/quick", status_code=201)
async def create_quick_invites(
    body: QuickInviteCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create quick invitations by count or by names list.
    
    Optimized: single quota check + batch INSERT for maximum speed.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.create")

    try:
        if not body.count and not body.names:
            raise HTTPException(400, "يجب تحديد العدد أو قائمة الأسماء")

        names = body.names or [None] * (body.count or 0)
        total = len(names)

        # Validate event exists
        event_result = await db.execute(
            text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
            {"eid": str(body.event_id), "tid": str(tenant_id)},
        )
        if not event_result.first():
            raise HTTPException(404, "المناسبة غير موجودة")

        # Centralized quota check
        await _quota_check_single(db, str(tenant_id), str(body.event_id), body.ticket_class, count=total)

        # ── Plan limits ──
        from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
        await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=total)
        _inv_total_res = await db.execute(
            text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
            {"eid": str(body.event_id), "tid": str(tenant_id)},
        )
        await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل مناسبة", requested=total)

        status_val = "created"
        rsvp_status_val = "pending"
        if not body.require_rsvp:
            status_val = "accepted"
            rsvp_status_val = "accepted"

        # Batch INSERT — single query for all invitations
        values_parts = []
        params: dict = {
            "tid": str(tenant_id),
            "eid": str(body.event_id),
            "tmpl": str(body.template_id) if body.template_id else None,
            "tc": body.ticket_class,
            "gate": str(body.gate_id) if body.gate_id else None,
            "uid": str(user.id),
            "status": status_val,
            "rsvp_status": rsvp_status_val,
            "meta": json.dumps({"require_rsvp": body.require_rsvp}, default=str),
        }
        for idx, name in enumerate(names):
            key = f"gn_{idx}"
            params[key] = name
            values_parts.append(
                f"(:tid, :eid, :tmpl, CAST(:tc AS ticket_class), :{key}, :gate, :uid, :status, :rsvp_status, CAST(:meta AS jsonb))"
            )

        insert_sql = f"""
            INSERT INTO invitations (
                tenant_id, event_id, template_id, ticket_class,
                guest_name, gate_id, created_by, status, rsvp_status, metadata
            ) VALUES {', '.join(values_parts)}
            RETURNING
                id, token, guest_name,
                ticket_class::text AS ticket_class,
                status::text AS status
        """

        result = await db.execute(text(insert_sql), params)
        created = [
            {
                "id": str(row["id"]),
                "token": row["token"],
                "guest_name": row["guest_name"],
                "ticket_class": row["ticket_class"],
                "status": row["status"],
            }
            for row in result.mappings().all()
        ]

        await log_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=user.id,
            action="invitations.quick_create",
            resource_type="invitation",
            metadata={
                "count": len(created),
                "event_id": str(body.event_id),
                "ticket_class": body.ticket_class,
            },
            ip_address=get_client_ip(request),
        )
        await db.commit()
        return {"created": len(created), "invitations": created}
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception("Quick invite creation failed")
        raise HTTPException(500, detail="تعذر إنشاء الدعوات حالياً. يرجى المحاولة لاحقاً.")


# ══════════════════════════════════════════════
# BULK FROM GUESTS (إنشاء دعوات من دفتر الضيوف)
# ══════════════════════════════════════════════

@router.post("/bulk-from-guests", status_code=201)
async def create_bulk_from_guests(
    body: BulkInviteFromGuests, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.create")

    # Resolve the actual batch before reserving capacity. Stale/cross-tenant
    # IDs must not block a valid batch or transiently overcharge its reservation.
    resolved = (await db.execute(
        text("SELECT id, full_name, full_name_ar, phone, email FROM guests WHERE id = ANY(CAST(:ids AS uuid[])) AND tenant_id = :tid"),
        {"ids": [str(gid) for gid in body.guest_ids], "tid": str(tenant_id)},
    )).mappings().all()
    guests_by_id = {str(row["id"]): row for row in resolved}
    body.guest_ids = [gid for gid in body.guest_ids if str(gid) in guests_by_id]
    if not body.guest_ids:
        return {"created": 0}

    if body.require_rsvp:
        # Check all guests first
        guest_checks = await db.execute(
            text("SELECT id, full_name, phone, email FROM guests WHERE id = ANY(CAST(:ids AS uuid[])) AND tenant_id = :tid"),
            {"ids": [str(gid) for gid in body.guest_ids], "tid": str(tenant_id)}
        )
        invalid_guests = []
        for r in guest_checks.mappings().all():
            phone = (r.get("phone") or "").strip()
            email = (r.get("email") or "").strip()
            if not phone and not email:
                invalid_guests.append(r["full_name"] or str(r["id"]))
        if invalid_guests:
            names_str = "، ".join(invalid_guests)
            raise HTTPException(
                status_code=400,
                detail=f"الضيوف التاليين يفتقرون إلى بيانات الاتصال (رقم الهاتف أو البريد الإلكتروني) اللازمة لتأكيد الحضور: {names_str}"
            )

    status_val = "created"
    rsvp_status_val = "pending"
    if not body.require_rsvp:
        status_val = "accepted"
        rsvp_status_val = "accepted"

    # Single batch quota check instead of per-guest
    await _quota_check_single(db, str(tenant_id), str(body.event_id), body.ticket_class, count=len(body.guest_ids))

    # ── Plan limits ──
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    _bulk_count = len(body.guest_ids)
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=_bulk_count)
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(body.event_id), "tid": str(tenant_id)},
    )
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل مناسبة", requested=_bulk_count)

    created = 0
    for gid in body.guest_ids:

        guest = guests_by_id[str(gid)]

        await db.execute(
            text("""
                INSERT INTO invitations (
                    tenant_id, event_id, template_id, guest_id, ticket_class,
                    guest_name, guest_name_ar, guest_phone, guest_whatsapp, guest_email,
                    gate_id, created_by, status, rsvp_status, metadata
                ) VALUES (
                    :tid, :eid, :tmpl, :gid, CAST(:tc AS ticket_class),
                    :gname, :gname_ar, :gphone, :gwhatsapp, :gemail,
                    :gate, :uid, :status, :rsvp_status, CAST(:meta AS jsonb)
                )
            """),
            {
                "tid": str(tenant_id), "eid": str(body.event_id),
                "tmpl": str(body.template_id) if body.template_id else None,
                "gid": str(gid), "tc": body.ticket_class,
                "gname": guest["full_name"], "gname_ar": guest.get("full_name_ar"),
                "gphone": guest.get("phone"), "gwhatsapp": guest.get("phone"), "gemail": guest.get("email"),
                "gate": str(body.gate_id) if body.gate_id else None,
                "uid": str(user.id),
                "status": status_val,
                "rsvp_status": rsvp_status_val,
                "meta": json.dumps({"require_rsvp": body.require_rsvp}, default=str),
            },
        )
        created += 1

    # The monthly reservation above charged for the full requested batch;
    # release capacity for any guest_ids that did not resolve to an invitation.
    if created < _bulk_count:
        from app.services.usage_service import release_usage
        await release_usage(db, tenant_id, "invitations_per_month", _bulk_count - created)

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="invitations.bulk_create", resource_type="invitation",
                    metadata={"count": created, "event_id": str(body.event_id)},
                    ip_address=get_client_ip(request))
    await db.commit()
    return {"created": created}


# ══════════════════════════════════════════════
# UPDATE / REVOKE
# ══════════════════════════════════════════════

@router.patch("/{invitation_id}", response_model=InvitationRead)
async def update_invitation(
    invitation_id: UUID, body: InvitationUpdate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "لا توجد حقول للتعديل")

    invite_check = await db.execute(
        text("SELECT is_registration FROM invitations WHERE id = :id AND tenant_id = :tid"),
        {"id": str(invitation_id), "tid": str(tenant_id)},
    )
    invite_row = invite_check.mappings().first()
    if not invite_row:
        raise HTTPException(404, "الدعوة غير موجودة")

    workflow_fields = {"rsvp_status", "status", "rsvp_message", "plus_one_count", "guest_count", "rsvp_at"}
    if invite_row.get("is_registration") and workflow_fields & set(updates.keys()):
        await require_permission(db, tenant_id, user.id, "events.edit")
    elif set(updates.keys()) <= workflow_fields:
        # RSVP and attendance-related fields mutate the invitation.  A
        # read-only Viewer must never be able to accept a guest, alter the
        # group size, or change an invitation's lifecycle state.
        await require_permission(db, tenant_id, user.id, "invitations.create")
    else:
        await require_permission(db, tenant_id, user.id, "invitations.create")

    if "gate_id" in updates and updates["gate_id"]:
        updates["gate_id"] = str(updates["gate_id"])

    if "metadata" in updates and updates["metadata"] is not None:
        updates["metadata"] = json.dumps(updates["metadata"])

    clauses = []
    for k in updates:
        if k == "metadata":
            clauses.append("metadata = CAST(:metadata AS jsonb)")
        else:
            clauses.append(f"{k} = :{k}")
    set_clauses = ", ".join(clauses)
    updates["id"] = str(invitation_id)
    updates["tid"] = str(tenant_id)

    result = await db.execute(
        text(f"UPDATE invitations SET {set_clauses}, updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING *"),
        updates,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدعوة غير موجودة")
    
    # ── Approval Barcode Generation ──
    # If the invitation is being accepted/approved and doesn't have a barcode, generate it now!
    row_dict = dict(row)
    if (updates.get("rsvp_status") == "accepted" or updates.get("status") == "accepted") and not row_dict.get("qr_data"):
        await _generate_barcode_for_row(db, tenant_id, row_dict["event_id"], row_dict)
        # Re-fetch invitation to get updated barcode fields
        refetch_res = await db.execute(
            text("SELECT * FROM invitations WHERE id = :id"),
            {"id": str(row["id"])}
        )
        updated_row = refetch_res.mappings().first()
        if updated_row:
            row_dict = dict(updated_row)
            # Re-render card if template is set
            if row_dict.get("template_id"):
                # Fetch event row for rendering
                ev_res = await db.execute(
                    text("SELECT * FROM events WHERE id = :eid"),
                    {"eid": str(row_dict["event_id"])}
                )
                ev_row = ev_res.mappings().first()
                if ev_row:
                    from app.routes.registration_forms import render_designed_card_for_invite
                    await render_designed_card_for_invite(
                        db, tenant_id, row_dict["event_id"], row_dict, row_dict["template_id"], dict(ev_row)
                    )
                    # Re-fetch final invitation details
                    final_res = await db.execute(
                        text("SELECT * FROM invitations WHERE id = :id"),
                        {"id": str(row["id"])}
                    )
                    row = final_res.mappings().first()

    await db.commit()
    from app.routes.fast_invitations import redact_generation_files
    values = await redact_generation_files(db, tenant_id, user.id, [row])
    return InvitationRead(**values[0])


@router.post("/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.revoke")

    result = await db.execute(
        text("""
            UPDATE invitations SET status = 'revoked', updated_at = now()
            WHERE id = :id AND tenant_id = :tid AND status NOT IN ('revoked', 'expired')
            RETURNING id
        """),
        {"id": str(invitation_id), "tid": str(tenant_id)},
    )
    if not result.first():
        raise HTTPException(400, "الدعوة غير موجودة أو ملغاة مسبقاً")

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="invitation.revoke", resource_type="invitation",
                    resource_id=str(invitation_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return {"message": "تم إلغاء الدعوة"}


@router.post("/bulk-revoke")
async def bulk_revoke(
    request: Request,
    invitation_ids: list[UUID] = [],
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.revoke")

    ids_str = [str(i) for i in invitation_ids]
    result = await db.execute(
        text("""
            UPDATE invitations SET status = 'revoked', updated_at = now()
            WHERE tenant_id = :tid AND id = ANY(CAST(:ids AS uuid[])) AND status NOT IN ('revoked', 'expired')
        """),
        {"tid": str(tenant_id), "ids": ids_str},
    )
    await db.commit()
    return {"revoked": result.rowcount}


# ══════════════════════════════════════════════
# SEND INVITATIONS
# ══════════════════════════════════════════════

@router.post("/send")
async def send_invitations(
    body: InvitationSend, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.send")

    if body.channel == DeliveryChannel.whatsapp:
        from app.services import whatsapp_service
        await require_permission(db, tenant_id, user.id, "whatsapp.send")
        if not body.client_request_id:
            raise HTTPException(422, "معرّف طلب ثابت مطلوب لإرسال WhatsApp.")
        if body.message:
            raise HTTPException(422, "إرسال WhatsApp يستخدم رسالة الدعوة الفردية المعتمدة.")
        if len(body.invitation_ids) > 100:
            raise HTTPException(422, "اختر حتى 100 دعوة في الطلب الواحد.")
        response = await whatsapp_service.queue_deliveries(db, tenant_id, user.id, body.invitation_ids,
                                                          body.client_request_id, allow_resend=body.allow_resend)
        await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id, action="whatsapp.queue",
                        resource_type="whatsapp", metadata={"request_id": response["request_id"], "queued": response["queued"]})
        await db.commit()
        return JSONResponse(status_code=202, content=response)

    # Fetch invitations before making a transport decision. This allows a
    # truthful failed-delivery audit trail without touching revoked/expired
    # invitations.
    invitations: list[dict] = []
    skipped = 0
    for inv_id in body.invitation_ids:
        inv = await db.execute(
            text("""
                SELECT i.id, i.guest_name, i.guest_phone, i.guest_whatsapp,
                       i.guest_email, i.token, i.status,
                       COALESCE(e.title, e.title_ar, 'فعاليتنا') AS event_title
                FROM invitations i
                JOIN events e ON e.id = i.event_id
                WHERE i.id = :id AND i.tenant_id = :tid
            """),
            {"id": str(inv_id), "tid": str(tenant_id)},
        )
        row = inv.mappings().first()
        if not row or row["status"] in ("revoked", "expired"):
            skipped += 1
            continue
        invitations.append(dict(row))

    channel = body.channel
    failed = 0
    sent = 0

    # A stale selection is not a transport outage. Report it as a no-op rather
    # than returning an infrastructure error merely because there was nothing
    # eligible to send.
    if not invitations:
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="invitations.send", resource_type="invitation",
            metadata={"count": 0, "failed": 0, "skipped": skipped, "channel": channel.value},
            ip_address=get_client_ip(request),
        )
        await db.commit()
        return {"sent": 0, "failed": 0, "skipped": skipped}

    # SMS and WhatsApp are deliberately fail-closed until a real provider is
    # integrated. "link" and "print" are local presentation actions, not
    # transports, so this endpoint must not label them as guest delivery.
    unsupported_channels = {
        DeliveryChannel.sms,
        DeliveryChannel.link,
        DeliveryChannel.print_,
    }
    if channel in unsupported_channels:
        for invitation in invitations:
            await _record_invitation_delivery(
                db,
                invitation_id=invitation["id"],
                channel=channel,
                recipient=_delivery_recipient(invitation, channel),
                status="failed",
                error_message="لا توجد خدمة إرسال مهيأة لهذه القناة.",
            )
            failed += 1
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="invitations.send", resource_type="invitation",
            metadata={
                "count": 0, "failed": failed, "skipped": skipped,
                "channel": channel.value, "reason": "transport_not_implemented",
            },
            ip_address=get_client_ip(request),
        )
        await db.commit()
        return JSONResponse(
            status_code=501,
            content={
                "sent": 0,
                "failed": failed,
                "skipped": skipped,
                "detail": "قناة الإرسال غير مهيأة بعد؛ لم يتم اعتبار أي دعوة مُرسلة.",
            },
        )

    # Email is the only implemented transport. Check its entitlement only for
    # a transport the process can actually use, and do not consume quota when
    # SMTP is unavailable.
    from app.services.feature_service import require_feature, enforce_monthly_limit
    await require_feature(db, tenant_id, "email_delivery")

    if not is_email_delivery_configured():
        for invitation in invitations:
            await _record_invitation_delivery(
                db,
                invitation_id=invitation["id"],
                channel=channel,
                recipient=_delivery_recipient(invitation, channel),
                status="failed",
                error_message="خدمة البريد الإلكتروني غير مهيأة حالياً.",
            )
            failed += 1
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="invitations.send", resource_type="invitation",
            metadata={
                "count": 0, "failed": failed, "skipped": skipped,
                "channel": channel.value, "reason": "smtp_unavailable",
            },
            ip_address=get_client_ip(request),
        )
        await db.commit()
        return JSONResponse(
            status_code=503,
            content={
                "sent": 0,
                "failed": failed,
                "skipped": skipped,
                "detail": "خدمة البريد الإلكتروني غير متاحة حالياً؛ لم يتم اعتبار أي دعوة مُرسلة.",
            },
        )

    # Only invitations with a real email address can reach the SMTP relay.
    # Missing contacts are recorded as failed and never consume quota.
    email_candidates = [item for item in invitations if _delivery_recipient(item, channel)]
    if email_candidates:
        await enforce_monthly_limit(
            db, tenant_id, "messages_per_month", "الرسائل الشهرية",
            count=len(email_candidates),
        )

    for invitation in invitations:
        recipient = _delivery_recipient(invitation, channel)
        if not recipient:
            await _record_invitation_delivery(
                db,
                invitation_id=invitation["id"],
                channel=channel,
                recipient=recipient,
                status="failed",
                error_message="لا يوجد بريد إلكتروني صالح لهذه الدعوة.",
            )
            failed += 1
            continue

        invitation_link = f"{settings.app_url.rstrip('/')}/i/{quote(str(invitation['token']), safe='')}"
        try:
            smtp_accepted = await asyncio.to_thread(
                send_event_invitation_email,
                recipient,
                invitation_link,
                invitation.get("event_title") or "فعاليتنا",
                invitation.get("guest_name") or "",
                body.message,
            )
        except Exception:
            logger.exception("Event invitation email dispatch failed for invitation %s", invitation["id"])
            smtp_accepted = False

        if not smtp_accepted:
            await _record_invitation_delivery(
                db,
                invitation_id=invitation["id"],
                channel=channel,
                recipient=recipient,
                status="failed",
                error_message="تعذّر على خادم البريد قبول الرسالة.",
            )
            failed += 1
            continue

        await _record_invitation_delivery(
            db,
            invitation_id=invitation["id"],
            channel=channel,
            recipient=recipient,
            status="sent",
        )
        # Preserve later lifecycle states (viewed/accepted/etc.); a successful
        # resend must never move an invitation backwards to "sent".
        await db.execute(
            text("UPDATE invitations SET status = 'sent', updated_at = now() WHERE id = :id AND status = 'created'"),
            {"id": str(invitation["id"])},
        )
        sent += 1

    # The atomic quota increment is a reservation. Release capacity for
    # candidate messages that the SMTP relay did not accept.
    if email_candidates and sent < len(email_candidates):
        from app.services.usage_service import release_usage
        await release_usage(
            db, tenant_id, "messages_per_month", len(email_candidates) - sent,
        )

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="invitations.send", resource_type="invitation",
                    metadata={
                        "count": sent, "failed": failed, "skipped": skipped,
                        "channel": channel.value,
                    },
                    ip_address=get_client_ip(request))
    await db.commit()
    result = {"sent": sent, "failed": failed, "skipped": skipped}
    if failed and not sent:
        return JSONResponse(status_code=503, content=result)
    if failed:
        return JSONResponse(status_code=207, content=result)
    return result


# ══════════════════════════════════════════════
# PUBLIC: VIEW INVITATION (by token, no auth)
# ══════════════════════════════════════════════

@router.get("/view/{token}")
async def view_invitation_public(
    token: str,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Public endpoint: view invitation by token (marks as viewed).
    Returns ONLY guest-safe fields — no tenant_id, internal IDs, or admin data."""
    result = await db.execute(
        text("""
            SELECT
                i.id, i.token, i.status, i.expires_at, i.ticket_class,
                i.guest_name, i.guest_name_ar,
                i.seat_number, i.table_number, i.hall, i.zone,
                i.barcode_png_url, i.render_image_url, i.card_image_url,
                i.qr_data, i.rsvp_status, i.rsvp_at, i.plus_one_count, i.rsvp_message, i.metadata,
                e.title AS event_title, e.title_ar AS event_title_ar,
                e.start_date, e.end_date,
                e.venue_name, e.venue_name_ar,
                e.venue_address, e.venue_map_url, e.venue_lat, e.venue_lng,
                e.allow_rsvp, e.allow_plus_one, e.cover_image_url
            FROM invitations i
            JOIN events e ON e.id = i.event_id
            WHERE i.token = :token
        """),
        {"token": token},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدعوة غير موجودة")

    if row["status"] in ("revoked", "expired"):
        raise HTTPException(410, "الدعوة ملغاة أو منتهية")
    await _reject_expired_public_invitation(db, dict(row))

    # Mark as viewed (update by primary key only)
    if row["status"] in ("created", "sent"):
        await db.execute(
            text("UPDATE invitations SET status = 'viewed', updated_at = now() WHERE id = :id AND token = :token"),
            {"id": str(row["id"]), "token": token},
        )
        await db.commit()

    return dict(row)


# ══════════════════════════════════════════════
# PUBLIC: RSVP (by token)
# ══════════════════════════════════════════════

@router.post("/rsvp/{token}")
async def rsvp_invitation(
    token: str, body: RsvpRequest,
    db: AsyncSession = Depends(get_privileged_db),
):
    """Public endpoint: RSVP to an invitation.
    Narrow query: only fetches the 4 fields needed for validation."""
    result = await db.execute(
        text("""
            SELECT i.id, i.tenant_id, i.event_id, i.ticket_class::text AS ticket_class,
                   i.status, i.expires_at, i.metadata,
                   COALESCE(i.guest_count, 1) AS guest_count,
                   COALESCE(i.plus_one_count, 0) AS plus_one_count,
                   e.allow_rsvp, e.allow_plus_one
            FROM invitations i JOIN events e ON e.id = i.event_id
            WHERE i.token = :token
        """),
        {"token": token},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدعوة غير موجودة")
    if row["status"] in ("revoked", "expired"):
        raise HTTPException(410, "الدعوة ملغاة أو منتهية")
    await _reject_expired_public_invitation(db, dict(row))

    meta = row["metadata"] or {}
    require_rsvp = meta.get("require_rsvp") is True or str(meta.get("require_rsvp")).lower() == "true"

    if not row["allow_rsvp"] and not require_rsvp:
        raise HTTPException(400, "RSVP غير مفعّل لهذه المناسبة")

    metadata = dict(row["metadata"] or {})
    current_guest_count = int(row["guest_count"] or 1)
    current_plus_one = int(row["plus_one_count"] or 0)
    persisted_base = metadata.get("rsvp_base_guest_count")
    # Trust the persisted baseline only when it matches the current effective
    # entitlement. This repairs rows created before RSVP companions were
    # counted without letting arbitrary metadata change the base allocation.
    if (
        isinstance(persisted_base, int)
        and persisted_base >= 1
        and current_guest_count == persisted_base + current_plus_one
    ):
        base_guest_count = persisted_base
    else:
        base_guest_count = current_guest_count

    plus_one = (
        body.plus_one_count
        if body.status == RsvpStatus.accepted and row["allow_plus_one"]
        else 0
    )
    new_guest_count = base_guest_count + plus_one
    quota_delta = new_guest_count - current_guest_count
    if quota_delta > 0:
        await _quota_check_single(
            db,
            str(row["tenant_id"]),
            str(row["event_id"]),
            row["ticket_class"],
            count=quota_delta,
        )

    metadata["rsvp_base_guest_count"] = base_guest_count
    new_status = "accepted" if body.status == RsvpStatus.accepted else (
        "declined" if body.status == RsvpStatus.declined else row["status"]
    )

    # Update by primary key + token double-check (prevents any cross-tenant leak)
    await db.execute(
        text("""
            UPDATE invitations SET
                rsvp_status = :rsvp, rsvp_at = now(), plus_one_count = :plus,
                guest_count = :guest_count, metadata = CAST(:metadata AS jsonb),
                rsvp_message = :msg, status = :st, updated_at = now()
            WHERE id = :id AND token = :token
        """),
        {
            "rsvp": body.status.value,
            "plus": plus_one,
            "guest_count": new_guest_count,
            "metadata": json.dumps(metadata),
            "msg": body.message,
            "st": new_status,
            "id": str(row["id"]),
            "token": token,
        },
    )
    await db.commit()
    return {"message": "تم تسجيل ردك بنجاح", "rsvp_status": body.status.value}


# ══════════════════════════════════════════════
# HELPER: Check quota
# ══════════════════════════════════════════════

async def _check_quota(db: AsyncSession, tenant_id: str, event_id: str, ticket_class: str):
    """Check if event has room for more invitations of this class.
    
    NOTE: Kept as a thin wrapper for backward compatibility
    (imported by registration_forms.py). Delegates to quota_service.
    """
    await _quota_check_single(db, tenant_id, event_id, ticket_class, count=1)


async def _generate_barcode_for_row(db: AsyncSession, tenant_id, event_id, inv: dict):
    """Generate QR barcode data and optionally upload to storage.
    
    Strategy: Always set qr_data + signature (fast, no network).
    Upload SVG/PNG to Storage only if available (non-blocking on failure).
    """
    try:
        invite_id = str(inv["id"])
        token = inv["token"]

        # Step 1: Build payload + signature (CPU only, instant)
        payload_info = barcode_service.build_barcode_payload(invite_id, token)

        # Always update qr_data + signature (no storage needed)
        await db.execute(
            text("""
                UPDATE invitations SET
                    barcode_payload = :payload,
                    barcode_signature = :sig,
                    qr_data = :qr_data,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "payload": payload_info["barcode_payload"],
                "sig": payload_info["signature"],
                "qr_data": payload_info["payload"],
                "id": invite_id,
            },
        )

        # Step 2: Try to upload images to storage (best-effort, 5s timeout)
        try:
            import asyncio

            def _sync_upload():
                """Run all sync storage I/O in a thread."""
                bc = barcode_service.generate_barcode_for_invitation(invite_id, token)
                svg_path = storage_service.upload_barcode_svg(tenant_id, event_id, inv["id"], bc["svg_bytes"])
                png_path = storage_service.upload_barcode_png(tenant_id, event_id, inv["id"], bc["png_bytes"])
                svg_url = storage_service.get_signed_url(svg_path, expires_in=86400 * 30)
                png_url = storage_service.get_signed_url(png_path, expires_in=86400 * 30)
                return svg_url, png_url

            loop = asyncio.get_event_loop()
            svg_url, png_url = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_upload),
                timeout=5.0
            )

            await db.execute(
                text("""
                    UPDATE invitations SET
                        barcode_svg_url = :svg,
                        barcode_png_url = :png,
                        updated_at = now()
                    WHERE id = :id
                """),
                {"svg": svg_url, "png": png_url, "id": invite_id},
            )
        except asyncio.TimeoutError:
            logger.warning("Storage upload timed out for %s (will retry in batch)", invite_id)
        except Exception as storage_err:
            logger.warning(
                "Storage upload skipped for %s (will retry in batch): %s",
                invite_id, storage_err
            )

    except Exception as e:
        logger.warning("Barcode generation failed for %s: %s", inv.get("id"), e)
