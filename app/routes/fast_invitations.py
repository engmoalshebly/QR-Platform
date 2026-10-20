"""
Fast Invitations API - Integrated Generation Endpoints.
Provides ultra-fast invitation creation with barcode, PDF, and ZIP generation.

Features:
- Single API call for everything
- Parallel processing for maximum speed
- Real-time progress tracking
- Multiple input formats
- Professional PDF output
- Optimized for large batches
"""
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List, Optional, Dict, Any
import logging
import io
import zipfile
import asyncio
from urllib.parse import unquote, urlparse

from app.auth import CurrentUser, decode_supabase_jwt, get_current_user, get_tenant_id_from_header
from app.database import get_db
from app.services.permission_service import require_permission
from app.services.audit_service import log_audit
from app.services.fast_generation_service import generate_invitations_fast, FastGenerationResult
from app.services import pdf_service, barcode_service, storage_service
from app.services.quota_service import check_quota_mixed
from app.config import get_settings
from app.security import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fast-invitations", tags=["Fast Invitations"])
settings = get_settings()

security_bearer = HTTPBearer(auto_error=False)

async def get_current_user_from_header_or_query(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> CurrentUser:
    """Authenticate through a bearer header only; URLs must never carry JWTs."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization token is required",
        )
    raw_token = credentials.credentials
    try:
        payload = await decode_supabase_jwt(raw_token)
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
        )
    if payload.get("role") != "authenticated":
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing user ID",
        )
    try:
        return CurrentUser(
            id=UUID(user_id),
            email=payload.get("email"),
            role=payload.get("role"),
            aal=payload.get("aal"),
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid authentication token")

def get_tenant_id_from_header_or_query(request: Request) -> UUID:
    tenant_id = request.headers.get("X-Tenant-ID") or request.query_params.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="X-Tenant-ID header or tenant_id query param is required",
        )
    try:
        return UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid tenant ID format",
        )


# ══════════════════════════════════════════════
# Pydantic Models
# ══════════════════════════════════════════════

from pydantic import BaseModel, Field, field_validator
from app.models.invitation import InvitationRead

async def require_generation_export(db, tenant_id, user_id, requested):
    if requested:
        from app.services.feature_service import require_feature
        await require_permission(db, tenant_id, user_id, 'invitations.export')
        await require_feature(db, tenant_id, 'pdf_export')


class FastInvitationRequest(BaseModel):
    """Request model for fast invitation generation."""
    event_id: UUID = Field(..., description="Event ID")
    invitations: List[Dict[str, Any]] = Field(
        ..., 
        min_items=1,
        max_items=1000,
        description="List of invitation data (max 1000 per request)"
    )
    layout_config: Optional[Dict[str, Any]] = Field(
        None,
        description="PDF layout configuration"
    )
    generate_zip: bool = Field(True, description="Generate ZIP file")
    generate_pdf: bool = Field(True, description="Generate PDF file")
    upload_individual_barcodes: bool = Field(
        True,
        description="Upload a separate PNG for every invitation. Disable for faster PDF/ZIP print batches."
    )

    @field_validator('invitations')
    @classmethod
    def validate_guests(cls, rows):
        from app.services.fast_generation_service import _normalize_invitation_row
        return [_normalize_invitation_row(row, index) for index, row in enumerate(rows)]

    @field_validator('layout_config')
    @classmethod
    def validate_layout(cls, layout):
        from app.models.batch import LayoutConfig
        return LayoutConfig(**layout).model_dump() if layout is not None else None


class FastInvitationByCount(BaseModel):
    """Request model for creating invitations by count."""
    event_id: UUID = Field(..., description="Event ID")
    count: int = Field(..., ge=1, le=1000, description="Number of invitations")
    ticket_class: str = Field("normal", pattern="^(vip|normal)$", description="Ticket class")
    guest_name_prefix: Optional[str] = Field(None, max_length=180, description="Guest name prefix")
    layout_config: Optional[Dict[str, Any]] = Field(None, description="PDF layout configuration")
    generate_zip: bool = Field(True, description="Generate ZIP file")
    generate_pdf: bool = Field(True, description="Generate PDF file")
    upload_individual_barcodes: bool = Field(
        True,
        description="Upload a separate PNG for every invitation. Disable for faster PDF/ZIP print batches."
    )


    @field_validator("layout_config")
    @classmethod
    def validate_layout(cls, layout):
        from app.models.batch import LayoutConfig
        return LayoutConfig(**layout).model_dump() if layout is not None else None


class FastGenerationResponse(BaseModel):
    """Response model for fast generation."""
    success: bool
    total_invitations: int
    generation_time_ms: int
    pdf_url: Optional[str] = None
    zip_url: Optional[str] = None
    pdf_size_mb: Optional[float] = None
    zip_size_mb: Optional[float] = None
    error_message: Optional[str] = None


class GenerationProgressResponse(BaseModel):
    """Response model for generation progress."""
    status: str
    progress_percent: int
    total_invitations: int
    processed_invitations: int
    current_stage: str
    estimated_remaining_seconds: Optional[int] = None


class GenerationHistoryItem(BaseModel):
    """A completed barcode generation operation for an event."""
    id: str
    total_invitations: int
    vip_count: int
    normal_count: int
    generated_at: Optional[str] = None
    pdf_url: Optional[str] = None
    zip_url: Optional[str] = None


class DeleteGenerationResponse(BaseModel):
    success: bool
    deleted_invitations: int
    deleted_files: int
    skipped_checked_in: int = 0
    message: str = ""


def _storage_path_from_signed_url(url: Optional[str]) -> Optional[str]:
    """Extract Supabase Storage object path from a signed/public URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        marker = "/object/sign/invitations/"
        if marker not in path:
            marker = "/object/public/invitations/"
        if marker not in path:
            return None
        return path.split(marker, 1)[1]
    except Exception:
        return None


async def _can_download_exports(db, tenant_id, user_id):
    from app.services.permission_service import has_permission
    from app.services.feature_service import check_feature_flag
    return (await has_permission(db, tenant_id, user_id, "invitations.export")
            and await check_feature_flag(db, tenant_id, "pdf_export"))


async def redact_generation_files(db, tenant_id, user_id, records):
    records = [dict(record) for record in records]
    if any(record.get('pdf_url') or record.get('zip_url') for record in records):
        if not await _can_download_exports(db, tenant_id, user_id):
            for record in records:
                record['pdf_url'] = record['zip_url'] = None
    return records


class RefreshDownloadRequest(BaseModel):
    reference: str = Field(..., min_length=1, max_length=8192)


async def _fresh_owned_download(db, tenant_id, reference):
    # Match a persisted reference first; never sign an arbitrary caller-supplied path.
    result = await db.execute(text("""
        SELECT event_id FROM invitations
        WHERE tenant_id = :tid AND (pdf_url = :ref OR zip_url = :ref)
          AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
        UNION ALL
        SELECT event_id FROM generation_batches
        WHERE tenant_id = :tid AND status = 'ready'
          AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
          AND (result_pdf_url = :ref OR result_zip_url = :ref)
        LIMIT 1
    """), {"tid": str(tenant_id), "ref": reference})
    row = result.first()
    if not row:
        raise HTTPException(404, "الملف غير موجود أو غير متاح لهذه المؤسسة")
    path = _storage_path_from_signed_url(reference)
    expected = f"{tenant_id}/{row[0]}/"
    if not path or not path.startswith(expected) or any(part in ("", ".", "..") for part in path.split("/")) or not path.lower().endswith((".pdf", ".zip")):
        raise HTTPException(404, "مرجع الملف غير صالح")
    url = await asyncio.to_thread(storage_service.get_signed_url, path, expires_in=300)
    if not url:
        raise HTTPException(503, "تعذر تجهيز التنزيل. أعد المحاولة")
    return url


@router.post("/refresh-download")
async def refresh_download(body: RefreshDownloadRequest, request: Request,
                           user: CurrentUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    tenant_id = get_tenant_id_from_header(request)
    await require_generation_export(db, tenant_id, user.id, True)
    return {"download_url": await _fresh_owned_download(db, tenant_id, body.reference)}


# ══════════════════════════════════════════════
# FAST GENERATION ENDPOINTS
# ══════════════════════════════════════════════

@router.post("/generate", response_model=FastGenerationResponse, status_code=201)
async def generate_invitations_fast_endpoint(
    request: FastInvitationRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate invitations with barcodes, PDF, and ZIP in one fast operation.
    
    This endpoint creates invitations, generates barcodes, creates PDF and ZIP files,
    and returns download URLs - all in a single optimized process.
    
    Performance: ~1000 invitations in 30-60 seconds
    """
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.create")
    from app.services.generation_operation_service import guard_legacy_generation_creation
    guard_legacy_generation_creation()
    
    # Validate event exists and belongs to tenant
    event_check = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(request.event_id), "tid": str(tenant_id)}
    )
    if not event_check.first():
        raise HTTPException(404, "الحدث غير موجود")
    if any(row['metadata']['require_rsvp'] for row in request.invitations):
        from app.services.feature_service import require_feature
        await require_feature(db, tenant_id, 'rsvp')
    await require_generation_export(db, tenant_id, user.id, request.generate_pdf or request.generate_zip)

    # Check quota
    await check_quota_mixed(db, str(tenant_id), str(request.event_id), request.invitations)

    # ── Plan limits ──
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    _fast_total = len(request.invitations)
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=sum(row["guest_count"] for row in request.invitations))
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(request.event_id), "tid": str(tenant_id)},
    )
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل حدث", requested=_fast_total)

    try:
        # Execute fast generation
        result = await generate_invitations_fast(
            db=db,
            tenant_id=str(tenant_id),
            event_id=str(request.event_id),
            invitations_data=request.invitations,
            layout_config=request.layout_config,
            generate_pdf=request.generate_pdf,
            generate_zip=request.generate_zip,
            upload_individual_barcodes=request.upload_individual_barcodes,
        )
        if not result.success:
            raise HTTPException(400, detail=result.error_message or "فشل في توليد الدعوات")
        # Log the operation
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="fast_invitations.generate", resource_type="event", 
            resource_id=str(request.event_id),
            metadata={
                "total_invitations": result.total_invitations,
                "generation_time_ms": result.generation_time_ms,
                "pdf_size_mb": result.pdf_size / (1024*1024) if result.pdf_size else None,
                "zip_size_mb": result.zip_size / (1024*1024) if result.zip_size else None
            }
        )
        await db.commit()
        
        # Prepare response
        response = FastGenerationResponse(
            success=result.success,
            total_invitations=result.total_invitations,
            generation_time_ms=result.generation_time_ms,
            pdf_url=result.pdf_url,
            zip_url=result.zip_url,
            pdf_size_mb=result.pdf_size / (1024*1024) if result.pdf_size else None,
            zip_size_mb=result.zip_size / (1024*1024) if result.zip_size else None,
            error_message=result.error_message
        )
        
        return response
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception("Fast invitation generation failed")
        raise HTTPException(500, "فشل في التوليد السريع")


@router.post("/generate-by-count", response_model=FastGenerationResponse, status_code=201)
async def generate_invitations_by_count(
    request: FastInvitationByCount,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate invitations by count with automatic naming.
    
    Creates the specified number of invitations with sequential guest names
    (Guest 1, Guest 2, etc.) or with custom prefix.
    """
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.create")
    from app.services.generation_operation_service import guard_legacy_generation_creation
    guard_legacy_generation_creation()
    
    # Validate event exists
    event_check = await db.execute(
        text("SELECT id FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(request.event_id), "tid": str(tenant_id)}
    )
    if not event_check.first():
        raise HTTPException(404, "الحدث غير موجود")
    
    await require_generation_export(db, tenant_id, user.id, request.generate_pdf or request.generate_zip)

    # Generate invitations data
    invitations_data = []
    prefix = request.guest_name_prefix or "Guest"
    
    for i in range(request.count):
        invitations_data.append({
            "guest_name": f"{prefix} {i+1}",
            "ticket_class": request.ticket_class
        })
    
    # Check quota
    await check_quota_mixed(db, str(tenant_id), str(request.event_id), invitations_data)

    # ── Plan limits ──
    from app.services.feature_service import enforce_monthly_limit, enforce_static_limit
    await enforce_monthly_limit(db, tenant_id, "invitations_per_month", "الدعوات الشهرية", count=request.count)
    _inv_total_res = await db.execute(
        text("SELECT COUNT(*) FROM invitations WHERE event_id = :eid AND tenant_id = :tid AND status NOT IN ('revoked','expired')"),
        {"eid": str(request.event_id), "tid": str(tenant_id)},
    )
    await enforce_static_limit(db, tenant_id, "invitations_per_event", _inv_total_res.scalar() or 0, "الدعوات لكل حدث", requested=request.count)

    try:
        # Execute fast generation
        result = await generate_invitations_fast(
            db=db,
            tenant_id=str(tenant_id),
            event_id=str(request.event_id),
            invitations_data=invitations_data,
            layout_config=request.layout_config,
            generate_pdf=request.generate_pdf,
            generate_zip=request.generate_zip,
            upload_individual_barcodes=request.upload_individual_barcodes,
        )
        
        # Log the operation
        if not result.success:
            raise HTTPException(400, detail=result.error_message or "فشل في توليد الدعوات")
        await log_audit(
            db, tenant_id=tenant_id, actor_user_id=user.id,
            action="fast_invitations.generate_by_count", resource_type="event",
            resource_id=str(request.event_id),
            metadata={
                "count": request.count,
                "ticket_class": request.ticket_class,
                "generation_time_ms": result.generation_time_ms,
                "total_invitations": result.total_invitations
            }
        )
        await db.commit()
        
        # Prepare response
        response = FastGenerationResponse(
            success=result.success,
            total_invitations=result.total_invitations,
            generation_time_ms=result.generation_time_ms,
            pdf_url=result.pdf_url,
            zip_url=result.zip_url,
            pdf_size_mb=result.pdf_size / (1024*1024) if result.pdf_size else None,
            zip_size_mb=result.zip_size / (1024*1024) if result.zip_size else None,
            error_message=result.error_message
        )
        
        return response
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception("Fast invitation generation by count failed")
        raise HTTPException(500, "فشل في التوليد السريع")


@router.get("/download/{event_id}/pdf")
async def download_event_pdf(
    event_id: UUID,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get download URL for the generated PDF of an event."""
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.export")
    
    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")
    
    # Get PDF URL from database
    result = await db.execute(
        text("""
            SELECT pdf_url
            FROM invitations 
            WHERE event_id = :eid AND tenant_id = :tid AND pdf_url IS NOT NULL
            GROUP BY pdf_url
            ORDER BY MAX(updated_at) DESC
            LIMIT 1
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    
    row = result.first()
    if not row or not row[0]:
        raise HTTPException(404, "ملف PDF غير موجود")
    
    return {"download_url": await _fresh_owned_download(db, tenant_id, row[0])}


@router.get("/download/{event_id}/zip")
async def download_event_zip(
    event_id: UUID,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get download URL for the generated ZIP of an event."""
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.export")
    
    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")
    
    # Get ZIP URL from database
    result = await db.execute(
        text("""
            SELECT zip_url
            FROM invitations 
            WHERE event_id = :eid AND tenant_id = :tid AND zip_url IS NOT NULL
            GROUP BY zip_url
            ORDER BY MAX(updated_at) DESC
            LIMIT 1
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    
    row = result.first()
    if not row or not row[0]:
        raise HTTPException(404, "ملف ZIP غير موجود")
    
    return {"download_url": await _fresh_owned_download(db, tenant_id, row[0])}


@router.get("/history/{event_id}", response_model=List[GenerationHistoryItem])
async def get_generation_history(
    event_id: UUID,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List completed fast generation operations and registration form submissions for an event."""
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.view")

    # 1. Fetch registration form submissions count
    reg_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_invitations,
                COUNT(CASE WHEN ticket_class = 'vip' THEN 1 END) AS vip_count,
                COUNT(CASE WHEN ticket_class = 'normal' THEN 1 END) AS normal_count,
                MAX(updated_at) AS generated_at
            FROM invitations
            WHERE event_id = :eid
              AND tenant_id = :tid
              AND is_registration = true
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    reg_row = reg_result.mappings().first()

    # 2. Fetch RSVP submissions count (virtual batch)
    rsvp_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_invitations,
                COUNT(CASE WHEN ticket_class = 'vip' THEN 1 END) AS vip_count,
                COUNT(CASE WHEN ticket_class = 'normal' THEN 1 END) AS normal_count,
                MAX(updated_at) AS generated_at,
                MAX(pdf_url) AS pdf_url,
                MAX(zip_url) AS zip_url
            FROM invitations
            WHERE event_id = :eid
              AND tenant_id = :tid
              AND (metadata IS NOT NULL AND metadata->>'require_rsvp' = 'true')
              AND is_registration = false
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    rsvp_row = rsvp_result.mappings().first()

    # 3. Fetch standard PDF/ZIP generation batches
    result = await db.execute(
        text("""
            SELECT
                md5(COALESCE(pdf_url, '') || '|' || COALESCE(zip_url, '')) AS id,
                COUNT(*) AS total_invitations,
                COUNT(CASE WHEN ticket_class = 'vip' THEN 1 END) AS vip_count,
                COUNT(CASE WHEN ticket_class = 'normal' THEN 1 END) AS normal_count,
                MAX(updated_at) AS generated_at,
                pdf_url,
                zip_url
            FROM invitations
            WHERE event_id = :eid
              AND tenant_id = :tid
              AND (pdf_url IS NOT NULL OR zip_url IS NOT NULL)
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
              AND is_registration = false
              AND (metadata IS NULL OR metadata->>'require_rsvp' IS DISTINCT FROM 'true')
            GROUP BY pdf_url, zip_url
            ORDER BY MAX(updated_at) DESC
            LIMIT 50
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )

    # 4. Fetch designed template/batch generations from generation_batches
    batch_result = await db.execute(
        text("""
            SELECT
                b.id::text AS id,
                COUNT(i.id) AS total_invitations,
                COUNT(CASE WHEN i.ticket_class = 'vip' THEN 1 END) AS vip_count,
                COUNT(CASE WHEN i.ticket_class = 'normal' THEN 1 END) AS normal_count,
                b.updated_at AS generated_at,
                b.result_pdf_url AS pdf_url,
                b.result_zip_url AS zip_url
            FROM generation_batches b
            LEFT JOIN batch_items bi ON bi.batch_id = b.id
            LEFT JOIN invitations i ON i.id = bi.invitation_id AND (i.metadata IS NULL OR i.metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            WHERE b.event_id = :eid
              AND b.tenant_id = :tid
              AND b.status = 'ready'
              AND (b.metadata IS NULL OR b.metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            GROUP BY b.id, b.updated_at, b.result_pdf_url, b.result_zip_url
            ORDER BY b.updated_at DESC
            LIMIT 50
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )

    items = []
    
    # Add virtual registrations row if any exist
    if reg_row and reg_row["total_invitations"] > 0:
        items.append({
            "id": "registration_submissions",
            "total_invitations": reg_row["total_invitations"],
            "vip_count": reg_row["vip_count"],
            "normal_count": reg_row["normal_count"],
            "generated_at": reg_row["generated_at"].isoformat() if reg_row["generated_at"] else None,
            "pdf_url": f"/api/v1/fast-invitations/history/{event_id}/registration_submissions/pdf",
            "zip_url": f"/api/v1/fast-invitations/history/{event_id}/registration_submissions/zip",
        })

    # Add virtual RSVP row if any exist
    if rsvp_row and rsvp_row["total_invitations"] > 0:
        items.append({
            "id": "rsvp_submissions",
            "total_invitations": rsvp_row["total_invitations"],
            "vip_count": rsvp_row["vip_count"],
            "normal_count": rsvp_row["normal_count"],
            "generated_at": rsvp_row["generated_at"].isoformat() if rsvp_row["generated_at"] else None,
            "pdf_url": rsvp_row["pdf_url"],
            "zip_url": rsvp_row["zip_url"],
        })

    for row in result.mappings().all():
        items.append({
            "id": row["id"],
            "total_invitations": row["total_invitations"],
            "vip_count": row["vip_count"],
            "normal_count": row["normal_count"],
            "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
            "pdf_url": row["pdf_url"],
            "zip_url": row["zip_url"],
        })

    for row in batch_result.mappings().all():
        items.append({
            "id": row["id"],
            "total_invitations": row["total_invitations"],
            "vip_count": row["vip_count"],
            "normal_count": row["normal_count"],
            "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
            "pdf_url": row["pdf_url"],
            "zip_url": row["zip_url"],
        })

    # Sort combined history items by generated_at date descending
    items.sort(key=lambda x: x["generated_at"] or "", reverse=True)
    if not await _can_download_exports(db, tenant_id, user.id):
        for item in items:
            item["pdf_url"] = None
            item["zip_url"] = None
    return items


@router.get("/history/{event_id}/{operation_id}", response_model=list[InvitationRead])
async def get_generation_operation_details(
    event_id: UUID,
    operation_id: str,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all invitations that belong to a given generation operation (by operation id).

    The operation id is the md5 hash of the concatenated pdf_url and zip_url used in the history grouping,
    the UUID string of a designed batch from generation_batches,
    or the special virtual IDs 'registration_submissions' / 'rsvp_submissions'.
    """
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.view")

    is_uuid = False
    try:
        if len(operation_id) == 36:
            UUID(operation_id)
            is_uuid = True
    except ValueError:
        pass

    if operation_id == "registration_submissions":
        result = await db.execute(
            text("""
                SELECT *
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND is_registration = true
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
                ORDER BY created_at DESC
            """),
            {"eid": str(event_id), "tid": str(tenant_id)},
        )
    elif operation_id == "rsvp_submissions":
        result = await db.execute(
            text("""
                SELECT *
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND (metadata IS NOT NULL AND metadata->>'require_rsvp' = 'true')
                  AND is_registration = false
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
                ORDER BY created_at DESC
            """),
            {"eid": str(event_id), "tid": str(tenant_id)},
        )
    elif is_uuid:
        result = await db.execute(
            text("""
                SELECT i.*
                FROM invitations i
                JOIN batch_items bi ON bi.invitation_id = i.id
                WHERE i.event_id = :eid
                  AND i.tenant_id = :tid
                  AND bi.batch_id = :opid
                  AND (i.metadata IS NULL OR i.metadata->>'generation_deleted' IS DISTINCT FROM 'true')
                ORDER BY i.created_at DESC
            """),
            {"eid": str(event_id), "tid": str(tenant_id), "opid": operation_id},
        )
    else:
        result = await db.execute(
            text("""
                SELECT *
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND md5(COALESCE(pdf_url, '') || '|' || COALESCE(zip_url, '')) = :opid
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
                ORDER BY created_at DESC
            """),
            {"eid": str(event_id), "tid": str(tenant_id), "opid": operation_id},
        )

    rows = result.mappings().all()
    values = await redact_generation_files(db, tenant_id, user.id, rows)
    return [InvitationRead(**row) for row in values]


@router.delete("/history/{event_id}/{operation_id}", response_model=DeleteGenerationResponse)
async def delete_generation_operation(
    event_id: UUID,
    operation_id: str,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete/revoke one fast generation operation or virtual batch with strict precautions."""
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "batches.manage")

    is_uuid = False
    try:
        if len(operation_id) == 36:
            UUID(operation_id)
            is_uuid = True
    except ValueError:
        pass

    # 1. Fetch invitations associated with this operation_id
    if operation_id == "registration_submissions":
        invites_res = await db.execute(
            text("""
                SELECT id, status, checked_in_at, checkin_count, guest_name
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND is_registration = true
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            """),
            {"eid": str(event_id), "tid": str(tenant_id)},
        )
    elif operation_id == "rsvp_submissions":
        invites_res = await db.execute(
            text("""
                SELECT id, status, checked_in_at, checkin_count, guest_name
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND (metadata IS NOT NULL AND metadata->>'require_rsvp' = 'true')
                  AND is_registration = false
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            """),
            {"eid": str(event_id), "tid": str(tenant_id)},
        )
    elif is_uuid:
        invites_res = await db.execute(
            text("""
                SELECT i.id, i.status, i.checked_in_at, i.checkin_count, i.guest_name
                FROM invitations i
                JOIN batch_items bi ON bi.invitation_id = i.id
                WHERE i.event_id = :eid
                  AND i.tenant_id = :tid
                  AND bi.batch_id = :opid
                  AND (i.metadata IS NULL OR i.metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            """),
            {"eid": str(event_id), "tid": str(tenant_id), "opid": operation_id},
        )
    else:
        invites_res = await db.execute(
            text("""
                SELECT id, status, checked_in_at, checkin_count, guest_name
                FROM invitations
                WHERE event_id = :eid
                  AND tenant_id = :tid
                  AND md5(COALESCE(pdf_url, '') || '|' || COALESCE(zip_url, '')) = :opid
                  AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            """),
            {"eid": str(event_id), "tid": str(tenant_id), "opid": operation_id},
        )

    all_invites = [dict(r) for r in invites_res.mappings().all()]
    if not all_invites:
        raise HTTPException(404, "سجل هذه المجموعة غير موجود أو تم إلغاؤه بالفعل")

    # 2. Check for checked-in invitations
    revokable_ids = []
    checked_in_names = []
    for inv in all_invites:
        is_checked_in = (
            inv["status"] == "checked_in"
            or inv["checked_in_at"] is not None
            or (inv["checkin_count"] or 0) > 0
        )
        if is_checked_in:
            checked_in_names.append(inv["guest_name"] or "ضيف")
        else:
            revokable_ids.append(inv["id"])

    total_count = len(all_invites)
    skipped_count = len(checked_in_names)

    if skipped_count == total_count:
        # All invitations are checked in, cannot delete anything!
        names_str = "، ".join(checked_in_names[:5])
        if len(checked_in_names) > 5:
            names_str += f"... وغيرهم ({len(checked_in_names)} ضيف)"
        raise HTTPException(
            400,
            f"لا يمكن إلغاء هذه المجموعة لأن جميع الضيوف قاموا بتسجيل الدخول بالفعل ({names_str})."
        )

    # 3. Soft-delete revokable ones
    deleted_count = 0
    if revokable_ids:
        # We can update in batches or single query using ANY
        await db.execute(
            text("""
                UPDATE invitations SET
                    status = 'revoked',
                    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                        'generation_deleted', true,
                        'generation_deleted_at', now(),
                        'generation_deleted_by', :user_id,
                        'generation_delete_operation_id', :opid
                    ),
                    updated_at = now()
                WHERE id = ANY(:ids)
            """),
            {
                "ids": revokable_ids,
                "user_id": str(user.id),
                "opid": operation_id,
            },
        )
        deleted_count = len(revokable_ids)

    # 4. If it's a designed batch, update batch status to cancelled/deleted
    if is_uuid:
        await db.execute(
            text("""
                UPDATE generation_batches SET
                    status = 'cancelled',
                    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                        'generation_deleted', true,
                        'generation_deleted_at', now(),
                        'generation_deleted_by', :user_id
                    ),
                    updated_at = now()
                WHERE id = :opid AND tenant_id = :tid
            """),
            {
                "opid": operation_id,
                "tid": str(tenant_id),
                "user_id": str(user.id),
            },
        )

    # Log audit
    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="fast_invitations.soft_delete_generation",
        resource_type="event",
        resource_id=str(event_id),
        metadata={
            "operation_id": operation_id,
            "soft_deleted_invitations": deleted_count,
            "skipped_checked_in": skipped_count,
        },
        ip_address=get_client_ip(http_request),
    )
    await db.commit()

    # Formulate safety warning message in Arabic
    if skipped_count > 0:
        names_str = "، ".join(checked_in_names[:3])
        if len(checked_in_names) > 3:
            names_str += f"... وغيرهم ({len(checked_in_names)} ضيف)"
        message = (
            f"تم إلغاء {deleted_count} دعوة بنجاح. "
            f"تم الإبقاء على {skipped_count} دعوة وتخطيها لأنهم قاموا بتسجيل الدخول بالفعل ({names_str})."
        )
    else:
        message = f"تم إلغاء جميع الدعوات في هذه المجموعة بنجاح (عدد {deleted_count} دعوة)."

    return {
        "success": True,
        "deleted_invitations": deleted_count,
        "deleted_files": 0,
        "skipped_checked_in": skipped_count,
        "message": message,
    }


@router.get("/stats/{event_id}")
async def get_generation_stats(
    event_id: UUID,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get generation statistics for an event."""
    tenant_id = get_tenant_id_from_header(http_request)
    await require_permission(db, tenant_id, user.id, "invitations.view")
    
    # Get statistics
    result = await db.execute(
        text("""
            SELECT 
                COUNT(*) as total_invitations,
                COUNT(CASE WHEN qr_data IS NOT NULL THEN 1 END) as generated_barcodes,
                COUNT(CASE WHEN pdf_url IS NOT NULL THEN 1 END) as has_pdf,
                COUNT(CASE WHEN zip_url IS NOT NULL THEN 1 END) as has_zip,
                COUNT(CASE WHEN status = 'sent' THEN 1 END) as sent_count,
                COUNT(CASE WHEN status = 'viewed' THEN 1 END) as viewed_count,
                COUNT(CASE WHEN status = 'accepted' THEN 1 END) as accepted_count,
                COUNT(CASE WHEN ticket_class = 'vip' THEN 1 END) as vip_count,
                COUNT(CASE WHEN ticket_class = 'normal' THEN 1 END) as normal_count,
                MAX(updated_at) as last_generation
            FROM invitations 
            WHERE event_id = :eid AND tenant_id = :tid
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
        """),
        {"eid": str(event_id), "tid": str(tenant_id)}
    )
    
    stats = result.mappings().first()
    
    return {
        "event_id": str(event_id),
        "total_invitations": stats["total_invitations"],
        "generated_barcodes": stats["generated_barcodes"],
        "has_pdf": stats["has_pdf"] > 0,
        "has_zip": stats["has_zip"] > 0,
        "sent_count": stats["sent_count"],
        "viewed_count": stats["viewed_count"],
        "accepted_count": stats["accepted_count"],
        "vip_count": stats["vip_count"],
        "normal_count": stats["normal_count"],
        "last_generation": stats["last_generation"],
        "generation_progress": {
            "barcodes": int((stats["generated_barcodes"] / stats["total_invitations"]) * 100) if stats["total_invitations"] > 0 else 0
        }
    }


# ══════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════

async def _check_event_quota(
    db: AsyncSession, tenant_id: str, event_id: str, invitations_data: List[Dict[str, Any]]
):
    """Legacy wrapper — delegates to centralized quota_service."""
    await check_quota_mixed(db, tenant_id, event_id, invitations_data)


async def _download_image_bytes(url: str) -> Optional[bytes]:
    """Download a bounded image from the configured private storage."""
    try:
        return await storage_service.download_reference(url, max_bytes=10 * 1024 * 1024)
    except Exception:
        logger.warning("Invitation image download failed")
    return None


def _generate_fallback_qr_bytes(token: str, invite_id: str | None = None) -> bytes:
    """Helper to generate fallback QR code image bytes."""
    # This fallback is used only where an invitation id is unavailable.  The
    # historic public URL remains accepted during migration.
    if invite_id:
        payload = barcode_service.build_barcode_payload(invite_id, token)["field_payload"]
    else:
        payload = f"{settings.app_url}/i/{token}"
    return barcode_service.generate_qr_png(payload, size_px=400)


@router.get("/history/{event_id}/registration_submissions/pdf")
async def download_registration_pdf(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user_from_header_or_query),
    db: AsyncSession = Depends(get_db),
):
    """Compile and stream all accepted registration invitations as a PDF."""
    tenant_id = get_tenant_id_from_header_or_query(request)
    await require_permission(db, tenant_id, user.id, "invitations.export")

    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")

    res = await db.execute(
        text("""
            SELECT id, token, guest_name, ticket_class, card_image_url, render_image_url, barcode_png_url
            FROM invitations
            WHERE event_id = :eid
              AND tenant_id = :tid
              AND is_registration = true
              AND status = 'accepted'
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            ORDER BY created_at DESC
        """),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    rows = res.mappings().all()
    if not rows:
        raise HTTPException(404, "لا توجد دعوات تسجيل مقبولة لتنزيلها")

    # Download or generate image for each in parallel
    tasks = []
    for r in rows:
        img_url = r["card_image_url"] or r["render_image_url"] or r["barcode_png_url"]
        if img_url:
            tasks.append(_download_image_bytes(img_url))
        else:
            tasks.append(asyncio.sleep(0, result=None))
    downloaded = await asyncio.gather(*tasks)

    card_images = []
    barcode_items = []
    has_designed = False

    for idx, r in enumerate(rows):
        img_bytes = downloaded[idx]
        if not img_bytes:
            img_bytes = _generate_fallback_qr_bytes(r["token"], str(r["id"]))

        is_designed_card = bool(r["card_image_url"] or r["render_image_url"])
        if is_designed_card:
            has_designed = True
            card_images.append(img_bytes)
        else:
            barcode_items.append({
                "png_bytes": img_bytes,
                "code": r["token"][:8],
                "guest_name": r["guest_name"] or "ضيف",
                "ticket_class": r["ticket_class"]
            })

    if has_designed:
        all_cards = card_images + [item["png_bytes"] for item in barcode_items]
        pdf_bytes = pdf_service.generate_cards_pdf(all_cards, {"card_per_page": True})
    else:
        layout = {
            "page_size": "A4",
            "orientation": "portrait",
            "rows": 5,
            "cols": 5,
            "margin_top_mm": 10,
            "margin_bottom_mm": 10,
            "margin_left_mm": 10,
            "margin_right_mm": 10,
            "gap_x_mm": 2,
            "gap_y_mm": 2,
            "show_code_text": False,
            "show_guest_name": True,
        }
        pdf_bytes = pdf_service.generate_barcode_grid_pdf(barcode_items, layout)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=registration_invitations_{event_id}.pdf"
        }
    )


@router.get("/history/{event_id}/registration_submissions/zip")
async def download_registration_zip(
    event_id: UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user_from_header_or_query),
    db: AsyncSession = Depends(get_db),
):
    """Compile and stream all accepted registration invitations as a ZIP archive."""
    tenant_id = get_tenant_id_from_header_or_query(request)
    await require_permission(db, tenant_id, user.id, "invitations.export")

    from app.services.feature_service import require_feature
    await require_feature(db, tenant_id, "pdf_export")

    res = await db.execute(
        text("""
            SELECT id, token, guest_name, ticket_class, card_image_url, render_image_url, barcode_png_url
            FROM invitations
            WHERE event_id = :eid
              AND tenant_id = :tid
              AND is_registration = true
              AND status = 'accepted'
              AND (metadata IS NULL OR metadata->>'generation_deleted' IS DISTINCT FROM 'true')
            ORDER BY created_at DESC
        """),
        {"eid": str(event_id), "tid": str(tenant_id)},
    )
    rows = res.mappings().all()
    if not rows:
        raise HTTPException(404, "لا توجد دعوات تسجيل مقبولة لتنزيلها")

    # Download in parallel
    tasks = []
    for r in rows:
        img_url = r["card_image_url"] or r["render_image_url"] or r["barcode_png_url"]
        if img_url:
            tasks.append(_download_image_bytes(img_url))
        else:
            tasks.append(asyncio.sleep(0, result=None))
    downloaded = await asyncio.gather(*tasks)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for idx, r in enumerate(rows):
            img_bytes = downloaded[idx]
            if not img_bytes:
                img_bytes = _generate_fallback_qr_bytes(r["token"], str(r["id"]))
            
            guest_name = r["guest_name"] or f"Guest_{idx+1}"
            safe_name = "".join(c for c in guest_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"{idx+1:04d}__{safe_name[:50]}.png"
            zf.writestr(filename, img_bytes)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=registration_invitations_{event_id}.zip"
        }
    )
