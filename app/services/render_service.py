"""
Render Service: Compose designed invitation images.
Takes a template (background + elements with relative coordinates)
and renders a final PNG image for each invitation.

Supports:
- Arabic RTL text with proper shaping (arabic-reshaper + python-bidi)
- Multiple QR/barcode elements
- Multiple text elements (guest_name, event_title, dates, custom)
- Auto-fit text within bounding box
- Relative coordinates (0→1) for responsive rendering
"""
import io
from contextvars import ContextVar
from contextlib import contextmanager
import base64
import logging
import os
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
import arabic_reshaper.letters as reshaper_letters
from bidi.algorithm import get_display

from app.services.barcode_service import generate_qr_png, generate_code128_png

logger = logging.getLogger(__name__)
MAX_SOURCE_IMAGE_PIXELS = 40_000_000

# Per-job pinned fonts propagate through asyncio.to_thread, without replacing
# global font discovery or sharing customer fonts between concurrent jobs.
_snapshot_fonts = ContextVar('generation_snapshot_fonts', default=None)

@contextmanager
def pinned_fonts(fonts):
    token = _snapshot_fonts.set(fonts)
    try:
        yield
    finally:
        _snapshot_fonts.reset(token)

# Font cache to avoid reloading
_font_cache: dict[str, ImageFont.FreeTypeFont] = {}

# Default font paths (Cairo for Arabic)
_DEFAULT_FONT_PATHS = {
    "Cairo": "fonts/Cairo-Regular.ttf",
    "Cairo-Bold": "fonts/Cairo-Bold.ttf",
    "Tajawal": "fonts/Tajawal-Regular.ttf",
    "Tajawal-Bold": "fonts/Tajawal-Bold.ttf",
    "Amiri": "fonts/Amiri-Regular.ttf",
    "Amiri-Bold": "fonts/Amiri-Bold.ttf",
    "Noto": "fonts/NotoSansArabic-Regular.ttf",
    "Noto-Bold": "fonts/NotoSansArabic-Bold.ttf",
    "NotoSansArabic": "fonts/NotoSansArabic-Regular.ttf",
    "NotoSansArabic-Bold": "fonts/NotoSansArabic-Bold.ttf",
    "Almarai": "fonts/Almarai-Regular.ttf",
    "Almarai-Bold": "fonts/Almarai-Bold.ttf",
    "Alexandria": "fonts/Alexandria-Regular.ttf",
    "Alexandria-Bold": "fonts/Alexandria-Bold.ttf",
    "ElMessiri": "fonts/ElMessiri-Regular.ttf",
    "ElMessiri-Bold": "fonts/ElMessiri-Bold.ttf",
    "ReemKufi": "fonts/ReemKufi-Regular.ttf",
    "ReemKufi-Bold": "fonts/ReemKufi-Bold.ttf",
    "Changa": "fonts/Changa-Regular.ttf",
    "Changa-Bold": "fonts/Changa-Bold.ttf",
}


def discover_fonts() -> dict[str, str]:
    """Scan the fonts/ directory dynamically to map all font paths on the fly."""
    font_paths = _DEFAULT_FONT_PATHS.copy()
    fonts_dir = "fonts"
    if not os.path.exists(fonts_dir):
        return font_paths

    try:
        for file in os.listdir(fonts_dir):
            if file.lower().endswith((".ttf", ".otf")):
                name_without_ext = os.path.splitext(file)[0]
                path = os.path.join(fonts_dir, file)
                
                # Register the exact name
                font_paths[name_without_ext] = path
                
                # Check for Regular / Bold suffixes
                if name_without_ext.endswith("-Bold"):
                    family = name_without_ext[:-5]
                    font_paths[family + "-Bold"] = path
                elif name_without_ext.endswith("-Regular"):
                    family = name_without_ext[:-8]
                    font_paths[family] = path
                    font_paths[family + "-Regular"] = path
                else:
                    # e.g., JannaLT
                    font_paths[name_without_ext] = path
    except Exception as e:
        logger.error(f"Error discovering dynamic fonts: {e}")

    return font_paths


FALLBACK_FONT = None  # Will use PIL default


