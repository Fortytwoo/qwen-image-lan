import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'QWENENC1'

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('This deployment requires Windows DPAPI.')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if protect:
        fn = crypt32.CryptProtectData
        description = 'Qwen local image service keys v1'
        second_type = wintypes.LPCWSTR
    else:
        fn = crypt32.CryptUnprotectData
        description = None
        second_type = ctypes.c_void_p
    fn.argtypes = [ctypes.POINTER(Blob), second_type, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)

def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)

def initialize_keys(path: Path) -> dict:
    if path.exists():
        return load_keys(path)
    data = {
        'username': 'qwen',
        'archive_key': base64.b64encode(AESGCM.generate_key(bit_length=256)).decode('ascii'),
        'session_key': base64.b64encode(AESGCM.generate_key(bit_length=256)).decode('ascii'),
        'tls_password': secrets.token_urlsafe(32),
    }
    save_keys(path, data)
    return data

def save_keys(path: Path, data: dict):
    atomic_write(path, dpapi(json.dumps(data).encode('utf-8'), protect=True))

def load_keys(path: Path) -> dict:
    return json.loads(dpapi(path.read_bytes(), protect=False))

class Cipher:
    def __init__(self, key: bytes):
        self.aes = AESGCM(key)

    def encrypt(self, data: bytes, scope: str) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + self.aes.encrypt(nonce, data, scope.encode('utf-8'))

    def decrypt(self, data: bytes, scope: str) -> bytes:
        if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 12 + 16:
            raise ValueError('Invalid encrypted record.')
        nonce = data[len(MAGIC):len(MAGIC) + 12]
        return self.aes.decrypt(nonce, data[len(MAGIC) + 12:], scope.encode('utf-8'))

class Sessions:
    def __init__(self, key: bytes):
        self.cipher = Cipher(key)
        self.active = {}

    def create(self, credential_id=None):
        now = int(time.time())
        self.active = {k:v for k,v in self.active.items() if v > now}
        payload = {'id': secrets.token_urlsafe(24), 'csrf': secrets.token_urlsafe(24), 'expires': now + 28800,
                   'credential_id':credential_id,'verified_at':now}
        self.active[payload['id']] = payload['expires']
        token = base64.urlsafe_b64encode(self.cipher.encrypt(json.dumps(payload).encode(), 'session/v1')).decode()
        return token, payload

    def read(self, token):
        try:
            payload = json.loads(self.cipher.decrypt(base64.urlsafe_b64decode(token), 'session/v1'))
            if payload['expires'] > time.time() and payload['id'] in self.active:
                return payload
        except Exception:
            pass
        return None

    def revoke(self, payload):
        self.active.pop(payload['id'], None)
