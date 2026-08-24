"""Event Registration Forms API: Admin settings and public submission handling."""
import logging
import re
from uuid import UUID
import json
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.services.permission_service import require_permission
from app.services.audit_service import log_audit
from app.security import get_client_ip
from app.models.registration_form import (
    RegistrationFormRead,
    RegistrationFormCreate,
    RegistrationFormUpdate,
    PublicRegistrationSubmit,
)
from app.routes.digital_invitations import _check_quota, _generate_barcode_for_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Event Registration Forms"])


async def render_designed_card_for_invite(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
    invite_row: dict,
    template_id: UUID,
    event_row: dict
) -> Optional[str]:
    """Helper to render template card immediately for registered guest in immediate mode."""
    try:
        # 1. Load the template
        t_res = await db.execute(
            text("SELECT * FROM invite_templates WHERE id = :id"),
            {"id": str(template_id)}
        )
        template = t_res.mappings().first()
        if not template:
            logger.warning(f"Template {template_id} not found, skipping designed card render.")
            return None

        # 2. Load template elements
        e_res = await db.execute(
            text("SELECT * FROM template_elements WHERE template_id = :tid AND is_visible = true ORDER BY sort_order, z_index"),
            {"tid": str(template_id)}
        )
        elements = [dict(el) for el in e_res.mappings().all()]

        # 3. Get background bytes
        from app.services import storage_service, render_service
        bg_url = template.get("background_url")
        bg_bytes = None
        if bg_url:
            try:
                bg_bytes = await storage_service.download_reference(bg_url)
            except Exception:
                logger.warning("Registration template background download failed")

        # 4. Build render context
        from app.services.batch_pipeline import _build_render_context
        ctx = _build_render_context(invite_row, {}, event=event_row, guest=None)

        canvas_width = template.get("width_px", 1240)
        canvas_height = template.get("height_px", 1754)
        slot_contexts = [ctx]

        # 5. Render image
        img_bytes = render_service.render_invitation_image(
            background_bytes=bg_bytes,
            elements=elements,
            context=ctx,
            slot_contexts=slot_contexts,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            background_transform=template.get("metadata", {}).get("background_transform") if template.get("metadata") else None,
            base_canvas=None
        )

        # 6. Upload render
        render_path = storage_service.upload_render_image(tenant_id, event_id, invite_row["id"], img_bytes)
        render_url = storage_service.get_signed_url(render_path, expires_in=86400 * 30)

        # 7. Update database
        await db.execute(
            text("UPDATE invitations SET render_image_url = :url, card_image_url = :url, updated_at = now() WHERE id = :id"),
            {"url": render_url, "id": str(invite_row["id"])},
        )
        return render_url

    except Exception as exc:
        logger.exception(f"Failed designed card rendering for invite {invite_row.get('id')}: {exc}")
        return None


# ══════════════════════════════════════════════
# ADMIN / ORGANIZER ENDPOINTS
# ══════════════════════════════════════════════

