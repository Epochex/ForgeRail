import json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer
IDENTITY = {'role':os.getenv('ROLE','core'), 'sha':os.getenv('BUILD_SHA','unknown'), 'config':os.getenv('CONFIG_VERSION','v1'), 'app_revision':os.getenv('APP_REVISION','v1'), 'started':time.time()}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/build-info':
            self.send_error(404); return
        body = json.dumps(IDENTITY).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
if __name__ == '__main__': HTTPServer(('0.0.0.0',8080), Handler).serve_forever()
