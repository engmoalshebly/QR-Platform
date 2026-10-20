"""Bounded CSV/XLSX readers. No macros, formulas, links or inferred row dropping."""
import csv
import io
import json
import posixpath
import re
import zipfile
from itertools import islice
from pathlib import Path
from xml.etree import ElementTree as ET
from app.services.fast_generation_service import _normalize_invitation_row

MAX_UPLOAD = 10*1024*1024
MAX_EXPANDED = 64*1024*1024
MAX_ROWS = 10000
MAX_COLUMNS = 128
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
csv.field_size_limit(32768)


def _xml(archive, name):
    # Validate before parsing, including declarations split across read boundaries.
    with archive.open(name) as stream:
        tail = b''
        for block in iter(lambda: stream.read(65536), b''):
            text = (tail+block).upper()
            if b'\x00' in text or b'<!DOCTYPE' in text or b'<!ENTITY' in text:
                raise ValueError('XML declarations are not allowed')
            tail = text[-16:]
    return archive.open(name)


def inspect_xlsx(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries)>2048 or len({e.filename for e in entries})!=len(entries):
            raise ValueError('Invalid spreadsheet archive')
        if sum(e.file_size for e in entries)>MAX_EXPANDED:
            raise ValueError('Expanded spreadsheet exceeds 64 MiB')
        for entry in entries:
            name = entry.filename.lower()
            if entry.flag_bits & 1 or '..' in Path(name).parts or name.startswith('/') or '\\' in name:
                raise ValueError('Unsafe spreadsheet archive')
            if entry.file_size>MAX_EXPANDED or entry.file_size>max(1024*1024,entry.compress_size*1000):
                raise ValueError('Spreadsheet compression ratio exceeds limit')
            if 'vbaproject' in name or name.startswith('xl/externallinks/'):
                raise ValueError('Macros and external workbook links are not supported')
        with _xml(archive,'xl/workbook.xml') as stream:
            book=ET.parse(stream).getroot()
        with _xml(archive,'xl/_rels/workbook.xml.rels') as stream:
            relationships=ET.parse(stream).getroot()
        targets={r.attrib['Id']:r.attrib.get('Target','') for r in relationships if r.attrib.get('TargetMode')!='External'}
        sheets=[]
        for sheet in book.findall(NS+'sheets/'+NS+'sheet'):
            target=targets.get(sheet.attrib.get(REL+'id'))
            if not target:
                continue
            filename=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
            if not filename.startswith('xl/worksheets/') or filename not in archive.namelist():
                raise ValueError('Invalid worksheet reference')
            sheets.append({'name':sheet.attrib['name'],'path':filename})
        if not 1<=len(sheets)<=32:
            raise ValueError('Spreadsheet must contain 1 to 32 worksheets')
        return sheets


def _xlsx_rows(path, sheet):
    sheets=inspect_xlsx(path)
    selected=next((s for s in sheets if s['name']==sheet),None)
    if selected is None:
        raise ValueError('Choose one of the available worksheets')
    with zipfile.ZipFile(path) as archive:
        strings=[]
        size=0
        if 'xl/sharedStrings.xml' in archive.namelist():
            with _xml(archive,'xl/sharedStrings.xml') as stream:
                for _,node in ET.iterparse(stream,events=('end',)):
                    if node.tag==NS+'si':
                        value=''.join(node.itertext())
                        size+=len(value.encode('utf-8'))
                        if size>8*1024*1024 or len(strings)>=100000 or len(value)>32768:
                            raise ValueError('Shared spreadsheet strings exceed limit')
                        strings.append(value)
                        node.clear()
        with _xml(archive,selected['path']) as stream:
            last_number=0
            for _,node in ET.iterparse(stream,events=('end',)):
                if node.tag!=NS+'row':
                    continue
                number=int(node.attrib.get('r',last_number+1))
                if number<=last_number or number>1048576:
                    raise ValueError('Invalid worksheet row numbers')
                last_number=number
                values=[]
                for cell in node.findall(NS+'c'):
                    address=cell.attrib.get('r','')
                    letters=re.match(r'^([A-Z]+)[1-9][0-9]*$',address)
                    if not letters:
                        raise ValueError('Invalid spreadsheet cell address')
                    index=0
                    for character in letters[1]:
                        index=index*26+ord(character)-64
                    if not 1<=index<=MAX_COLUMNS:
                        raise ValueError('Spreadsheet exceeds 128 columns')
                    if cell.find(NS+'f') is not None:
                        value={'invalid_formula':True}
                    elif cell.attrib.get('t')=='inlineStr':
                        inline=cell.find(NS+'is')
                        value=''.join(inline.itertext()) if inline is not None else ''
                    else:
                        value=cell.findtext(NS+'v','')
                        if cell.attrib.get('t')=='s':
                            value=strings[int(value)]
                        elif cell.attrib.get('t')=='b':
                            value=(value=='1')
                        elif cell.attrib.get('t')=='e':
                            value={'invalid_cell':True}
                    if len(str(value))>32768:
                        raise ValueError('Spreadsheet cell exceeds limit')
                    while len(values)<index:
                        values.append('')
                    values[index-1]=value
                yield number,values
                node.clear()