def _get_font(family: str = "Cairo", size: float = 24, weight: str = "normal") -> ImageFont.FreeTypeFont:
    """Load a font with caching. Falls back to default if not found."""
    pinned = _snapshot_fonts.get()
    if pinned is not None:
        content = pinned.get(f'{family}:{weight}')
        if content is None:
            raise ValueError('Missing immutable font')
        return ImageFont.truetype(io.BytesIO(content), max(1, int(size)))
    key = f"{family}-{weight}"
    if weight == "bold":
        key = f"{family}-Bold"
    elif weight in ("normal", "regular"):
        key = f"{family}-Regular"

    cache_key = f"{key}:{int(size)}"
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    font_paths = discover_fonts()
    font_path = font_paths.get(key) or font_paths.get(family)
    
    # Try case-insensitive lookup
    if not font_path:
        key_lower = key.lower()
        family_lower = family.lower()
        for k, p in font_paths.items():
            if k.lower() == key_lower or k.lower() == family_lower:
                font_path = p
                break
    try:
        if font_path:
            font = ImageFont.truetype(font_path, int(size))
        else:
            # Fallback to Cairo (full Arabic coverage) before arial
            font = ImageFont.truetype("fonts/Cairo-Regular.ttf", int(size))
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("fonts/Cairo-Regular.ttf", int(size))
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("arial.ttf", int(size))
            except (OSError, IOError):
                font = ImageFont.load_default()

    _font_cache[cache_key] = font
    return font


# Build a translation mapping from isolated presentation forms to their unshaped equivalents.
# This prevents modern web fonts (like Cairo/Tajawal) that lack glyph mappings for the
# Unicode isolated presentation forms block from rendering them as tofu boxes.
_ISOLATED_TO_STANDARD = {}
for _unshaped, _forms in reshaper_letters.LETTERS_ARABIC.items():
    _isolated = _forms[reshaper_letters.ISOLATED]
    if _isolated:
        _ISOLATED_TO_STANDARD[_isolated] = _unshaped

if hasattr(reshaper_letters, 'LETTERS_ARABIC_V2'):
    for _unshaped, _forms in reshaper_letters.LETTERS_ARABIC_V2.items():
        _isolated = _forms[reshaper_letters.ISOLATED]
        if _isolated:
            _ISOLATED_TO_STANDARD[_isolated] = _unshaped


def _reshape_arabic(text: str) -> str:
    """Reshape Arabic text for proper display (connected letters + RTL)."""
    if not text:
        return ""
    try:
        reshaped = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped)
        # Clean up isolated forms to avoid tofu boxes in modern web fonts
        return "".join(_ISOLATED_TO_STANDARD.get(char, char) for char in bidi_text)
    except Exception:
        return text

def _get_text_line_width_with_spacing(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    letter_spacing_px: float
) -> int:
    # Check if text contains Arabic characters
    has_arabic = any(u'\u0600' <= char <= u'\u06FF' or u'\u0750' <= char <= u'\u077F' or u'\u08A0' <= char <= u'\u08FF' or u'\uFB50' <= char <= u'\uFDFF' or u'\uFE70' <= char <= u'\uFEFF' for char in text)
    if letter_spacing_px == 0 or has_arabic:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    else:
        width = 0
        for i, char in enumerate(text):
            width += draw.textlength(char, font=font)
            if i < len(text) - 1:
                width += letter_spacing_px
        return int(width)


def _draw_text_line_with_spacing(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    letter_spacing_px: float
):
    x, y = xy
    has_arabic = any(u'\u0600' <= char <= u'\u06FF' or u'\u0750' <= char <= u'\u077F' or u'\u08A0' <= char <= u'\u08FF' or u'\uFB50' <= char <= u'\uFDFF' or u'\uFE70' <= char <= u'\uFEFF' for char in text)
    if letter_spacing_px == 0 or has_arabic:
        draw.text((x, y), text, font=font, fill=fill)
    else:
        for char in text:
            draw.text((x, y), char, font=font, fill=fill)
            char_w = draw.textlength(char, font=font)
            x += char_w + letter_spacing_px


def _measure_text_dimensions(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    line_height: float,
    letter_spacing: float
) -> tuple[int, int]:
    lines = text.split("\n")
    widths = []
    for line in lines:
        w = _get_text_line_width_with_spacing(draw, line, font, letter_spacing)
        widths.append(w)
    max_w = max(widths) if widths else 0

    bbox_single = draw.textbbox((0, 0), "Hgالاسم", font=font)
    single_line_h = bbox_single[3] - bbox_single[1]

    if len(lines) <= 1:
        total_h = single_line_h
    else:
        total_h = int(single_line_h + (len(lines) - 1) * single_line_h * line_height)

    return max_w, total_h


