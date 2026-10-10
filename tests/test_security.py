import base64
import json
import io
from pathlib import Path
import tempfile
import time
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"service"))

from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
import httpx
from PIL import Image

from archive import Archive
from main import make_app, SIGMAS
from security import Cipher, initialize_keys
from images import prepare_reference, MAX_IMAGE_BYTES
from test_authenticator import TestAuthenticator

HOST = 'https://qwen-test.local:8443'
IMAGE = b'\x89PNG\r\n\x1a\nsecure-archive-test'

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='qwen-security-',dir=str(Path(__file__).parents[1]))
        self.root = Path(self.temporary.name)
        self.keys = initialize_keys(self.root/'keys.dpapi')
        self.config = {'keys':str(self.root/'keys.dpapi'),'archive':str(self.root/'archive'),
                       'backend':'http://backend','network':'192.168.50.0/24',
                       'hosts':['qwen-test.local','192.168.50.10'],'webui':str(Path(__file__).parents[1]/'vendor/webui.html'),
                       'passkeys':str(self.root/'passkeys.dpapi'),'rp_id':'qwen-test.local','origin':HOST,'port':8443,
                       'ca_der':str(self.root/'ca.cer')}
        self.calls = []
        def backend(request):
            if request.method == 'POST':
                self.calls.append(json.loads(request.content))
                return httpx.Response(202,json={'id':'job_test','kind':'img_gen','status':'queued','created':int(time.time()),'poll_url':'/sdcpp/v1/jobs/job_test'})
            return httpx.Response(200,json={'id':'job_test','kind':'img_gen','status':'completed','created':int(time.time()),
                'started':int(time.time()),'completed':int(time.time()),'queue_position':0,'error':None,
                'result':{'output_format':'png','images':[{'index':0,'b64_json':base64.b64encode(IMAGE).decode()}]}})
        self.transport = httpx.MockTransport(backend)

    def tearDown(self):
        self.temporary.cleanup()

    def client(self,remote='127.0.0.1'):
        return TestClient(make_app(self.config,self.transport),base_url=HOST,client=(remote,50000))

    def login(self,client):
        authenticator=TestAuthenticator()
        token,_=client.app.state.gateway.passkeys.create_grant(local_owner=True)
        options=client.post('/auth/register/options',json={'enrollment_token':token,'label':'test'},headers={'Origin':HOST}).json()
        response=client.post('/auth/register/verify',json=authenticator.registration(options,HOST),headers={'Origin':HOST})
        self.assertEqual(response.status_code,200)
        self.assertIn('httponly',response.headers['set-cookie'].lower())
        self.assertIn('secure',response.headers['set-cookie'].lower())
        return {'Origin':HOST,'X-Qwen-CSRF':client.get('/session').json()['csrf']}

    def test_encryption_tamper_and_scope(self):
        cipher = Cipher(base64.b64decode(self.keys['archive_key']))
        ciphertext = cipher.encrypt(b'private prompt and pixels','test/metadata')
        self.assertNotIn(b'private prompt',ciphertext)
        self.assertEqual(cipher.decrypt(ciphertext,'test/metadata'),b'private prompt and pixels')
        with self.assertRaises(InvalidTag):
            cipher.decrypt(ciphertext,'another/record')
        with self.assertRaises(InvalidTag):
            cipher.decrypt(ciphertext[:-1]+bytes([ciphertext[-1]^1]),'test/metadata')

    def test_auth_csrf_and_logout(self):
        with self.client() as client:
            self.assertEqual(client.get('/',follow_redirects=False).status_code,303)
            self.assertEqual(client.get('/archive/records').status_code,401)
            self.assertEqual(client.post('/login',json={'username':'qwen','password':'incorrect'},headers={'Origin':HOST}).status_code,410)
            self.assertNotIn('type="password"',client.get('/login').text)
            headers = self.login(client)
            self.assertEqual(client.post('/sdcpp/v1/img_gen',json={'prompt':'hello'},headers={'Origin':HOST}).status_code,403)
            self.assertEqual(client.post('/sdcpp/v1/img_gen',json={'prompt':'hello'},headers={**headers,'Origin':'https://untrusted.example'}).status_code,403)
            self.assertEqual(client.get('/sdcpp/v1/jobs/unowned-job').status_code,404)
            self.assertEqual(client.post('/logout',headers=headers).status_code,200)
            self.assertEqual(client.get('/archive/records').status_code,401)

    def test_network_and_host_restrictions(self):
        with self.client(remote='203.0.113.7') as client:
            self.assertEqual(client.get('/health',headers={'X-Forwarded-For':'192.168.60.96'}).status_code,403)
        with self.client() as client:
            self.assertEqual(client.get('/health',headers={'Host':'untrusted.example'}).status_code,400)
            self.assertEqual(client.get('http://192.168.50.10:8443/health').status_code,400)

    def test_durable_capture_without_browser_polling(self):
        prompt = 'retain-test-中文提示词-<script>literal</script>'
        with self.client() as client:
            headers = self.login(client)
            response = client.post('/sdcpp/v1/img_gen',json={'prompt':prompt,'sample_params':{'custom_sigmas':[]}},headers=headers)
            self.assertEqual(response.status_code,202)
            deadline = time.time()+5
            while time.time()<deadline:
                records = client.get('/archive/records').json()['records']
                if records[0]['status']=='completed':
                    break
                time.sleep(.05)
            self.assertEqual(records[0]['status'],'completed')
            record = records[0]
            self.assertEqual(record['request']['prompt'],prompt)
            self.assertEqual(self.calls[0]['sample_params']['custom_sigmas'],SIGMAS)
            self.assertEqual(client.get('/archive/records/'+record['id']+'/images/0').content,IMAGE)
        for path in (self.root/'archive').iterdir():
            self.assertNotIn(prompt.encode(),path.read_bytes())
            self.assertNotIn(IMAGE,path.read_bytes())
        with self.client() as reopened:
            self.login(reopened)
            recovered = reopened.get('/archive/records').json()['records'][0]
            self.assertEqual(recovered['status'],'completed')
            self.assertEqual(reopened.get('/archive/records/'+recovered['id']+'/images/0').content,IMAGE)
            self.assertEqual(reopened.get('/sdcpp/v1/jobs/job_test').json()['status'],'completed')

    def reference(self, size=(2048,1024)):
        buffer=io.BytesIO()
        Image.new('RGB',size,'orange').save(buffer,format='PNG')
        return buffer.getvalue()

    def test_reference_validation_and_memory_bounds(self):
        original=self.reference()
        retained,descriptor,normalized=prepare_reference(base64.b64encode(original).decode())
        self.assertEqual(retained,original)
        self.assertEqual((descriptor['model_width'],descriptor['model_height']),(1024,512))
        with Image.open(io.BytesIO(base64.b64decode(normalized.split(',',1)[1]))) as decoded:
            self.assertEqual(decoded.size,(1024,512))
        for size in ((777,509),(8192,32)):
            _,geometry,_=prepare_reference(base64.b64encode(self.reference(size)).decode())
            self.assertTrue(32<=geometry['model_width']<=1024)
            self.assertTrue(32<=geometry['model_height']<=1024)
            self.assertEqual(geometry['model_width']%32,0)
            self.assertEqual(geometry['model_height']%32,0)
        for invalid in ('https://example.com/image.png','data:image/svg+xml;base64,PHN2Zz4=',123,
                        base64.b64encode(b'not an image').decode(), 'A'*(((MAX_IMAGE_BYTES+2)//3)*4+4)):
            with self.assertRaises(ValueError):
                prepare_reference(invalid)

    def test_editing_archive_and_invalid_requests(self):
        original=self.reference()
        encoded='data:image/png;base64,'+base64.b64encode(original).decode()
        with self.client() as client:
            self.assertEqual(client.get('/edit',follow_redirects=False).status_code,303)
            self.assertEqual(client.get('/archive/records/'+'a'*32+'/references/0').status_code,401)
            headers=self.login(client)
            self.assertIn('参考图改图',client.get('/edit').text)
            for update in ({'ref_images':[encoded,encoded]}, {'ref_images':['invalid']},
                           {'ref_images':'invalid'}, {'ref_images':[encoded],'width':1536},
                           {'ref_images':[encoded],'batch_count':2}, {'init_image':encoded}):
                response=client.post('/sdcpp/v1/img_gen',json={'prompt':'edit-test-中文',**update},headers=headers)
                self.assertEqual(response.status_code,400,response.text)
            self.assertEqual(self.calls,[])
            response=client.post('/sdcpp/v1/img_gen',json={'prompt':'edit-test-中文','ref_images':[encoded],
                'image_preprocess':'unbounded','ref_image_args':'resize_before_vae=true'},headers=headers)
            self.assertEqual(response.status_code,202)
            deadline=time.time()+5
            while time.time()<deadline:
                record=client.get('/archive/records').json()['records'][0]
                if record['status']=='completed':break
                time.sleep(.05)
            self.assertEqual(record['status'],'completed')
            record_id=record['id']
            self.assertEqual(record['mode'],'editing')
            self.assertNotIn('ref_images',record['request'])
            self.assertEqual(record['references'][0]['width'],2048)
            self.assertEqual(client.get('/archive/records/'+record_id+'/references/0').content,original)
            self.assertEqual(client.get('/archive/records/'+record_id+'/references/1').status_code,404)
            self.assertEqual(self.calls[0]['ref_image_args'],'resize_before_vae=false')
            self.assertEqual(self.calls[0]['image_preprocess'],'target=ref,mode=none')
            self.assertNotEqual(self.calls[0]['ref_images'][0],encoded)
        cipher=Cipher(base64.b64decode(self.keys['archive_key']))
        path=self.root/'archive'/(record_id+'.0.reference.enc')
        self.assertNotIn(original,path.read_bytes())
        with self.assertRaises(InvalidTag):
            cipher.decrypt(path.read_bytes(),record_id+'/image/0/v1')
        with self.client() as reopened:
            self.login(reopened)
            self.assertEqual(reopened.get('/archive/records/'+record_id+'/references/0').content,original)
            self.assertEqual(reopened.get('/archive/records/'+record_id+'/images/0').content,IMAGE)

    def enroll(self,client,authenticator=None,label='test'):
        authenticator=authenticator or TestAuthenticator()
        token,_=client.app.state.gateway.passkeys.create_grant(local_owner=True)
        response=client.post('/auth/register/options',json={'enrollment_token':token,'label':label},headers={'Origin':HOST})
        self.assertEqual(response.status_code,200,response.text)
        response=client.post('/auth/register/verify',json=authenticator.registration(response.json(),HOST),headers={'Origin':HOST})
        self.assertEqual(response.status_code,200,response.text)
        return authenticator,token

    def test_passkey_enrollment_grants_and_domain(self):
        with self.client() as client:
            self.assertEqual(client.get('https://192.168.50.10:8443/login',follow_redirects=False).headers['location'],HOST+'/login')
            self.assertEqual(client.post('/auth/register/options',json={'label':'random visitor'},headers={'Origin':HOST}).status_code,403)
            self.assertEqual(client.post('/auth/register/options',json={'enrollment_token':'invalid','label':'invalid'},headers={'Origin':HOST}).status_code,403)
            authenticator,token=self.enroll(client)
            self.assertEqual(client.post('/auth/register/options',json={'enrollment_token':token,'label':'replay'},headers={'Origin':HOST}).status_code,403)
            headers={'Origin':HOST,'X-Qwen-CSRF':client.get('/session').json()['csrf']}
            key_id=client.get('/auth/passkeys').json()['current']
            self.assertEqual(client.post('/auth/passkeys/'+key_id+'/revoke',headers=headers).status_code,400)
            self.assertEqual(client.post('/auth/enrollment',headers={'Origin':HOST}).status_code,403)
            invite=client.post('/auth/enrollment',headers=headers)
            self.assertEqual(invite.status_code,200)
            self.assertNotIn('public_key',client.get('/auth/passkeys').text)
        persisted=(self.root/'passkeys.dpapi').read_bytes()
        self.assertNotIn(b'"credentials"',persisted)
        self.assertNotIn(authenticator.user_id.encode(),persisted)

    def test_passkey_authentication_signature_and_replay(self):
        with self.client() as client:
            authenticator,_=self.enroll(client)
            session=client.get('/session').json()
            client.post('/logout',headers={'Origin':HOST,'X-Qwen-CSRF':session['csrf']})
            options=client.post('/auth/login/options',headers={'Origin':HOST})
            self.assertEqual(options.json()['userVerification'],'required')
            cookie=client.cookies.get('__Host-qwen-ceremony')
            response_data=authenticator.authentication(options.json(),HOST)
            response=client.post('/auth/login/verify',json=response_data,headers={'Origin':HOST})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/archive/records').status_code,200)
            client.cookies.set('__Host-qwen-ceremony',cookie,domain='qwen-test.local',path='/')
            self.assertEqual(client.post('/auth/login/verify',json=response_data,headers={'Origin':HOST}).status_code,401)
        with self.client() as restarted:
            options=restarted.post('/auth/login/options',headers={'Origin':HOST})
            response=restarted.post('/auth/login/verify',json=authenticator.authentication(options.json(),HOST),headers={'Origin':HOST})
            self.assertEqual(response.status_code,200,response.text)

    def test_passkey_rejects_wrong_origin_uv_challenge_signature_and_counter(self):
        with self.client() as client:
            authenticator,_=self.enroll(client)
            invalid=[{'uv':False},{'origin':'https://untrusted.example'},{'challenge':'untrusted-challenge'},
                     {'rp_id':'untrusted.example'},{'bad_signature':True},{'crossOrigin':True}]
            for changes in invalid:
                options=client.post('/auth/login/options',headers={'Origin':HOST}).json()
                changes=dict(changes)
                origin=changes.pop('origin',HOST)
                response=client.post('/auth/login/verify',json=authenticator.authentication(options,origin,**changes),headers={'Origin':HOST})
                self.assertEqual(response.status_code,401,response.text)
            options=client.post('/auth/login/options',headers={'Origin':HOST}).json()
            self.assertEqual(client.post('/auth/login/verify',json=authenticator.authentication(options,HOST),headers={'Origin':HOST}).status_code,200)
            options=client.post('/auth/login/options',headers={'Origin':HOST}).json()
            self.assertEqual(client.post('/auth/login/verify',json=authenticator.authentication(options,HOST,counter=1),headers={'Origin':HOST}).status_code,401)

    def test_passkey_registration_requires_user_verification(self):
        with self.client() as client:
            token,_=client.app.state.gateway.passkeys.create_grant(local_owner=True)
            options=client.post('/auth/register/options',json={'enrollment_token':token,'label':'test'},headers={'Origin':HOST}).json()
            self.assertEqual(options['authenticatorSelection']['residentKey'],'required')
            self.assertEqual(options['authenticatorSelection']['userVerification'],'required')
            response=client.post('/auth/register/verify',json=TestAuthenticator().registration(options,HOST,uv=False),headers={'Origin':HOST})
            self.assertEqual(response.status_code,401)
            self.assertEqual(client.get('/auth/status').json()['configured'],False)

    def test_passkey_revocation_invalidates_existing_sessions(self):
        with self.client() as client:
            first,_=self.enroll(client)
            first_session_cookie=client.cookies.get('__Host-qwen-session')
            first_id=client.get('/auth/passkeys').json()['current']
            self.enroll(client,label='second device')
            headers={'Origin':HOST,'X-Qwen-CSRF':client.get('/session').json()['csrf']}
            self.assertEqual(client.post('/auth/passkeys/'+first_id+'/revoke',headers=headers).status_code,200)
            client.cookies.set('__Host-qwen-session',first_session_cookie,domain='qwen-test.local',path='/')
            self.assertEqual(client.get('/archive/records').status_code,401)
            options=client.post('/auth/login/options',headers={'Origin':HOST}).json()
            self.assertEqual(client.post('/auth/login/verify',json=first.authentication(options,HOST),headers={'Origin':HOST}).status_code,401)

if __name__=='__main__':
    unittest.main(verbosity=2)
