import asyncio
import base64
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import copy
import ipaddress
import json
from pathlib import Path
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
import httpx

from archive import Archive
from pages import LOGIN, HISTORY, NATIVE_NAV, EDIT, REGISTER, PASSKEY_MANAGEMENT
from security import Sessions, load_keys
from images import prepare_reference
from passkeys import Passkeys, PasskeyError, CEREMONY_COOKIE, CEREMONY_SECONDS

SIGMAS = [1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0]
COOKIE = '__Host-qwen-session'

class Gateway:
    def __init__(self, config, transport=None):
        self.config = config
        self.keys = load_keys(Path(config['keys']))
        self.archive = Archive(Path(config['archive']), base64.b64decode(self.keys['archive_key']))
        self.sessions = Sessions(base64.b64decode(self.keys['session_key']))
        self.passkeys = Passkeys(config['passkeys'],config['rp_id'],config['origin'])
        self.records = {item['id']:item for item in self.archive.list()}
        self.jobs = {item['job_id']:item['id'] for item in self.records.values() if item.get('job_id')}
        self.tasks = {}
        self.failures = defaultdict(deque)
        self.backend = httpx.AsyncClient(base_url=config['backend'], trust_env=False, timeout=30, transport=transport)

    def save(self, record):
        self.archive.save(record)
        self.records[record['id']] = record

    def start_tracking(self, record):
        if record['id'] not in self.tasks:
            task = asyncio.create_task(self.track(record['id']))
            self.tasks[record['id']] = task
            task.add_done_callback(lambda done, record_id=record['id']: self.tasks.pop(record_id, None))

    def complete(self, record, job):
        if self.records[record['id']]['status'] == 'completed':
            return
        result = job.get('result') or {}
        image_format = result.get('output_format','png')
        if image_format not in ('png','jpeg','webp'):
            raise ValueError('Unsupported image format.')
        images = result.get('images') or []
        if not images or len(images)>4:
            raise ValueError('Invalid completed image count.')
        image_records = []
        for index,image in enumerate(images):
            data = base64.b64decode(image['b64_json'],validate=True)
            self.archive.store_image(record['id'],index,data)
            image_records.append({'index':index,'format':image_format,'bytes':len(data)})
        completed_record = {**record,'status':'completed','images':image_records,
                            'completed':job.get('completed',int(time.time())),
                            'started':job.get('started'),'error':None}
        self.save(completed_record)

    async def track(self, record_id):
        failures = 0
        while True:
            record = self.records[record_id]
            try:
                response = await self.backend.get('/sdcpp/v1/jobs/' + record['job_id'])
                if response.status_code in (404,410):
                    record.update(status='failed', error='模型服务已重启或任务已过期；原提示词与参数已保留。')
                    self.save(record)
                    return
                response.raise_for_status()
                job = response.json()
                failures = 0
                if job['status'] == 'completed':
                    self.complete(record,job)
                    return
                if job['status'] in ('failed','cancelled'):
                    record.update(status=job['status'], error=job.get('error'), completed=job.get('completed'))
                    self.save(record)
                    return
                if record['status'] != job['status']:
                    record['status'] = job['status']
                    self.save(record)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, KeyError, ValueError, OSError):
                failures += 1
                if failures >= 30:
                    record.update(status='failed', error='无法读取模型任务结果；原提示词与参数已保留。')
                    self.save(record)
                    return
            await asyncio.sleep(2)

    def job_snapshot(self, record):
        job = {key:record.get(key) for key in ('created','started','completed','status','error')}
        job.update(id=record['job_id'], kind='img_gen', queue_position=0, result=None)
        if record['status'] == 'completed':
            job['result'] = {'output_format':record['images'][0]['format'], 'images':[
                {'index':image['index'], 'b64_json':base64.b64encode(self.archive.read_image(record['id'],image['index'])).decode('ascii')}
                for image in record['images']]}
        return job

