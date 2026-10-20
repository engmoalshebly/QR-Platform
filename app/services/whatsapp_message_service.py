"""Message authoring, bounded image normalization, and immutable send snapshots."""
import io
import re
import warnings
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text

DEFAULT_RSVP = 'مرحباً {guest_name}،\n\nيسعدنا دعوتك إلى *{event_name}*.\n📅 {event_date}\n📍 {event_location}\n\nيرجى تأكيد حضورك أو الاعتذار عبر رابطك الخاص أدناه.\nنتطلع إلى لقائك.'
DEFAULT_TICKET = 'مرحباً {guest_name}،\n\nيسعدنا حضورك في *{event_name}*.\n📅 {event_date}\n📍 {event_location}\n\nدعوتك ورمز الدخول متاحان عبر رابطك الخاص أدناه. احتفظ بالدعوة لإبرازها عند البوابة.\nأهلاً بك.'
VARIABLES = ('guest_name','event_name','event_date','event_location')
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024


def message_length(value):
    # OpenWA validates JavaScript string lengths (UTF-16 code units).
    try: return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError: raise HTTPException(422,"النص يتضمن محارف غير صالحة.")


def validate_template(value):
    value = value.strip()
    if not value or message_length(value)>700:
        raise HTTPException(422,'اكتب نصاً من 1 إلى 700 حرف.')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):
        raise HTTPException(422,'النص يتضمن محارف غير صالحة.')
    rest=re.sub(r'\{(?:'+ '|'.join(VARIABLES)+r')\}', '', value)
    if '{' in rest or '}' in rest:
        raise HTTPException(422,'استخدم متغيرات الرسالة المتاحة فقط.')
    return value


def render(template, inv, event, link):
    date=event.get('start_date')
    zone=event.get('timezone') or 'Asia/Aden'
    try: zone=ZoneInfo(zone)
    except (ValueError,KeyError): zone=ZoneInfo('Asia/Aden')
    values={
        'guest_name':str(inv.get('guest_name_ar') or inv.get('guest_name') or 'ضيفنا الكريم')[:150],
        'event_name':str(event.get('title_ar') or event.get('title') or 'الفعالية')[:200],
        'event_date':date.astimezone(zone).strftime('%Y/%m/%d، %H:%M') if date else 'يُحدد لاحقاً',
        'event_location':str(event.get('venue_name') or event.get('venue_address') or 'حسب تفاصيل الدعوة')[:150],
    }
    # One substitution pass: user data cannot become another template variable.
    body=re.sub(r'\{('+ '|'.join(VARIABLES)+r')\}',lambda match:values[match[1]],template)
    return body+'\n\n'+link


def normalize_image(content):
    if not content or len(content)>MAX_UPLOAD_BYTES:
        raise HTTPException(422,'اختر صورة PNG أو JPG أو WEBP بحجم لا يتجاوز 5MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as original:
                if original.format not in ('PNG','JPEG','WEBP') or original.width*original.height>16_000_000:
                    raise ValueError()
                original.seek(0)
                oriented=ImageOps.exif_transpose(original)
                oriented.thumbnail((1200,1200))
                rgb=Image.new('RGB',oriented.size,'white')
                if oriented.mode in ('RGBA','LA'):
                    rgb.paste(oriented,mask=oriented.getchannel('A'))
                else: rgb.paste(oriented.convert('RGB'))
                for dimension in (1200,1000,800,640):
                    rgb.thumbnail((dimension,dimension))
                    for quality in (85,75,60):
                        output=io.BytesIO();rgb.save(output,'JPEG',quality=quality,optimize=True)
                        if output.tell()<=MAX_IMAGE_BYTES:return output.getvalue()
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise HTTPException(422,'تعذر قراءة الصورة. اختر صورة صالحة بأبعاد أصغر.')
    raise HTTPException(422,'الصورة كبيرة بعد المعالجة. اختر صورة أبسط أو أصغر.')


async def event_owned(db,tid,eid):
    event=(await db.execute(text('SELECT * FROM events WHERE id=:eid AND tenant_id=:tid AND deleted_at IS NULL'),{'tid':str(tid),'eid':str(eid)})).mappings().first()
    if not event:raise HTTPException(404,'الحدث غير متاح.')
    return event


async def config(db,tid,eid):
    row=(await db.execute(text('SELECT rsvp_text,ticket_text,image_id,version FROM whatsapp_message_templates WHERE tenant_id=:tid AND event_id=:eid'),{'tid':str(tid),'eid':str(eid)})).mappings().first()
    return dict(row) if row else {'rsvp_text':DEFAULT_RSVP,'ticket_text':DEFAULT_TICKET,'image_id':None,'version':0}


async def image(db,tid,eid,iid):
    row=(await db.execute(text('SELECT id,content,mime_type FROM whatsapp_message_images WHERE id=:iid AND tenant_id=:tid AND event_id=:eid'),{'iid':str(iid),'tid':str(tid),'eid':str(eid)})).mappings().first()
    if not row:raise HTTPException(404,'الصورة غير متاحة لهذا الحدث.')
    return row
