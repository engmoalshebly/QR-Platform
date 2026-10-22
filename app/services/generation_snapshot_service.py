"""Capture immutable design bytes before the short admission transaction."""
import asyncio
import base64
import hashlib
import io
import json
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse
from fastapi import HTTPException
from PIL import Image, features
from sqlalchemy import text
from app.services import render_service, storage_service

MAX_ASSET_BYTES = 20 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 40 * 1024 * 1024


def renderer_fingerprint():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('generation_snapshot_service.py', 'barcode_service.py', 'render_service.py', 'pdf_service.py', 'generation_render_service.py', 'batch_pipeline.py', 'generation_worker_service.py', 'generation_export_service.py'):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    digest.update((root.parent / 'models/batch.py').read_bytes())
    # Source bytes alone do not identify the renderer: a patched Pillow/font
    # engine may produce different pixels. Missing dependencies fail before
    # admission, rather than assigning a misleading compatible fingerprint.
    for package in ('pillow', 'qrcode', 'reportlab', 'PyMuPDF', 'arabic-reshaper', 'python-bidi'):
        digest.update(json.dumps([package, metadata.version(package)], separators=(',', ':')).encode())
    for library in ('freetype2', 'raqm'):
        digest.update(json.dumps([library, features.version(library)], separators=(',', ':')).encode())
    return digest.hexdigest()


async def _reference_bytes(reference, tenant_id):
    if reference.startswith('data:image/'):
        try:
            header, encoded = reference.split(',', 1)
            if header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64') or len(encoded) > MAX_ASSET_BYTES * 4 // 3 + 4:
                raise ValueError()
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise HTTPException(422, 'صورة القالب المضمّنة غير صالحة')
    else:
        if not storage_service.is_trusted_storage_url(reference):
            raise HTTPException(422, 'أصول القالب يجب أن تكون محفوظة في تخزين المنصة')
        path = unquote(urlparse(reference).path)
        object_path = None
        for marker in ('/object/sign/invitations/', '/object/public/invitations/', '/object/authenticated/invitations/'):
            if marker in path:
                object_path = path.split(marker, 1)[1]
                break
        if not object_path or '%' in object_path or not object_path.startswith(f'{tenant_id}/') or any(part in ('', '.', '..') for part in object_path.split('/')):
            raise HTTPException(422, 'أصل القالب لا يتبع المؤسسة الحالية')
        try:
            # Read the private object itself: an expired signed URL is not a lost asset.
            content = await asyncio.wait_for(asyncio.to_thread(storage_service.download_file, object_path), timeout=15)
        except Exception:
            raise HTTPException(503, 'تعذر تثبيت أصل القالب. لم تُقبل العملية؛ أعد المحاولة')
    if not content or len(content) > MAX_ASSET_BYTES:
        raise HTTPException(422, 'حجم أصل القالب يتجاوز الحد المسموح')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > min(render_service.MAX_SOURCE_IMAGE_PIXELS,16_000_000):
                raise ValueError()
            mime_type = Image.MIME.get(image.format, 'image/png')
            image.verify()
    except Exception:
        raise HTTPException(422, 'صورة القالب غير صالحة أو أبعادها كبيرة جدًا')
    return content, mime_type


def _font_bytes(family, weight):
    paths = render_service.discover_fonts()
    key = f'{family}-Bold' if weight == 'bold' else f'{family}-Regular'
    filename = paths.get(key) or paths.get(family)
    if not filename:
        filename = next((value for name,value in paths.items() if name.lower() in (key.lower(),family.lower())), None)
    if not filename or not Path(filename).is_file():
        filename = paths.get('Cairo-Regular') or paths.get('Cairo')
    if not filename or not Path(filename).is_file():
        filename = str(Path(__file__).resolve().parents[1] / 'assets/fonts/Amiri-Regular.ttf')
        if not Path(filename).is_file():
            filename = str(Path(__file__).resolve().parents[2] / 'fonts/Amiri-Regular.ttf')
    content = Path(filename).read_bytes()
    if not content or len(content) > MAX_ASSET_BYTES:
        raise HTTPException(422, 'خط القالب غير صالح أو يتجاوز الحد المسموح')
    return content