def _auto_fit_text(
    draw: ImageDraw.ImageDraw,
    display_text: str,
    box_width: int,
    box_height: int,
    font_family: str,
    font_weight: str,
    max_font_size: float,
    min_font_size: float = 12.0,
    line_height: float = 1.2,
    letter_spacing: float = 0.0
) -> tuple[ImageFont.FreeTypeFont, str]:
    # Strategy 1: single-line shrink
    for size in range(int(max_font_size), int(min_font_size) - 1, -1):
        font = _get_font(font_family, size, font_weight)
        text_w, text_h = _measure_text_dimensions(draw, display_text, font, line_height, letter_spacing)
        if text_w <= box_width and text_h <= box_height:
            return font, display_text

    # Strategy 2: word-wrap into 2 lines at min font size
    font = _get_font(font_family, min_font_size, font_weight)
    words = display_text.split()
    if len(words) >= 2:
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        wrapped = f"{line1}\n{line2}"
        text_w, text_h = _measure_text_dimensions(draw, wrapped, font, line_height, letter_spacing)
        if text_w <= box_width and text_h <= box_height:
            return font, wrapped

    # Strategy 3: truncate with ellipsis
    for end in range(len(display_text) - 1, 0, -1):
        truncated = display_text[:end] + "…"
        text_w, text_h = _measure_text_dimensions(draw, truncated, font, line_height, letter_spacing)
        if text_w <= box_width:
            return font, truncated

    return font, display_text


def _resolve_data_key(data_key: str, context: dict) -> str:
    """
    Resolve a data_key like 'guest.name' or 'event.title' from context.
    Supports nested keys via dot notation including custom_fields.
    """
    parts = data_key.split(".")
    value = context
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            return ""
    return str(value) if value else ""


def _resolve_dynamic_text(data_key: str, context: dict) -> str:
    """
    Professional multi-strategy resolver for dynamic text elements.

    The design editor lets users type arbitrary labels as data_key values.
    This resolver uses a 4-phase strategy to find the matching value:

      Phase 1: Exact dot-notation path (e.g. "guest.name" → context["guest"]["name"])
      Phase 2: Well-known aliases for core fields (Arabic + English synonyms)
      Phase 3: Deep recursive search across the entire context tree
      Phase 4: Case-insensitive fuzzy match in custom fields

    This makes rendering fully dynamic — any Excel column name the user adds
    to the template will be found automatically without code changes.
    """
    if not data_key:
        return ""

    key_norm = data_key.strip().lower()

    # ── Phase 1: Exact dot-notation path ──
    if "." in data_key:
        val = _resolve_data_key(data_key, context)
        if val:
            return val

    # ── Phase 2: Well-known aliases for core structured fields ──
    # These map user-facing labels to the canonical nested context paths.
    _ALIAS_MAP: dict[frozenset[str], tuple[list[tuple[str, str]], str]] = {}

    # guest_name_aliases → (search paths, fallback)
    _GUEST_NAME_KEYS = frozenset({
        'guest.name', 'guest.name_ar', 'guest_name', 'name',
        'الاسم', 'اسم الضيف', 'guestname', 'اسم_الضيف',
    })
    _EVENT_TITLE_KEYS = frozenset({
        'event.title', 'event.title_ar', 'event_title', 'title',
        'العنوان', 'اسم الفعالية', 'اسم_الفعالية', 'عنوان الفعالية',
    })
    _EVENT_DATE_KEYS = frozenset({
        'event.date', 'event_date', 'date',
        'التاريخ', 'تاريخ', 'eventdate',
        'تاريخ الفعالية', 'تاريخ_الفعالية',
    })
    _EVENT_TIME_KEYS = frozenset({
        'event.time', 'event_time', 'time',
        'الوقت', 'وقت', 'eventtime',
        'وقت الفعالية', 'وقت_الفعالية',
    })
    _EVENT_LOC_KEYS = frozenset({
        'event.location', 'event.location_ar', 'event_location',
        'location', 'المكان', 'الموقع', 'venue',
    })
    _SEAT_KEYS = frozenset({
        'custom.seat', 'seat_number', 'seat',
        'رقم المقعد', 'المقعد', 'seatnumber', 'رقم_المقعد',
    })
    _GATE_KEYS = frozenset({
        'custom.gate', 'gate', 'البوابة', 'بوابة', 'gatenumber',
    })
    _HALL_KEYS = frozenset({
        'custom.hall', 'hall', 'القاعة', 'قاعة', 'hallname',
    })
    _TABLE_KEYS = frozenset({
        'custom.table', 'table_number', 'table',
        'الطاولة', 'رقم الطاولة', 'tablenumber', 'رقم_الطاولة',
    })
    _INVITE_CODE_KEYS = frozenset({
        'invite.code', 'code', 'الكود', 'كود', 'رقم الدعوة',
    })
    _GUEST_COUNT_KEYS = frozenset({
        'invite.guest_count', 'guest_count', 'عدد الأشخاص',
        'عدد الدعوات', 'count', 'invitation_count',
    })

    # Check aliases and resolve from canonical paths
    if key_norm in _GUEST_NAME_KEYS:
        return (
            context.get("guest", {}).get("name")
            or context.get("guest", {}).get("name_ar")
            or ""
        )
    if key_norm in _EVENT_TITLE_KEYS:
        return (
            context.get("event", {}).get("title")
            or context.get("event", {}).get("title_ar")
            or ""
        )
    if key_norm in _EVENT_DATE_KEYS:
        return (
            context.get("event", {}).get("date")
            or context.get("guest", {}).get("date_value")
            or ""
        )
    if key_norm in _EVENT_TIME_KEYS:
        return context.get("event", {}).get("time") or ""
    if key_norm in _EVENT_LOC_KEYS:
        return (
            context.get("event", {}).get("location")
            or context.get("event", {}).get("location_ar")
            or context.get("event", {}).get("venue_address")
            or ""
        )
    _EVENT_ADDR_KEYS = frozenset({
        'event.address', 'event_address', 'address',
        'العنوان', 'عنوان', 'venue_address', 'عنوان المكان',
    })
    if key_norm in _EVENT_ADDR_KEYS:
        return context.get("event", {}).get("venue_address") or ""
    if key_norm in _SEAT_KEYS:
        return str(context.get("custom", {}).get("seat") or "")
    if key_norm in _GATE_KEYS:
        return str(context.get("custom", {}).get("gate") or "")
    if key_norm in _HALL_KEYS:
        return str(context.get("custom", {}).get("hall") or "")
    if key_norm in _TABLE_KEYS:
        return str(context.get("custom", {}).get("table") or "")
    if key_norm in _INVITE_CODE_KEYS:
        return str(context.get("invite", {}).get("code") or "")
    if key_norm in _GUEST_COUNT_KEYS:
        val = context.get("invite", {}).get("guest_count")
        return str(val) if val else ""

    # ── Phase 3: Deep recursive search across entire context tree ──
    # This is what makes it truly dynamic: any Excel column name the user
    # added (e.g. "الشركة", "company", "الجنسية", "nationality") will be
    # found anywhere in the nested context dict automatically.
    found = _deep_search(key_norm, context)
    if found is not None:
        return str(found)

    # ── Phase 4: Dot-notation fallback for unknown paths ──
    if "." not in data_key:
        # Try as dot-notation with common prefixes
        for prefix in ("guest", "event", "invite", "custom"):
            val = _resolve_data_key(f"{prefix}.{data_key}", context)
            if val:
                return val

    logger.debug("Dynamic text key '%s' not resolved in context keys: %s",
                 data_key, list(context.keys()))
    return ""


