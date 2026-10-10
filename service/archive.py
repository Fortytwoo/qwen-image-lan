import json
from pathlib import Path
import re
import secrets

from security import Cipher, atomic_write

class Archive:
    def __init__(self, root: Path, key: bytes):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.cipher = Cipher(key)

    def valid_id(self, record_id: str):
        if not re.fullmatch(r'[a-f0-9]{32}', record_id):
            raise ValueError('Invalid record ID.')
        return record_id

    def create(self, metadata: dict):
        record_id = secrets.token_hex(16)
        metadata = {**metadata, 'id': record_id, 'images': []}
        self.save(metadata)
        return metadata

    def save(self, metadata: dict):
        record_id = self.valid_id(metadata['id'])
        payload = json.dumps(metadata, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        atomic_write(self.root / f'{record_id}.meta.enc', self.cipher.encrypt(payload, f'{record_id}/metadata/v1'))

    def get(self, record_id: str):
        record_id = self.valid_id(record_id)
        payload = self.cipher.decrypt((self.root / f'{record_id}.meta.enc').read_bytes(), f'{record_id}/metadata/v1')
        return json.loads(payload)

    def list(self):
        records = []
        for path in self.root.glob('*.meta.enc'):
            records.append(self.get(path.name.split('.')[0]))
        return sorted(records, key=lambda item: item['created'], reverse=True)

    def store_image(self, record_id: str, index: int, data: bytes):
        record_id = self.valid_id(record_id)
        if not 0 <= index < 4:
            raise ValueError('Invalid image index.')
        atomic_write(self.root / f'{record_id}.{index}.image.enc', self.cipher.encrypt(data, f'{record_id}/image/{index}/v1'))

    def read_image(self, record_id: str, index: int):
        record_id = self.valid_id(record_id)
        if not 0 <= index < 4:
            raise ValueError('Invalid image index.')
        return self.cipher.decrypt((self.root / f'{record_id}.{index}.image.enc').read_bytes(), f'{record_id}/image/{index}/v1')

    def store_reference(self, record_id: str, index: int, data: bytes):
        record_id = self.valid_id(record_id)
        if index != 0:
            raise ValueError('Invalid reference index.')
        atomic_write(self.root / f'{record_id}.{index}.reference.enc', self.cipher.encrypt(data, f'{record_id}/reference/{index}/v1'))

    def read_reference(self, record_id: str, index: int):
        record_id = self.valid_id(record_id)
        if index != 0:
            raise ValueError('Invalid reference index.')
        return self.cipher.decrypt((self.root / f'{record_id}.{index}.reference.enc').read_bytes(), f'{record_id}/reference/{index}/v1')
