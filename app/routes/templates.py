"""Templates API: CRUD for invite templates, elements, and assets."""
import base64
import io
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
import json
from PIL import Image

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db
from app.models.template import (
    TemplateCreate, TemplateRead, TemplateUpdate,
    ElementCreate, ElementRead, ElementUpdate,
    AssetRead,
)
from app.services.permission_service import require_permission
from app.services.audit_service import log_audit
from app.services import storage_service
from app.services.render_service import render_invitation_image, prepare_background_canvas
from app.security import get_client_ip

router = APIRouter(prefix="/templates", tags=["Templates"])
logger = logging.getLogger(__name__)

A4_CANVAS_WIDTH = 1240
A4_CANVAS_HEIGHT = 1754


def _fit_to_a4_canvas(image: Image.Image) -> tuple[bytes, int, int]:
    """Return a white A4 PNG canvas with the uploaded design centered inside it."""
    image = image.convert("RGBA")
    canvas = Image.new("RGBA", (A4_CANVAS_WIDTH, A4_CANVAS_HEIGHT), "#ffffff")
    scale = min(A4_CANVAS_WIDTH / image.width, A4_CANVAS_HEIGHT / image.height)
    target_w = max(1, int(image.width * scale))
    target_h = max(1, int(image.height * scale))
    resized = image.resize((target_w, target_h), Image.LANCZOS)
    paste_x = (A4_CANVAS_WIDTH - target_w) // 2
    paste_y = (A4_CANVAS_HEIGHT - target_h) // 2
    canvas.paste(resized, (paste_x, paste_y), resized)

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue(), A4_CANVAS_WIDTH, A4_CANVAS_HEIGHT


def _read_background_upload(file: UploadFile, content: bytes) -> tuple[bytes, str, int, int]:
    """Normalize any background upload to an A4 PNG and return width/height."""

    if file.content_type == "application/pdf":
        try:
            import fitz

            document = fitz.open(stream=content, filetype="pdf")
            if document.page_count < 1:
                raise HTTPException(400, "ملف PDF فارغ")
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            png_bytes, width_px, height_px = _fit_to_a4_canvas(image)
            return png_bytes, "image/png", width_px, height_px
        except ImportError:
            raise HTTPException(500, "يلزم تثبيت PyMuPDF لدعم رفع ملفات PDF")
        except HTTPException:
            raise
        except Exception:
            logger.warning("Could not convert uploaded template PDF", exc_info=True)
            raise HTTPException(400, "تعذر تحويل ملف PDF إلى صورة")

    try:
        with Image.open(io.BytesIO(content)) as image_file:
            png_bytes, width_px, height_px = _fit_to_a4_canvas(image_file)
        return png_bytes, "image/png", width_px, height_px
    except Exception:
        logger.warning("Could not parse uploaded template image", exc_info=True)
        raise HTTPException(400, "تعذر قراءة أبعاد الصورة")


# ══════════════════════════════════════════════
# TEMPLATES CRUD
# ══════════════════════════════════════════════