def raw_rows(path, kind, sheet=None, delimiter=","):
    if kind=='xlsx':
        yield from _xlsx_rows(path,sheet)
    else:
        with Path(path).open('r',encoding='utf-8-sig',newline='') as stream:
            for number,values in enumerate(csv.reader(stream,strict=True,delimiter=delimiter),1):
                if len(values)>MAX_COLUMNS:
                    raise ValueError('CSV exceeds 128 columns')
                yield number,values


def normalize_rows(path,kind,sheet=None,mapping=None,require_rsvp=False,delimiter=","):
    iterator=raw_rows(path,kind,sheet,delimiter)
    _,headers=next(iterator,(0,[]))
    headers=[str(value).strip() for value in headers]
    if not headers or not all(headers) or len(headers)!=len(set(headers)):
        raise ValueError('Column headers must be nonempty and unique')
    if sum(len(header.encode('utf-8')) for header in headers)>8192 or any(len(header)>200 for header in headers):
        raise ValueError('Column header exceeds limit')
    mapping=mapping or {header:header for header in headers}
    if len(set(mapping.values()))!=len(mapping) or any(value not in headers for value in mapping.values()):
        raise ValueError('Column mapping references missing or repeated columns')
    for count,(number,values) in enumerate(iterator,1):
        if count>MAX_ROWS:
            raise ValueError('At most 10000 data rows are supported')
        if len(values)>len(headers):
            raise ValueError('A data row contains more fields than the header')
        raw=dict(zip(headers,values))
        blank=not any(value not in ('',None) for value in values)
        data={target:raw.get(source,'') for target,source in mapping.items()}
        errors=[]
        normalized=None
        if not blank:
            try:
                if any(isinstance(value,str) and '\x00' in value for value in values):
                    raise ValueError('Null characters are not supported in spreadsheet values')
                if any(isinstance(value,dict) or (isinstance(value,str) and value.startswith('=')) for value in values):
                    raise ValueError('Formula/error cells must be replaced with explicit values')
                if len(json.dumps(raw,ensure_ascii=False,default=str).encode())>16384:
                    raise ValueError('Row exceeds 16 KiB')
                normalized=_normalize_invitation_row({**data,'require_rsvp':require_rsvp},number-1)
            except (ValueError,TypeError) as error:
                errors=[str(error)[:500]]
        raw={key:(value.replace('\x00','\\u0000') if isinstance(value,str) else value) for key,value in raw.items()}
        if len(json.dumps(raw,ensure_ascii=False,default=str).encode())>16384:
            raw={key:str(value).encode('utf-8')[:256].decode('utf-8',errors='ignore') for key,value in list(raw.items())[:16]}
            raw['__preview_truncated']=True
        yield {'row_number':number,'raw_data':raw,'normalized_data':normalized,
               'errors':errors,'excluded':blank}


def next_chunk(iterator, limit=100):
    return list(islice(iterator,limit))
