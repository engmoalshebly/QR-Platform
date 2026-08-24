"""
Fast Generation Service - Integrated Barcode + PDF + ZIP Generation.
Optimized for maximum speed with parallel processing and memory efficiency.

Process Flow:
1. Create invitations (if needed)
2. Generate barcodes + signatures in parallel batches
3. Create PDF directly from barcode images (no intermediate storage)
4. Create ZIP from barcode images
5. Upload all files in parallel
6. Update database with URLs

Performance Optimizations:
- Parallel barcode generation (ThreadPoolExecutor)
- Direct PDF generation from memory
- Streaming ZIP creation
- Batch database updates
- Minimal memory footprint
"""
import asyncio
import io
import json
import logging
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4


from app.services import barcode_service, storage_service, pdf_service
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Performance tuning
BARCODE_BATCH_SIZE = 50  # Process 50 barcodes in parallel
MAX_WORKERS = 8  # Maximum parallel threads
DEFAULT_BARCODE_SIZE = 400  # Default barcode size if not specified in layout

# Canonical invitation columns accepted by fast generation.
# Unknown keys are preserved in metadata for forward-compatibility.
INVITATION_DB_COLUMNS = {
    "ticket_class",
    "guest_name",
    "guest_count",
    "guest_name_ar",
    "guest_phone",
    "guest_whatsapp",
    "guest_email",
    "seat_number",
    "table_number",
    "hall",
    "zone",
    "notes",
}

# Normalize common import/file headers to canonical DB field names.
INVITATION_COLUMN_ALIASES = {
    "name": "guest_name",
    "full_name": "guest_name",
    "guest": "guest_name",
    "الاسم": "guest_name",
    "اسم_الضيف": "guest_name",
    "الضيف": "guest_name",
    "الاسم_بالعربي": "guest_name_ar",
    "الاسم_العربي": "guest_name_ar",
    "اسم_الضيف_بالعربي": "guest_name_ar",
    "phone": "guest_phone",
    "mobile": "guest_phone",
    "tel": "guest_phone",
    "رقم_الهاتف": "guest_phone",
    "الهاتف": "guest_phone",
    "رقم_الجوال": "guest_phone",
    "الجوال": "guest_phone",
    "موبايل": "guest_phone",
    "الموبايل": "guest_phone",
    "تليفون": "guest_phone",
    "الهاتف_المحمول": "guest_phone",
    "whatsapp": "guest_whatsapp",
    "wa_phone": "guest_whatsapp",
    "whatsapp_phone": "guest_whatsapp",
    "واتساب": "guest_whatsapp",
    "رقم_واتساب": "guest_whatsapp",
    "email": "guest_email",
    "البريد": "guest_email",
    "البريد_الإلكتروني": "guest_email",
    "البريد_الالكتروني": "guest_email",
    "الايميل": "guest_email",
    "ايميل": "guest_email",
    "بريد": "guest_email",
    "بريد_الكتروني": "guest_email",
    "seat": "seat_number",
    "رقم_المقعد": "seat_number",
    "المقعد": "seat_number",
    "مقعد": "seat_number",
    "table": "table_number",
    "رقم_الطاولة": "table_number",
    "الطاولة": "table_number",
    "طاولة": "table_number",
    "class": "ticket_class",
    "ticket": "ticket_class",
    "ticket_type": "ticket_class",
    "فئة_التذكرة": "ticket_class",
    "الفئة": "ticket_class",
    "نوع_التذكرة": "ticket_class",
    "ملاحظات": "notes",
    "ملاحظة": "notes",
    "عدد_المرافقين": "guest_count",
    "عدد_المدعوين": "guest_count",
    "عدد_الأشخاص": "guest_count",
    "عدد_الاقارب": "guest_count",
}

METADATA_OBJECT_KEYS = {"metadata", "custom_fields", "extra_fields"}


class FastGenerationResult:
    """Result of fast generation process."""
    def __init__(self):
        self.success = False
        self.total_invitations = 0
        self.pdf_url = None
        self.zip_url = None
        self.pdf_size = 0
        self.zip_size = 0
        self.generation_time_ms = 0
        self.error_message = None


def _normalize_input_key(key: Any) -> str:
    """Normalize an input key for resilient file/header mapping."""
    text_key = str(key or "").strip().lower()
    return text_key.replace(" ", "_").replace("-", "_")


