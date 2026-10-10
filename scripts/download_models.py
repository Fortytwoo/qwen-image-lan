import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import urllib.parse
import urllib.request
import zipfile

def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def download(item,path):
    url=urllib.parse.urlparse(item['url'])
    if url.scheme!='https' or url.hostname not in ('github.com','huggingface.co'):
        raise ValueError('Unexpected download origin.')
    if path.exists():
        if path.stat().st_size==item['size'] and digest(path)==item['sha256']:
            print('Verified existing '+item['name'],flush=True)
            return
        raise ValueError('Existing file differs; it was preserved: '+str(path))
    partial=path.with_name(path.name+'.part')
    for attempt in range(4):
        if attempt:time.sleep(5)
        offset=partial.stat().st_size if partial.exists() else 0
        if offset==item['size']:break
        if offset>item['size']:raise ValueError('Oversized partial file was preserved.')
        headers={'User-Agent':'qwen-image-lan-installer/1'}
        if offset:headers['Range']=f'bytes={offset}-'
        try:
            with urllib.request.urlopen(urllib.request.Request(item['url'],headers=headers),timeout=30) as response:
                if offset and (response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
                    raise ValueError('Server did not honor safe download resume.')
                received=offset
                reported=time.monotonic()
                with partial.open('ab' if offset else 'wb') as stream:
                    while chunk:=response.read1(1024*1024):
                        stream.write(chunk);received+=len(chunk)
                        if received>item['size']:raise ValueError('Unexpected download size.')
                        if time.monotonic()-reported>=15:
                            print(f'{item["name"]}: {received/item["size"]:.1%}',flush=True)
                            reported=time.monotonic()
                    stream.flush();os.fsync(stream.fileno())
            if received!=item['size']:raise OSError('Incomplete download.')
            break
        except (OSError,TimeoutError) as error:
            print(type(error).__name__+'; retrying with partial data retained.',flush=True)
            if attempt==3:raise
    if digest(partial)!=item['sha256']:raise ValueError('SHA256 mismatch; partial data was preserved.')
    partial.replace(path)
    print('Downloaded and verified '+item['name'],flush=True)

def extract(path,destination):
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            target=(destination/entry.filename.replace('\\','/')).resolve()
            if not target.is_relative_to(destination) or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe archive path.')
            if entry.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            payload=archive.read(entry)
            if target.exists() and target.read_bytes()==payload:continue
            if target.exists():raise ValueError('Existing engine file differs; preserved: '+str(target))
            with target.open('xb') as stream:stream.write(payload)

def install(manifest,root,skip_download=False):
    root=Path(root)
    requested=False
    for item in manifest['downloads']:
        if Path(item['name']).name!=item['name'] or item['kind'] not in ('model','archive'):
            raise ValueError('Invalid manifest filename or kind.')
        destination=root/('downloads' if item['kind']=='archive' else 'models')/item['name']
        destination.parent.mkdir(parents=True,exist_ok=True)
        if skip_download:
            if not destination.exists() or destination.stat().st_size!=item['size'] or digest(destination)!=item['sha256']:
                raise ValueError('Offline installation needs an already verified file: '+str(destination))
        else:
            if requested:time.sleep(5)
            download(item,destination)
            requested=True
        if item['kind']=='archive':extract(destination,root/'engine')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--root',required=True)
    parser.add_argument('--skip-download',action='store_true')
    args=parser.parse_args()
    install(json.loads(Path(args.manifest).read_text(encoding='utf-8')),args.root,args.skip_download)