async def read_json(request, limit=128*1024):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, '请求内容过大。')
    try:
        data = json.loads(body)
        if not isinstance(data,dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError):
        raise HTTPException(400, '请求格式不正确。')

def make_app(config, transport=None):
    gateway = Gateway(config,transport)
    network = ipaddress.ip_network(config['network'])

    @asynccontextmanager
    async def lifespan(app):
        for record in gateway.records.values():
            if record['status'] in ('queued','generating') and record.get('job_id'):
                gateway.start_tracking(record)
            elif record['status'] == 'submitting':
                record.update(status='failed', error='提交时服务中断；原提示词与参数已保留。')
                gateway.save(record)
        yield
        tasks = list(gateway.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await gateway.backend.aclose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.gateway = gateway
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config['hosts'])

    def secure(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Permissions-Policy'] = 'publickey-credentials-create=(self), publickey-credentials-get=(self)'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        return response

    @app.middleware('http')
    async def security_layer(request, call_next):
        try:
            address = ipaddress.ip_address(request.client.host)
        except ValueError:
            return secure(JSONResponse({'detail':'仅允许局域网访问。'},status_code=403))
        if not address.is_loopback and address not in network:
            return secure(JSONResponse({'detail':'仅允许局域网访问。'},status_code=403))
        if request.url.scheme != 'https':
            return secure(JSONResponse({'detail':'请使用 HTTPS 访问。'},status_code=400))
        path = request.url.path
        if request.url.hostname not in {host.lower() for host in config['hosts']}:
            return secure(JSONResponse({'detail':'访问域名不正确。'},status_code=400))
        if (request.url.hostname != config['rp_id'] or request.url.port != config['port']) and path not in ('/health','/ca.cer'):
            if request.method in ('GET','HEAD'):
                return secure(RedirectResponse(config['origin']+path+('?' + request.url.query if request.url.query else ''),status_code=303))
            if path != '/login':
                return secure(JSONResponse({'detail':'请使用 Passkey 域名入口访问。'},status_code=421))
        public = path in ('/login','/health','/ca.cer','/register','/auth/status',
                         '/auth/login/options','/auth/login/verify','/auth/register/options','/auth/register/verify')
        session = gateway.sessions.read(request.cookies.get(COOKIE,''))
        if session and not gateway.passkeys.active(session.get('credential_id')):
            session = None
        request.state.session = session
        if not public and not session:
            if path in ('/','/history','/edit','/passkeys'):
                return secure(RedirectResponse('/login',status_code=303))
            return secure(JSONResponse({'detail':'请先登录。'},status_code=401))
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin','')
            expected_origin = config['origin']
            if origin != expected_origin or request.headers.get('sec-fetch-site') == 'cross-site':
                return secure(JSONResponse({'detail':'请求来源验证失败。'},status_code=403))
            if path not in ('/login','/auth/login/options','/auth/login/verify','/auth/register/options','/auth/register/verify') and (not session or request.headers.get('x-qwen-csrf') != session['csrf']):
                return secure(JSONResponse({'detail':'请求验证失败，请刷新页面。'},status_code=403))
        return secure(await call_next(request))

    @app.get('/health')
    async def health():
        return {'status':'ok','scope':'lan-only','encrypted_archive':True,'authentication':'passkey'}

    @app.get('/ca.cer')
    async def ca_certificate():
        return FileResponse(config['ca_der'],media_type='application/pkix-cert',filename='Qwen-LAN-CA.cer')

    @app.get('/login')
    async def login_page():
        return HTMLResponse(LOGIN)

    @app.post('/login')
    async def login(request: Request):
        raise HTTPException(410,'密码登录已移除，请使用 Passkey 登录。')

    @app.get('/register')
    async def register_page():
        return HTMLResponse(REGISTER)

    @app.get('/passkeys')
    async def passkey_management():
        return HTMLResponse(PASSKEY_MANAGEMENT)

    @app.get('/auth/status')
    async def auth_status(request: Request):
        return {'authentication':'passkey','configured':bool(gateway.passkeys.credentials()),
                'authenticated':bool(request.state.session)}

    def rate_limit(request):
        attempts = gateway.failures[request.client.host]
        while attempts and attempts[0] < time.time()-300:
            attempts.popleft()
        if len(attempts) >= 8:
            raise HTTPException(429,'登录尝试过多，请 5 分钟后重试。')
        return attempts

    def ceremony_response(token, options):
        response = JSONResponse(options)
        response.set_cookie(CEREMONY_COOKIE,token,max_age=CEREMONY_SECONDS,httponly=True,secure=True,samesite='strict',path='/')
        return response

    def login_response(credential_id):
        token,session = gateway.sessions.create(credential_id)
        response = JSONResponse({'ok':True})
        response.set_cookie(COOKIE,token,max_age=28800,httponly=True,secure=True,samesite='strict',path='/')
        response.delete_cookie(CEREMONY_COOKIE,path='/',secure=True,httponly=True,samesite='strict')
        return response

    def fresh_session(request):
        session = request.state.session
        if not session or time.time()-session['verified_at']>300:
            raise HTTPException(403,'管理 Passkey 前请重新使用 Passkey 登录。')
        return session

    @app.post('/auth/login/options')
    async def login_options(request: Request):
        rate_limit(request)
        try:
            token,options=gateway.passkeys.begin_login(request.client.host,replace=request.cookies.get(CEREMONY_COOKIE))
            return ceremony_response(token,options)
        except PasskeyError as error:
            raise HTTPException(400,str(error))

    @app.post('/auth/login/verify')
    async def login_verify(request: Request):
        attempts=rate_limit(request)
        credential=await read_json(request,96*1024)
        try:
            credential_id=gateway.passkeys.finish_login(request.cookies.get(CEREMONY_COOKIE),credential,request.client.host)
        except PasskeyError as error:
            attempts.append(time.time())
            raise HTTPException(401,str(error))
        attempts.clear()
        return login_response(credential_id)

    @app.post('/auth/register/options')
    async def register_options(request: Request):
        rate_limit(request)
        data=await read_json(request,4096)
        session=request.state.session
        if not data.get('enrollment_token'):
            session=fresh_session(request)
            if request.headers.get('x-qwen-csrf')!=session['csrf']:
                raise HTTPException(403,'请求验证失败，请刷新页面。')
        try:
            token,options=gateway.passkeys.begin_registration(data.get('enrollment_token'),data.get('label','这台设备'),
                request.client.host,session=session,replace=request.cookies.get(CEREMONY_COOKIE))
            return ceremony_response(token,options)
        except PasskeyError as error:
            raise HTTPException(403,str(error))

    @app.post('/auth/register/verify')
    async def register_verify(request: Request):
        attempts=rate_limit(request)
        credential=await read_json(request,96*1024)
        try:
            credential_id=gateway.passkeys.finish_registration(request.cookies.get(CEREMONY_COOKIE),credential,
                request.client.host,session=request.state.session)
        except PasskeyError as error:
            attempts.append(time.time())
            raise HTTPException(401,str(error))
        attempts.clear()
        return login_response(credential_id)

    @app.get('/auth/passkeys')
    async def passkey_list(request: Request):
        return {'credentials':gateway.passkeys.credentials(),'current':request.state.session['credential_id']}

    @app.post('/auth/enrollment')
    async def enrollment(request: Request):
        fresh_session(request)
        try:
            token,expires=gateway.passkeys.create_grant()
            return {'url':config['origin']+'/register#enroll='+token,'expires':expires}
        except PasskeyError as error:
            raise HTTPException(400,str(error))

    @app.post('/auth/passkeys/{credential_id}/revoke')
    async def revoke_passkey(credential_id: str,request: Request):
        fresh_session(request)
        try:
            gateway.passkeys.revoke(credential_id)
            return {'ok':True}
        except PasskeyError as error:
            raise HTTPException(400,str(error))

    @app.post('/logout')
    async def logout(request: Request):
        gateway.sessions.revoke(request.state.session)
        response = JSONResponse({'ok':True})
        response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict')
        return response

    @app.get('/session')
    async def session_info(request: Request):
        return {'username':gateway.keys['username'],'csrf':request.state.session['csrf']}

    @app.get('/')
    async def native_ui():
        html = Path(config['webui']).read_text(encoding='utf-8')
        return HTMLResponse(html.replace('<body>','<body>'+NATIVE_NAV,1))

    @app.get('/history')
    async def history():
        return HTMLResponse(HISTORY)

    @app.get('/edit')
    async def editing():
        return HTMLResponse(EDIT)

    @app.get('/sdcpp/v1/capabilities')
    async def capabilities():
        try:
            response = await gateway.backend.get('/sdcpp/v1/capabilities')
            response.raise_for_status()
            return JSONResponse(response.json())
        except httpx.HTTPError:
            raise HTTPException(503,'生图引擎暂不可用。')

    @app.post('/sdcpp/v1/img_gen')
    async def submit(request: Request):
        data = await read_json(request,12*1024*1024)
        prompt = data.get('prompt','')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>12000:
            raise HTTPException(400,'请填写 1 至 12000 字符的提示词。')
        if any(data.get(key) for key in ('init_image','mask_image','control_image','ip_adapter_image','end_image','control_frames')):
            raise HTTPException(400,'改图请使用“参考图片”；暂不支持初始图片、蒙版或控制图片。')
        references = data.get('ref_images',[])
        if references is None:
            references = []
        if not isinstance(references,list) or len(references)>1:
            raise HTTPException(400,'当前改图支持一张参考图片。')
        prepared_reference = None
        if references:
            try:
                prepared_reference = await asyncio.to_thread(prepare_reference,references[0])
            except ValueError as error:
                raise HTTPException(400,str(error))
            data['ref_images'] = [prepared_reference[2]]
            # Bound native preprocessing as well as the uploaded image.
            data['image_preprocess'] = 'target=ref,mode=none'
            data['ref_image_args'] = 'resize_before_vae=false'
            data['auto_resize_ref_image'] = False
            data['increase_ref_index'] = False
        if sum(record['status'] in ('submitting','queued','generating') for record in gateway.records.values()) >= 8:
            raise HTTPException(429,'队列已满，请稍后提交。')
        for field in ('width','height'):
            value = data.get(field,1024)
            if type(value) is not int or value<256 or value>1536 or value%32:
                raise HTTPException(400,'图片宽高应为 256 至 1536 范围内的 32 的倍数。')
            data[field] = value
        batch = data.get('batch_count',1)
        if type(batch) is not int or not 1<=batch<=4:
            raise HTTPException(400,'生成数量应为 1 至 4。')
        if prepared_reference and (max(data['width'],data['height'])>1024 or batch!=1):
            raise HTTPException(400,'改图输出最长边不超过 1024，每次生成一张。')
        sampling = data.setdefault('sample_params',{})
        if not isinstance(sampling,dict):
            raise HTTPException(400,'采样参数格式不正确。')
        sampling.update(custom_sigmas=SIGMAS,sample_steps=8,sample_method='euler')
        if not isinstance(sampling.get('guidance',{}),dict):
            raise HTTPException(400,'引导参数格式不正确。')
        sampling.setdefault('guidance',{})['txt_cfg'] = 1.0
        image_format = data.get('output_format','png')
        if image_format not in ('png','jpeg','webp'):
            raise HTTPException(400,'输出格式应为 PNG、JPEG 或 WebP。')
        data['output_format'] = image_format
        data['hires'] = {'enabled':False}
        retained_request = copy.deepcopy(data)
        retained_request.pop('ref_images',None)
        record = gateway.archive.create({'created':int(time.time()),'status':'submitting','request':retained_request,
            'references':[prepared_reference[1]] if prepared_reference else [],
            'mode':'editing' if prepared_reference else 'text-to-image','job_id':None,'error':None})
        gateway.records[record['id']] = record
        try:
            if prepared_reference:
                gateway.archive.store_reference(record['id'],0,prepared_reference[0])
            response = await gateway.backend.post('/sdcpp/v1/img_gen',json=data)
            response.raise_for_status()
            job = response.json()
            record.update(job_id=job['id'],status=job['status'])
            gateway.save(record)
            gateway.jobs[job['id']] = record['id']
            gateway.start_tracking(record)
            return JSONResponse(job,status_code=202)
        except (httpx.HTTPError,KeyError,ValueError,OSError):
            record.update(status='failed',error='提交生图任务失败；提示词和参数已保存。')
            gateway.save(record)
            raise HTTPException(503,'提交失败，提示词和参数已保存，可稍后重试。')

    @app.get('/sdcpp/v1/jobs/{job_id}')
    async def job_status(job_id: str):
        record_id = gateway.jobs.get(job_id)
        if not record_id:
            raise HTTPException(404,'未找到任务。')
        record = gateway.records[record_id]
        if record['status'] in ('completed','failed','cancelled'):
            return gateway.job_snapshot(record)
        try:
            response = await gateway.backend.get('/sdcpp/v1/jobs/'+job_id)
            response.raise_for_status()
            job = response.json()
            if job['status'] == 'completed':
                gateway.complete(record,job)
                return gateway.job_snapshot(gateway.records[record_id])
            return job
        except (httpx.HTTPError,OSError,ValueError,KeyError):
            raise HTTPException(503,'任务结果暂不可用，请稍后刷新。')

    @app.post('/sdcpp/v1/jobs/{job_id}/cancel')
    async def cancel(job_id: str):
        if job_id not in gateway.jobs:
            raise HTTPException(404,'未找到任务。')
        response = await gateway.backend.post('/sdcpp/v1/jobs/'+job_id+'/cancel')
        return Response(response.content,status_code=response.status_code,media_type='application/json')

    @app.get('/archive/records')
    async def records(page: int=1):
        if page<1:
            raise HTTPException(400,'页码无效。')
        items = sorted(gateway.records.values(),key=lambda item:item['created'],reverse=True)
        return {'total':len(items),'records':items[(page-1)*30:page*30]}

    def get_record(record_id):
        record = gateway.records.get(record_id)
        if not record:
            raise HTTPException(404,'未找到历史记录。')
        return record

    @app.get('/archive/records/{record_id}/export')
    async def export(record_id: str):
        record = get_record(record_id)
        return Response(json.dumps(record,ensure_ascii=False,indent=2).encode('utf-8'),media_type='application/json',
                        headers={'Content-Disposition':f'attachment; filename="qwen-{record_id}.json"'})

    @app.get('/archive/records/{record_id}/images/{index}')
    async def archive_image(record_id: str,index: int,download: int=0):
        record = get_record(record_id)
        image = next((item for item in record.get('images',[]) if item['index']==index),None)
        if not image:
            raise HTTPException(404,'未找到图片。')
        headers = {'Content-Disposition':f'attachment; filename="qwen-{record_id}-{index}.{image["format"]}"'} if download else {}
        return Response(gateway.archive.read_image(record_id,index),media_type='image/'+image['format'],headers=headers)

    @app.get('/archive/records/{record_id}/references/{index}')
    async def archive_reference(record_id: str,index: int,download: int=0):
        record = get_record(record_id)
        reference = next((item for item in record.get('references',[]) if item['index']==index),None)
        if not reference:
            raise HTTPException(404,'未找到原图。')
        headers = {'Content-Disposition':f'attachment; filename="qwen-{record_id}-original.{reference["format"]}"'} if download else {}
        return Response(gateway.archive.read_reference(record_id,index),media_type='image/'+reference['format'],headers=headers)

    return app
