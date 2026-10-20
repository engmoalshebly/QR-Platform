"""Offline real-QR resource/coverage proof; no Supabase or WhatsApp writes.

Run with test-only INVITE_HMAC_SECRET and GENERATION_WORKSPACE_DIR on disk.
This measures parsing + export core, not production network throughput (P5).
"""
import argparse
import hashlib
import io
import json
import os
import resource
import sys
import time
import zipfile
from pathlib import Path
from uuid import UUID
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.services.generation_workspace_service import workspace
from app.services.generation_import_parser import normalize_rows
from app.services.generation_export_service import PartBuilder
from app.services import generation_render_service as render
from app.services import barcode_service
from app.services import pdf_service


def run(count):
    assert os.environ.get('INVITE_HMAC_SECRET','').startswith('p3-local-only'), 'Use an isolated test signing key'
    import fitz
    start=time.monotonic()
    font=Path(pdf_service.__file__).resolve().parents[1]/'assets/fonts/Amiri-Regular.ttf'
    if not font.exists():
        font=Path(pdf_service.__file__).resolve().parents[2]/'fonts/Amiri-Regular.ttf'
    assets={hashlib.sha256(font.read_bytes()).hexdigest():{'content':font.read_bytes()}}
    layout={'rows':5,'cols':5,'show_guest_name':True}
    peak_disk=0
    metrics={'pdf_pages':0,'pdf_images':0,'zip_images':0,'pdf_parts':0,'zip_parts':0}
    total_coverage={'pdf':[],'zip':[]}
    with workspace() as scratch:
        source=scratch.output('.csv')
        with source.open('w') as stream:
            stream.write('guest_name,guest_count,ticket_class\n')
            for index in range(count):
                stream.write(f'ضيف {index},٣,'+('vip' if index%10==0 else 'normal')+'\n')
        def new_builders():
            return {kind:PartBuilder(scratch,kind,4*1024*1024,50) for kind in ('pdf','zip')}
        builders=new_builders()
        expected={}
        page=[]
        rows=[]
        batch_rows=[]
        def disk_peak():
            nonlocal peak_disk
            peak_disk=max(peak_disk,sum(p.stat().st_size for p in scratch.path.iterdir() if p.name not in ('.reservation','.active')))
        def flush_page():
            builders['pdf'].add_pdf_page(render.pdf_page('quick',page,layout,assets),list(rows))
            builders['zip'].add_images(page,list(rows))
            disk_peak()
            for entry in page:
                entry['file'].unlink()
            page.clear()
            rows.clear()
        def verify_and_publish_batch():
            for builder in builders.values():
                builder.finish_part()
            disk_peak()
            for kind,builder in builders.items():
                coverage=[row for part in builder.parts for row in part['rows']]
                assert coverage==batch_rows
                total_coverage[kind].extend(coverage)
                metrics[kind+'_parts']+=len(builder.parts)
                for part in builder.parts:
                    assert part['byte_size']<=4*1024*1024
                    if kind=='pdf':
                        with fitz.open(part['file']) as document:
                            metrics['pdf_pages']+=len(document)
                            metrics['pdf_images']+=sum(len(page.get_images()) for page in document)
                    else:
                        with zipfile.ZipFile(part['file']) as archive:
                            for name in archive.namelist():
                                assert hashlib.sha256(archive.read(name)).hexdigest()==expected[name]
                                metrics['zip_images']+=1
                    # A real worker streams/commits the part before deleting it.
                    # This isolated benchmark verifies it and simulates that release.
                    part['file'].unlink()
            expected.clear()
            batch_rows.clear()
        processed=0
        for row in normalize_rows(source,'csv'):
            assert not row['errors'] and row['normalized_data']['guest_count']==3
            number=row['row_number']
            token=hashlib.sha256(str(number).encode()).hexdigest()[:48]
            invitation={**row['normalized_data'],'id':UUID(int=number),'token':token}
            content,info=render.barcode(invitation,{'barcode_size_px':200})
            assert barcode_service.verify_signature(str(invitation['id']),token,info['signature'])
            path=scratch.output('.png')
            scratch.write(path,[content])
            name=f'{number:05d}.png'
            expected[name]=hashlib.sha256(content).hexdigest()
            page.append({'file':path,'name':name,'guest_name':invitation['guest_name'],'code':token[:8]})
            rows.append(str(number))
            batch_rows.append(str(number))
            processed+=1
            if len(page)==25:
                flush_page()
            if processed%250==0:
                verify_and_publish_batch()
                builders=new_builders()
            if processed%1000==0:
                print('processed',processed,flush=True)
        if page:
            flush_page()
        if batch_rows:
            verify_and_publish_batch()
        expected_rows=[str(number) for number in range(2,count+2)]
        assert total_coverage['pdf']==expected_rows and total_coverage['zip']==expected_rows
        assert metrics['pdf_pages']==(count+24)//25 and metrics['pdf_images']==count and metrics['zip_images']==count
        result={'rows':count,'people':count*3,**metrics,
                'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
                'peak_files_mib':round(peak_disk/1024/1024,2),'max_part_bytes':4*1024*1024,
                'working_batch_rows':250,'wall_seconds':round(time.monotonic()-start,2),
                'coverage_exact':True,'remote_storage_used':False}
        assert result['peak_rss_mib']<384 and peak_disk<256*1024*1024
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rows',type=int,choices=(1000,10000),required=True)
    parser.add_argument('--output',type=Path,required=True)
    options=parser.parse_args()
    result=run(options.rows)
    options.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result))