@router.get("/events/{event_id}/registration-form", response_model=RegistrationFormRead)
async def get_registration_form(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve registration form settings (admin)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.view")

    # Verify event belongs to tenant
    event_res = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    if not event_res.first():
        raise HTTPException(404, "الحدث غير موجود")

    result = await db.execute(
        text("SELECT * FROM event_registration_forms WHERE event_id = :eid AND tenant_id = :tid"),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        # Create a default disabled form
        result = await db.execute(
            text("""
                INSERT INTO event_registration_forms (
                    tenant_id, event_id, is_enabled, barcode_generation_mode, default_ticket_class, fields, expires_at
                )
                VALUES (:tid, :eid, false, 'immediate', 'normal', '[]'::jsonb, null)
                RETURNING *
            """),
            {"tid": str(tenant_id), "eid": str(event_id)},
        )
        row = result.mappings().first()
        await db.commit()

    return RegistrationFormRead(**dict(row))


@router.post("/events/{event_id}/registration-form", response_model=RegistrationFormRead)
async def save_registration_form(
    event_id: UUID,
    body: RegistrationFormCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update registration form settings (admin)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "events.edit")

    # Verify event belongs to tenant
    event_res = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    if not event_res.first():
        raise HTTPException(404, "الحدث غير موجود")

    if body.default_template_id:
        template = await db.execute(text("""
            SELECT 1 FROM invite_templates
            WHERE id=:template_id AND tenant_id=:tenant_id AND is_active=true
              AND (event_id=:event_id OR event_id IS NULL)
        """), {"template_id": str(body.default_template_id), "tenant_id": str(tenant_id),
                "event_id": str(event_id)})
        if not template.first():
            raise HTTPException(422, "قالب التسجيل غير متاح لهذا الحدث")

    if body.is_enabled:
        from app.services.feature_service import enforce_static_limit, acquire_plan_limit_lock
        await acquire_plan_limit_lock(db, tenant_id, "registration_forms_max")
        from app.services.entitlement_service import get_billing_scope_tenant_ids
        scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
        enabled_res = await db.execute(
            text("""
                SELECT COUNT(*) FROM event_registration_forms
                WHERE tenant_id = ANY(:tids) AND is_enabled = true AND event_id != :eid
            """),
            {"tids": [str(item) for item in scope_tenant_ids], "eid": str(event_id)},
        )
        enabled_count = enabled_res.scalar() or 0
        await enforce_static_limit(
            db, tenant_id, "registration_forms_max",
            enabled_count, "نماذج التسجيل النشطة",
        )

    fields_json = json.dumps([f.model_dump() for f in body.fields], ensure_ascii=False)

    # Upsert event_registration_forms
    result = await db.execute(
        text("""
            INSERT INTO event_registration_forms (
                tenant_id, event_id, is_enabled, barcode_generation_mode, default_ticket_class,
                default_template_id, success_message_ar, success_message_en,
                pending_approval_message_ar, pending_approval_message_en, fields, expires_at
            )
            VALUES (
                :tid, :eid, :is_enabled, :mode, CAST(:tc AS ticket_class),
                :tmpl, :success_ar, :success_en,
                :pending_ar, :pending_en, CAST(:fields AS jsonb), :expires_at
            )
            ON CONFLICT (event_id) DO UPDATE SET
                is_enabled = EXCLUDED.is_enabled,
                barcode_generation_mode = EXCLUDED.barcode_generation_mode,
                default_ticket_class = EXCLUDED.default_ticket_class,
                default_template_id = EXCLUDED.default_template_id,
                success_message_ar = EXCLUDED.success_message_ar,
                success_message_en = EXCLUDED.success_message_en,
                pending_approval_message_ar = EXCLUDED.pending_approval_message_ar,
                pending_approval_message_en = EXCLUDED.pending_approval_message_en,
                fields = EXCLUDED.fields,
                expires_at = EXCLUDED.expires_at,
                updated_at = now()
            RETURNING *
        """),
        {
            "tid": str(tenant_id),
            "eid": str(event_id),
            "is_enabled": body.is_enabled,
            "mode": body.barcode_generation_mode,
            "tc": body.default_ticket_class.value if hasattr(body.default_ticket_class, "value") else str(body.default_ticket_class),
            "tmpl": str(body.default_template_id) if body.default_template_id else None,
            "success_ar": body.success_message_ar,
            "success_en": body.success_message_en,
            "pending_ar": body.pending_approval_message_ar,
            "pending_en": body.pending_approval_message_en,
            "fields": fields_json,
            "expires_at": body.expires_at,
        }
    )
    row = result.mappings().first()
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="event.registration_form_update", resource_type="event", resource_id=str(event_id),
                    ip_address=get_client_ip(request))
    await db.commit()
    return RegistrationFormRead(**dict(row))


# ══════════════════════════════════════════════
# PUBLIC ENDPOINTS
# ══════════════════════════════════════════════

@router.get("/public/events/{slug}/logo")
async def get_public_event_logo(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve a published event logo through the API so canvas downloads are CORS-safe."""
    logo = (await db.execute(text("""
        SELECT a.file_url, a.mime_type
        FROM event_assets a
        JOIN events e ON e.id=a.event_id
        WHERE e.slug=:slug AND e.deleted_at IS NULL
          AND e.status IN ('published','active')
          AND a.asset_type IN ('logo','cover_image')
        ORDER BY CASE WHEN a.asset_type='logo' THEN 0 ELSE 1 END,
                 a.created_at DESC LIMIT 1
    """), {"slug": slug})).mappings().first()
    if not logo:
        raise HTTPException(404, "شعار الحدث غير موجود")
    from app.services import storage_service
    try:
        content = await storage_service.download_reference(logo["file_url"], max_bytes=5 * 1024 * 1024)
    except Exception as error:
        logger.warning("Public event logo download failed for slug %s", slug)
        raise HTTPException(404, "تعذر تحميل شعار الحدث") from error
    return Response(
        content=content,
        media_type=logo["mime_type"] or "image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )

@router.get("/public/events/{slug}/register-info")
async def get_public_register_info(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch public event and registration form settings (no auth)."""
    # Fetch event details
    event_res = await db.execute(
        text("""
            SELECT id, tenant_id, title, title_ar, start_date, end_date,
                   venue_name, venue_name_ar, venue_address, cover_image_url,
                   (SELECT file_url FROM event_assets
                    WHERE event_id=events.id AND asset_type='logo'
                    ORDER BY created_at DESC LIMIT 1) AS logo_path
            FROM events
            WHERE slug = :slug AND deleted_at IS NULL AND status IN ('published','active')
        """),
        {"slug": slug}
    )
    event_row = event_res.mappings().first()
    if not event_row:
        raise HTTPException(404, "الحدث غير موجود")
    event_data = dict(event_row)
    logo_path = event_data.pop("logo_path", None)
    if logo_path or event_data.get("cover_image_url"):
        event_data["logo_url"] = f"/api/v1/public/events/{slug}/logo"

    # Fetch registration form settings
    form_res = await db.execute(
        text("SELECT * FROM event_registration_forms WHERE event_id = :eid"),
        {"eid": str(event_row["id"])}
    )
    form_row = form_res.mappings().first()
    
    # If no form row exists, it means registration is not configured/enabled yet.
    if not form_row:
        return {
            "event": event_data,
            "form": {
                "is_enabled": False,
                "expires_at": None,
                "fields": [],
                "success_message_ar": None,
                "success_message_en": None,
                "pending_approval_message_ar": None,
                "pending_approval_message_en": None
            }
        }
        
    return {
        "event": event_data,
        "form": {
            "is_enabled": form_row["is_enabled"],
            "expires_at": form_row["expires_at"].isoformat() if form_row["expires_at"] else None,
            "fields": form_row["fields"],
            "success_message_ar": form_row["success_message_ar"],
            "success_message_en": form_row["success_message_en"],
            "pending_approval_message_ar": form_row["pending_approval_message_ar"],
            "pending_approval_message_en": form_row["pending_approval_message_en"]
        }
    }


@router.post("/public/events/{slug}/register")
async def public_register(
    slug: str,
    body: PublicRegistrationSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Handle public guest registration submission (no auth)."""
    # 1. Fetch event
    event_res = await db.execute(
        text("""
            SELECT id, tenant_id, title, title_ar, start_date, end_date,
                   venue_name, venue_name_ar, venue_address, cover_image_url,
                   (SELECT file_url FROM event_assets
                    WHERE event_id=events.id AND asset_type='logo'
                    ORDER BY created_at DESC LIMIT 1) AS logo_path
            FROM events
            WHERE slug = :slug AND deleted_at IS NULL AND status IN ('published','active')
        """),
        {"slug": slug}
    )
    event_row = event_res.mappings().first()
    if not event_row:
        raise HTTPException(404, "الحدث غير موجود")
    event_data = dict(event_row)
    logo_path = event_data.pop("logo_path", None)
    if logo_path:
        from app.services import storage_service
        event_data["logo_url"] = (
            storage_service.get_signed_url(logo_path, expires_in=86400 * 365)
            if logo_path.startswith(f"{event_data['tenant_id']}/{event_data['id']}/") else logo_path
        )

    tenant_id = event_row["tenant_id"]
    event_id = event_row["id"]

    # 2. Fetch form config
    form_res = await db.execute(
        text("SELECT * FROM event_registration_forms WHERE event_id = :eid"),
        {"eid": str(event_id)}
    )
    form_row = form_res.mappings().first()
    if not form_row or not form_row["is_enabled"]:
        raise HTTPException(400, "التسجيل مغلق لهذا الحدث")

    # Check expiration time
    if form_row.get("expires_at"):
        from datetime import datetime, timezone
        if datetime.now(timezone.utc) > form_row["expires_at"]:
            raise HTTPException(400, "عذراً، لقد انتهى وقت التسجيل في هذه الفعالية")

    # 3. Check quota limit (event-level)
    await _check_quota(db, str(tenant_id), str(event_id), form_row["default_ticket_class"])

    # The event-level advisory lock is now held. Re-check under that lock so
    # concurrent retries cannot both pass the first lookup and create twice.
    existing = (await db.execute(text("""
        SELECT id, token, guest_name, ticket_class, status, barcode_png_url, card_image_url
        FROM invitations
        WHERE event_id=:eid AND registration_request_id=:request_id
    """), {"eid": str(event_id), "request_id": str(body.registration_request_id)})).mappings().first()
    if existing:
        immediate = form_row["barcode_generation_mode"] == "immediate"
        return {
            "status": "success" if immediate else "pending",
            "message": (form_row["success_message_ar"] if immediate else form_row["pending_approval_message_ar"]),
            "mode": form_row["barcode_generation_mode"],
            "invitation": {
                "id": str(existing["id"]), "token": existing["token"] if immediate else None,
                "guest_name": existing["guest_name"], "ticket_class": existing["ticket_class"],
                "barcode_png_url": existing["barcode_png_url"] if immediate else None,
                "card_image_url": existing["card_image_url"] if immediate else None,
            },
        }

    phone_key = re.sub(r"\D", "", body.guest_phone)
    email_key = body.guest_email.strip().casefold() if body.guest_email else None
    duplicate = (await db.execute(text("""
        SELECT
          EXISTS(
            SELECT 1 FROM invitations
            WHERE event_id=:eid AND is_registration=true
              AND regexp_replace(COALESCE(guest_phone, ''), '[^0-9]+', '', 'g')=:phone_key
          ) AS phone_exists,
          CASE WHEN CAST(:email_key AS text) IS NULL THEN false ELSE EXISTS(
            SELECT 1 FROM invitations
            WHERE event_id=:eid AND is_registration=true
              AND lower(trim(COALESCE(guest_email, '')))=CAST(:email_key AS text)
          ) END AS email_exists
    """), {"eid": str(event_id), "phone_key": phone_key, "email_key": email_key})).mappings().one()
    duplicate_fields = []
    if duplicate["phone_exists"]:
        duplicate_fields.append("رقم الهاتف")
    if duplicate["email_exists"]:
        duplicate_fields.append("البريد الإلكتروني")
    if duplicate_fields:
        raise HTTPException(409, {
            "message": "سبق التسجيل في هذا الحدث بهذه البيانات",
            "fields": duplicate_fields,
        })

    # 3b. Plan limits (platform-level)
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية")
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل حدث")

    # 4. Save custom answers into invitation metadata using human-readable labels
    custom_fields_with_labels = {}
    fields_list = form_row["fields"] or []
    configured_fields = {field.get("id"): field for field in fields_list if isinstance(field, dict) and field.get("id")}
    unknown_fields = set((body.custom_answers or {}).keys()) - set(configured_fields)
    if unknown_fields:
        raise HTTPException(422, "تحتوي الإجابة على حقول غير معرّفة في النموذج")
    missing_required = [
        field.get("label") or field_id for field_id, field in configured_fields.items()
        if field.get("required") and not field.get("system")
        and (body.custom_answers or {}).get(field_id) in (None, "", False, [])
    ]
    if missing_required:
        raise HTTPException(422, {"message": "حقول مطلوبة ناقصة", "fields": missing_required})
    if body.custom_answers:
        fields_map = {}
        for f in fields_list:
            if isinstance(f, dict) and "id" in f:
                fields_map[f["id"]] = f.get("label") or f["id"]
        for fid, val in body.custom_answers.items():
            label = fields_map.get(fid, fid)
            custom_fields_with_labels[label] = val

    metadata = {
        "custom_fields": custom_fields_with_labels,
        "is_registration": True
    }

    mode = form_row["barcode_generation_mode"]
    
    # Map invitation status based on mode
    # immediate -> status='created', rsvp_status='accepted' (or status='accepted' directly)
    # deferred -> status='created', rsvp_status='pending'
    if mode == "immediate":
        status_val = "accepted"
        rsvp_status_val = "accepted"
    else:
        status_val = "created"
        rsvp_status_val = "pending"

    # 5. Insert invitation
    # Note: token and token_hash are generated automatically on DB side
    try:
        insert_res = await db.execute(
            text("""
            INSERT INTO invitations (
                tenant_id, event_id, template_id, ticket_class,
                guest_name, guest_name_ar, guest_phone, guest_email,
                status, rsvp_status, metadata, is_registration, registration_request_id,
                registration_phone_key, registration_email_key
            ) VALUES (
                :tid, :eid, :tmpl, CAST(:tc AS ticket_class),
                :gname, :gname_ar, :gphone, :gemail,
                :status, :rsvp_status, CAST(:meta AS jsonb), true, :request_id,
                :phone_key, :email_key
            )
            RETURNING *
            """),
            {
            "tid": str(tenant_id),
            "eid": str(event_id),
            "tmpl": str(form_row["default_template_id"]) if form_row["default_template_id"] else None,
            "tc": form_row["default_ticket_class"],
            "gname": body.guest_name,
            "gname_ar": body.guest_name,  # Arabic and English name equal for self-registration
            "gphone": body.guest_phone,
            "gemail": body.guest_email,
            "status": status_val,
            "rsvp_status": rsvp_status_val,
            "meta": json.dumps(metadata, ensure_ascii=False),
            "request_id": str(body.registration_request_id),
            "phone_key": phone_key,
            "email_key": email_key,
            }
        )
    except IntegrityError as error:
        await db.rollback()
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", "") or ""
        field = "البريد الإلكتروني" if "email" in constraint else "رقم الهاتف"
        raise HTTPException(409, {
            "message": "سبق التسجيل في هذا الحدث بهذه البيانات",
            "fields": [field],
        }) from error
    row = insert_res.mappings().first()
    inv_dict = dict(row)

    # 6. If immediate mode, generate barcode and designed card image immediately
    if mode == "immediate":
        # Generate barcode payload/signature + Storage uploads
        await _generate_barcode_for_row(db, tenant_id, event_id, inv_dict)

        # Re-fetch invitation to get updated barcode fields
        refetch_res = await db.execute(
            text("SELECT * FROM invitations WHERE id = :id"),
            {"id": str(row["id"])}
        )
        updated_inv_dict = dict(refetch_res.mappings().first())

        # Render Designed Card if a template is set
        if form_row["default_template_id"]:
            card_url = await render_designed_card_for_invite(
                db, tenant_id, event_id, updated_inv_dict, form_row["default_template_id"], event_data
            )
            if card_url:
                updated_inv_dict["card_image_url"] = card_url
                updated_inv_dict["render_image_url"] = card_url

        await db.commit()
        
        # Return final registration result
        return {
            "status": "success",
            "message": form_row["success_message_ar"] or "تم تسجيلكم بنجاح!",
            "mode": "immediate",
            "invitation": {
                "id": str(updated_inv_dict["id"]),
                "token": updated_inv_dict["token"],
                "guest_name": updated_inv_dict["guest_name"],
                "ticket_class": updated_inv_dict["ticket_class"],
                "barcode_png_url": updated_inv_dict.get("barcode_png_url"),
                "card_image_url": updated_inv_dict.get("card_image_url")
            }
        }
    else:
        # Deferred mode: just commit and return success
        await db.commit()
        return {
            "status": "pending",
            "message": form_row["pending_approval_message_ar"] or "تم استلام طلبكم بنجاح وهو قيد المراجعة.",
            "mode": "deferred",
            "invitation": {
                "id": str(inv_dict["id"]),
                "guest_name": inv_dict["guest_name"]
            }
        }