def _deep_search(key_norm: str, obj: dict, _depth: int = 0) -> object | None:
    """
    Recursively search a nested dict for a key matching key_norm.

    Searches breadth-first: checks all keys at the current level first,
    then recurses into nested dicts. This ensures that top-level custom
    fields (most likely to be user-intended) are found before deeply
    nested ones. Max depth of 4 prevents infinite loops.
    """
    if _depth > 4 or not isinstance(obj, dict):
        return None

    # Level 1: exact match (case-insensitive)
    for k, v in obj.items():
        if k.strip().lower() == key_norm and v not in (None, "", {}, []):
            return v

    # Level 2: recurse into nested dicts
    for k, v in obj.items():
        if isinstance(v, dict):
            found = _deep_search(key_norm, v, _depth + 1)
            if found is not None:
                return found

    return None


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_value_by_type(value: str, format_type: str) -> str:
    import datetime
    if not value:
        return ""
    
    value_str = str(value).strip()
    
    if format_type == "date":
        # Format date
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                clean_val = value_str
                if clean_val.endswith("Z"):
                    clean_val = clean_val[:-1] + "+00:00"
                dt = datetime.datetime.strptime(clean_val, fmt)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue
        # Try to parse as Excel date serial number if it's purely numeric
        if value_str.isdigit() or (value_str.replace('.', '', 1).isdigit() and value_str.count('.') <= 1):
            try:
                days = int(float(value_str))
                # Excel base date is 1899-12-30 due to 1900 leap year bug
                base_date = datetime.datetime(1899, 12, 30)
                dt = base_date + datetime.timedelta(days=days)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
                
    elif format_type == "time":
        # Format time
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%H:%M:%S",
            "%H:%M",
        ):
            try:
                clean_val = value_str
                if clean_val.endswith("Z"):
                    clean_val = clean_val[:-1] + "+00:00"
                if "T" in clean_val or "-" in clean_val:
                    dt = datetime.datetime.strptime(clean_val, fmt)
                else:
                    dt = datetime.datetime.strptime(clean_val, fmt)
                return dt.strftime("%I:%M %p").lstrip('0')
            except Exception:
                continue
                
    elif format_type == "number":
        try:
            val_float = float(value_str)
            if val_float.is_integer():
                return str(int(val_float))
            return f"{val_float:.2f}".rstrip('0').rstrip('.')
        except ValueError:
            pass
            
    return value_str


