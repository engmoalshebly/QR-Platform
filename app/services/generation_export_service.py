"""Bounded PDF/ZIP parts from disk. Only one page's image bytes are resident."""
import io
import zipfile
from pathlib import Path
import fitz
from app.services.generation_workspace_service import WorkspaceFull,file_digest


class PartBuilder:
    def __init__(self,workspace,kind,max_bytes,max_pages):
        self.workspace,self.kind=workspace,kind
        self.max_bytes,self.max_pages=max_bytes,max_pages
        self.document=None
        self.path=None
        self.rows=[]
        self.units=0
        self.payload_bytes=0
        self.parts=[]

    def _start(self):
        self.path=self.workspace.output('.'+self.kind)
        self.document=fitz.open() if self.kind=='pdf' else zipfile.ZipFile(self.path,'w',zipfile.ZIP_STORED)
        self.rows=[]
        self.units=0
        self.payload_bytes=0

    def add_pdf_page(self,content,rows):
        if len(content)>self.max_bytes//2:
            raise WorkspaceFull('A single PDF page exceeds the export budget')
        if self.document is not None and (self.units>=self.max_pages or self.payload_bytes+len(content)>self.max_bytes//2):
            self.finish_part()
        if self.document is None:
            self._start()
        with fitz.open(stream=content,filetype='pdf') as page:
            if len(page)!=1:
                raise ValueError('Export unit must contain exactly one PDF page')
            self.document.insert_pdf(page)
        self.payload_bytes+=len(content)
        self.units+=1
        self.rows.extend(rows)

    def add_images(self,entries,rows):
        size=sum(Path(entry['file']).stat().st_size for entry in entries)
        if size+65536>self.max_bytes:
            raise WorkspaceFull('A page of images exceeds the export budget')
        if self.document is not None and (self.units>=self.max_pages or self.payload_bytes+size+65536>self.max_bytes):
            self.finish_part()
        if self.document is None:
            self._start()
        for entry in entries:
            self.document.write(entry['file'],arcname=entry['name'])
        self.payload_bytes+=size
        self.units+=1
        self.rows.extend(rows)
        self.workspace.check()

    def finish_part(self):
        if self.document is None:
            return
        try:
            if self.kind=='pdf':
                self.document.save(self.path,garbage=4,deflate=True)
            else:
                self.document.close()
        finally:
            if self.kind=='pdf':
                self.document.close()
            self.document=None
        self.path.chmod(0o600)
        self.workspace.check()
        size,digest=file_digest(self.path)
        if not 0<size<=self.max_bytes:
            raise WorkspaceFull('Export part exceeds maximum bytes')
        if self.kind=='pdf':
            with fitz.open(self.path) as document:
                if len(document)!=self.units:
                    raise ValueError('PDF page count mismatch')
        else:
            with zipfile.ZipFile(self.path) as archive:
                if archive.testzip() is not None or len(archive.namelist())!=len(set(archive.namelist())):
                    raise ValueError('ZIP verification failed')
        self.parts.append({'kind':self.kind,'file_part':len(self.parts),'file':self.path,
                           'rows':list(self.rows),'byte_size':size,'sha256':digest})

    def close(self):
        if self.document is not None:
            self.document.close()
            self.document=None
