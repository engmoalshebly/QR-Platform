"""
PDF Generation Service.
Creates PDF documents with barcode grids or designed invitation cards.

Supports:
- Grid layout (NxM barcodes per page) for QUICK mode
- One card per page for DESIGNED mode
- A4, Letter, and custom page sizes
- Code text and guest name labels under barcodes
- High DPI for print quality
"""
import io
import logging
import math
import threading
from pathlib import Path
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from typing import Optional

from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)

_FONT_LOCK = threading.Lock()

def _guest_label(name: str, width: float) -> str:
    with _FONT_LOCK:
        if "InvitationArabic" not in pdfmetrics.getRegisteredFontNames():
            path = Path(__file__).resolve().parents[1] / "assets/fonts/Amiri-Regular.ttf"
            if not path.exists():
                path = Path(__file__).resolve().parents[2] / "fonts/Amiri-Regular.ttf"
            pdfmetrics.registerFont(TTFont("InvitationArabic", str(path)))
    logical = str(name)
    while logical:
        label = get_display(arabic_reshaper.reshape(logical))
        if pdfmetrics.stringWidth(label, "InvitationArabic", 8) <= width:
            return label
        logical = logical[:-1]
    return ""

# Page size map
PAGE_SIZES = {
    "A4": A4,
    "a4": A4,
    "Letter": letter,
    "letter": letter,
}


def _get_page_size(layout: dict) -> tuple[float, float]:
    """Get page dimensions from layout config."""
    page_size_name = layout.get("page_size", "A4")

    if page_size_name.lower() == "custom":
        w = float(layout.get("custom_width_mm", 210)) * mm
        h = float(layout.get("custom_height_mm", 297)) * mm
    else:
        w, h = PAGE_SIZES.get(page_size_name, A4)

    if layout.get("orientation", "portrait") == "landscape":
        w, h = h, w

    return w, h


def generate_barcode_grid_pdf(
    barcode_images: list[dict],
    layout: dict,
) -> bytes:
    """
    Generate a PDF with barcodes arranged in a grid.

    Args:
        barcode_images: List of dicts with:
            - png_bytes: PNG image bytes of the barcode
            - code: Short code text (optional)
            - guest_name: Guest name (optional)
        layout: Layout config dict with grid settings

    Returns:
        PDF bytes
    """
    page_w, page_h = _get_page_size(layout)

    rows = int(layout.get("rows", 5))
    cols = int(layout.get("cols", 5))
    margin_top = float(layout.get("margin_top_mm", 10)) * mm
    margin_bottom = float(layout.get("margin_bottom_mm", 10)) * mm
    margin_left = float(layout.get("margin_left_mm", 10)) * mm
    margin_right = float(layout.get("margin_right_mm", 10)) * mm
    gap_x = float(layout.get("gap_x_mm", 2)) * mm
    gap_y = float(layout.get("gap_y_mm", 2)) * mm
    show_code = layout.get("show_code_text", True)
    show_name = layout.get("show_guest_name", True)

    # Calculate cell dimensions
    usable_w = page_w - margin_left - margin_right
    usable_h = page_h - margin_top - margin_bottom
    cell_w = (usable_w - (cols - 1) * gap_x) / cols
    cell_h = (usable_h - (rows - 1) * gap_y) / rows

    # Text space below barcode
    text_space = 0
    if show_code:
        text_space += 10
    if show_name:
        text_space += 10

    items_per_page = rows * cols
    total_pages = math.ceil(len(barcode_images) / items_per_page) if barcode_images else 1

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))

    for page_idx in range(total_pages):
        if page_idx > 0:
            c.showPage()

        start = page_idx * items_per_page
        page_items = barcode_images[start:start + items_per_page]

        for idx, item in enumerate(page_items):
            row = idx // cols
            col = idx % cols

            # Cell position (top-left, ReportLab origin is bottom-left)
            cx = margin_left + col * (cell_w + gap_x)
            cy = page_h - margin_top - row * (cell_h + gap_y) - cell_h

            # Draw barcode image centered in cell
            png_bytes = item.get("png_bytes")
            if png_bytes:
                img = ImageReader(io.BytesIO(png_bytes))
                img_w = cell_w
                img_h = cell_h - text_space

                # Maintain aspect ratio
                aspect = 1.0
                iw, ih = img.getSize()
                if iw > 0 and ih > 0:
                    aspect = iw / ih

                if img_w / img_h > aspect:
                    draw_w = img_h * aspect
                    draw_h = img_h
                else:
                    draw_w = img_w
                    draw_h = img_w / aspect

                # Center in cell
                draw_x = cx + (cell_w - draw_w) / 2
                draw_y = cy + text_space + (img_h - draw_h) / 2

                c.drawImage(img, draw_x, draw_y, draw_w, draw_h, preserveAspectRatio=True)

            # Draw code text
            text_y = cy
            c.setFont("Helvetica", 6)

            if show_name and item.get("guest_name"):
                name = _guest_label(item["guest_name"], cell_w - 4)
                c.setFont("InvitationArabic", 8)
                text_w = c.stringWidth(name, "InvitationArabic", 8)
                c.drawString(cx + (cell_w - text_w) / 2, text_y + 2, name)
                text_y += 10

            if show_code and item.get("code"):
                c.setFont("Helvetica", 6)
                code = item["code"]
                text_w = c.stringWidth(code, "Helvetica", 6)
                c.drawString(cx + (cell_w - text_w) / 2, text_y + 2, code)

    c.save()
    return buf.getvalue()


def generate_cards_pdf(
    card_images: list[bytes],
    layout: dict,
) -> bytes:
    """
    Generate a PDF with one designed card per page (or grid of cards).

    Args:
        card_images: List of PNG bytes for each rendered card
        layout: Layout config dict

    Returns:
        PDF bytes
    """
    card_per_page = layout.get("card_per_page", True)

    if card_per_page:
        return _generate_one_per_page(card_images, layout)
    else:
        # Convert to barcode_images format and use grid
        items = [{"png_bytes": img} for img in card_images]
        return generate_barcode_grid_pdf(items, layout)


def _generate_one_per_page(card_images: list[bytes], layout: dict) -> bytes:
    """One card per page, centered, maintaining aspect ratio."""
    page_w, page_h = _get_page_size(layout)
    margin_top = float(layout.get("margin_top_mm", 0)) * mm
    margin_bottom = float(layout.get("margin_bottom_mm", 0)) * mm
    margin_left = float(layout.get("margin_left_mm", 0)) * mm
    margin_right = float(layout.get("margin_right_mm", 0)) * mm

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))

    for idx, img_bytes in enumerate(card_images):
        if idx > 0:
            c.showPage()

        img = ImageReader(io.BytesIO(img_bytes))
        iw, ih = img.getSize()

        # Scale to fit page with margins
        max_w = page_w - margin_left - margin_right
        max_h = page_h - margin_top - margin_bottom

        scale = min(max_w / iw, max_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale

        # Center on page
        draw_x = margin_left + (max_w - draw_w) / 2
        draw_y = margin_bottom + (max_h - draw_h) / 2

        c.drawImage(img, draw_x, draw_y, draw_w, draw_h, preserveAspectRatio=True)

    c.save()
    return buf.getvalue()
