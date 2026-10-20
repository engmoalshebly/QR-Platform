"""
Supabase Storage Service.
Handles file upload, download, signed URLs, and path management.
All invitation assets stored in 'invitations' bucket with structured paths.

Path structure:
  {tenant_id}/{event_id}/barcodes/{invite_id}.svg
  {tenant_id}/{event_id}/barcodes/{invite_id}.png
  {tenant_id}/{event_id}/renders/{invite_id}.png
  {tenant_id}/{event_id}/batches/{batch_id}/result.pdf
  {tenant_id}/{event_id}/batches/{batch_id}/images.zip
  {tenant_id}/{event_id}/batches/{batch_id}/preview_{n}.png
"""
import logging
import asyncio
import re
from urllib.parse import urlparse
from uuid import UUID
from typing import Optional

import httpx

from app.database import get_supabase_admin
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BUCKET = "invitations"
MAX_TRUSTED_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _get_client():
    return get_supabase_admin()


async def ensure_bucket_exists():
    """Create the invitations bucket if it doesn't exist."""
    try:
        client = _get_client()
        buckets = client.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if BUCKET not in bucket_names:
            client.storage.create_bucket(
                BUCKET,
                options={"public": False, "file_size_limit": 524288000},  # 500MB
            )
            logger.info("Created storage bucket: %s", BUCKET)
    except Exception as e:
        logger.warning("Could not ensure bucket exists: %s", e)


async def check_health() -> None:
    """Verify Storage API access without mutating state."""
    await asyncio.to_thread(lambda: _get_client().storage.list_buckets())


def build_path(tenant_id: UUID, event_id: UUID, *parts: str) -> str:
    """Build a structured storage path."""
    return f"{tenant_id}/{event_id}/{'/'.join(parts)}"


