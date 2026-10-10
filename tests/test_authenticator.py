import hashlib
import json
import secrets
import struct

import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from webauthn.helpers import bytes_to_base64url

class TestAuthenticator:
    """Software test fixture only: never enroll it in the production service."""
    def __init__(self):
        self.private_key=ec.generate_private_key(ec.SECP256R1())
        self.credential_id=secrets.token_bytes(32)
        self.counter=0
        self.user_id=None

    def client_data(self, options, origin, kind, **changes):
        value={'type':kind,'challenge':options['challenge'],'origin':origin,'crossOrigin':False,**changes}
        return json.dumps(value,separators=(',',':')).encode()

    def registration(self, options, origin, *, uv=True, rp_id=None, **changes):
        self.user_id=options['user']['id']
        numbers=self.private_key.public_key().public_numbers()
        cose={1:2,3:-7,-1:1,-2:numbers.x.to_bytes(32,'big'),-3:numbers.y.to_bytes(32,'big')}
        data=hashlib.sha256((rp_id or options['rp']['id']).encode()).digest()+bytes([0x41|(4 if uv else 0)])+struct.pack('>I',0)
        data+=b'\0'*16+struct.pack('>H',len(self.credential_id))+self.credential_id+cbor2.dumps(cose)
        return {'id':bytes_to_base64url(self.credential_id),'rawId':bytes_to_base64url(self.credential_id),'type':'public-key',
                'response':{'clientDataJSON':bytes_to_base64url(self.client_data(options,origin,'webauthn.create',**changes)),
                'attestationObject':bytes_to_base64url(cbor2.dumps({'fmt':'none','authData':data,'attStmt':{}})),
                'transports':['internal']},'clientExtensionResults':{'credProps':{'rk':True}}}

    def authentication(self, options, origin, *, uv=True, counter=None, rp_id=None, bad_signature=False, **changes):
        self.counter=self.counter+1 if counter is None else counter
        data=hashlib.sha256((rp_id or options['rpId']).encode()).digest()+bytes([1|(4 if uv else 0)])+struct.pack('>I',self.counter)
        client_data=self.client_data(options,origin,'webauthn.get',**changes)
        signature=self.private_key.sign(data+hashlib.sha256(client_data).digest(),ec.ECDSA(hashes.SHA256()))
        if bad_signature:signature=signature[:-1]+bytes([signature[-1]^1])
        return {'id':bytes_to_base64url(self.credential_id),'rawId':bytes_to_base64url(self.credential_id),'type':'public-key',
                'response':{'clientDataJSON':bytes_to_base64url(client_data),'authenticatorData':bytes_to_base64url(data),
                            'signature':bytes_to_base64url(signature),'userHandle':self.user_id},'clientExtensionResults':{}}
