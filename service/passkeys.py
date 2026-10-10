import base64
from contextlib import contextmanager
import hashlib
import json
import msvcrt
from pathlib import Path
import secrets
import time

from webauthn import generate_authentication_options, generate_registration_options, options_to_json
from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement
from webauthn.helpers.structs import UserVerificationRequirement, PublicKeyCredentialDescriptor
from webauthn.helpers.cose import COSEAlgorithmIdentifier

from security import dpapi, atomic_write

CEREMONY_COOKIE = '__Host-qwen-ceremony'
CEREMONY_SECONDS = 180
GRANT_SECONDS = 600

class PasskeyError(ValueError):
    pass

class Passkeys:
    """Private Windows-owner store shared safely by the gateway and enrollment CLI."""
    def __init__(self, path, rp_id, origin):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.rp_id = rp_id
        self.origin = origin
        self.pending = {}
        with self.state() as state:
            if state.get('rp_id',rp_id) != rp_id:
                raise RuntimeError('Passkey RP ID changed; existing credentials must not be reassigned.')
            state['rp_id'] = rp_id

    @contextmanager
    def state(self):
        lock_path = self.path.with_suffix('.lock')
        with lock_path.open('a+b') as lock:
            if lock_path.stat().st_size == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
            try:
                if self.path.exists():
                    state=json.loads(dpapi(self.path.read_bytes(),protect=False))
                else:
                    state={'version':1,'user_id':bytes_to_base64url(secrets.token_bytes(32)),
                           'credentials':{},'grants':{}}
                yield state
                atomic_write(self.path,dpapi(json.dumps(state,separators=(',',':')).encode('utf-8'),protect=True))
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

    def credentials(self):
        with self.state() as state:
            return [{k:v for k,v in item.items() if k not in ('public_key','sign_count')}
                    for item in state['credentials'].values() if not item.get('revoked')]

    def active(self, credential_id):
        with self.state() as state:
            credential=state['credentials'].get(credential_id)
            return bool(credential and not credential.get('revoked'))

    def create_grant(self, *, local_owner=False):
        token=secrets.token_urlsafe(32)
        digest=hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.state() as state:
            now=int(time.time())
            state['grants']={key:value for key,value in state['grants'].items() if value['expires']>now}
            if len(state['grants'])>=16:
                raise PasskeyError('未使用的注册链接过多，请等待旧链接过期。')
            state['grants'][digest]={'expires':now+GRANT_SECONDS,'local_owner':local_owner}
        return token,now+GRANT_SECONDS

    def grant_digest(self, token):
        if not isinstance(token,str) or not 40<=len(token)<=100:
            raise PasskeyError('注册链接无效或已过期，请在服务电脑重新生成。')
        try:
            return hashlib.sha256(token.encode('ascii')).hexdigest()
        except UnicodeError:
            raise PasskeyError('注册链接无效。') from None

    def check_grant(self, state, digest):
        grant=state['grants'].get(digest)
        if not grant or grant['expires']<time.time():
            raise PasskeyError('注册链接已使用或已过期，请重新生成。')

    def ceremony(self, kind, client_ip, *, grant=None, session=None, label=None, replace=None):
        now=time.time()
        self.pending={key:item for key,item in self.pending.items() if item['expires']>now}
        if replace:
            self.pending.pop(replace,None)
        if len(self.pending)>=256 or sum(item['ip']==client_ip for item in self.pending.values())>=8:
            raise PasskeyError('验证请求过多，请稍后重试。')
        challenge=secrets.token_bytes(32)
        token=secrets.token_urlsafe(32)
        self.pending[token]={'kind':kind,'ip':client_ip,'expires':now+CEREMONY_SECONDS,
            'challenge':challenge,'grant':grant,'session':session,'label':label}
        return token,challenge

    def take(self, token, kind, client_ip):
        item=self.pending.pop(token,None)
        if not item or item['kind']!=kind or item['ip']!=client_ip or item['expires']<time.time():
            raise PasskeyError('验证已过期，请重新点击按钮。')
        return item

    def begin_registration(self, token, label, client_ip, *, session=None, replace=None):
        if not isinstance(label,str) or not 1<=len(label.strip())<=64:
            raise PasskeyError('请填写 1 至 64 字符的设备名称。')
        digest=self.grant_digest(token) if token else None
        with self.state() as state:
            active=[item for item in state['credentials'].values() if not item.get('revoked')]
            if len(active)>=16:
                raise PasskeyError('最多保留 16 把 Passkey，请先移除不用的设备。')
            if digest:
                self.check_grant(state,digest)
            elif not session or not self.active_in_state(state,session['credential_id']):
                raise PasskeyError('请先使用 Passkey 登录，或使用服务电脑生成的注册链接。')
            ceremony,challenge=self.ceremony('registration',client_ip,grant=digest,
                session=session['id'] if session else None,label=label.strip(),replace=replace)
            options=generate_registration_options(rp_id=self.rp_id,rp_name='Qwen Image 局域网',
                user_id=base64url_to_bytes(state['user_id']),user_name='qwen',user_display_name='Qwen Image',
                challenge=challenge,timeout=CEREMONY_SECONDS*1000,
                authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(item['id'])) for item in active],
                supported_pub_key_algs=[COSEAlgorithmIdentifier.ECDSA_SHA_256,COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256])
        return ceremony,json.loads(options_to_json(options))

    @staticmethod
    def active_in_state(state, credential_id):
        item=state['credentials'].get(credential_id)
        return bool(item and not item.get('revoked'))

    @staticmethod
    def check_client_data(credential):
        try:
            client=json.loads(base64url_to_bytes(credential['response']['clientDataJSON']))
            if not isinstance(client,dict) or client.get('crossOrigin',False) is not False or client.get('topOrigin'):
                raise ValueError()
        except (ValueError,KeyError,TypeError):
            raise PasskeyError('不允许跨站或嵌入页面中的 Passkey 请求。') from None

    def finish_registration(self, token, credential, client_ip, *, session=None):
        pending=self.take(token,'registration',client_ip)
        self.check_client_data(credential)
        try:
            verified=verify_registration_response(credential=credential,expected_challenge=pending['challenge'],
                expected_rp_id=self.rp_id,expected_origin=self.origin,require_user_verification=True,
                supported_pub_key_algs=[COSEAlgorithmIdentifier.ECDSA_SHA_256,COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256])
        except Exception:
            raise PasskeyError('Passkey 创建验证失败，请重新创建并完成设备确认。') from None
        credential_id=bytes_to_base64url(verified.credential_id)
        with self.state() as state:
            if pending['grant']:
                self.check_grant(state,pending['grant'])
            elif not session or session['id']!=pending['session'] or not self.active_in_state(state,session['credential_id']):
                raise PasskeyError('登录已失效，请重新登录。')
            if credential_id in state['credentials']:
                raise PasskeyError('这把 Passkey 已注册，请使用它登录。')
            if sum(not item.get('revoked') for item in state['credentials'].values())>=16:
                raise PasskeyError('Passkey 数量已满。')
            now=int(time.time())
            state['credentials'][credential_id]={'id':credential_id,'label':pending['label'],'created':now,'last_used':now,
                'last_authenticated':None,
                'public_key':bytes_to_base64url(verified.credential_public_key),'sign_count':verified.sign_count,
                'device_type':verified.credential_device_type.value,'backed_up':verified.credential_backed_up,'revoked':False}
            if pending['grant']:
                state['grants'].pop(pending['grant'])
        return credential_id

    def begin_login(self, client_ip, *, replace=None):
        if not self.credentials():
            raise PasskeyError('尚未设置 Passkey，请先在服务电脑完成首次注册。')
        token,challenge=self.ceremony('authentication',client_ip,replace=replace)
        options=generate_authentication_options(rp_id=self.rp_id,challenge=challenge,
            user_verification=UserVerificationRequirement.REQUIRED,timeout=CEREMONY_SECONDS*1000)
        return token,json.loads(options_to_json(options))

    def finish_login(self, token, credential, client_ip):
        pending=self.take(token,'authentication',client_ip)
        self.check_client_data(credential)
        if not isinstance(credential.get('id'),str) or len(credential['id'])>4096:
            raise PasskeyError('Passkey 格式不正确。')
        try:
            credential_id=bytes_to_base64url(base64url_to_bytes(credential['id']))
        except (KeyError,TypeError,ValueError):
            raise PasskeyError('Passkey 格式不正确。') from None
        with self.state() as state:
            item=state['credentials'].get(credential_id)
            if not item or item.get('revoked'):
                raise PasskeyError('这把 Passkey 未注册或已移除。')
            if credential.get('response',{}).get('userHandle')!=state['user_id']:
                raise PasskeyError('Passkey 用户验证失败。')
            try:
                verified=verify_authentication_response(credential=credential,expected_challenge=pending['challenge'],
                    expected_rp_id=self.rp_id,expected_origin=self.origin,
                    credential_public_key=base64url_to_bytes(item['public_key']),
                    credential_current_sign_count=item['sign_count'],require_user_verification=True)
            except Exception:
                raise PasskeyError('Passkey 签名验证失败，请重新登录并完成设备确认。') from None
            item.update(sign_count=verified.new_sign_count,last_used=int(time.time()),last_authenticated=int(time.time()),
                        device_type=verified.credential_device_type.value,backed_up=verified.credential_backed_up)
        return credential_id

    def revoke(self, credential_id):
        with self.state() as state:
            if not self.active_in_state(state,credential_id):
                raise PasskeyError('未找到这把 Passkey。')
            if sum(not item.get('revoked') for item in state['credentials'].values())<=1:
                raise PasskeyError('请至少保留一把 Passkey；先添加新设备，再移除旧设备。')
            state['credentials'][credential_id]['revoked']=True
            state['credentials'][credential_id]['revoked_at']=int(time.time())
