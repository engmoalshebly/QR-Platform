"""Pydantic models for Generation Batches pipeline.

Guest Data Policy (snapshot):
    When an invitation is created, guest_name/phone/email are copied
    from the guest record at creation time. If the guest record changes
    later, existing invitations are NOT updated. This is intentional:
    the invitation represents a point-in-time snapshot for audit and
    print accuracy.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class BatchStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    generating_barcodes = "generating_barcodes"
    rendering_images = "rendering_images"
    generating_pdf = "generating_pdf"
    generating_zip = "generating_zip"
    ready = "ready"
    failed = "failed"
    cancelled = "cancelled"


# ── Layout Config (PDF grid settings) ──

# Page sizes in mm (width, height) for portrait orientation
PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
}


def mm_to_px(mm: float, dpi: int = 300) -> int:
    """Convert millimeters to pixels: px = (mm / 25.4) * dpi"""
    return int((mm / 25.4) * dpi)


def px_to_mm(px: int, dpi: int = 300) -> float:
    """Convert pixels to millimeters: mm = (px * 25.4) / dpi"""
    return round((px * 25.4) / dpi, 2)


class LayoutConfig(BaseModel):
    """PDF layout configuration with full validation.

    Mode defaults:
      - quick mode  → grid N×M barcodes per page (card_per_page=False)
      - designed mode → 1 card per page (card_per_page=True)

    Unit conversion:
      px = (mm / 25.4) * dpi
      mm = (px * 25.4) / dpi

    If barcode_size_px is None, it is auto-calculated from cell size.
    """
    page_size: str = Field("A4", pattern=r"^(A4|Letter|custom)$")
    orientation: str = Field("portrait", pattern=r"^(portrait|landscape)$")
    rows: int = Field(5, ge=1, le=20)
    cols: int = Field(5, ge=1, le=20)
    margin_top_mm: float = Field(10, ge=0, le=100)
    margin_bottom_mm: float = Field(10, ge=0, le=100)
    margin_left_mm: float = Field(10, ge=0, le=100)
    margin_right_mm: float = Field(10, ge=0, le=100)
    gap_x_mm: float = Field(2, ge=0, le=50)
    gap_y_mm: float = Field(2, ge=0, le=50)
    barcode_size_px: Optional[int] = Field(None, ge=100, le=2000)  # None = auto from cell
    barcode_size_mode: str = Field("fit", pattern=r"^(fit|contain)$")  # fit=stretch, contain=aspect
    show_code_text: bool = True
    show_guest_name: bool = True
    caption_field: str = Field("guest_name", pattern=r"^(guest_name|code|none)$")  # label under barcode
    dpi: int = Field(300, ge=72, le=600)
    card_per_page: bool = False              # true = 1 card per page (designed)
    custom_width_mm: Optional[float] = Field(None, ge=50, le=1000)
    custom_height_mm: Optional[float] = Field(None, ge=50, le=1000)
    barcode_render: str = Field("png", pattern=r"^(svg|png)$")  # format in ZIP
    cell_padding_mm: float = Field(1, ge=0, le=20)

    @model_validator(mode="before")
    @classmethod
    def validate_custom_size(cls, values):
        """Require custom dimensions when page_size is 'custom'."""
        if isinstance(values, dict):
            if values.get("page_size") == "custom":
                if not values.get("custom_width_mm") or not values.get("custom_height_mm"):
                    raise ValueError("custom_width_mm and custom_height_mm are required when page_size is 'custom'")
        return values

    @model_validator(mode="after")
    def validate_usable_grid(self):
        width, height = PAGE_SIZES_MM.get(self.page_size, (210.0, 297.0))
        if self.page_size == "custom":
            width, height = self.custom_width_mm, self.custom_height_mm
        if self.orientation == "landscape":
            width, height = height, width
        cell_width = (width - self.margin_left_mm - self.margin_right_mm - self.gap_x_mm * (self.cols - 1)) / self.cols
        cell_height = (height - self.margin_top_mm - self.margin_bottom_mm - self.gap_y_mm * (self.rows - 1)) / self.rows
        label_mm = (int(self.show_code_text) + int(self.show_guest_name)) * 10 / (72 / 25.4)
        if cell_width <= self.cell_padding_mm * 2 or cell_height <= self.cell_padding_mm * 2 + label_mm:
            raise ValueError("الهوامش والمسافات وعدد الصفوف لا تترك مساحة صالحة للرموز والنصوص")
        return self

    @property
    def resolved_barcode_size_px(self) -> int:
        """Return barcode_size_px, or auto-calculate from cell size if None."""
        if self.barcode_size_px is not None:
            return self.barcode_size_px
        # Auto-calculate from available cell width
        page_w, _ = PAGE_SIZES_MM.get(self.page_size, (210.0, 297.0))
        if self.page_size == "custom" and self.custom_width_mm:
            page_w = self.custom_width_mm
        if self.orientation == "landscape":
            page_w, _ = _, page_w  # swap
            if self.page_size == "custom" and self.custom_height_mm:
                page_w = self.custom_height_mm
        usable_w = page_w - self.margin_left_mm - self.margin_right_mm - (self.gap_x_mm * (self.cols - 1))
        cell_w_mm = (usable_w / self.cols) - (self.cell_padding_mm * 2)
        return max(100, mm_to_px(cell_w_mm, self.dpi))


# ── Batch Create ──

class BatchCreate(BaseModel):
    event_id: UUID
    template_id: Optional[UUID] = None
    mode: str = Field("quick", pattern="^(quick|designed)$")                      # quick / designed
    ticket_class: str = Field("normal", pattern="^(normal|vip)$")             # vip / normal
    output_formats: list[str] = Field(default=["pdf", "zip"])
    barcode_format: str = "qr"               # qr, barcode128
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    invitation_ids: Optional[list[UUID]] = None  # specific invitations, or all for event
    metadata: Optional[dict] = None


# ── Batch Read ──

class BatchRead(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: UUID
    template_id: Optional[UUID] = None
    mode: str
    ticket_class: str
    count_total: int
    count_done: int
    count_failed: int
    layout_json: Optional[dict] = None
    output_formats: list[str] = []
    barcode_format: str = "qr"
    status: str
    progress: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_pdf_url: Optional[str] = None
    result_zip_url: Optional[str] = None
    result_preview_urls: list[str] = []
    duration_ms: Optional[int] = None
    result_pdf_size: Optional[int] = None
    result_zip_size: Optional[int] = None
    error_summary: Optional[dict] = None
    created_by: Optional[UUID] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


# ── Batch Item Read ──

class BatchItemRead(BaseModel):
    id: UUID
    batch_id: UUID
    invitation_id: UUID
    render_status: str
    error_message: Optional[str] = None
    barcode_url: Optional[str] = None
    render_url: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


# ── Batch Summary (for list view) ──

class BatchSummary(BaseModel):
    id: UUID
    event_id: UUID
    mode: str
    ticket_class: str
    count_total: int
    count_done: int
    count_failed: int
    status: str
    progress: int
    result_pdf_url: Optional[str] = None
    result_zip_url: Optional[str] = None
    created_at: datetime
