"""Check only publishable files; never print matched credential contents."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BANNED_SUFFIXES={'.dpapi','.enc','.pem','.cer','.pfx','.key','.gguf','.safetensors','.exe','.dll','.zip','.part','.log','.png','.jpg','.jpeg','.webp'}
BANNED_PARTS={'private','certs','models','downloads','engine','logs','backups','.venv','__pycache__'}
PATTERNS={
    'github credential':re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
    'private key material':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'personal Windows path':re.compile(r'[A-Z]:[\\/]Users[\\/][^\s<>"\']+',re.I),
    'author runtime identity':re.compile('zhu'+'anz'+r'|192\.168\.60\.133|midi\.lizhijian\.xyz',re.I),
}

def check(name,data):
    path=Path(name)
    failures=[]
    if path.suffix.lower() in BANNED_SUFFIXES or any(part.lower() in BANNED_PARTS for part in path.parts):
        failures.append('generated/private/binary filename')
    if path.name in ('config.json','process.json','certificate-fingerprint.json'):
        failures.append('runtime config filename')
    if len(data)>2*1024*1024:failures.append('unexpectedly large file')
    try:text=data.decode('utf-8-sig')
    except UnicodeError:failures.append('unexpected binary file');text=''
    for label,pattern in PATTERNS.items():
        if pattern.search(text):failures.append(label)
    return failures

def scan(history=False):
    failures=[]
    git=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True)
    if git.returncode==0:
        names=[name for name in git.stdout.decode().split('\0') if name]
        if not names:raise RuntimeError('Stage the intended source files before scanning.')
    else:
        names=[str(path.relative_to(ROOT)) for path in ROOT.rglob('*') if path.is_file()
               and not any(part in ('.git','__pycache__','.venv') for part in path.parts)]
    for name in names:
        for reason in check(name,(ROOT/name).read_bytes()):failures.append((name,reason))
    if history and git.returncode==0:
        entries=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=ROOT,text=True).splitlines()
        for entry in entries:
            oid,_,name=entry.partition(' ')
            if not name:continue
            kind=subprocess.check_output(['git','cat-file','-t',oid],cwd=ROOT,text=True).strip()
            if kind!='blob':continue
            data=subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT)
            for reason in check(name,data):failures.append(('history:'+name,reason))
    for name,reason in failures:print(name+': '+reason)
    if failures:return False
    print(f'Public tree passed: {len(names)} source files; no runtime/private/binary artifacts detected.')
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    sys.exit(0 if scan(args.history) else 1)
