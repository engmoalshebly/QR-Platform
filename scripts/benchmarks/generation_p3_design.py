"""High-resolution designed-page memory probe, no external services."""
import hashlib
import io
import json
import os
import resource
import sys
from pathlib import Path
from uuid import UUID
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import Image
from app.services import generation_render_service as render,barcode_service,pdf_service
from app.services.generation_workspace_service import workspace
from app.services.generation_export_service import PartBuilder

assert os.environ.get('INVITE_HMAC_SECRET','').startswith('p3-local-only')
font=Path(pdf_service.__file__).resolve().parents[1]/'assets/fonts/Amiri-Regular.ttf'
if not font.exists():
    font=Path(pdf_service.__file__).resolve().parents[2]/'fonts/Amiri-Regular.ttf'
font_content=font.read_bytes()
font_hash=hashlib.sha256(font_content).hexdigest()
buf=io.BytesIO()
with Image.new('RGB',(3000,4000),'white') as background:
    background.save(buf,'PNG')
bg=buf.getvalue()
bg_hash=hashlib.sha256(bg).hexdigest()
assets={bg_hash:{'content':bg,'mime_type':'image/png'},font_hash:{'content':font_content,'mime_type':'font/ttf'}}
snapshot={'template':{'width_px':3000,'height_px':4000},'background_sha256':bg_hash,
 'fonts':{'Amiri:normal':font_hash},'elements':[
  {'element_type':'qr_code','x':.1,'y':.1,'width':.4,'height':.3,'data_key':'invite.barcode_payload'},
  {'element_type':'custom_text','x':.1,'y':.7,'width':.8,'height':.1,'static_content':'دعوة','font_family':'Amiri','font_weight':'normal','font_size':48}],
 'images':{}}
with workspace() as scratch:
    builder=PartBuilder(scratch,'pdf',32*1024*1024,50)
    for index in range(3):
        info=barcode_service.build_barcode_payload(str(UUID(int=index+1)),'p3-isolated-token-'+str(index))
        context={'invite':{'barcode_payload':info['barcode_payload'],'code':str(index),'ticket_class':'normal'}}
        content=render.designed(snapshot,assets,[context])
        file=scratch.output('.png')
        scratch.write(file,[content])
        del content
        entry={'file':file,'name':str(index)+'.png'}
        page=render.pdf_page('designed',[entry],{},assets)
        builder.add_pdf_page(page,[str(index)])
        del page
        file.unlink()
    builder.finish_part()
    result={'canvas_pixels':12_000_000,'pages':3,'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
      'pdf_parts':len(builder.parts),'total_file_bytes':sum(p['byte_size'] for p in builder.parts),'remote_storage_used':False}
    assert result['peak_rss_mib']<640
    print(json.dumps(result))