async def prepare_snapshot(db, tenant_id, body):
    result = await db.execute(text('SELECT * FROM events WHERE id=:eid AND tenant_id=:tid'),
                              {'eid': str(body.event_id), 'tid': str(tenant_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, 'المناسبة غير موجودة')
    event = dict(row)
    if event.get('deleted_at') or event.get('status') == 'cancelled':
        raise HTTPException(409, 'لا يمكن إنشاء دعوات لمناسبة محذوفة أو ملغاة')
    event_snapshot = {key: event.get(key) for key in ('id', 'title', 'title_ar', 'start_date', 'end_date', 'location', 'address', 'description', 'public_slug', 'venue_name', 'venue_name_ar', 'venue_address', 'venue_city', 'venue_country', 'venue_map_url')}
    assets, templates, references, contents = {}, {}, {}, {}

    async def read_reference(reference):
        if not reference.startswith('data:') and not storage_service.is_trusted_storage_url(reference):
            raise HTTPException(422, 'أصول القالب يجب أن تكون محفوظة في تخزين المنصة')
        identity = reference if reference.startswith('data:') else (urlparse(reference).netloc, unquote(urlparse(reference).path))
        if identity not in references:
            content,mime = await _reference_bytes(reference, tenant_id)
            digest = hashlib.sha256(content).hexdigest()
            references[identity] = (contents.setdefault(digest,content),mime)
        return references[identity]

    def add_asset(key, content, kind, mime_type):
        if len(key)>500:
            raise HTTPException(422, 'اسم الخط أو وصف أحد أصول القالب أطول من الحد المسموح')
        digest = hashlib.sha256(content).hexdigest()
        content = contents.setdefault(digest, content)
        assets[key] = {'sha256': digest, 'content': content, 'kind': kind, 'mime_type': mime_type}
        if sum(len(item['content']) for item in {item['sha256']: item for item in assets.values()}.values()) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(422, 'مجموع أصول التصميم كبير جدًا لهذه العملية')
        return assets[key]['sha256']

    if body.mode == 'quick' and 'pdf' in body.output_formats:
        # The PDF label font is pinned even if the application image changes.
        bundled = Path(__file__).resolve().parents[1] / 'assets/fonts/Amiri-Regular.ttf'
        if not bundled.exists():
            bundled = Path(__file__).resolve().parents[2] / 'fonts/Amiri-Regular.ttf'
        add_asset('quick:label-font', await asyncio.to_thread(bundled.read_bytes), 'font', 'font/ttf')

    for ticket_class, template_id in body.templates.items():
        result = await db.execute(text("SELECT t.*,s.element_count,s.element_bytes,CASE WHEN s.element_count<=200 AND s.element_bytes<=6291456 THEN COALESCE((SELECT jsonb_agg(to_jsonb(el) ORDER BY el.z_index,el.id) FROM template_elements el WHERE el.template_id=t.id),'[]'::jsonb) ELSE NULL END AS snapshot_elements FROM invite_templates t CROSS JOIN LATERAL (SELECT count(*) AS element_count,COALESCE(sum(octet_length(to_jsonb(el)::text)),0) AS element_bytes FROM template_elements el WHERE el.template_id=t.id) s WHERE t.id=:id AND t.tenant_id=:tid AND (t.event_id=:eid OR t.event_id IS NULL)"),
            {'id': str(template_id), 'tid': str(tenant_id), 'eid': str(body.event_id)})
        row = result.mappings().first()
        if not row or row['ticket_class'] != ticket_class or row['template_type'] != 'designed':
            raise HTTPException(422, 'القالب غير موجود أو لا يطابق فئة الضيوف والمناسبة')
        template = dict(row)
        if (template.get('width_px') or 1080)*(template.get('height_px') or 1920)>12_000_000:
            raise HTTPException(422, 'أبعاد صفحة التصميم تتجاوز 12 مليون بكسل')
        if template.pop('element_count') > 200 or template.pop('element_bytes') > 6*1024*1024:
            raise HTTPException(422, 'القالب كبير جدًا: الحد 200 عنصر و6MiB لبيانات العناصر')
        elements = template.pop('snapshot_elements')
        if not template.get('background_url') or not any(el.get('is_visible', True) and el['element_type'] in ('barcode', 'qr_code') for el in elements):
            raise HTTPException(422, 'القالب غير مكتمل: يجب حفظ الخلفية ومكان رمز الدخول')
        background, mime = await read_reference(template['background_url'])
        prefix = f'template:{ticket_class}'
        background_hash = add_asset(prefix + ':background', background, 'background', mime)
        fonts, images = {}, {}
        for element in elements:
            if element['element_type'] == 'image' and element.get('static_content'):
                content, mime = await read_reference(element['static_content'])
                images[str(element['id'])] = add_asset(prefix + ':image:' + str(element['id']), content, 'image', mime)
                element['static_content'] = 'snapshot:' + images[str(element['id'])]
            if element['element_type'] not in ('image', 'barcode', 'qr_code'):
                family, weight = element.get('font_family') or 'Cairo', element.get('font_weight') or 'normal'
                font_key = f'{family}:{weight}'
                if font_key not in fonts:
                    content = await asyncio.to_thread(_font_bytes, family, weight)
                    fonts[font_key] = add_asset(prefix + ':font:' + font_key, content, 'font', 'font/ttf')
        # Remove mutable URL references. Bytes are selected through the manifest.
        template['background_url'] = 'snapshot:' + background_hash
        templates[ticket_class] = {'template': template, 'elements': elements, 'background_sha256': background_hash,
                                   'fonts': fonts, 'images': images}
    return {'event': json.loads(json.dumps(event_snapshot, default=str)),
            'templates': json.loads(json.dumps(templates, default=str)), 'assets': assets,
            'renderer_sha256': renderer_fingerprint()}