def _normalize_invitation_row(inv_data: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """Normalize one invitation row and preserve unknown fields under metadata."""
    row: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}

    for raw_key, value in inv_data.items():
        normalized_key = _normalize_input_key(raw_key)
        canonical_key = INVITATION_COLUMN_ALIASES.get(normalized_key, normalized_key)

        if canonical_key in INVITATION_DB_COLUMNS:
            row[canonical_key] = value
            continue

        if normalized_key in METADATA_OBJECT_KEYS and isinstance(value, dict):
            metadata.update(value)
            continue

        # Keep non-schema data for future use instead of dropping it.
        if value is not None:
            metadata[str(raw_key)] = value

    ticket_class = str(row.get("ticket_class") or "normal").strip().lower()
    row["ticket_class"] = ticket_class if ticket_class in {"vip", "normal"} else "normal"
    row["guest_name"] = row.get("guest_name") or f"Guest {idx + 1}"
    try:
        row["guest_count"] = max(1, int(row.get("guest_count") or 1))
    except (TypeError, ValueError):
        row["guest_count"] = 1

    row_metadata = row.get("metadata")
    if isinstance(row_metadata, dict):
        metadata = {**row_metadata, **metadata}
    row["metadata"] = metadata

    return row


async def generate_invitations_fast(
    db,
    tenant_id: str,
    event_id: str,
    invitations_data: List[Dict[str, Any]],
    layout_config: Optional[Dict[str, Any]] = None,
    generate_pdf: bool = True,
    generate_zip: bool = True,
    upload_individual_barcodes: bool = True,
) -> FastGenerationResult:
    """
    Fast integrated generation of invitations, barcodes, PDF, and ZIP.
    
    Args:
        db: Database session
        tenant_id: Tenant UUID
        event_id: Event UUID
        invitations_data: List of invitation data dicts
        layout_config: PDF layout configuration
        
    Returns:
        FastGenerationResult with URLs and metrics
    """
    start_time = asyncio.get_event_loop().time()
    result = FastGenerationResult()
    
    try:
        # Use default layout if not provided
        if not layout_config:
            layout_config = {
                "page_size": "A4",
                "rows": 5,
                "cols": 5,
                "margin_top_mm": 10,
                "margin_bottom_mm": 10,
                "margin_left_mm": 10,
                "margin_right_mm": 10,
                "gap_x_mm": 2,
                "gap_y_mm": 2,
                "show_code_text": False,
                "show_guest_name": False,
                "barcode_size_px": DEFAULT_BARCODE_SIZE
            }
        
        # Resolve barcode size from layout config
        barcode_size = int(layout_config.get("barcode_size_px", DEFAULT_BARCODE_SIZE) or DEFAULT_BARCODE_SIZE)
        
        # Step 1: Create invitations in database
        logger.info(f"Creating {len(invitations_data)} invitations...")
        created_invitations = await _create_invitations_batch(
            db, tenant_id, event_id, invitations_data
        )
        result.total_invitations = len(created_invitations)
        
        if not created_invitations:
            result.error_message = "No invitations were created"
            return result
        
        # Step 2: Generate all barcodes in parallel batches
        logger.info("Generating barcodes in parallel...")
        barcode_results = await _generate_barcodes_parallel(
            tenant_id, event_id, created_invitations, barcode_size
        )
        
        pdf_bytes = b""
        zip_bytes = b""
        pdf_size = 0
        zip_size = 0

        # Step 3: Generate PDF directly from barcode images
        if generate_pdf:
            logger.info("Generating PDF...")
            pdf_bytes, pdf_size = await _generate_pdf_unified(
                barcode_results, layout_config
            )

        # Step 4: Generate ZIP from barcode images
        if generate_zip:
            logger.info("Generating ZIP...")
            zip_bytes, zip_size = await _generate_zip_fast(barcode_results)

        # Step 5: Upload requested aggregate files in parallel
        logger.info("Uploading files...")
        pdf_url, zip_url = await _upload_files_parallel(
            tenant_id, event_id, pdf_bytes if generate_pdf else None, zip_bytes if generate_zip else None
        )

        # Step 6: Update database with URLs
        logger.info("Updating database...")
        await _update_invitations_with_urls(
            db,
            created_invitations,
            barcode_results,
            pdf_url,
            zip_url,
            upload_individual_barcodes=upload_individual_barcodes,
        )
        
        # Set success result
        result.success = True
        result.pdf_url = pdf_url
        result.zip_url = zip_url
        result.pdf_size = pdf_size
        result.zip_size = zip_size
        
    except Exception as e:
        logger.error(f"Fast generation failed: {e}")
        result.error_message = str(e)
    
    finally:
        result.generation_time_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        logger.info(f"Fast generation completed in {result.generation_time_ms}ms")
    
    return result