def upload_file(
    path: str,
    file_data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Upload file to Supabase Storage.
    Returns storage path (not a URL).
    """
    client = _get_client()
    try:
        client.storage.from_(BUCKET).upload(
            path=path,
            file=file_data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        logger.debug("Uploaded: %s (%d bytes)", path, len(file_data))
        return path
    except Exception as e:
        logger.error("Upload failed for %s: %s", path, e)
        raise


async def upload_bytes(
    path: str,
    file_data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Async wrapper for uploading bytes to storage.
    Returns storage path (not a URL).
    """
    return await asyncio.to_thread(upload_file, path, file_data, content_type)


def get_public_url(path: str) -> str:
    """Get a public URL for a file (bucket must be public or use signed URL)."""
    client = _get_client()
    res = client.storage.from_(BUCKET).get_public_url(path)
    return res


def get_signed_url(path: str, expires_in: int = None) -> str:
    """Get a signed URL valid for expires_in seconds.
    Defaults to settings.signed_url_expiry (1 hour) if not specified."""
    if expires_in is None:
        expires_in = settings.signed_url_expiry
    client = _get_client()
    res = client.storage.from_(BUCKET).create_signed_url(path, expires_in)
    return res.get("signedURL", "") if isinstance(res, dict) else res


def download_file(path: str) -> bytes:
    """Download file content from storage."""
    client = _get_client()
    return client.storage.from_(BUCKET).download(path)


def is_trusted_storage_url(value: str) -> bool:
    configured_host = urlparse(settings.supabase_url).hostname
    parsed = urlparse(value)
    if (
        not configured_host
        or parsed.scheme != "https"
        or parsed.hostname != configured_host
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return False
    allowed_prefixes = (
        f"/storage/v1/object/sign/{BUCKET}/",
        f"/storage/v1/object/public/{BUCKET}/",
        f"/storage/v1/object/authenticated/{BUCKET}/",
    )
    return parsed.path.startswith(allowed_prefixes)


def download_reference_sync(reference: str, max_bytes: int = MAX_TRUSTED_DOWNLOAD_BYTES) -> bytes:
    if reference.startswith(("http://", "https://")):
        if not is_trusted_storage_url(reference):
            raise ValueError("Untrusted storage URL")
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            with client.stream("GET", reference) as response:
                response.raise_for_status()
                declared_size = response.headers.get("content-length")
                if declared_size and declared_size.isdigit() and int(declared_size) > max_bytes:
                    raise ValueError("Storage object exceeds download limit")
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise ValueError("Storage object exceeds download limit")
                    content.extend(chunk)
                return bytes(content)

    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,1024}", reference) or ".." in reference.split("/"):
        raise ValueError("Invalid storage path")
    content = download_file(reference)
    if len(content) > max_bytes:
        raise ValueError("Storage object exceeds download limit")
    return content


async def download_reference(reference: str, max_bytes: int = MAX_TRUSTED_DOWNLOAD_BYTES) -> bytes:
    return await asyncio.to_thread(download_reference_sync, reference, max_bytes)


def delete_file(path: str) -> bool:
    """Delete a file from storage."""
    try:
        client = _get_client()
        client.storage.from_(BUCKET).remove([path])
        return True
    except Exception as e:
        logger.warning("Delete failed for %s: %s", path, e)
        return False


def delete_folder(prefix: str) -> bool:
    """Delete all files under a prefix (folder)."""
    try:
        client = _get_client()
        files = client.storage.from_(BUCKET).list(prefix)
        if files:
            paths = [f"{prefix}/{f['name']}" for f in files]
            client.storage.from_(BUCKET).remove(paths)
        return True
    except Exception as e:
        logger.warning("Delete folder failed for %s: %s", prefix, e)
        return False


def upload_barcode_svg(tenant_id: UUID, event_id: UUID, invite_id: UUID, svg_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "barcodes", f"{invite_id}.svg")
    return upload_file(path, svg_data, "image/svg+xml")


def upload_barcode_png(tenant_id: UUID, event_id: UUID, invite_id: UUID, png_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "barcodes", f"{invite_id}.png")
    return upload_file(path, png_data, "image/png")


def upload_render_image(tenant_id: UUID, event_id: UUID, invite_id: UUID, png_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "renders", f"{invite_id}.png")
    return upload_file(path, png_data, "image/png")


def upload_batch_pdf(tenant_id: UUID, event_id: UUID, batch_id: UUID, pdf_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "batches", str(batch_id), "result.pdf")
    return upload_file(path, pdf_data, "application/pdf")


def upload_batch_zip(tenant_id: UUID, event_id: UUID, batch_id: UUID, zip_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "batches", str(batch_id), "images.zip")
    return upload_file(path, zip_data, "application/zip")


def upload_preview(tenant_id: UUID, event_id: UUID, batch_id: UUID, index: int, png_data: bytes) -> str:
    path = build_path(tenant_id, event_id, "batches", str(batch_id), f"preview_{index}.png")
    return upload_file(path, png_data, "image/png")


def storage_ssl_context():
    """Honor the mounted private CA bundle without enabling environment proxies."""
    import os
    import ssl
    return ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE'))


def upload_disk_file(path: str, source, content_type: str) -> str:
    """Stream a private object from disk without materializing the file in RAM."""
    import httpx
    from pathlib import Path
    from urllib.parse import quote
    source = Path(source)
    endpoint = settings.supabase_url.rstrip('/')+'/storage/v1/object/'+BUCKET+'/'+quote(path,safe='/')
    headers = {'Authorization':'Bearer '+settings.supabase_service_role_key,
               'apikey':settings.supabase_service_role_key,'Content-Type':content_type,
               'Content-Length':str(source.stat().st_size),'x-upsert':'false'}
    with httpx.Client(timeout=60,follow_redirects=False,trust_env=False,verify=storage_ssl_context()) as client, source.open('rb') as stream:
        response=client.post(endpoint,headers=headers,content=stream)
        response.raise_for_status()
    return path


def verify_disk_object(path: str, expected_size: int, expected_sha256: str) -> None:
    """Verify the private stored object by bounded streaming GET, no signed URL."""
    import hashlib
    import httpx
    from urllib.parse import quote
    endpoint = settings.supabase_url.rstrip('/')+'/storage/v1/object/'+BUCKET+'/'+quote(path,safe='/')
    headers = {'Authorization':'Bearer '+settings.supabase_service_role_key,
               'apikey':settings.supabase_service_role_key}
    digest=hashlib.sha256()
    size=0
    with httpx.Client(timeout=60,follow_redirects=False,trust_env=False,verify=storage_ssl_context()) as client:
        with client.stream('GET',endpoint,headers=headers) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(1024*1024):
                size+=len(chunk)
                if size>expected_size:
                    raise ValueError('Stored object exceeds expected size')
                digest.update(chunk)
    if size!=expected_size or digest.hexdigest()!=expected_sha256:
        raise ValueError('Stored object integrity mismatch')
