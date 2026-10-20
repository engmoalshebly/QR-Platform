"""Pure rendering from immutable operation inputs. No database or remote reads."""
import base64
import copy
import hashlib
from pathlib import Path
from app.models.batch import LayoutConfig
from app.services import barcode_service, render_service, pdf_service
from app.services.batch_pipeline import (_expand_repeated_sheet_slots, _auto_assign_slot_indices,
    _barcode_elements, _extract_background_transform, _build_render_context)


def barcode(invitation, layout):
    info=barcode_service.build_barcode_payload(str(invitation['id']),invitation['token'])
    vip=invitation['ticket_class']=='vip'
    content=barcode_service.generate_qr_png(info['field_payload'],
        size_px=LayoutConfig(**layout).resolved_barcode_size_px,error_level='H' if vip else 'M')
    if vip:
        content=barcode_service.add_center_badge_to_png(content,'VIP')
    return content,info


def contexts(items, batch, event):
    # Canonical guest data is frozen; only identity/token come from invitations.
    result=[]
    for item in items:
        inv={**item['normalized_data'],'id':item['invitation_id'],'token':item['token'],
             'barcode_payload':item['stage_results']['barcode']['info']['barcode_payload']}
        result.append(_build_render_context(inv,batch,event=event))
    return result


def expanded_elements(snapshot):
    return _auto_assign_slot_indices(_expand_repeated_sheet_slots(copy.deepcopy(snapshot['elements'])))


def slots(snapshot):
    count=len(_barcode_elements(expanded_elements(snapshot)))
    if not count:
        raise ValueError('Snapshot requires a visible entry-code slot')
    return count


def designed(snapshot, assets, group_contexts):
    template=snapshot['template']
    elements=expanded_elements(snapshot)
    for element in elements:
        if element['element_type']=='image' and element.get('static_content'):
            ref=element['static_content']
            if not ref.startswith('snapshot:') or ref[9:] not in assets:
                raise ValueError('Missing immutable image')
            asset=assets[ref[9:]]
            element['static_content']=f"data:{asset['mime_type']};base64,"+base64.b64encode(asset['content']).decode()
    background=assets[snapshot['background_sha256']]['content']
    fonts={key:assets[digest]['content'] for key,digest in snapshot['fonts'].items()}
    with render_service.pinned_fonts(fonts):
        return render_service.render_invitation_image(background_bytes=background,elements=elements,
            context=group_contexts[0],slot_contexts=group_contexts,
            canvas_width=template.get('width_px',1080),canvas_height=template.get('height_px',1920),
            background_transform=_extract_background_transform(template))


def pdf(mode, entries, layout, assets):
    if mode=='designed':
        return pdf_service.generate_cards_pdf([entry['png_bytes'] for entry in entries],{**layout,'card_per_page':True})
    # This renderer uses the bundled font. Refuse a different image/font rather
    # than silently altering a frozen snapshot. Uploaded design fonts are pinned.
    path=Path(pdf_service.__file__).resolve().parents[1]/'assets/fonts/Amiri-Regular.ttf'
    if not path.exists():
        path=Path(pdf_service.__file__).resolve().parents[2]/'fonts/Amiri-Regular.ttf'
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest not in assets:
        raise ValueError('Immutable PDF label font mismatch')
    return pdf_service.generate_barcode_grid_pdf(entries,layout)


def pdf_page(mode,entries,layout,assets):
    """At most one page and 12 megapixels of quick images, regardless of DPI."""
    import io
    import math
    from PIL import Image
    page=[]
    edge=max(1,int(math.sqrt(12_000_000/max(1,len(entries)))))
    for entry in entries:
        content=Path(entry['file']).read_bytes()
        if mode=='quick':
            with Image.open(io.BytesIO(content)) as image:
                if image.width>edge or image.height>edge:
                    image.thumbnail((edge,edge),Image.Resampling.NEAREST)
                    target=io.BytesIO()
                    image.save(target,'PNG')
                    content=target.getvalue()
        page.append({**entry,'png_bytes':content})
    return pdf(mode,page,layout,assets)