@router.get("", response_model=list[TemplateRead])
async def list_templates(
    request: Request,
    event_id: UUID = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.view")

    query = "SELECT * FROM invite_templates WHERE tenant_id = :tid"
    params: dict = {"tid": str(tenant_id)}
    if event_id:
        query += " AND (event_id = :eid OR event_id IS NULL)"
        params["eid"] = str(event_id)
    query += " ORDER BY created_at DESC"

    result = await db.execute(text(query), params)
    return [TemplateRead(**dict(r)) for r in result.mappings().all()]


@router.post("", response_model=TemplateRead, status_code=201)
async def create_template(
    body: TemplateCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.create")
    if body.background_url is not None:
        raise HTTPException(400, "استخدم مسار رفع خلفية القالب المعتمد")

    # ── Plan limit: designed_templates ──
    if body.template_type == "designed":
        from app.services.feature_service import enforce_static_limit, acquire_plan_limit_lock
        await acquire_plan_limit_lock(db, tenant_id, "designed_templates")
        from app.services.entitlement_service import get_billing_scope_tenant_ids
        scope_tenant_ids = await get_billing_scope_tenant_ids(db, tenant_id)
        tmpl_count_res = await db.execute(
            text("SELECT COUNT(*) FROM invite_templates WHERE tenant_id = ANY(:tids) AND template_type = 'designed'"),
            {"tids": [str(item) for item in scope_tenant_ids]},
        )
        current_templates = tmpl_count_res.scalar() or 0
        await enforce_static_limit(db, tenant_id, "designed_templates", current_templates, "القوالب المصممة")

    result = await db.execute(
        text("""
            INSERT INTO invite_templates (
                tenant_id, event_id, name, template_type, ticket_class,
                width_px, height_px, orientation,
                background_url, background_color, quick_style,
                is_default, metadata, created_by
            ) VALUES (
                :tid, :eid, :name, CAST(:ttype AS template_type), CAST(:tc AS ticket_class),
                :w, :h, :orient,
                :bg_url, :bg_color, CAST(:qstyle AS jsonb),
                :is_default, CAST(:meta AS jsonb), :uid
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id),
            "eid": str(body.event_id) if body.event_id else None,
            "name": body.name, "ttype": body.template_type, "tc": body.ticket_class,
            "w": body.width_px, "h": body.height_px, "orient": body.orientation,
            "bg_url": body.background_url, "bg_color": body.background_color,
            "qstyle": json.dumps(body.quick_style or {}, default=str),
            "is_default": body.is_default,
            "meta": json.dumps(body.metadata or {}, default=str),
            "uid": str(user.id),
        },
    )
    row = result.mappings().first()
    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="template.create", resource_type="template", resource_id=str(row["id"]),
                    ip_address=get_client_ip(request))
    await db.commit()
    return TemplateRead(**dict(row))


@router.get("/fonts")
def list_fonts():
    """List all available fonts in the fonts/ directory."""
    fonts_dir = "fonts"
    families = set()
    
    # Scan actual files to build clean family list
    if os.path.exists(fonts_dir):
        for filename in os.listdir(fonts_dir):
            if not filename.lower().endswith((".ttf", ".otf")):
                continue
            name = os.path.splitext(filename)[0]
            # Strip common suffixes to get the family name
            family = name
            for suffix in ("-Regular", "-Bold", "-Italic", "-Light", "-Medium", "-SemiBold", "-ExtraBold", "-Thin"):
                if family.endswith(suffix):
                    family = family[:-len(suffix)]
                    break
            families.add(family)
    
    # Always include hardcoded defaults even if files don't exist yet
    for default_family in ["Cairo", "Tajawal", "Amiri", "Noto", "NotoSansArabic"]:
        families.add(default_family)
    
    result = []
    for f in sorted(list(families)):
        result.append({
            "value": f,
            "label": f
        })
    return result


@router.post("/fonts/upload")
async def upload_font(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a new TTF or OTF font file."""
    # Fonts are shared server-side assets; only platform staff may write them.
    from app.services.staff_service import require_staff
    await require_staff(user=user, db=db)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".ttf", ".otf"):
        raise HTTPException(400, "فقط ملفات الخطوط من نوع .ttf أو .otf مدعومة")
        
    # Normalize filename: lowercase extension, remove non-alphanumeric (except dashes and underscores)
    base = os.path.splitext(os.path.basename(file.filename))[0]
    safe_base = "".join(c for c in base if c.isalnum() or c in ("-", "_")).strip()
    if not safe_base:
        safe_base = "uploaded_font"
    filename = f"{safe_base}{ext}"
    
    os.makedirs("fonts", exist_ok=True)
    target_path = os.path.join("fonts", filename)
    
    try:
        content = await file.read(MAX_FONT_SIZE + 1)
        if len(content) > MAX_FONT_SIZE:
            raise HTTPException(413, "حجم ملف الخط يتجاوز 5MB")
        # Verify that PIL can load it
        try:
            from PIL import ImageFont
            ImageFont.truetype(io.BytesIO(content), 12)
        except Exception:
            raise HTTPException(400, "ملف الخط غير صالح أو تالف")
            
        with open(target_path, "wb") as f:
            f.write(content)
            
        # Clear render cache to force reloading
        from app.services.render_service import _font_cache
        _font_cache.clear()
        
        # Get family name
        family = os.path.splitext(filename)[0]
        if family.endswith("-Regular"):
            family = family[:-8]
        elif family.endswith("-Bold"):
            family = family[:-5]
            
        return {"status": "success", "font_family": family}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Platform font upload failed filename=%s", filename)
        raise HTTPException(500, "فشل رفع الخط")


@router.get("/fonts/file/{filename}")
def get_font_file(filename: str):
    """Serve a font file for previewing in the design editor."""
    filename = os.path.basename(filename)
    if not filename.lower().endswith((".ttf", ".otf")):
        raise HTTPException(400, "غير مسموح بتحميل هذا الملف")
        
    # Apply the same normalization to the requested filename to match the saved filename structure
    base, ext = os.path.splitext(filename)
    safe_base = "".join(c for c in base if c.isalnum() or c in ("-", "_")).strip()
    if not safe_base:
        safe_base = "uploaded_font"
    normalized_filename = f"{safe_base}{ext.lower()}"
        
    path = os.path.join("fonts", normalized_filename)
    if not os.path.exists(path):
        fonts_dir = "fonts"
        if os.path.exists(fonts_dir):
            # 1. Case-insensitive exact match
            target_lower = normalized_filename.lower()
            for file in os.listdir(fonts_dir):
                if file.lower() == target_lower:
                    path = os.path.join(fonts_dir, file)
                    break
            else:
                # 2. Family-based matching (strip common suffixes and find matching file)
                family = safe_base
                suffixes = ("-Regular", "-Bold", "-Italic", "-Light", "-Medium", "-SemiBold", "-ExtraBold", "-Thin")
                for suffix in suffixes:
                    if family.lower().endswith(suffix.lower()):
                        family = family[:-len(suffix)]
                        break
                
                family_lower = family.lower()
                candidates = []
                for file in os.listdir(fonts_dir):
                    if not file.lower().endswith(ext.lower()):
                        continue
                    file_base = os.path.splitext(file)[0].lower()
                    if file_base == family_lower or file_base.startswith(family_lower + "-") or file_base.startswith(family_lower + "_"):
                        candidates.append(file)
                
                if candidates:
                    # If original request wanted bold, prefer bold candidates
                    is_bold_req = any(x in safe_base.lower() for x in ("bold", "semibold", "extrabold"))
                    if is_bold_req:
                        bold_candidates = [c for c in candidates if "bold" in c.lower()]
                        if bold_candidates:
                            path = os.path.join(fonts_dir, bold_candidates[0])
                        else:
                            path = os.path.join(fonts_dir, candidates[0])
                    else:
                        # Prefer regular/normal candidates
                        regular_candidates = [c for c in candidates if "regular" in c.lower() or "normal" in c.lower()]
                        if regular_candidates:
                            path = os.path.join(fonts_dir, regular_candidates[0])
                        else:
                            path = os.path.join(fonts_dir, candidates[0])
                else:
                    raise HTTPException(404, "ملف الخط غير موجود")
        else:
            raise HTTPException(404, "ملف الخط غير موجود")
        
    media_type = "font/ttf" if path.lower().endswith(".ttf") else "font/otf"
    response = FileResponse(
        path,
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
    return response


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(
    template_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.view")

    result = await db.execute(
        text("SELECT * FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "القالب غير موجود")
    return TemplateRead(**dict(row))


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_template(
    template_id: UUID, body: TemplateUpdate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "لا توجد حقول للتعديل")
    if updates.get("background_url") is not None:
        raise HTTPException(400, "استخدم مسار رفع خلفية القالب المعتمد")

    # Serialize JSON fields
    for jf in ["quick_style", "metadata"]:
        if jf in updates and updates[jf] is not None:
            updates[jf] = json.dumps(updates[jf], default=str)

    set_parts = []
    for k in updates:
        if k in ("quick_style", "metadata"):
            set_parts.append(f"{k} = CAST(:{k} AS jsonb)")
        elif k == "template_type":
            set_parts.append(f"{k} = CAST(:{k} AS template_type)")
        elif k == "ticket_class":
            set_parts.append(f"{k} = CAST(:{k} AS ticket_class)")
        else:
            set_parts.append(f"{k} = :{k}")

    updates["id"] = str(template_id)
    updates["tid"] = str(tenant_id)

    result = await db.execute(
        text(f"UPDATE invite_templates SET {', '.join(set_parts)}, updated_at = now() WHERE id = :id AND tenant_id = :tid RETURNING *"),
        updates,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "القالب غير موجود")
    await db.commit()
    return TemplateRead(**dict(row))


@router.post("/background/inspect")
async def inspect_background(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(400, f"نوع الملف غير مدعوم. المسموح: {', '.join(allowed)}")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "حجم الملف يتجاوز 10MB")

    normalized_content, mime_type, width_px, height_px = _read_background_upload(file, content)
    return {
        "width_px": width_px,
        "height_px": height_px,
        "mime_type": mime_type,
        "file_size": len(normalized_content),
        "preview_data_url": f"data:{mime_type};base64,{base64.b64encode(normalized_content).decode('ascii')}",
    }


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.delete")

    result = await db.execute(
        text("DELETE FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "القالب غير موجود")
    await db.commit()


# ══════════════════════════════════════════════
# TEMPLATE ELEMENTS (إحداثيات العناصر)
# ══════════════════════════════════════════════

@router.get("/{template_id}/elements", response_model=list[ElementRead])
async def list_elements(
    template_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.view")

    # Verify template belongs to tenant
    tmpl = await db.execute(
        text("SELECT id FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    if not tmpl.first():
        raise HTTPException(404, "القالب غير موجود")

    result = await db.execute(
        text("SELECT * FROM template_elements WHERE template_id = :tid ORDER BY sort_order, z_index"),
        {"tid": str(template_id)},
    )
    return [ElementRead(**dict(r)) for r in result.mappings().all()]


@router.post("/{template_id}/elements", response_model=ElementRead, status_code=201)
async def add_element(
    template_id: UUID, body: ElementCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    result = await db.execute(
        text("""
            INSERT INTO template_elements (
                template_id, element_type, label, data_key,
                x, y, width, height, rotation,
                font_family, font_size, font_weight, font_color,
                text_align, text_direction, line_height, letter_spacing,
                qr_size, qr_color, qr_bg_color, qr_error_level,
                static_content, is_visible, z_index, sort_order, slot_index
            ) VALUES (
                :tmpl, :etype, :label, :dk,
                :x, :y, :w, :h, :rot,
                :ff, :fs, :fw, :fc,
                :ta, :td, :lh, :ls,
                :qs, :qc, :qbg, :qel,
                :sc, :vis, :zi, :so, :slot_idx
            )
            RETURNING *
        """),
        {
            "tmpl": str(template_id), "etype": body.element_type, "label": body.label, "dk": body.data_key,
            "x": body.x, "y": body.y, "w": body.width, "h": body.height, "rot": body.rotation,
            "ff": body.font_family, "fs": body.font_size, "fw": body.font_weight, "fc": body.font_color,
            "ta": body.text_align, "td": body.text_direction, "lh": body.line_height, "ls": body.letter_spacing,
            "qs": body.qr_size, "qc": body.qr_color, "qbg": body.qr_bg_color, "qel": body.qr_error_level,
            "sc": body.static_content, "vis": body.is_visible, "zi": body.z_index, "so": body.sort_order,
            "slot_idx": body.slot_index,
        },
    )
    row = result.mappings().first()
    await db.commit()
    return ElementRead(**dict(row))


@router.patch("/{template_id}/elements/{element_id}", response_model=ElementRead)
async def update_element(
    template_id: UUID, element_id: UUID, body: ElementUpdate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "لا توجد حقول للتعديل")

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["eid"] = str(element_id)
    updates["tmpl"] = str(template_id)

    result = await db.execute(
        text(f"UPDATE template_elements SET {set_clauses} WHERE id = :eid AND template_id = :tmpl RETURNING *"),
        updates,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "العنصر غير موجود")
    await db.commit()
    return ElementRead(**dict(row))


@router.delete("/{template_id}/elements/{element_id}", status_code=204)
async def delete_element(
    template_id: UUID, element_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    result = await db.execute(
        text("DELETE FROM template_elements WHERE id = :eid AND template_id = :tmpl"),
        {"eid": str(element_id), "tmpl": str(template_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(404, "العنصر غير موجود")
    await db.commit()


@router.put("/{template_id}/elements", response_model=list[ElementRead])
async def replace_all_elements(
    template_id: UUID, elements: list[ElementCreate], request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace all elements of a template (used by the canvas editor save)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    # Delete existing
    await db.execute(
        text("DELETE FROM template_elements WHERE template_id = :tmpl"),
        {"tmpl": str(template_id)},
    )

    # Insert new
    created = []
    for el in elements:
        result = await db.execute(
            text("""
                INSERT INTO template_elements (
                    template_id, element_type, label, data_key,
                    x, y, width, height, rotation,
                    font_family, font_size, font_weight, font_color,
                    text_align, text_direction, line_height, letter_spacing,
                    qr_size, qr_color, qr_bg_color, qr_error_level,
                    static_content, is_visible, z_index, sort_order, slot_index
                ) VALUES (
                    :tmpl, :etype, :label, :dk,
                    :x, :y, :w, :h, :rot,
                    :ff, :fs, :fw, :fc,
                    :ta, :td, :lh, :ls,
                    :qs, :qc, :qbg, :qel,
                    :sc, :vis, :zi, :so, :slot_idx
                )
                RETURNING *
            """),
            {
                "tmpl": str(template_id), "etype": el.element_type, "label": el.label, "dk": el.data_key,
                "x": el.x, "y": el.y, "w": el.width, "h": el.height, "rot": el.rotation,
                "ff": el.font_family, "fs": el.font_size, "fw": el.font_weight, "fc": el.font_color,
                "ta": el.text_align, "td": el.text_direction, "lh": el.line_height, "ls": el.letter_spacing,
                "qs": el.qr_size, "qc": el.qr_color, "qbg": el.qr_bg_color, "qel": el.qr_error_level,
                "sc": el.static_content, "vis": el.is_visible, "zi": el.z_index, "so": el.sort_order,
                "slot_idx": el.slot_index,
            },
        )
        created.append(ElementRead(**dict(result.mappings().first())))

    await db.commit()
    return created


# ══════════════════════════════════════════════
# TEMPLATE ASSETS
# ══════════════════════════════════════════════

@router.post("/{template_id}/background")
async def upload_background(
    template_id: UUID, request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a background image for a designed template. Stores in Supabase Storage."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    # Verify template
    tmpl = await db.execute(
        text("SELECT id, event_id FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    row = tmpl.mappings().first()
    if not row:
        raise HTTPException(404, "القالب غير موجود")

    # Validate file type
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(400, f"نوع الملف غير مدعوم. المسموح: {', '.join(allowed)}")

    # Read and upload
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "حجم الملف يتجاوز 10MB")

    from app.services.feature_service import require_storage_for_upload
    await require_storage_for_upload(db, tenant_id, len(content))

    content, stored_mime, width_px, height_px = _read_background_upload(file, content)
    ext = "png" if stored_mime == "image/png" else (file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "png")

    event_id = row["event_id"] or "shared"
    path = storage_service.build_path(
        tenant_id, event_id, "templates", str(template_id), f"background.{ext}"
    )
    storage_service.upload_file(path, content, stored_mime)
    bg_url = storage_service.get_signed_url(path, expires_in=86400 * 365)

    # Update template dimensions to the normalized A4 canvas.
    await db.execute(
        text("""
            UPDATE invite_templates
            SET background_url = :url,
                width_px = :width_px,
                height_px = :height_px,
                orientation = 'portrait',
                updated_at = now()
            WHERE id = :id
        """),
        {"url": bg_url, "width_px": width_px, "height_px": height_px, "id": str(template_id)},
    )

    # Save as asset record
    await db.execute(
        text("""
            INSERT INTO template_assets (template_id, asset_type, file_url, file_name, file_size, mime_type)
            VALUES (:tid, 'background', :url, :fname, :fsize, :mime)
        """),
        {
            "tid": str(template_id), "url": bg_url,
            "fname": file.filename, "fsize": len(content), "mime": stored_mime,
        },
    )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="template.upload_background", resource_type="template",
        resource_id=str(template_id),
        metadata={"file_name": file.filename, "file_size": len(content)},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return {"background_url": bg_url, "file_size": len(content), "mime_type": stored_mime, "width_px": width_px, "height_px": height_px}


# Font governance constants
# Only TTF/OTF supported — Pillow/FreeType cannot render WOFF/WOFF2 at runtime.
ALLOWED_FONT_MIMES = {"font/ttf", "font/otf",
                      "application/x-font-ttf", "application/x-font-otf",
                      "application/octet-stream"}  # fallback for browsers
ALLOWED_FONT_EXTENSIONS = {".ttf", ".otf"}
MAX_FONT_SIZE = 5 * 1024 * 1024   # 5MB
MAX_ASSET_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_FONT_FALLBACK = {"ar": "Cairo", "en": "Arial", "default": "Cairo"}


@router.post("/{template_id}/assets")
async def upload_asset(
    template_id: UUID, request: Request,
    file: UploadFile = File(...),
    asset_type: str = "overlay",
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an asset (overlay, logo, stamp, font) for a template.
    Font files: max 5MB, allowed types: .ttf, .otf only (Pillow/FreeType compatible).
    WOFF/WOFF2 not supported in runtime renderer."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    # Verify template
    tmpl = await db.execute(
        text("SELECT id, event_id FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    row = tmpl.mappings().first()
    if not row:
        raise HTTPException(404, "القالب غير موجود")

    content = await file.read()

    # Font-specific governance
    if asset_type == "font":
        if len(content) > MAX_FONT_SIZE:
            raise HTTPException(400, "حجم ملف الخط يتجاوز 5MB")
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_FONT_EXTENSIONS:
            raise HTTPException(400, f"نوع الخط غير مدعوم. المسموح: {', '.join(ALLOWED_FONT_EXTENSIONS)}")
        # Validate font file magic bytes (TTF/OTF signatures only)
        if len(content) >= 4:
            valid_sigs = [b'\x00\x01\x00\x00', b'OTTO', b'true', b'typ1']
            if not any(content.startswith(s) for s in valid_sigs):
                raise HTTPException(400, "الملف ليس خط صالح (TTF/OTF فقط)")
    else:
        if len(content) > MAX_ASSET_SIZE:
            raise HTTPException(400, "حجم الملف يتجاوز 10MB")

    event_id = row["event_id"] or "shared"
    import uuid
    # Keep only ASCII letters, numbers, dashes, underscores, and dots for the storage path
    ext = os.path.splitext(file.filename or "")[1].lower()
    ext = "." + "".join(c for c in ext if c.isascii() and c.isalnum()) if ext else ""
    clean_prefix = "".join(c for c in os.path.splitext(file.filename or "asset")[0] if c.isascii() and (c.isalnum() or c in ("-", "_")))
    if not clean_prefix:
        clean_prefix = "asset"
    safe_name = f"{clean_prefix}_{uuid.uuid4().hex[:8]}{ext}"
    
    path = storage_service.build_path(
        tenant_id, event_id, "templates", str(template_id), "assets", safe_name
    )
    storage_service.upload_file(path, content, file.content_type or "application/octet-stream")
    asset_url = storage_service.get_signed_url(path, expires_in=86400 * 365)

    result = await db.execute(
        text("""
            INSERT INTO template_assets (template_id, asset_type, file_url, file_name, file_size, mime_type)
            VALUES (:tid, :atype, :url, :fname, :fsize, :mime)
            RETURNING *
        """),
        {
            "tid": str(template_id), "atype": asset_type, "url": asset_url,
            "fname": file.filename, "fsize": len(content), "mime": file.content_type,
        },
    )
    asset_row = result.mappings().first()
    await db.commit()

    return AssetRead(**dict(asset_row))


@router.get("/{template_id}/assets", response_model=list[AssetRead])
async def list_assets(
    template_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.view")

    result = await db.execute(
        text("SELECT * FROM template_assets WHERE template_id = :tid ORDER BY sort_order"),
        {"tid": str(template_id)},
    )
    return [AssetRead(**dict(r)) for r in result.mappings().all()]


@router.delete("/{template_id}/assets/{asset_id}", status_code=204)
async def delete_asset(
    template_id: UUID, asset_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.edit")

    result = await db.execute(
        text("DELETE FROM template_assets WHERE id = :id AND template_id = :tid RETURNING file_url"),
        {"id": str(asset_id), "tid": str(template_id)},
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "الملف غير موجود")
    await db.commit()


# ══════════════════════════════════════════════
# TEMPLATE PREVIEW
# ══════════════════════════════════════════════

class PreviewRequest(BaseModel):
    """معاينة القالب مع بيانات اختبار"""
    guest_name: str = "أحمد علي"
    guest_phone: str = ""
    guest_email: str = ""
    guest_company: str = ""
    guest_title: str = ""
    event_title: str = "حفل تخرج"
    event_date: str = "2025-06-15"
    event_time: str = "19:00"
    event_location: str = "فندق الريتز"
    event_address: str = "طريق الملك فهد، حي العليا"
    seat_number: str = "A12"
    table_number: str = "5"
    custom_data: dict = {}


@router.post("/{template_id}/preview")
async def preview_template(
    template_id: UUID, body: PreviewRequest, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    معاينة القالب مع بيانات اختبارية قبل الطباعة.
    ترجع صورة PNG للمعاينة.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.view")

    # جلب بيانات القالب
    tmpl = await db.execute(
        text("SELECT * FROM invite_templates WHERE id = :id AND tenant_id = :tid"),
        {"id": str(template_id), "tid": str(tenant_id)},
    )
    template = dict(tmpl.mappings().first() or {})
    if not template:
        raise HTTPException(404, "القالب غير موجود")

    # جلب العناصر
    elements_result = await db.execute(
        text("SELECT * FROM template_elements WHERE template_id = :tid ORDER BY z_index, sort_order"),
        {"tid": str(template_id)},
    )
    elements = [dict(r) for r in elements_result.mappings().all()]

    # جلب الخلفية
    if not template.get("background_url"):
        raise HTTPException(400, "القالب لا يحتوي على خلفية")

    try:
        background_bytes = await storage_service.download_reference(template["background_url"])
    except Exception:
        logger.exception("Template background download failed template_id=%s", template_id)
        raise HTTPException(500, "تعذر تحميل خلفية القالب")

    # بناء بيانات السياق للمعاينة
    context = {
        "guest": {
            "name": body.guest_name,
            "name_ar": body.guest_name,
            "phone": body.guest_phone,
            "email": body.guest_email,
            "company": body.guest_company,
            "title": body.guest_title,
        },
        "event": {
            "title": body.event_title,
            "date": body.event_date,
            "time": body.event_time,
            "location": body.event_location,
            "venue_address": body.event_address,
        },
        "invite": {
            "code": "PREVIEW123",
            "barcode_payload": "https://example.com/invite/preview",
            "guest_count": 1,
        },
        "custom": {
            "seat": body.seat_number,
            "table": body.table_number,
            **body.custom_data,
        },
    }

    try:
        # رسم الدعوة
        canvas_width = template.get("width_px", 1240)
        canvas_height = template.get("height_px", 1754)

        preview_png = render_invitation_image(
            background_bytes=background_bytes,
            elements=elements,
            context=context,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            background_transform=template.get("metadata", {}).get("background_transform"),
            output_format="PNG",
        )

        return StreamingResponse(
            io.BytesIO(preview_png),
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename=preview_{template_id}.png"},
        )
    except Exception:
        logger.exception("Template preview render failed template_id=%s", template_id)
        raise HTTPException(500, "تعذر رسم معاينة القالب")


class AITemplateGenerateRequest(BaseModel):
    prompt: str
    ticket_class: str = "normal"
    orientation: str = "portrait"
    event_id: Optional[UUID] = None


@router.post("/generate-ai", response_model=TemplateRead, status_code=201)
async def generate_template_ai(
    body: AITemplateGenerateRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an invitation template using AI.
    Only available on Pro, Business, and Enterprise plans.
    Consumes 1 AI request from the tenant's monthly limits.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "templates.create")

    # 1. Enforce AI feature flag (available on Pro, Business, Enterprise)
    from app.services.feature_service import require_feature, enforce_monthly_limit
    await require_feature(db, tenant_id, "ai_features")

    # 2. Enforce monthly limit
    await enforce_monthly_limit(db, tenant_id, "ai_requests_per_month", "طلبات الذكاء الاصطناعي")

    # 3. Create a designed template inside DB based on the prompt
    w = 1240 if body.orientation == "portrait" else 1754
    h = 1754 if body.orientation == "portrait" else 1240

    bg_color = "#ffffff"
    prompt_lower = body.prompt.lower()
    if any(word in prompt_lower for word in ("dark", "مظلم", "أسود", "black", "داكن")):
        bg_color = "#1e293b"
    elif any(word in prompt_lower for word in ("gold", "ذهبي", "أصفر", "yellow")):
        bg_color = "#fef08a"
    elif any(word in prompt_lower for word in ("blue", "أزرق", "سماوي")):
        bg_color = "#eff6ff"

    result = await db.execute(
        text("""
            INSERT INTO invite_templates (
                tenant_id, event_id, name, template_type, ticket_class,
                width_px, height_px, orientation,
                background_url, background_color, quick_style,
                is_default, metadata, created_by
            ) VALUES (
                :tid, :eid, :name, 'designed', CAST(:tc AS ticket_class),
                :w, :h, :orient,
                null, :bg_color, '{}'::jsonb,
                false, CAST(:meta AS jsonb), :uid
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id),
            "eid": str(body.event_id) if body.event_id else None,
            "name": f"قالب ذكي: {body.prompt[:30]}",
            "tc": body.ticket_class,
            "w": w,
            "h": h,
            "orient": body.orientation,
            "bg_color": bg_color,
            "meta": json.dumps({"ai_generated": True, "prompt": body.prompt}),
            "uid": str(user.id),
        },
    )
    row = result.mappings().first()
    template_id = row["id"]

    # 4. Generate default template elements arranged professionally
    elements = [
        # guest_name
        {
            "element_type": "guest_name",
            "label": "الاسم الكامل للضيف",
            "x": 0.5, "y": 0.45, "width": 0.8, "height": 0.06,
            "font_family": "Cairo", "font_size": 36.0, "font_weight": "bold",
            "font_color": "#C9A96E" if bg_color == "#1e293b" else "#0f172a",
            "text_align": "center", "z_index": 1, "sort_order": 1,
        },
        # event_title
        {
            "element_type": "event_title",
            "label": "اسم الفعالية",
            "x": 0.5, "y": 0.25, "width": 0.9, "height": 0.08,
            "font_family": "Cairo", "font_size": 48.0, "font_weight": "bold",
            "font_color": "#ffffff" if bg_color == "#1e293b" else "#1e293b",
            "text_align": "center", "z_index": 2, "sort_order": 2,
        },
        # qr_code
        {
            "element_type": "qr_code",
            "label": "رمز الاستجابة السريعة (QR)",
            "x": 0.5, "y": 0.75, "width": 0.25, "height": 0.18,
            "qr_size": 0.18, "maintain_square": True,
            "z_index": 3, "sort_order": 3,
        },
        # event_date
        {
            "element_type": "event_date",
            "label": "تاريخ الحدث",
            "x": 0.35, "y": 0.9, "width": 0.3, "height": 0.04,
            "font_family": "Cairo", "font_size": 22.0, "font_weight": "normal",
            "font_color": "#94a3b8" if bg_color == "#1e293b" else "#475569",
            "text_align": "right", "z_index": 4, "sort_order": 4,
        },
        # event_location
        {
            "element_type": "event_location",
            "label": "موقع الحدث",
            "x": 0.65, "y": 0.9, "width": 0.3, "height": 0.04,
            "font_family": "Cairo", "font_size": 22.0, "font_weight": "normal",
            "font_color": "#94a3b8" if bg_color == "#1e293b" else "#475569",
            "text_align": "left", "z_index": 5, "sort_order": 5,
        }
    ]

    for el in elements:
        await db.execute(
            text("""
                INSERT INTO template_elements (
                    template_id, element_type, label, x, y, width, height,
                    font_family, font_size, font_weight, font_color, text_align,
                    qr_size, z_index, sort_order, is_visible
                ) VALUES (
                    :tid, :etype, :label, :x, :y, :w, :h,
                    :font_family, :font_size, :font_weight, :font_color, :text_align,
                    :qr_size, :z_index, :sort_order, true
                )
            """),
            {
                "tid": str(template_id),
                "etype": el["element_type"],
                "label": el["label"],
                "x": el["x"], "y": el["y"], "w": el["width"], "h": el["height"],
                "font_family": el.get("font_family", "Cairo"),
                "font_size": el.get("font_size", 24.0),
                "font_weight": el.get("font_weight", "normal"),
                "font_color": el.get("font_color", "#000000"),
                "text_align": el.get("text_align", "center"),
                "qr_size": el.get("qr_size", 0.15),
                "z_index": el["z_index"],
                "sort_order": el["sort_order"],
            }
        )

    await log_audit(db, tenant_id=tenant_id, actor_user_id=user.id,
                    action="template.generate_ai", resource_type="template", resource_id=str(template_id),
                    ip_address=get_client_ip(request))
    await db.commit()

    # Re-fetch full record to make sure it includes autogenerated fields
    refetched = await db.execute(
        text("SELECT * FROM invite_templates WHERE id = :id"),
        {"id": str(template_id)}
    )
    return TemplateRead(**dict(refetched.mappings().first()))