def _element_box_px(elem: dict, canvas_width: int, canvas_height: int) -> tuple[int, int, int, int]:
    """
    Convert a stored relative design box into exact canvas pixels.

    The editor stores x/y as the top-left corner of the element in relative
    coordinates (0→1). We convert directly to pixel values without any
    mirroring — text direction (RTL/LTR) only affects text alignment within
    the bounding box, not the box position itself.
    """
    x_rel = _to_float(elem.get("x"), 0.5)
    y_rel = _to_float(elem.get("y"), 0.5)
    width_rel = _to_float(elem.get("width"), 0.2)
    height_rel = _to_float(elem.get("height"), 0.05)

    left = round(x_rel * canvas_width)
    top = round(y_rel * canvas_height)
    width = round(width_rel * canvas_width)
    height = round(height_rel * canvas_height)

    left = max(0, min(canvas_width - 1, left))
    top = max(0, min(canvas_height - 1, top))
    width = max(1, min(width, canvas_width - left))
    height = max(1, min(height, canvas_height - top))
    return left, top, width, height


def _qr_box_px(elem: dict, canvas_width: int, canvas_height: int) -> tuple[int, int, int]:
    """
    Resolve the QR square from the saved design box.

    The editor stores QR elements as a square side represented by two relative
    dimensions: width/canvas_width and height/canvas_height. The renderer keeps
    that contract exactly and never moves or auto-enlarges the slot.
    """
    left, top, width, height = _element_box_px(elem, canvas_width, canvas_height)
    side = min(width, canvas_width - left, canvas_height - top)
    return left, top, max(1, side)


def prepare_background_canvas(
    background_bytes: bytes,
    canvas_width: int,
    canvas_height: int,
    background_transform: Optional[dict] = None,
) -> Image.Image:
    """Create a reusable background canvas for designed invitation rendering."""
    with Image.open(io.BytesIO(background_bytes)) as source_background:
        if source_background.width * source_background.height > MAX_SOURCE_IMAGE_PIXELS:
            raise ValueError("Background image dimensions exceed limit")
        bg = source_background.convert("RGBA")
    transform = background_transform or {}
    fit_mode = str(transform.get("fit_mode") or transform.get("fitMode") or "contain")
    scale = float(transform.get("scale") or 1)
    offset_x = float(transform.get("offset_x") or transform.get("offsetX") or 0)
    offset_y = float(transform.get("offset_y") or transform.get("offsetY") or 0)

    canvas = Image.new("RGBA", (canvas_width, canvas_height), "#ffffff")

    bg_ratio = bg.width / bg.height if bg.height else 1
    canvas_ratio = canvas_width / canvas_height if canvas_height else 1
    if fit_mode == "cover":
        if bg_ratio > canvas_ratio:
            target_h = canvas_height
            target_w = int(target_h * bg_ratio)
        else:
            target_w = canvas_width
            target_h = int(target_w / bg_ratio)
    else:
        if bg_ratio > canvas_ratio:
            target_w = canvas_width
            target_h = int(target_w / bg_ratio)
        else:
            target_h = canvas_height
            target_w = int(target_h * bg_ratio)

    target_w = max(1, int(target_w * scale))
    target_h = max(1, int(target_h * scale))
    bg = bg.resize((target_w, target_h), Image.LANCZOS)
    paste_x = int((canvas_width - target_w) / 2 + offset_x)
    paste_y = int((canvas_height - target_h) / 2 + offset_y)
    canvas.paste(bg, (paste_x, paste_y), bg)
    return canvas


