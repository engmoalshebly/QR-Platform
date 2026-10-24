"""
Batch Pipeline Orchestrator.
Manages the full generation lifecycle:
  1. Create batch + batch_items from invitations
  2. Generate barcodes (SVG + PNG) for each invitation
  3. Render designed images (DESIGNED mode only)
  4. Generate PDF (grid or per-page)
  5. Generate ZIP of all images
  6. Update progress and status throughout

Designed to be idempotent: can restart a failed batch
without duplicating work (checks render_status per item).
"""
import io
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
import zipfile
import traceback
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from app.services import barcode_service, storage_service, pdf_service, render_service
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PREVIEW_COUNT = 5  # Number of preview images to generate


def _barcode_elements(elements: list[dict]) -> list[dict]:
    """Return visible QR/barcode slots in the same order used by the renderer."""
    return [
        element for element in elements
        if element.get("is_visible", True) and element.get("element_type") in ("qr_code", "barcode")
    ]


def _float_value(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slot_visual_key(slot: dict) -> tuple[int, float]:
    y = _float_value(slot.get("y"))
    row = 0 if y < 0.5 else 1
    return row, _float_value(slot.get("x"))


def _split_slots(elements: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split elements into non-slots, barcode slots, and slot companions.

    Slot companions are dynamic_text elements that have a slot_index — they
    are logically tied to a specific barcode slot and must be duplicated
    alongside it when expanding repeated sheets.
    """
    slots = _barcode_elements(elements)
    slot_companions = [
        e for e in elements
        if e.get("is_visible", True)
        and e.get("element_type") in ("dynamic_text", "guest_name")
        and e.get("slot_index") is not None
    ]
    slot_companion_ids = {id(e) for e in slot_companions}
    slot_ids = {id(e) for e in slots}
    non_slots = [
        e for e in elements
        if id(e) not in slot_ids and id(e) not in slot_companion_ids
    ]
    return non_slots, slots, slot_companions


def _expand_repeated_sheet_slots(elements: list[dict]) -> list[dict]:
    """
    Prepare QR slots for rendering.

    Sorts barcode/QR elements by visual position (top-left → bottom-right)
    so the batch pipeline assigns guest data in consistent visual order.

    The number of slots is always preserved exactly as the designer placed them:
    - 1 QR code in design → 1 invitation per page
    - 4 QR codes in design → 4 invitations per page
    """
    non_slots, slots, companions = _split_slots(elements)
    ordered_slots = sorted(slots, key=_slot_visual_key)
    return [*non_slots, *companions, *ordered_slots]


def _auto_assign_slot_indices(elements: list[dict]) -> list[dict]:
    """
    Auto-assign correct slot_index to dynamic_text elements based on visual position.

    When the user manually duplicates dynamic_text elements in the editor for
    a 2×2 layout, all copies often get the same slot_index (e.g., all slot_index=0).
    This causes all 4 cards to display the same guest data.

    This function:
    1. Finds barcode slots and sorts them by visual position (top-left → bottom-right)
    2. For each group of dynamic_text elements sharing the same data_key,
       if they have incorrect/duplicate slot_index values, re-assigns them
       based on proximity to the nearest barcode slot.
    """
    barcode_slots = sorted(
        [e for e in elements if e.get("is_visible", True)
         and e.get("element_type") in ("qr_code", "barcode")],
        key=_slot_visual_key
    )
    num_slots = len(barcode_slots)
    if num_slots < 2:
        return elements

    # Compute barcode slot centers for proximity matching
    slot_centers = []
    for slot in barcode_slots:
        sx = _float_value(slot.get("x")) + _float_value(slot.get("width")) / 2
        sy = _float_value(slot.get("y")) + _float_value(slot.get("height")) / 2
        slot_centers.append((sx, sy))

    # Group dynamic_text elements by data_key
    from collections import defaultdict
    dk_groups: dict[str, list[dict]] = defaultdict(list)
    for elem in elements:
        if (elem.get("is_visible", True)
            and elem.get("element_type") in ("dynamic_text", "guest_name")
            and elem.get("data_key")):
            dk_groups[elem["data_key"]].append(elem)

    for data_key, group in dk_groups.items():
        if len(group) < 2:
            continue
        if len(group) != num_slots:
            # Can't auto-assign if count doesn't match barcode count
            continue

        # Check if slot_indices are already correctly assigned (all unique, 0..N-1)
        existing_indices = [e.get("slot_index") for e in group]
        expected = set(range(num_slots))
        if set(existing_indices) == expected:
            continue  # Already correct

        # Re-assign: sort group by proximity to barcode slots
        # For each barcode slot, find the closest dynamic_text element
        assigned = set()
        assignments: list[tuple[int, dict]] = []

        for slot_idx, (cx, cy) in enumerate(slot_centers):
            best_dist = float("inf")
            best_elem = None
            for elem in group:
                if id(elem) in assigned:
                    continue
                ex = _float_value(elem.get("x")) + _float_value(elem.get("width")) / 2
                ey = _float_value(elem.get("y")) + _float_value(elem.get("height")) / 2
                dist = (ex - cx) ** 2 + (ey - cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_elem = elem
            if best_elem is not None:
                assigned.add(id(best_elem))
                assignments.append((slot_idx, best_elem))

        for slot_idx, elem in assignments:
            elem["slot_index"] = slot_idx

        logger.info(
            f"Auto-assigned slot_index for '{data_key}': "
            f"{[e.get('slot_index') for e in group]}"
        )

    return elements


def _chunked(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        size = 1
    return [items[index:index + size] for index in range(0, len(items), size)]


def _sanitize_filename(name: str, index: int, ext: str = "png") -> str:
    """
    Build a safe, sequential filename for ZIP entries.
    Format: 0001__Ahmed_AlAli.png  (sequential + sanitized guest name)
    """
    seq = str(index + 1).zfill(4)
    if not name or not name.strip():
        return f"{seq}__Guest.{ext}"
    # Normalize unicode, keep alphanumeric + spaces/hyphens
    clean = unicodedata.normalize("NFKD", name)
    clean = re.sub(r"[^\w\s\-]", "", clean, flags=re.UNICODE)
    clean = re.sub(r"\s+", "_", clean.strip())
    if not clean:
        clean = "Guest"
    return f"{seq}__{clean[:60]}.{ext}"


async def run_batch_pipeline(db: AsyncSession, batch_id: UUID) -> dict:
    """
    Execute the full batch generation pipeline.
    Returns dict with status and result URLs.
    """
    pipeline_start = time.monotonic()

    try:
        # Load batch
        batch = await _load_batch(db, batch_id)
        if not batch:
            return {"status": "failed", "error": "Batch not found"}

        if batch.get("operation_id"):
            # P1 outbox jobs belong to the durable P2 worker. Never render a
            # snapshot-backed operation through the legacy live-template path.
            return {"status": "queued", "code": "DURABLE_WORKER_REQUIRED"}

        if batch["status"] in ("ready", "cancelled"):
            return {"status": batch["status"], "message": "Batch already processed"}

        if batch.get("count_total", 0) > 1000:
            raise ValueError("الحد الحالي 1000 دعوة للعملية الواحدة")

        tenant_id = batch["tenant_id"]
        event_id = batch["event_id"]
        template_id = batch.get("template_id")
        mode = batch["mode"]
        layout = batch["layout_json"] or {}
        output_formats = batch.get("output_formats", ["pdf", "zip"])
        if mode == "designed" and not template_id:
            raise ValueError("يجب اختيار قالب تصميم صالح")

        if output_formats:
            from app.services.permission_service import require_permission
            from app.services.feature_service import require_feature
            await require_permission(db, tenant_id, batch["created_by"], "invitations.export")
            await require_feature(db, tenant_id, "pdf_export")

        # Ensure the storage bucket exists before generating any assets.
        await storage_service.ensure_bucket_exists()

        # ── Phase 1: Generate barcodes ──
        await _update_status(db, batch_id, "generating_barcodes", 5)
        items = await _load_batch_items(db, batch_id)

        barcode_results = []
        for idx, item in enumerate(items):
            if item["render_status"] == "done" and item.get("barcode_url"):
                # Already done (idempotent restart)
                inv = await _load_invitation(db, item["invitation_id"])
                png_bytes = await storage_service.download_reference(item["barcode_url"])
                if not inv or not png_bytes:
                    raise ValueError("تعذر استعادة الباركود المكتمل لإعادة تجهيز الملفات")
                barcode_results.append({**item, "inv": inv, "png_bytes": png_bytes})
                continue

            try:
                await _update_item_status(db, item["id"], "pending", started=True)

                # Get invitation data
                inv = await _load_invitation(db, item["invitation_id"])
                if not inv:
                    await _update_item_status(db, item["id"], "failed", error="Invitation not found")
                    continue

                if mode == "designed":
                    payload_info = barcode_service.build_barcode_payload(str(inv["id"]), inv["token"])
                    bc = {
                        "payload": payload_info["barcode_payload"],
                        "signature": payload_info["signature"],
                        "payload_url": payload_info["payload"],
                        "png_bytes": None,
                    }
                else:
                    # Use resolved size (auto-calculated from cell if not set).
                    from app.models.batch import LayoutConfig as _LC
                    _lc = _LC(**(layout if layout else {}))
                    bc = barcode_service.generate_barcode_for_invitation(
                        str(inv["id"]), inv["token"],
                        size_px=_lc.resolved_barcode_size_px,
                    )

                if mode == "designed":
                    # Designed cards render QR codes directly into the final A4 image.
                    # Avoid per-invitation storage uploads here; they dominate runtime.
                    svg_url = None
                    png_url = None
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
                            "payload": bc["payload"], "sig": bc["signature"],
                            "qr_data": bc["payload_url"],
                            "id": str(inv["id"]),
                        },
                    )
                else:
                    # Quick/grid mode still needs standalone barcode assets.
                    svg_path = storage_service.upload_barcode_svg(
                        tenant_id, event_id, inv["id"], bc["svg_bytes"]
                    )
                    png_path = storage_service.upload_barcode_png(
                        tenant_id, event_id, inv["id"], bc["png_bytes"]
                    )

                    svg_url = storage_service.get_signed_url(svg_path, expires_in=86400 * 30)
                    png_url = storage_service.get_signed_url(png_path, expires_in=86400 * 30)
                    if not svg_url or not png_url or not bc.get("png_bytes"):
                        raise ValueError("لم يكتمل حفظ رمز الدخول")

                    await db.execute(
                        text("""
                            UPDATE invitations SET
                                barcode_svg_url = :svg, barcode_png_url = :png,
                                barcode_payload = :payload, barcode_signature = :sig,
                                qr_data = :qr_data, updated_at = now()
                            WHERE id = :id
                        """),
                        {
                            "svg": svg_url, "png": png_url,
                            "payload": bc["payload"], "sig": bc["signature"],
                            "qr_data": bc["payload_url"],
                            "id": str(inv["id"]),
                        },
                    )

                # Update batch item
                await db.execute(
                    text("""
                        UPDATE batch_items SET
                            barcode_url = :url, render_status = :st, completed_at = now()
                        WHERE id = :id
                    """),
                    {"url": png_url, "st": "done" if mode == "quick" else "pending", "id": str(item["id"])},
                )

                item["barcode_url"] = png_url
                item["png_bytes"] = bc.get("png_bytes")
                item["inv"] = inv
                barcode_results.append(item)

            except Exception as e:
                logger.error("Barcode generation failed for item %s: %s", item["id"], e)
                await _update_item_status(db, item["id"], "failed", error=str(e))

            # Update progress
            progress = int(((idx + 1) / len(items)) * 40) + 5  # 5-45%
            await _update_progress(db, batch_id, progress)
            if idx % 50 == 0:
                await db.commit()

        await db.commit()

        # ── Phase 2: Render designed images (DESIGNED mode only) ──
        render_images = []
        render_entries = []
        if mode == "designed" and template_id:
            await _update_status(db, batch_id, "rendering_images", 45)

            template = await _load_template(db, template_id)
            elements = await _load_template_elements(db, template_id)
            bg_bytes = await _load_background(template)

            if not bg_bytes or not elements or not _barcode_elements(elements):
                raise ValueError("القالب غير مكتمل: يجب توفير الخلفية ومكان رمز الدخول")

            # Load event data once for all invitations
            event_data = await _load_event(db, event_id)

            if bg_bytes and elements:
                # Canvas dimensions MUST match the template as designed in the editor.
                # prepare_background_canvas handles fitting/centering the background
                # image within these dimensions automatically.
                canvas_w = template.get("width_px", 1080)
                canvas_h = template.get("height_px", 1920)
                logger.info(f"Using template canvas: {canvas_w}×{canvas_h}")

                background_transform = _extract_background_transform(template)
                render_elements = _expand_repeated_sheet_slots(elements)
                render_elements = _auto_assign_slot_indices(render_elements)
                base_canvas = render_service.prepare_background_canvas(
                    bg_bytes,
                    canvas_w,
                    canvas_h,
                    background_transform,
                )

                slots_per_card = max(1, len(_barcode_elements(render_elements)))
                card_groups = _chunked(barcode_results, slots_per_card)

                for idx, group in enumerate(card_groups):
                    primary_item = group[0]
                    primary_inv = primary_item.get("inv") or await _load_invitation(db, primary_item["invitation_id"])
                    if not primary_inv:
                        continue

                    try:
                        slot_contexts = []
                        for item in group:
                            inv = item.get("inv") or await _load_invitation(db, item["invitation_id"])
                            if not inv:
                                continue

                            guest_data = None
                            if inv.get("guest_id"):
                                guest_data = await _load_guest(db, inv["guest_id"])

                            slot_contexts.append(
                                _build_render_context(inv, batch, event=event_data, guest=guest_data)
                            )

                        if not slot_contexts:
                            continue

                        # Non-barcode dynamic text uses the first invitation in the card.
                        context = slot_contexts[0]

                        # Render image
                        img_bytes = render_service.render_invitation_image(
                            background_bytes=bg_bytes,
                            elements=render_elements,
                            context=context,
                            slot_contexts=slot_contexts,
                            canvas_width=canvas_w,
                            canvas_height=canvas_h,
                            background_transform=background_transform,
                            base_canvas=base_canvas,
                        )

                        # Upload render
                        render_path = storage_service.upload_render_image(
                            tenant_id, event_id, primary_inv["id"], img_bytes
                        )
                        render_url = storage_service.get_signed_url(render_path, expires_in=86400 * 30)
                        if not render_url or not img_bytes:
                            raise ValueError("لم يكتمل حفظ بطاقة الدعوة")

                        # Update all invitations represented by this designed card.
                        for item in group:
                            inv_id = str(item["invitation_id"])
                            await db.execute(
                                text("UPDATE invitations SET render_image_url = :url, card_image_url = :url, updated_at = now() WHERE id = :id"),
                                {"url": render_url, "id": inv_id},
                            )

                            # Update batch item
                            await db.execute(
                                text("UPDATE batch_items SET render_url = :url, render_status = 'done', completed_at = now() WHERE id = :id"),
                                {"url": render_url, "id": str(item["id"])},
                            )
                            item["render_bytes"] = img_bytes
                            item["render_url"] = render_url

                        render_images.append(img_bytes)
                        guest_name = primary_inv.get("guest_name") or primary_inv.get("guest_name_ar") or ""
                        render_entries.append({
                            "bytes": img_bytes,
                            "name": guest_name or f"card_{idx + 1}",
                            "index": idx,
                        })

                    except Exception as e:
                        logger.error("Render failed for designed card group %s: %s", idx + 1, e)
                        for item in group:
                            await _update_item_status(db, item["id"], "failed", error=str(e))

                    progress = int(((idx + 1) / len(card_groups)) * 30) + 45  # 45-75%
                    await _update_progress(db, batch_id, progress)
                    if idx % 20 == 0:
                        await db.commit()

            await db.commit()

        # ── Phase 3: Generate PDF ──
        result_pdf_url = None
        result_pdf_size = 0
        result_zip_size = 0
        if "pdf" in output_formats:
            await _update_status(db, batch_id, "generating_pdf", 75)

            try:
                if mode == "designed" and render_images:
                    pdf_bytes = pdf_service.generate_cards_pdf(
                        render_images,
                        {**layout, "card_per_page": True},
                    )
                else:
                    # Quick mode: grid of barcodes
                    pdf_items = []
                    for item in barcode_results:
                        inv = item.get("inv") or {}
                        pdf_items.append({
                            "png_bytes": item.get("png_bytes"),
                            "code": inv.get("token", "")[:8] if inv else "",
                            "guest_name": inv.get("guest_name", ""),
                        })
                    pdf_bytes = pdf_service.generate_barcode_grid_pdf(pdf_items, layout)

                result_pdf_size = len(pdf_bytes)
                pdf_path = storage_service.upload_batch_pdf(tenant_id, event_id, batch_id, pdf_bytes)
                result_pdf_url = storage_service.get_signed_url(pdf_path, expires_in=86400 * 7)

            except Exception as e:
                logger.error("PDF generation failed: %s", e)

            await _update_progress(db, batch_id, 85)

        # ── Phase 4: Generate ZIP (tempfile-based to prevent OOM) ──
        result_zip_url = None
        if "zip" in output_formats:
            await _update_status(db, batch_id, "generating_zip", 85)

            try:
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    tmp_path = tmp.name
                    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                        if mode == "designed" and render_entries:
                            for entry in render_entries:
                                fname = _sanitize_filename(entry["name"], entry["index"], "png")
                                zf.writestr(fname, entry["bytes"])
                        else:
                            for idx, item in enumerate(barcode_results):
                                inv = item.get("inv") or {}
                                guest_name = inv.get("guest_name") or inv.get("guest_name_ar") or ""
                                if not item.get("png_bytes"):
                                    continue
                                fname = _sanitize_filename(guest_name, idx, "png")
                                zf.writestr(f"qr/{fname}", item["png_bytes"])

                # Read from disk instead of holding everything in RAM
                result_zip_size = os.path.getsize(tmp_path)
                with open(tmp_path, "rb") as f:
                    zip_bytes = f.read()
                zip_path = storage_service.upload_batch_zip(tenant_id, event_id, batch_id, zip_bytes)
                result_zip_url = storage_service.get_signed_url(zip_path, expires_in=86400 * 7)
                del zip_bytes  # free memory immediately

            except Exception as e:
                logger.error("ZIP generation failed: %s", e)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            await _update_progress(db, batch_id, 95)

        # ── Phase 5: Generate previews ──
        preview_urls = []
        try:
            source_items = render_images if render_images else [i.get("png_bytes") for i in barcode_results[:PREVIEW_COUNT] if i.get("png_bytes")]
            for idx, img_bytes in enumerate(source_items[:PREVIEW_COUNT]):
                if img_bytes:
                    preview_path = storage_service.upload_preview(tenant_id, event_id, batch_id, idx, img_bytes)
                    preview_url = storage_service.get_signed_url(preview_path, expires_in=86400 * 7)
                    preview_urls.append(preview_url)
        except Exception as e:
            logger.warning("Preview generation failed: %s", e)

        # ── Finalize with metrics ──
        duration_ms = int((time.monotonic() - pipeline_start) * 1000)

        # Reload persisted item results; the input snapshot does not reflect updates.
        items = await _load_batch_items(db, batch_id)
        done_count = sum(item.get("render_status") == "done" for item in items)
        fail_count = 0
        fail_reasons = {}
        for item in items:
            if item.get("render_status") != "done":
                fail_count += 1
                reason = (item.get("error_message") or "unknown")[:80]
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

        if "pdf" in output_formats and (not result_pdf_url or not result_pdf_size):
            fail_reasons["PDF output missing"] = 1
        if "zip" in output_formats and (not result_zip_url or not result_zip_size):
            fail_reasons["ZIP output missing"] = 1
        final_status = "failed" if fail_count or fail_reasons or not items else "ready"

        import json as _json
        error_summary = _json.dumps(fail_reasons, ensure_ascii=False) if fail_reasons else "{}"

        await db.execute(
            text("""
                UPDATE generation_batches SET
                    status = :final_status, progress = 100,
                    result_pdf_url = :pdf, result_zip_url = :zip,
                    result_preview_urls = :previews,
                    completed_at = now(), updated_at = now(),
                    duration_ms = :dur,
                    result_pdf_size = :pdf_size,
                    result_zip_size = :zip_size,
                    error_summary = CAST(:errs AS jsonb),
                    error_message = :failure_message,
                    count_done = :done, count_failed = :failed
                WHERE id = :id AND status <> 'cancelled'
            """),
            {
                "final_status": final_status,
                "pdf": result_pdf_url, "zip": result_zip_url,
                "previews": preview_urls,
                "id": str(batch_id),
                "dur": duration_ms,
                "pdf_size": result_pdf_size if "pdf" in output_formats else 0,
                "zip_size": result_zip_size if "zip" in output_formats else 0,
                "errs": error_summary,
                "failure_message": "لم تكتمل جميع الدعوات أو الملفات المطلوبة. راجع تفاصيل العملية قبل إعادة المحاولة." if final_status == "failed" else None,
                "done": done_count,
                "failed": fail_count,
            },
        )
        await db.commit()

        logger.info(
            "Batch %s completed: %d/%d items in %dms (PDF: %s, ZIP: %s)",
            batch_id, len(barcode_results), len(items), duration_ms,
            f"{result_pdf_size/1024:.0f}KB" if result_pdf_url else "N/A",
            f"{result_zip_size/1024:.0f}KB" if result_zip_url else "N/A",
        )

        return {
            "status": final_status,
            "result_pdf_url": result_pdf_url,
            "result_zip_url": result_zip_url,
            "preview_urls": preview_urls,
            "count_total": len(items),
            "count_done": done_count,
            "count_failed": fail_count,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        logger.error("Batch pipeline failed: %s\n%s", e, traceback.format_exc())
        await _update_status(db, batch_id, "failed", 0, error=str(e))
        await db.commit()
        return {"status": "failed", "error": str(e)}


# ══════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════

async def _load_batch(db: AsyncSession, batch_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT * FROM generation_batches WHERE id = :id"),
        {"id": str(batch_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_batch_items(db: AsyncSession, batch_id: UUID) -> list[dict]:
    result = await db.execute(
        text("SELECT * FROM batch_items WHERE batch_id = :bid ORDER BY created_at"),
        {"bid": str(batch_id)},
    )
    return [dict(r) for r in result.mappings().all()]


async def _load_invitation(db: AsyncSession, invitation_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT * FROM invitations WHERE id = :id"),
        {"id": str(invitation_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_event(db: AsyncSession, event_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT * FROM events WHERE id = :id"),
        {"id": str(event_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_guest(db: AsyncSession, guest_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT * FROM guests WHERE id = :id"),
        {"id": str(guest_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_template(db: AsyncSession, template_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT * FROM invite_templates WHERE id = :id"),
        {"id": str(template_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_template_elements(db: AsyncSession, template_id: UUID) -> list[dict]:
    result = await db.execute(
        text("SELECT * FROM template_elements WHERE template_id = :tid ORDER BY z_index, sort_order"),
        {"tid": str(template_id)},
    )
    return [dict(r) for r in result.mappings().all()]


def _extract_background_transform(template: dict | None) -> dict | None:
    if not template:
        return None
    metadata = template.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    transform = metadata.get("background_transform") or metadata.get("backgroundTransform")
    return transform if isinstance(transform, dict) else None


async def _load_background(template: dict | None) -> bytes | None:
    """Download template background image from storage."""
    if not template or not template.get("background_url"):
        return None
    try:
        return await storage_service.download_reference(template["background_url"])
    except Exception as e:
        logger.error("Failed to load background: %s", e)
    return None


def _event_local(ev: dict, fmt: str) -> str:
    """Event start in the event's own time zone (it is stored in UTC).

    Printing the stored value directly put UTC dates and times on invitations.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    start = ev.get("start_date")
    if not start:
        return ""
    try:
        moment = start if isinstance(start, datetime) else datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            moment = moment.astimezone(ZoneInfo(ev.get("timezone") or "UTC"))
        return moment.strftime(fmt)
    except (ValueError, KeyError, OSError):
        text_value = str(start)
        return text_value[:10] if fmt.startswith("%Y") else text_value[11:16]


def _build_render_context(inv: dict, batch: dict, event: dict = None, guest: dict = None) -> dict:
    """
    Build the data context dict for template rendering.
    Supports nested resolution via data_key (e.g. guest.custom_fields.seat).
    """
    ev = event or {}
    g = guest or {}
    
    # Extract custom_fields from guest record
    guest_custom = g.get("custom_fields") or {}
    
    # Extract custom_fields from invitation metadata (from Excel upload)
    inv_meta = inv.get("metadata") or {}
    if isinstance(inv_meta, str):
        import json
        try:
            inv_meta = json.loads(inv_meta)
        except Exception:
            inv_meta = {}
            
    inv_custom = inv_meta.get("custom_fields") or {}
    
    # Merge custom fields (invitation metadata overrides guest record)
    custom_fields = {**guest_custom, **inv_custom}

    ctx = {
        "guest": {
            "name": inv.get("guest_name") or inv.get("guest_name_ar") or g.get("full_name") or "",
            "name_ar": inv.get("guest_name_ar") or inv.get("guest_name") or g.get("full_name_ar") or "",
            "date_value": custom_fields.get("date_value", ""),
            "phone": inv.get("guest_phone") or g.get("phone") or "",
            "email": inv.get("guest_email") or g.get("email") or "",
            "company": inv_custom.get("company") or inv_custom.get("الشركة") or g.get("company") or "",
            "title": inv_custom.get("title") or inv_custom.get("المسمى") or g.get("title") or "",
            "custom_fields": custom_fields,
        },
        "event": {
            "title": ev.get("title") or "",
            "title_ar": ev.get("title_ar") or ev.get("title") or "",
            "date": _event_local(ev, "%Y-%m-%d"),
            "time": _event_local(ev, "%H:%M"),
            "location": ev.get("venue_name") or ev.get("venue_name_ar") or "",
            "location_ar": ev.get("venue_name_ar") or ev.get("venue_name") or "",
            "venue_address": ev.get("venue_address") or "",
            "venue_city": ev.get("venue_city") or "",
        },
        "invite": {
            "code": inv.get("token", "")[:8],
            "token": inv.get("token", ""),
            "barcode_payload": inv.get("barcode_payload") or inv.get("qr_data") or inv.get("token", ""),
            "ticket_class": str(inv.get("ticket_class", "normal")),
            "guest_count": inv.get("guest_count", 1),
        },
        "custom": {
            "seat": inv.get("seat_number") or custom_fields.get("seat", ""),
            "table": inv.get("table_number") or custom_fields.get("table", ""),
            "gate": custom_fields.get("gate", ""),
            "hall": inv.get("hall") or custom_fields.get("hall", ""),
            "zone": inv.get("zone") or custom_fields.get("zone", ""),
            **custom_fields,
        },
    }

    return ctx


async def _update_status(db: AsyncSession, batch_id: UUID, status: str, progress: int = 0, error: str = None):
    params: dict = {"id": str(batch_id), "st": status, "prog": progress}
    query = "UPDATE generation_batches SET status = :st, progress = :prog, updated_at = now()"
    if error:
        query += ", error_message = :err"
        params["err"] = error
    if status == "generating_barcodes" and progress <= 5:
        query += ", started_at = COALESCE(started_at, now())"
    query += " WHERE id = :id"
    await db.execute(text(query), params)


async def _update_progress(db: AsyncSession, batch_id: UUID, progress: int):
    await db.execute(
        text("UPDATE generation_batches SET progress = :p, updated_at = now() WHERE id = :id"),
        {"p": min(progress, 100), "id": str(batch_id)},
    )


async def _update_item_status(db: AsyncSession, item_id: UUID, status: str, error: str = None, started: bool = False):
    params: dict = {"id": str(item_id), "st": status}
    query = "UPDATE batch_items SET render_status = :st"
    if error:
        query += ", error_message = :err"
        params["err"] = error
    if started:
        query += ", started_at = now()"
    if status in ("done", "failed"):
        query += ", completed_at = now()"
    query += " WHERE id = :id"
    await db.execute(text(query), params)