async def _create_invitations_batch(
    db, tenant_id: str, event_id: str, invitations_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Create multiple invitations in a single database operation."""
    from sqlalchemy import text
    
    created_invitations = []

    values_list = []
    params = {"tenant_id": tenant_id, "event_id": event_id}
    for idx, inv_data in enumerate(invitations_data):
        normalized = _normalize_invitation_row(inv_data, idx)

        ticket_class_key = f"ticket_class_{idx}"
        guest_name_key = f"guest_name_{idx}"
        guest_name_ar_key = f"guest_name_ar_{idx}"
        guest_phone_key = f"guest_phone_{idx}"
        guest_whatsapp_key = f"guest_whatsapp_{idx}"
        guest_email_key = f"guest_email_{idx}"
        guest_count_key = f"guest_count_{idx}"
        seat_number_key = f"seat_number_{idx}"
        table_number_key = f"table_number_{idx}"
        hall_key = f"hall_{idx}"
        zone_key = f"zone_{idx}"
        notes_key = f"notes_{idx}"
        metadata_key = f"metadata_{idx}"
        status_key = f"status_{idx}"
        rsvp_status_key = f"rsvp_status_{idx}"

        meta = normalized.get("metadata") or {}
        # Ensure require_rsvp is stored in metadata if not present
        require_rsvp = meta.get("require_rsvp", False)
        meta["require_rsvp"] = require_rsvp

        status_val = "created"
        rsvp_status_val = "pending"
        if not require_rsvp:
            status_val = "accepted"
            rsvp_status_val = "accepted"

        params[ticket_class_key] = normalized.get("ticket_class")
        params[guest_name_key] = normalized.get("guest_name")
        params[guest_count_key] = normalized.get("guest_count", 1)
        params[guest_name_ar_key] = normalized.get("guest_name_ar")
        params[guest_phone_key] = normalized.get("guest_phone")
        params[guest_whatsapp_key] = normalized.get("guest_whatsapp")
        params[guest_email_key] = normalized.get("guest_email")
        params[seat_number_key] = normalized.get("seat_number")
        params[table_number_key] = normalized.get("table_number")
        params[hall_key] = normalized.get("hall")
        params[zone_key] = normalized.get("zone")
        params[notes_key] = normalized.get("notes")
        params[metadata_key] = json.dumps(meta, default=str)
        params[status_key] = status_val
        params[rsvp_status_key] = rsvp_status_val

        values_list.append(
            f"(:tenant_id, :event_id, CAST(:{ticket_class_key} AS ticket_class), "
            f":{guest_name_key}, :{guest_count_key}, :{guest_name_ar_key}, :{guest_phone_key}, :{guest_whatsapp_key}, :{guest_email_key}, "
            f":{seat_number_key}, :{table_number_key}, :{hall_key}, :{zone_key}, :{notes_key}, "
            f"CAST(:{metadata_key} AS jsonb), :{status_key}, :{rsvp_status_key}, now(), now())"
        )
    
    insert_query = f"""
        INSERT INTO invitations (
            tenant_id, event_id, ticket_class,
            guest_name, guest_count, guest_name_ar, guest_phone, guest_whatsapp, guest_email,
            seat_number, table_number, hall, zone, notes,
            metadata, status, rsvp_status, created_at, updated_at
        ) VALUES {','.join(values_list)}
        RETURNING id, tenant_id, event_id, token, guest_name, ticket_class, metadata
    """
    
    result = await db.execute(text(insert_query), params)
    await db.commit()
    
    for row in result.mappings().all():
        created_invitations.append(dict(row))
    
    return created_invitations


async def _generate_barcodes_parallel(
    tenant_id: str, event_id: str, invitations: List[Dict[str, Any]],
    barcode_size: int = 400
) -> List[Dict[str, Any]]:
    """Generate barcodes in parallel batches for maximum speed."""
    
    def generate_single_barcode(invitation: Dict[str, Any]) -> Dict[str, Any]:
        """Generate barcode for a single invitation."""
        try:
            invite_id = str(invitation['id'])
            token = invitation['token']
            ticket_class = invitation.get('ticket_class', 'normal')
            
            # Use the canonical signed, PII-free field representation.  Keep
            # payload_url only for the public invitation page metadata.
            payload = barcode_service.build_barcode_payload(invite_id, token)
            signature = payload["signature"]
            payload_url = payload["payload"]
            
            png_bytes = barcode_service.generate_qr_png(
                payload["field_payload"],
                size_px=barcode_size,
                fg_color="#000000",
                bg_color="#ffffff",
                error_level="H" if ticket_class.lower() == "vip" else "M",
            )
            if ticket_class.lower() == "vip":
                png_bytes = barcode_service.add_center_badge_to_png(png_bytes, "VIP")
            
            return {
                'invitation_id': invite_id,
                'token': token,
                'signature': signature,
                'payload_url': payload_url,
                'field_payload': payload["field_payload"],
                'png_bytes': png_bytes,
                'guest_name': invitation.get('guest_name', 'Guest'),
                'ticket_class': ticket_class
            }
            
        except Exception as e:
            logger.error(f"Failed to generate barcode for {invitation.get('id')}: {e}")
            return None
    
    # Process in parallel batches
    all_results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for i in range(0, len(invitations), BARCODE_BATCH_SIZE):
            batch = invitations[i:i + BARCODE_BATCH_SIZE]
            
            # Submit batch to thread pool
            futures = [
                executor.submit(generate_single_barcode, inv) 
                for inv in batch
            ]
            
            # Collect results
            for future in futures:
                result = future.result()
                if result:
                    all_results.append(result)
    
    return all_results


async def _generate_pdf_unified(
    barcode_results: List[Dict[str, Any]], layout_config: Dict[str, Any]
) -> tuple[bytes, int]:
    """Generate PDF using the unified pdf_service for consistent output."""
    
    # Convert barcode_results to the format expected by pdf_service
    pdf_items = []
    for item in barcode_results:
        pdf_items.append({
            "png_bytes": item['png_bytes'],
            "code": item.get('token', '')[:8],
            "guest_name": item.get('guest_name', ''),
            "ticket_class": item.get('ticket_class', 'normal'),
        })
    
    pdf_bytes = pdf_service.generate_barcode_grid_pdf(pdf_items, layout_config)
    return pdf_bytes, len(pdf_bytes)


async def _generate_zip_fast(barcode_results: List[Dict[str, Any]]) -> tuple[bytes, int]:
    """Generate ZIP file from barcode images efficiently."""
    
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
        for idx, result in enumerate(barcode_results):
            # Sanitize filename
            guest_name = result['guest_name'] or f'Guest_{idx+1}'
            safe_name = "".join(c for c in guest_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"{idx+1:04d}__{safe_name[:50]}.png"
            
            # Add file to ZIP
            zip_file.writestr(filename, result['png_bytes'])
    
    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()
    
    return zip_bytes, len(zip_bytes)


async def _upload_files_parallel(
    tenant_id: str, event_id: str, pdf_bytes: Optional[bytes], zip_bytes: Optional[bytes]
) -> tuple[Optional[str], Optional[str]]:
    """Upload PDF and ZIP files in parallel."""
    generation_id = uuid4().hex[:12]
    
    async def upload_pdf():
        if pdf_bytes is None:
            return None
        pdf_path = f"{tenant_id}/{event_id}/barcodes/fast_generation_{generation_id}.pdf"
        await storage_service.upload_bytes(pdf_path, pdf_bytes, content_type="application/pdf")
        return storage_service.get_signed_url(pdf_path, expires_in=86400 * 7)
    
    async def upload_zip():
        if zip_bytes is None:
            return None
        zip_path = f"{tenant_id}/{event_id}/barcodes/fast_generation_{generation_id}.zip"
        await storage_service.upload_bytes(zip_path, zip_bytes, content_type="application/zip")
        return storage_service.get_signed_url(zip_path, expires_in=86400 * 7)
    
    # Upload in parallel
    pdf_url, zip_url = await asyncio.gather(upload_pdf(), upload_zip())
    
    return pdf_url, zip_url


async def _update_invitations_with_urls(
    db, invitations: List[Dict[str, Any]], 
    barcode_results: List[Dict[str, Any]],
    pdf_url: Optional[str],
    zip_url: Optional[str],
    upload_individual_barcodes: bool = True,
):
    """Update invitations with barcode data and file URLs."""
    from sqlalchemy import text
    
    # Create mapping of invitation_id to barcode data
    barcode_map = {result['invitation_id']: result for result in barcode_results}
    
    # Update each invitation
    for invitation in invitations:
        invite_id = str(invitation['id'])
        barcode_data = barcode_map.get(invite_id)
        
        if barcode_data:
            barcode_url = None
            if upload_individual_barcodes:
                # Optional: useful for per-invitation previews, expensive for large print batches.
                barcode_path = f"{invitation['tenant_id']}/{invitation['event_id']}/barcodes/{invite_id}.png"
                await storage_service.upload_bytes(
                    barcode_path,
                    barcode_data['png_bytes'],
                    content_type="image/png"
                )
                barcode_url = storage_service.get_signed_url(barcode_path, expires_in=86400 * 30)
            
            # Update database
            await db.execute(text("""
                UPDATE invitations SET
                    barcode_png_url = COALESCE(:barcode_url, barcode_png_url),
                    barcode_signature = :signature,
                    barcode_payload = :payload,
                    qr_data = :qr_data,
                    pdf_url = COALESCE(:pdf_url, pdf_url),
                    zip_url = COALESCE(:zip_url, zip_url),
                    updated_at = now()
                WHERE id = :id
            """), {
                "barcode_url": barcode_url,
                "signature": barcode_data['signature'],
                "payload": barcode_data['field_payload'],
                "qr_data": barcode_data['payload_url'],
                "pdf_url": pdf_url,
                "zip_url": zip_url,
                "id": invite_id
            })
    
    await db.commit()