def render_invitation_image(
    background_bytes: bytes,
    elements: list[dict],
    context: dict,
    slot_contexts: Optional[list[dict]] = None,
    canvas_width: int = 1080,
    canvas_height: int = 1920,
    background_transform: Optional[dict] = None,
    base_canvas: Optional[Image.Image] = None,
    output_format: str = "PNG",
) -> bytes:
    """
    Render a single invitation image by compositing elements onto background.

    Args:
        background_bytes: Background image bytes (PNG/JPG)
        elements: List of template_elements (from DB) sorted by z_index
        context: Data context dict with keys like:
            {
                "guest": {"name": "أحمد", "name_ar": "أحمد", "date_value": "2025-06-15"},
                "event": {"title": "حفل تخرج", "date": "2025-06-15", "time": "19:00",
                          "location": "فندق الريتز"},
                "invite": {"code": "ABC123", "token": "...", "barcode_payload": "..."},
                "custom": {"seat": "A12", "table": "5"}
            }
        canvas_width: Target output width in pixels
        canvas_height: Target output height in pixels

    Returns:
        PNG bytes of the rendered invitation
    """
    canvas = base_canvas.copy() if base_canvas is not None else prepare_background_canvas(
        background_bytes,
        canvas_width,
        canvas_height,
        background_transform,
    )

    # Create overlay for drawing
    overlay = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Map element_type to default data_key (used when data_key is not set explicitly)
    TYPE_TO_KEY = {
        "guest_name": "guest.name",
        "guest_count": "invite.guest_count",
        "event_title": "event.title",
        "event_date": "event.date",
        "event_time": "event.time",
        "event_location": "event.location",
        "event_address": "event.address",
        "seat_number": "custom.seat",
        "gate": "custom.gate",
        "hall": "custom.hall",
        "table_number": "custom.table",
    }

    barcode_slot_index = 0

    for elem in elements:
        if not elem.get("is_visible", True):
            continue

        etype = elem.get("element_type", "")
        # Frontend stores x/y as the element top-left corner.
        left, top, ew, eh = _element_box_px(elem, canvas_width, canvas_height)

        rotation = float(elem.get("rotation", 0))
        # Center point (used only for rotation pivot)
        cx = left + ew // 2
        cy = top + eh // 2

        if etype in ("qr_code", "barcode"):
            element_context = context
            if slot_contexts:
                if barcode_slot_index >= len(slot_contexts):
                    barcode_slot_index += 1
                    continue
                element_context = slot_contexts[barcode_slot_index]
            barcode_slot_index += 1

            data_key = elem.get("data_key") or "invite.barcode_payload"
            payload = _resolve_data_key(data_key, element_context)
            if not payload:
                continue

            qr_color = elem.get("qr_color") or elem.get("font_color") or "#000000"
            qr_bg = elem.get("qr_bg_color") or "#ffffff"
            error_level = elem.get("qr_error_level") or elem.get("error_level") or "M"
            barcode_label = element_context.get("invite", {}).get("code") or payload

            if etype == "barcode":
                label_box_h = max(18, int(eh * 0.24))
                barcode_box_h = max(24, eh - label_box_h)

                barcode_png = generate_code128_png(
                    payload,
                    width_px=max(1, ew),
                    height_px=max(1, barcode_box_h),
                    fg_color=qr_color,
                    bg_color=qr_bg,
                )
                barcode_img = Image.open(io.BytesIO(barcode_png)).convert("RGBA")

                composed = Image.new("RGBA", (ew, eh), (0, 0, 0, 0))
                composed_draw = ImageDraw.Draw(composed)

                label_font, label_text = _auto_fit_text(
                    composed_draw,
                    str(barcode_label),
                    ew - 10,
                    label_box_h,
                    elem.get("font_family", "Cairo"),
                    elem.get("font_weight", "normal"),
                    max(12.0, float(elem.get("font_size", 24)) * 0.7),
                )
                label_bbox = composed_draw.textbbox((0, 0), label_text, font=label_font)
                label_w = label_bbox[2] - label_bbox[0]
                label_x = (ew - label_w) // 2
                label_y = 0
                composed_draw.text((label_x, label_y), label_text, font=label_font, fill=elem.get("font_color", "#111111"))

                barcode_y = label_box_h
                composed.paste(barcode_img, (0, barcode_y), barcode_img)

                if rotation:
                    composed = composed.rotate(-rotation, expand=True, resample=Image.BICUBIC)

                paste_x = left if not rotation else cx - composed.width // 2
                paste_y = top if not rotation else cy - composed.height // 2
                overlay.paste(composed, (paste_x, paste_y), composed)

            elif etype == "qr_code":
                qr_width_px = ew
                qr_height_px = eh

                maintain_square = elem.get("maintain_square", True)
                if maintain_square:
                    qr_size = qr_width_px
                else:
                    qr_size = qr_width_px

                qr_png = generate_qr_png(
                    payload,
                    size_px=max(1, qr_size),
                    fg_color=qr_color,
                    bg_color=qr_bg,
                    error_level=error_level,
                )
                qr_img = Image.open(io.BytesIO(qr_png)).convert("RGBA")

                # Center QR if smaller than the bounding box
                if qr_img.width < qr_width_px or qr_img.height < qr_height_px:
                    padded = Image.new("RGBA", (qr_width_px, qr_height_px), (0, 0, 0, 0))
                    paste_inner_x = (qr_width_px - qr_img.width) // 2
                    paste_inner_y = (qr_height_px - qr_img.height) // 2
                    padded.paste(qr_img, (paste_inner_x, paste_inner_y), qr_img)
                    qr_img = padded

                if rotation:
                    qr_img = qr_img.rotate(-rotation, expand=True, resample=Image.BICUBIC)

                paste_x = left if not rotation else cx - qr_img.width // 2
                paste_y = top if not rotation else cy - qr_img.height // 2
                overlay.paste(qr_img, (paste_x, paste_y), qr_img)

        elif etype == "image":
            # Static image element (logo, stamp, etc.)
            image_url = elem.get("static_content", "")
            if image_url:
                if image_url.startswith("blob:"):
                    logger.warning(f"Found client-side blob URL in image element: {image_url}. Skipping rendering.")
                    continue
                try:
                    img_bytes = None
                    if image_url.startswith("data:image/"):
                        header, encoded = image_url.split(",", 1)
                        if header not in {
                            "data:image/png;base64",
                            "data:image/jpeg;base64",
                            "data:image/webp;base64",
                        } or len(encoded) > 8 * 1024 * 1024:
                            raise ValueError("Invalid embedded image")
                        img_bytes = base64.b64decode(encoded, validate=True)
                        if len(img_bytes) > 5 * 1024 * 1024:
                            raise ValueError("Embedded image exceeds limit")
                    else:
                        if not image_url.startswith("https://"):
                            raise ValueError("Image elements require a trusted signed URL")
                        from app.services import storage_service
                        img_bytes = storage_service.download_reference_sync(
                            image_url,
                            max_bytes=5 * 1024 * 1024,
                        )

                    if img_bytes:
                        with Image.open(io.BytesIO(img_bytes)) as user_img:
                            if user_img.width * user_img.height > MAX_SOURCE_IMAGE_PIXELS:
                                raise ValueError("Image element dimensions exceed limit")
                            user_img = user_img.convert("RGBA")
                            # Pillow 10+ uses Resampling enum
                            resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                            user_img = user_img.resize((ew, eh), resample_filter)
                            if rotation:
                                rotate_filter = getattr(Image, "Resampling", Image).BICUBIC
                                user_img = user_img.rotate(-rotation, expand=True, resample=rotate_filter)
                            
                            paste_x = left if not rotation else cx - user_img.width // 2
                            paste_y = top if not rotation else cy - user_img.height // 2
                            overlay.paste(user_img, (paste_x, paste_y), user_img)
                except Exception as e:
                    if _snapshot_fonts.get() is not None:
                        raise ValueError('Immutable image element could not be rendered') from e
                    logger.error(f"Error rendering image element: {e}")

        elif etype == "custom_text":
            # Static text (not from data)
            text = elem.get("static_content", "")
            if not text:
                continue
            _draw_text_element(draw, overlay, text, elem, left, top, ew, eh, cx, cy, rotation, canvas_width, canvas_height)

        elif etype == "dynamic_text":
            # Dynamic text — resolve via smart alias-based lookup
            data_key = elem.get("data_key", "")
            if not data_key:
                continue
            # Use slot_contexts if available and element has slot_index
            slot_idx = elem.get("slot_index")
            if slot_contexts and slot_idx is not None and 0 <= slot_idx < len(slot_contexts):
                element_context = slot_contexts[slot_idx]
            else:
                element_context = context
            text = _resolve_dynamic_text(data_key, element_context)
            if not text:
                continue
            
            # Apply format if specified in static_content (we use static_content for format)
            fmt_type = elem.get("static_content")
            if fmt_type in ("date", "time", "number"):
                text = _format_value_by_type(text, fmt_type)
                
            _draw_text_element(draw, overlay, text, elem, left, top, ew, eh, cx, cy, rotation, canvas_width, canvas_height)

        else:
            # Legacy dynamic text element — use explicit data_key if set, else fallback by type
            data_key = elem.get("data_key") or TYPE_TO_KEY.get(etype, f"custom.{etype}")
            # Use slot_contexts if available and element has slot_index
            slot_idx = elem.get("slot_index")
            if slot_contexts and slot_idx is not None and 0 <= slot_idx < len(slot_contexts):
                element_context = slot_contexts[slot_idx]
            else:
                element_context = context
            text = _resolve_dynamic_text(data_key, element_context)
            if not text:
                continue
                
            # Auto-format based on element type
            if etype == "event_date":
                text = _format_value_by_type(text, "date")
            elif etype == "event_time":
                text = _format_value_by_type(text, "time")
                
            _draw_text_element(draw, overlay, text, elem, left, top, ew, eh, cx, cy, rotation, canvas_width, canvas_height)

    # Composite overlay onto background
    result = Image.alpha_composite(canvas, overlay)
    result = result.convert("RGB")

    buf = io.BytesIO()
    save_kwargs = {"quality": 95}
    if output_format.upper() == "PNG":
        save_kwargs["compress_level"] = 1
    result.save(buf, format=output_format, **save_kwargs)
    return buf.getvalue()


