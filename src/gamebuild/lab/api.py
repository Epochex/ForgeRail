"""Same-origin loopback UI and a small authenticated action API."""
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from gamebuild.diagnostics import _redact
from .service import LabService
from .store import LabConflict
from .sanitize import clean

WEB = Path(__file__).parent/'web'


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class NewRun(Body):
    case_id: str = Field(min_length=2, max_length=2)
    variant: str = Field(min_length=1, max_length=80)


class Action(Body):
    kind: str = Field(min_length=1, max_length=20)
    request_key: str = Field(min_length=1, max_length=100)


def create_lab_app(root: Path, token: str | None = None):
    root = Path(root).resolve()
    token = token or secrets.token_urlsafe(32)
    session = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = LabService(root)
        try: yield
        finally: app.state.service.close()

    app = FastAPI(title='ForgeRail Engineering Lab', docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware('http')
    async def local_boundary(request, call_next):
        host = urlsplit('//'+request.headers.get('host','')).hostname
        if host not in ('127.0.0.1', 'localhost', '::1'):
            return JSONResponse({'detail':'loopback host required'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'same-origin request required'}, status_code=403)
        if request.url.path == '/' and request.query_params.get('access'):
            if not hmac.compare_digest(request.query_params['access'], token):
                return JSONResponse({'detail':'invalid launch credential'}, status_code=401)
            response = RedirectResponse('/', status_code=303)
            response.set_cookie('forgerail_lab', session, httponly=True, samesite='strict')
            response.headers['Cache-Control'] = 'no-store'
            return response
        if request.url.path != '/health' and not hmac.compare_digest(request.cookies.get('forgerail_lab',''), session):
            if request.url.path == '/':
                return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>ForgeRail · 打开实验台</title><main style="font:18px system-ui;max-width:600px;margin:15vh auto;padding:24px"><h1>ForgeRail · Engineering Lab</h1><p>请使用终端打印的完整启动链接打开。已有启动凭据也可在这里输入。</p><form><label>启动凭据 <input name="access" type="password" required></label><button>进入工作台</button></form></main></html>', status_code=401)
            return JSONResponse({'detail':'session required; reopen the printed launch URL'}, status_code=401)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(LabConflict)
    async def conflict(_, exc): return JSONResponse({'detail':str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(_, exc): return JSONResponse({'detail':'record not found'}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, exc): return JSONResponse({'detail':str(exc)}, status_code=400)

    def journal(): return app.state.service.journal

    def scrub(value):
        return clean(value,[root])

    @app.get('/health')
    def health(): return {'ok':True, 'service':'forgerail-lab', 'execution_mode':'lab'}

    @app.get('/')
    def index():
        return FileResponse(WEB/'index.html')

    @app.get('/lab/api/cases')
    def cases():
        from .catalog import CASES
        return CASES

    @app.post('/lab/api/runs', status_code=201)
    def new_run(body: NewRun):
        from .catalog import CASES
        case = next((x for x in CASES if x['id']==body.case_id), None)
        if not case or body.variant not in [v['id'] for v in case['variants']]:
            raise HTTPException(422, 'unknown case or fault variant')
        return journal().create(body.case_id, body.variant)

    @app.get('/lab/api/runs')
    def runs(): return journal().runs()

    @app.get('/lab/api/runs/{rid}')
    def run(rid: str): return scrub(journal().snapshot(rid))

    @app.post('/lab/api/runs/{rid}/actions', status_code=202)
    def action(rid: str, body: Action):
        return scrub(app.state.service.submit(rid, body.kind, body.request_key))

    @app.post('/lab/api/runs/{rid}/cancel')
    def cancel(rid: str): return app.state.service.cancel(rid)

    @app.get('/lab/api/runs/{rid}/events')
    def events(rid: str, after: int = 0):
        journal().snapshot(rid)
        if after < 0: raise HTTPException(422, 'after must be nonnegative')
        return scrub(journal().events(rid, after))

    @app.get('/lab/api/runs/{rid}/evidence/{eid}')
    def evidence(rid: str, eid: str):
        item, path = journal().evidence(rid, eid)
        if path.suffix in ('.json','.log','.txt','.diff','.xml'):
            return Response(path.read_bytes(),
                            media_type='application/json' if path.suffix=='.json' else 'text/plain',
                            headers={'Content-Disposition':f'inline; filename="{path.name}"'})
        return FileResponse(path, filename=path.name, media_type='application/octet-stream')

    @app.get('/lab/api/runs/{rid}/export')
    def export(rid: str):
        result = scrub(journal().snapshot(rid))
        return Response(json.dumps(result, ensure_ascii=False, indent=2), media_type='application/json',
                        headers={'Content-Disposition':f'attachment; filename="forgerail-{rid[:8]}.json"'})

    if WEB.exists(): app.mount('/lab/static', StaticFiles(directory=WEB), name='lab-static')
    return app
