"""
Generation Batches API.
Create, start, monitor, and download batch generation results.
Supports both QUICK (barcode grids) and DESIGNED (rendered cards) modes.
"""
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy import text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional

from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.database import get_db, AsyncSessionLocal
from pydantic import BaseModel, Field, model_validator
from app.models.batch import BatchCreate, BatchRead, BatchItemRead, BatchSummary, LayoutConfig
from app.services.permission_service import require_permission
from app.services.audit_service import log_audit
from app.services import batch_pipeline, storage_service
from app.services.quota_service import check_quota as quota_check_single
from app.config import get_settings
from app.security import get_client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batches", tags=["Generation Batches"])
settings = get_settings()


# ══════════════════════════════════════════════
# LIST BATCHES
# ══════════════════════════════════════════════

@router.get("", response_model=list[BatchSummary])
async def list_batches(
    request: Request,
    event_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.view")

    query = "SELECT * FROM generation_batches WHERE tenant_id = :tid"
    params: dict = {"tid": str(tenant_id)}

    if event_id:
        query += " AND event_id = :eid"
        params["eid"] = str(event_id)
    if status_filter:
        query += " AND status = :st"
        params["st"] = status_filter

    query += " ORDER BY created_at DESC LIMIT :lim"
    params["lim"] = limit

    result = await db.execute(text(query), params)
    rows = [dict(r) for r in result.mappings().all()]
    from app.routes.fast_invitations import _can_download_exports
    if not await _can_download_exports(db, tenant_id, user.id):
        for row in rows:
            row["result_pdf_url"] = row["result_zip_url"] = None
    return [BatchSummary(**row) for row in rows]


# ══════════════════════════════════════════════
# GET BATCH DETAILS
# ══════════════════════════════════════════════

@router.get("/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.view")

    result = await db.execute(
        text("SELECT * FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدفعة غير موجودة")
    values = dict(row)
    from app.routes.fast_invitations import _can_download_exports
    if not await _can_download_exports(db, tenant_id, user.id):
        values["result_pdf_url"] = values["result_zip_url"] = None
    return BatchRead(**values)


# ══════════════════════════════════════════════
# GET BATCH ITEMS (per-invitation status)
# ══════════════════════════════════════════════

@router.get("/{batch_id}/items", response_model=list[BatchItemRead])
async def get_batch_items(
    batch_id: UUID, request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, le=1000),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.view")

    # Verify batch belongs to tenant
    batch = await db.execute(
        text("SELECT id FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    if not batch.first():
        raise HTTPException(404, "الدفعة غير موجودة")

    query = "SELECT * FROM batch_items WHERE batch_id = :bid"
    params: dict = {"bid": str(batch_id)}
    if status_filter:
        query += " AND render_status = :st"
        params["st"] = status_filter
    query += " ORDER BY created_at LIMIT :lim"
    params["lim"] = limit

    result = await db.execute(text(query), params)
    return [BatchItemRead(**dict(r)) for r in result.mappings().all()]


# ══════════════════════════════════════════════
# CREATE BATCH
# ══════════════════════════════════════════════

@router.post("", response_model=BatchRead, status_code=201)
async def create_batch(
    body: BatchCreate, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a generation batch. Links existing invitations to the batch.
    If invitation_ids not provided, uses all invitations for the event+ticket_class.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.create")

    from app.routes.fast_invitations import require_generation_export
    await require_generation_export(db, tenant_id, user.id, bool(body.output_formats))

    # Verify event exists
    event = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(body.event_id), "tid": str(tenant_id)},
    )
    if not event.first():
        raise HTTPException(404, "المناسبة غير موجودة")

    if body.template_id:
        template = await db.execute(
            text("""
                SELECT id, ticket_class, template_type
                FROM invite_templates
                WHERE id = :tid AND tenant_id = :tenant_id
                  AND (event_id = :eid OR event_id IS NULL)
            """),
            {
                "tid": str(body.template_id),
                "tenant_id": str(tenant_id),
                "eid": str(body.event_id),
            },
        )
        template_row = template.mappings().first()
        if not template_row:
            raise HTTPException(404, "Ø§Ù„Ù‚Ø§Ù„Ø¨ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯")
        if template_row["ticket_class"] != body.ticket_class:
            raise HTTPException(400, "Ù†ÙˆØ¹ Ø§Ù„Ù‚Ø§Ù„Ø¨ Ù„Ø§ ÙŠØ·Ø§Ø¨Ù‚ Ù†ÙˆØ¹ Ø§Ù„Ø¯Ø¹ÙˆØ§Øª")
        if body.mode == "designed" and template_row["template_type"] != "designed":
            raise HTTPException(400, "ÙŠØ¬Ø¨ Ø§Ø®ØªÙŠØ§Ø± Ù‚Ø§Ù„Ø¨ ØªØµÙ…ÙŠÙ…")

    # Get invitation IDs
    if body.invitation_ids:
        inv_ids = [str(i) for i in body.invitation_ids]
        inv_result = await db.execute(
            text("""
                SELECT id FROM invitations
                WHERE id IN :ids AND tenant_id = :tid AND event_id = :eid
                  AND ticket_class = :tc
                  AND status NOT IN ('revoked', 'expired')
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": inv_ids, "tid": str(tenant_id), "eid": str(body.event_id), "tc": body.ticket_class},
        )
    else:
        inv_result = await db.execute(
            text("""
                SELECT id FROM invitations
                WHERE tenant_id = :tid AND event_id = :eid AND ticket_class = :tc
                  AND status NOT IN ('revoked', 'expired')
                ORDER BY created_at
            """),
            {"tid": str(tenant_id), "eid": str(body.event_id), "tc": body.ticket_class},
        )

    invitation_ids = [str(r[0]) for r in inv_result.fetchall()]
    if body.invitation_ids and len(invitation_ids) != len(body.invitation_ids):
        raise HTTPException(400, "Ø¨Ø¹Ø¶ Ø§Ù„Ø¯Ø¹ÙˆØ§Øª Ù„Ø§ ØªØ·Ø§Ø¨Ù‚ Ù†ÙˆØ¹ Ø§Ù„Ø¯ÙØ¹Ø© Ø£Ùˆ ØºÙŠØ± ØµØ§Ù„Ø­Ø©")
    if not invitation_ids:
        raise HTTPException(400, "لا توجد دعوات صالحة لهذه المناسبة")

    if len(invitation_ids) > 1000:
        raise HTTPException(400, 'الحد الحالي 1000 دعوة للعملية الواحدة. اختر مجموعة أصغر.')

    # Create batch
    layout_json = json.dumps(body.layout.model_dump(), default=str)

    result = await db.execute(
        text("""
            INSERT INTO generation_batches (
                tenant_id, event_id, template_id, mode, ticket_class,
                count_total, layout_json, output_formats, barcode_format,
                status, created_by, metadata
            ) VALUES (
                :tid, :eid, :tmpl, :mode, :tc,
                :count, CAST(:layout AS jsonb), :formats, :bf,
                'draft', :uid, CAST(:meta AS jsonb)
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id), "eid": str(body.event_id),
            "tmpl": str(body.template_id) if body.template_id else None,
            "mode": body.mode, "tc": body.ticket_class,
            "count": len(invitation_ids),
            "layout": layout_json,
            "formats": body.output_formats,
            "bf": body.barcode_format,
            "uid": str(user.id),
            "meta": json.dumps(body.metadata or {}, default=str),
        },
    )
    batch_row = result.mappings().first()
    batch_id = batch_row["id"]

    # Create batch items
    for inv_id in invitation_ids:
        await db.execute(
            text("INSERT INTO batch_items (batch_id, invitation_id) VALUES (:bid, :iid)"),
            {"bid": str(batch_id), "iid": inv_id},
        )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="batch.create", resource_type="batch", resource_id=str(batch_id),
        metadata={"count": len(invitation_ids), "mode": body.mode},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    return BatchRead(**dict(batch_row))


# ══════════════════════════════════════════════
# START BATCH (trigger pipeline)
# ══════════════════════════════════════════════

@router.post("/{batch_id}/start")
async def start_batch(
    batch_id: UUID, request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the batch generation pipeline via Celery worker (or BackgroundTask fallback)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.create")

    # Concurrency guard: pg_advisory_xact_lock prevents double-start
    lock_key = int.from_bytes(batch_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    # Verify batch
    result = await db.execute(
        text("SELECT id, status, output_formats, count_total, operation_id FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدفعة غير موجودة")

    if row["status"] not in ("draft", "failed"):
        raise HTTPException(400, f"لا يمكن بدء دفعة بحالة: {row['status']}")

    if row.get("operation_id"):
        raise HTTPException(409, "هذه الدفعة جزء من عملية محفوظة وتدار من خلال العملية الرئيسية")
    if row["count_total"] > 1000:
        raise HTTPException(400, "الحد الحالي 1000 دعوة للعملية الواحدة")
    from app.routes.fast_invitations import require_generation_export
    await require_generation_export(db, tenant_id, user.id, bool(row["output_formats"]))

    # Mark as queued
    await db.execute(
        text("UPDATE generation_batches SET status = 'queued', error_message = NULL, progress = 0, updated_at = now() WHERE id = :id"),
        {"id": str(batch_id)},
    )

    # Reset failed items for retry
    await db.execute(
        text("UPDATE batch_items SET render_status = 'pending', error_message = NULL WHERE batch_id = :bid AND render_status = 'failed'"),
        {"bid": str(batch_id)},
    )

    await db.commit()

    # Dispatch to Celery worker (production) or BackgroundTask (dev fallback)
    _dispatch_pipeline(str(batch_id), background_tasks)

    return {"message": "تم إنشاء الدعوات", "batch_id": str(batch_id), "status": "queued"}


def _dispatch_pipeline(batch_id: str, background_tasks: BackgroundTasks):
    """Send pipeline to Celery worker, or fall back to BackgroundTask in dev."""
    if settings.use_worker:
        try:
            from app.worker import run_pipeline_task
            run_pipeline_task.delay(batch_id)
            logger.info("Dispatched batch %s to Celery worker", batch_id)
            return
        except Exception as e:
            if settings.is_production:
                raise HTTPException(503, 'تعذر إرسال عملية الإنشاء للعامل؛ راجع حالة الدفعة قبل إعادة المحاولة') from e
            logger.warning("Celery dispatch unavailable; using development fallback")

    if settings.is_production:
        raise HTTPException(503, 'العامل مطلوب للإنشاء في بيئة الإنتاج')
    # Fallback: in-process background task (dev only — dies on restart)
    background_tasks.add_task(_run_pipeline_background, batch_id)
    logger.info("Running batch %s via BackgroundTask (dev fallback)", batch_id)


async def _run_pipeline_background(batch_id: str):
    """Run the batch pipeline with its own DB session (BackgroundTask fallback)."""
    from uuid import UUID as _UUID
    async with AsyncSessionLocal() as db:
        try:
            result = await batch_pipeline.run_batch_pipeline(db, _UUID(batch_id))
            if result.get("status") == "failed":
                logger.error("Background pipeline failed: %s", result.get("error"))
        except Exception as e:
            logger.error("Background pipeline exception: %s", e)
            await db.execute(
                text("UPDATE generation_batches SET status = 'failed', error_message = :err, updated_at = now() WHERE id = :id"),
                {"err": str(e)[:500], "id": batch_id},
            )
            await db.commit()


# ══════════════════════════════════════════════
# CANCEL BATCH
# ══════════════════════════════════════════════

@router.post("/{batch_id}/cancel")
async def cancel_batch(
    batch_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.manage")

    result = await db.execute(
        text("""
            UPDATE generation_batches SET status = 'cancelled', updated_at = now()
            WHERE id = :id AND tenant_id = :tid AND operation_id IS NULL AND status NOT IN ('ready', 'cancelled')
            RETURNING id
        """),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    if not result.first():
        raise HTTPException(400, "لا يمكن إلغاء هذه الدفعة")

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="batch.cancel", resource_type="batch", resource_id=str(batch_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"message": "تم إلغاء الدفعة"}


# ══════════════════════════════════════════════
# RETRY FAILED BATCH
# ══════════════════════════════════════════════

@router.post("/{batch_id}/retry")
async def retry_batch(
    batch_id: UUID, request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed batch. Only re-processes failed items (idempotent)."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.manage")

    # Concurrency guard
    lock_key = int.from_bytes(batch_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    result = await db.execute(
        text("SELECT id, status, output_formats, count_total, operation_id FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدفعة غير موجودة")
    if row["status"] != "failed":
        raise HTTPException(400, "يمكن إعادة المحاولة فقط للدفعات الفاشلة")

    if row.get("operation_id"):
        raise HTTPException(409, "هذه الدفعة جزء من عملية محفوظة وتدار من خلال العملية الرئيسية")
    if row["count_total"] > 1000:
        raise HTTPException(400, "الحد الحالي 1000 دعوة للعملية الواحدة")
    from app.routes.fast_invitations import require_generation_export
    await require_generation_export(db, tenant_id, user.id, bool(row["output_formats"]))

    # Reset failed items
    await db.execute(
        text("UPDATE batch_items SET render_status = 'pending', error_message = NULL WHERE batch_id = :bid AND render_status = 'failed'"),
        {"bid": str(batch_id)},
    )
    await db.execute(
        text("UPDATE generation_batches SET status = 'queued', error_message = NULL, progress = 0, updated_at = now() WHERE id = :id"),
        {"id": str(batch_id)},
    )
    await db.commit()

    _dispatch_pipeline(str(batch_id), background_tasks)

    return {"message": "تم إعادة المحاولة", "batch_id": str(batch_id)}


# ══════════════════════════════════════════════
# DOWNLOAD LINKS (signed URLs)
# ══════════════════════════════════════════════

@router.get("/{batch_id}/download/pdf")
async def download_pdf(
    batch_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a fresh signed URL for the batch PDF."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.export")

    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")

    result = await db.execute(
        text("SELECT result_pdf_url, status, event_id FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدفعة غير موجودة")
    if row["status"] != "ready":
        raise HTTPException(400, "الدفعة ليست جاهزة بعد")
    if not row["result_pdf_url"]:
        raise HTTPException(404, "لا يوجد ملف PDF لهذه الدفعة")

    # Generate fresh signed URL
    path = storage_service.build_path(tenant_id, row["event_id"], "batches", str(batch_id), "result.pdf")
    url = storage_service.get_signed_url(path, expires_in=3600)

    return {"url": url, "expires_in": 3600}


@router.get("/{batch_id}/download/zip")
async def download_zip(
    batch_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a fresh signed URL for the batch ZIP."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.export")

    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")

    result = await db.execute(
        text("SELECT result_zip_url, status, event_id FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "الدفعة غير موجودة")
    if row["status"] != "ready":
        raise HTTPException(400, "الدفعة ليست جاهزة بعد")
    if not row["result_zip_url"]:
        raise HTTPException(404, "لا يوجد ملف ZIP لهذه الدفعة")

    path = storage_service.build_path(tenant_id, row["event_id"], "batches", str(batch_id), "images.zip")
    url = storage_service.get_signed_url(path, expires_in=3600)

    return {"url": url, "expires_in": 3600}


# ══════════════════════════════════════════════
# BATCH STATS
# ══════════════════════════════════════════════

@router.get("/{batch_id}/stats")
async def batch_stats(
    batch_id: UUID, request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed stats for a batch."""
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "batches.view")

    batch = await db.execute(
        text("SELECT * FROM generation_batches WHERE id = :id AND tenant_id = :tid"),
        {"id": str(batch_id), "tid": str(tenant_id)},
    )
    batch_row = batch.mappings().first()
    if not batch_row:
        raise HTTPException(404, "الدفعة غير موجودة")

    items_stats = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE render_status = 'done') AS done,
                COUNT(*) FILTER (WHERE render_status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE render_status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE render_status = 'skipped') AS skipped
            FROM batch_items WHERE batch_id = :bid
        """),
        {"bid": str(batch_id)},
    )
    stats = items_stats.mappings().first()

    # Get failed items details
    failed_items = await db.execute(
        text("""
            SELECT bi.id, bi.invitation_id, bi.error_message, i.guest_name
            FROM batch_items bi
            LEFT JOIN invitations i ON i.id = bi.invitation_id
            WHERE bi.batch_id = :bid AND bi.render_status = 'failed'
            LIMIT 20
        """),
        {"bid": str(batch_id)},
    )

    from app.routes.fast_invitations import _can_download_exports
    can_export = await _can_download_exports(db, tenant_id, user.id)
    return {
        "batch": {
            "id": str(batch_row["id"]),
            "status": batch_row["status"],
            "progress": batch_row["progress"],
            "mode": batch_row["mode"],
            "started_at": batch_row.get("started_at"),
            "completed_at": batch_row.get("completed_at"),
        },
        "items": dict(stats),
        "failed_details": [dict(r) for r in failed_items.mappings().all()],
        "result": {
            "pdf_url": batch_row.get("result_pdf_url") if can_export else None,
            "zip_url": batch_row.get("result_zip_url") if can_export else None,
            "preview_urls": batch_row.get("result_preview_urls", []),
        },
    }


# ══════════════════════════════════════════════
# CREATE AND START DESIGNED BATCH FAST (SINGLE REQUEST)
# ══════════════════════════════════════════════

class BatchGenerateDesignedFast(BaseModel):
    event_id: UUID
    template_id: UUID
    ticket_class: str = "normal"
    invitations: list[dict] = Field(..., min_items=1, max_items=1000, description="List of guest invitation objects")
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    output_formats: list[str] = Field(default=["pdf", "zip"])
    barcode_format: str = "qr"
    metadata: Optional[dict] = None

    @model_validator(mode='after')
    def validate_guests(self):
        from app.services.fast_generation_service import _normalize_invitation_row
        if self.ticket_class not in ('vip', 'normal'):
            raise ValueError('فئة التذكرة غير صالحة')
        if set(self.output_formats) - {'pdf', 'zip'} or len(set(self.output_formats)) != len(self.output_formats):
            raise ValueError('صيغ الملفات المطلوبة غير صالحة')
        if self.barcode_format != 'qr':
            raise ValueError('هذه العملية تدعم QR فقط')
        if any(row.get('ticket_class', self.ticket_class) != self.ticket_class for row in self.invitations):
            raise ValueError('فئة الضيوف يجب أن تطابق فئة القالب المختار')
        self.invitations = [_normalize_invitation_row({**row, 'ticket_class': self.ticket_class}, index)
                            for index, row in enumerate(self.invitations)]
        return self

@router.post("/generate-designed-fast", response_model=BatchRead, status_code=201)
async def generate_designed_fast(
    body: BatchGenerateDesignedFast,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create all invitations and start designed generation batch in a single optimized request.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "invitations.create")
    await require_permission(db, tenant_id, user.id, "batches.create")

    from app.services.generation_operation_service import guard_legacy_generation_creation
    guard_legacy_generation_creation()

    # Validate event exists
    event_check = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(body.event_id), "tid": str(tenant_id)},
    )
    if not event_check.first():
        raise HTTPException(404, "المناسبة غير موجودة")

    # Validate template exists
    template = await db.execute(
        text("""
            SELECT id, ticket_class, template_type
            FROM invite_templates
            WHERE id = :tid AND tenant_id = :tenant_id
              AND (event_id = :eid OR event_id IS NULL)
        """),
        {
            "tid": str(body.template_id),
            "tenant_id": str(tenant_id),
            "eid": str(body.event_id),
        },
    )
    template_row = template.mappings().first()
    if not template_row:
        raise HTTPException(404, "القالب غير موجود")
    if template_row["ticket_class"] != body.ticket_class:
        raise HTTPException(400, "نوع القالب لا يطابق نوع الدفعة")
    if template_row["template_type"] != "designed":
        raise HTTPException(400, "يجب اختيار قالب تصميم")

    from app.routes.fast_invitations import require_generation_export
    await require_generation_export(db, tenant_id, user.id, bool(body.output_formats))
    if any(row['metadata']['require_rsvp'] for row in body.invitations):
        from app.services.feature_service import require_feature
        await require_feature(db, tenant_id, 'rsvp')
    total_people = sum(row['guest_count'] for row in body.invitations)

    # Check quota
    total_invitations = len(body.invitations)
    await quota_check_single(
        db, str(tenant_id), str(body.event_id),
        body.ticket_class, count=total_people
    )

    # ── Plan limits ──
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=total_people)
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(body.event_id), "tid": str(tenant_id)},
    )
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل مناسبة", requested=total_invitations)

    # Batch insert invitations
    values_parts = []
    params = {
        "tid": str(tenant_id),
        "eid": str(body.event_id),
        "tmpl": str(body.template_id),
        "tc": body.ticket_class,
        "uid": str(user.id),
    }
    
    import json
    for idx, inv_data in enumerate(body.invitations):
        name = inv_data.get("guest_name") or f"Guest {idx + 1}"
        count = inv_data.get("guest_count") or 1
        meta = inv_data.get("metadata") or {}
        
        require_rsvp = meta['require_rsvp']
        phone_key, whatsapp_key, email_key = f'phone_{idx}', f'whatsapp_{idx}', f'email_{idx}'
        params[phone_key] = inv_data.get('guest_phone')
        params[whatsapp_key] = inv_data.get('guest_whatsapp')
        params[email_key] = inv_data.get('guest_email')

        status_val = "created"
        rsvp_status_val = "pending"
        if not require_rsvp:
            status_val = "accepted"
            rsvp_status_val = "accepted"
        
        name_key = f"name_{idx}"
        count_key = f"count_{idx}"
        meta_key = f"meta_{idx}"
        status_key = f"status_{idx}"
        rsvp_status_key = f"rsvp_status_{idx}"
        
        params[name_key] = name
        params[count_key] = count
        params[meta_key] = json.dumps(meta, default=str)
        params[status_key] = status_val
        params[rsvp_status_key] = rsvp_status_val
        
        values_parts.append(
            f"(:tid, :eid, :tmpl, CAST(:tc AS ticket_class), :{name_key}, :{count_key}, :{phone_key}, :{whatsapp_key}, :{email_key}, CAST(:{meta_key} AS jsonb), :uid, :{status_key}, :{rsvp_status_key}, now(), now())"
        )
    
    insert_sql = f"""
        INSERT INTO invitations (
            tenant_id, event_id, template_id, ticket_class,
            guest_name, guest_count, guest_phone, guest_whatsapp, guest_email, metadata, created_by, status, rsvp_status, created_at, updated_at
        ) VALUES {', '.join(values_parts)}
        RETURNING id
    """
    
    result = await db.execute(text(insert_sql), params)
    invitation_ids = [str(r[0]) for r in result.fetchall()]

    if not invitation_ids:
        raise HTTPException(400, "لم يتم إنشاء أي دعوات")

    # Create batch
    layout_json = json.dumps(body.layout.model_dump(), default=str)

    batch_result = await db.execute(
        text("""
            INSERT INTO generation_batches (
                tenant_id, event_id, template_id, mode, ticket_class,
                count_total, layout_json, output_formats, barcode_format,
                status, created_by, metadata
            ) VALUES (
                :tid, :eid, :tmpl, 'designed', :tc,
                :count, CAST(:layout AS jsonb), :formats, :bf,
                'draft', :uid, CAST(:meta AS jsonb)
            )
            RETURNING *
        """),
        {
            "tid": str(tenant_id), "eid": str(body.event_id),
            "tmpl": str(body.template_id),
            "tc": body.ticket_class,
            "count": len(invitation_ids),
            "layout": layout_json,
            "formats": body.output_formats,
            "bf": body.barcode_format,
            "uid": str(user.id),
            "meta": json.dumps(body.metadata or {}, default=str),
        },
    )
    batch_row = batch_result.mappings().first()
    batch_id = batch_row["id"]

    # Create batch items
    for inv_id in invitation_ids:
        await db.execute(
            text("INSERT INTO batch_items (batch_id, invitation_id) VALUES (:bid, :iid)"),
            {"bid": str(batch_id), "iid": inv_id},
        )

    # Queue the batch
    queued_result = await db.execute(
        text("UPDATE generation_batches SET status = 'queued', error_message = NULL, progress = 0, updated_at = now() WHERE id = :id RETURNING *"),
        {"id": str(batch_id)},
    )
    # Capture the response while transaction-local tenant RLS is still set.
    response = BatchRead(**dict(queued_result.mappings().one()))
    await db.commit()

    # Dispatch to pipeline asynchronously
    _dispatch_pipeline(str(batch_id), background_tasks)

    return response
