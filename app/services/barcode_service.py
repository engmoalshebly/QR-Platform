"""
Barcode/QR Generation Service.
Generates QR codes as SVG and PNG with HMAC-signed payloads.
Supports: QR Code, Code128 barcode.
"""
import hashlib
import hmac
import io
import logging
from uuid import UUID

import barcode
import qrcode
import qrcode.image.svg
from qrcode.image.pil import PilImage
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def _get_hmac_key() -> bytes:
    """Get the dedicated HMAC key for invitation signing (NOT the JWT secret)."""
    return settings.resolved_hmac_key.encode("utf-8")


def _get_prev_hmac_key() -> bytes | None:
    """Get the previous HMAC key for rotation grace period."""
    prev = settings.invite_hmac_secret_prev
    return prev.encode("utf-8") if prev else None


def _sign_with_key(invite_id: str, token: str, key: bytes) -> str:
    """Create HMAC-SHA256 signature with a specific key.

    Returns first 16 bytes (128-bit) of the digest as 32 hex characters.
    NOT 16 hex chars (which would be only 64-bit).

    Encoding: sig = hmac_sha256(key, msg).digest()[:16].hex()
    Result:   32 hex chars = 128-bit security strength
    """
    message = f"{invite_id}:{token}".encode("utf-8")
    digest_bytes = hmac.new(key, message, hashlib.sha256).digest()  # 32 bytes
    return digest_bytes[:16].hex()  # 16 bytes → 32 hex chars (128-bit)


def sign_payload(invite_id: str, token: str) -> str:
    """Create HMAC signature using the current primary key."""
    return _sign_with_key(invite_id, token, _get_hmac_key())


def verify_signature(invite_id: str, token: str, signature: str) -> bool:
    """
    Verify HMAC signature. Tries current key first, then previous key
    (rotation grace period). This allows rotating INVITE_HMAC_SECRET
    without invalidating existing barcodes during the transition.
    """
    if hmac.compare_digest(_sign_with_key(invite_id, token, _get_hmac_key()), signature):
        return True
    prev_key = _get_prev_hmac_key()
    if prev_key and hmac.compare_digest(_sign_with_key(invite_id, token, prev_key), signature):
        return True
    return False


def build_barcode_payload(invite_id: str, token: str) -> dict:
    """
    Build the full barcode payload with signature.
    Returns dict with payload string and signature.
    """
    signature = sign_payload(invite_id, token)
    # v1 is opaque (no guest data) and signed.  ``payload`` remains the old
    # public URL for compatibility with existing invitation pages and callers;
    # barcode images use ``field_payload`` below.
    payload_url = f"{settings.app_url}/i/{token}"
    field_payload = f"qentry:v1:{invite_id}:{token}:{signature}"
    return {
        "payload": payload_url,
        "field_payload": field_payload,
        "signature": signature,
        "barcode_payload": field_payload,
    }


def generate_qr_svg(data: str, box_size: int = 10, border: int = 1, error_level: str = "M") -> bytes:
    """Generate QR code as SVG bytes."""
    error_map = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
                 "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_map.get(error_level, qrcode.constants.ERROR_CORRECT_M),
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    factory = qrcode.image.svg.SvgPathImage
    img = qr.make_image(image_factory=factory)

    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def generate_qr_png(
    data: str,
    size_px: int = 400,
    fg_color: str = "#000000",
    bg_color: str = "#ffffff",
    error_level: str = "M",
) -> bytes:
    """Generate QR code as PNG bytes at specified size."""
    error_map = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
                 "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_map.get(error_level, qrcode.constants.ERROR_CORRECT_M),
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=PilImage,
        fill_color=fg_color,
        back_color=bg_color,
    )

    # Resize to target size
    pil_img = img.get_image()
    pil_img = pil_img.resize((size_px, size_px), resample=1)  # LANCZOS

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def generate_code128_png(
    data: str,
    width_px: int = 480,
    height_px: int = 180,
    fg_color: str = "#000000",
    bg_color: str = "#ffffff",
) -> bytes:
    """Generate a horizontal Code128 barcode PNG."""
    writer = ImageWriter()
    code = barcode.get("code128", data, writer=writer)
    buf = io.BytesIO()
    code.write(
        buf,
        options={
            "write_text": False,
            "foreground": fg_color,
            "background": bg_color,
            "quiet_zone": 4.0,
            "module_width": 0.25,
            "module_height": max(15.0, float(height_px) * 0.7),
            "font_size": 0,
            "text_distance": 1,
        },
    )

    buf.seek(0)
    img = Image.open(buf).convert("RGBA")
    target_width = max(1, int(width_px))
    target_height = max(1, int(height_px))
    img = img.resize((target_width, target_height), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def add_center_badge_to_png(
    png_bytes: bytes,
    label: str = "VIP",
    max_width_ratio: float = 0.24,
    height_ratio: float = 0.14,
) -> bytes:
    """Add a small centered badge to QR PNG while preserving scanability."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    width, height = img.size

    badge_w = int(width * max_width_ratio)
    badge_h = int(height * height_ratio)
    badge_w = max(48, min(badge_w, int(width * 0.28)))
    badge_h = max(24, min(badge_h, int(height * 0.16)))
    x = (width - badge_w) // 2
    y = (height - badge_h) // 2
    radius = max(4, badge_h // 5)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [x, y, x + badge_w, y + badge_h],
        radius=radius,
        fill="#ffffff",
        outline="#000000",
        width=max(2, width // 180),
    )

    try:
        font = ImageFont.truetype("arialbd.ttf", max(12, badge_h // 2))
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = x + (badge_w - text_w) // 2
    text_y = y + (badge_h - text_h) // 2 - 1
    draw.text((text_x, text_y), label, fill="#000000", font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_barcode_for_invitation(
    invite_id: str,
    token: str,
    size_px: int = 400,
    qr_color: str = "#000000",
    qr_bg_color: str = "#ffffff",
    error_level: str = "M",
) -> dict:
    """
    Generate both SVG and PNG barcode for an invitation.
    Returns dict with svg_bytes, png_bytes, payload, signature.
    """
    payload_info = build_barcode_payload(invite_id, token)
    payload_url = payload_info["payload"]
    field_payload = payload_info["field_payload"]

    svg_bytes = generate_qr_svg(field_payload, error_level=error_level)
    png_bytes = generate_qr_png(
        field_payload,
        size_px=size_px,
        fg_color=qr_color,
        bg_color=qr_bg_color,
        error_level=error_level,
    )

    return {
        "svg_bytes": svg_bytes,
        "png_bytes": png_bytes,
        "payload": payload_info["barcode_payload"],
        "signature": payload_info["signature"],
        "payload_url": payload_url,
    }
