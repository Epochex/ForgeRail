"""Small helpers shared by local scenarios; never fabricate observations."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time
import urllib.request
import urllib.error
import uuid


def sha(value): return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def tree_digest(directory):
    return sha(json.dumps([(p.relative_to(directory).as_posix(), sha(p.read_bytes()))
                           for p in sorted(Path(directory).rglob('*')) if p.is_file() and '.git' not in p.parts], sort_keys=True))


def state(ctx, **changes):
    path = ctx.repo / 'scenario.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if changes:
        value.update(changes)
        ctx.write('scenario.json', value)
    return value


def evidence(ctx, name, value):
    path = ctx.output / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    ctx.record('验证证据', 'INFO', name, path=path.relative_to(ctx.root).as_posix(), sha256=sha(path.read_bytes()))
    return value


@contextmanager
def loopback(handler):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def http(url, body=None):
    start = time.monotonic()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
    try:
        # Explicitly bypass host proxy settings for loopback-only experiments.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
            status, raw = response.status, response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    return {'status':status, 'body':json.loads(raw), 'duration_ms':round((time.monotonic()-start)*1000,3)}


def store_handler(store):
    from gamebuild.store import Conflict
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            code = 200
            try:
                if self.path == '/claim': result = store.claim(body['worker'], body.get('lease_seconds',30))
                elif self.path == '/report': result = store.report(**body)
                elif self.path == '/submit': result = store.submit(body['request'], body['key'])
                else: code, result = 404, {'error':'unknown endpoint'}
            except Conflict as exc:
                code, result = 409, {'error':str(exc)}
            raw = json.dumps(result).encode()
            self.send_response(code); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    return Handler
