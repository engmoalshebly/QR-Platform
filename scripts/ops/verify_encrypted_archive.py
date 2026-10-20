#!/usr/bin/env python3
"""Restore a GPG tar archive privately; verify every extracted byte without listing names."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def restore(archive, destination, limit=1024**3):
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    manifest=[]
    seen=set()
    total=0
    process=subprocess.Popen(['gpg','--batch','--quiet','--decrypt',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as source:
            for member in source:
                relative=PurePosixPath(member.name)
                if relative.is_absolute() or '..' in relative.parts or not (member.isdir() or member.isfile()):
                    raise ValueError('Unsafe archive entry')
                target=destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(mode=0o700,parents=True,exist_ok=True)
                    continue
                if str(relative) in seen:
                    raise ValueError('Duplicate archive entry')
                seen.add(str(relative))
                total+=member.size
                if total>limit:
                    raise ValueError('Archive exceeds restore budget')
                target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                digest=hashlib.sha256()
                with source.extractfile(member) as reader,target.open('xb') as writer:
                    target.chmod(0o600)
                    while chunk:=reader.read(1024*1024):
                        digest.update(chunk);writer.write(chunk)
                check=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
                if check!=digest.hexdigest() or target.stat().st_size!=member.size:
                    raise ValueError('Restored file differs from archive')
                manifest.append((str(relative),check,member.size))
        while process.stdout.read(1024*1024):
            pass
        if process.wait()!=0:
            raise ValueError('Archive decryption failed')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill();process.wait()
    return {'files':len(manifest),'bytes':total,'manifest_sha256':hashlib.sha256(json.dumps(sorted(manifest)).encode()).hexdigest(),'all_files_verified':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();result=restore(a.archive,a.destination);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