def _draw_text_element(
    draw: ImageDraw.ImageDraw,
    overlay: Image.Image,
    text: str,
    elem: dict,
    left: int, top: int, ew: int, eh: int,
    cx: int, cy: int,
    rotation: float,
    canvas_width: int, canvas_height: int,
):
    """
    Draw a text element with Arabic support, alignment, and optional rotation.

    Uses the exact font_size from the editor (WYSIWYG) so the output
    matches what the user sees in the design editor.

    Coordinates (left, top) represent the top-left of the bounding box — the
    same reference point the editor uses. Text alignment (center/right/left)
    is applied *within* this bounding box so the rendered result matches
    the editor preview exactly.
    """
    font_family = elem.get("font_family", "Cairo")
    font_size = float(elem.get("font_size", 24))
    font_weight = elem.get("font_weight", "normal")
    font_color = elem.get("font_color", "#000000")
    text_align = elem.get("text_align", "center")
    text_direction = elem.get("text_direction", "rtl")
    line_height = float(elem.get("line_height", 1.2))
    letter_spacing = float(elem.get("letter_spacing", 0.0))

    # Reshape Arabic text
    if text_direction == "rtl":
        text = _reshape_arabic(text)

    # Apply canvas scaling if template was designed at different width
    template_design_width = float(elem.get("_design_width", canvas_width))
    if template_design_width > 0 and abs(template_design_width - canvas_width) > 1:
        scale = canvas_width / template_design_width
        font_size = font_size * scale
        letter_spacing = letter_spacing * scale

    # Auto-fit: find the largest font ≤ font_size that fits in the box width
    font, display_text = _auto_fit_text(
        draw, text, ew, eh, font_family, font_weight, font_size,
        line_height=line_height, letter_spacing=letter_spacing
    )

    lines = display_text.split("\n")
    bbox_single = draw.textbbox((0, 0), "Hgالاسم", font=font)
    single_line_h = bbox_single[3] - bbox_single[1]

    if rotation and abs(rotation) > 0.5:
        # Measure total dimensions of this multi-line block
        text_w, text_h = _measure_text_dimensions(draw, display_text, font, line_height, letter_spacing)
        
        txt_img = Image.new("RGBA", (text_w + 20, text_h + 20), (0, 0, 0, 0))
        txt_draw = ImageDraw.Draw(txt_img)
        
        for i, line in enumerate(lines):
            line_w = _get_text_line_width_with_spacing(txt_draw, line, font, letter_spacing)
            
            # Horizontal alignment within the temp image
            if text_align == "center":
                lx = 10 + (text_w - line_w) // 2
            elif text_align == "right":
                lx = 10 + text_w - line_w
            else:
                lx = 10
                
            ly = int(10 + i * single_line_h * line_height)
            _draw_text_line_with_spacing(txt_draw, (lx, ly), line, font, font_color, letter_spacing)
            
        txt_img = txt_img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
        paste_x = cx - txt_img.width // 2
        paste_y = cy - txt_img.height // 2
        overlay.paste(txt_img, (paste_x, paste_y), txt_img)
    else:
        for i, line in enumerate(lines):
            line_w = _get_text_line_width_with_spacing(draw, line, font, letter_spacing)
            
            # Horizontal alignment within bounding box
            if text_align == "center":
                tx = left + (ew - line_w) // 2
            elif text_align == "right":
                tx = left + ew - line_w
            else:  # left
                tx = left
                
            ty = int(top + i * single_line_h * line_height)
            _draw_text_line_with_spacing(draw, (tx, ty), line, font, font_color, letter_spacing)
