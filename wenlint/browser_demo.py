"""Loopback-only offline desktop walkthrough, no model or filesystem write API."""
from __future__ import annotations

import argparse
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .desktop import DesktopApi, frontend_index


def make_server(port=8765):
    api = DesktopApi()
    token = secrets.token_urlsafe(32)
    root = frontend_index().parent.resolve()
    bridge = '''<script>
const call=async(method,payload)=>{const r=await fetch('/api/'+method,{method:'POST',headers:{'Content-Type':'application/json','X-WenLint-Token':TOKEN},body:JSON.stringify(payload||{})});return r.json()};
window.pywebview={api:Object.fromEntries(['app_info','static_scan','start_agent_review','agent_review_status','cancel_agent_review'].map(m=>[m,p=>call(m,p)]))};
for(const m of ['open_file','open_workspace','workspace_read','workspace_index','workspace_write','save_original'])window.pywebview.api[m]=async()=>({ok:false,error:'浏览器演示支持粘贴文本；文件和工作区功能请使用桌面版。'});
window.pywebview.api.save_revision=async(p)=>{const url=URL.createObjectURL(new Blob([p.text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=p.suggestedName||'wenlint-review.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return {ok:true,path:a.download}};
</script>'''.replace('TOKEN', json.dumps(token))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, b'{}')
            path = urlsplit(self.path).path
            if path == '/':
                content = (root / 'index.html').read_text(encoding='utf-8')
                return self.send(200, content.replace('<head>', '<head>'+bridge).encode(), 'text/html; charset=utf-8')
            target = (root / path.lstrip('/')).resolve()
            if not target.is_relative_to(root / 'assets') or not target.is_file():
                return self.send(404, b'{}')
            types = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml'}
            self.send(200, target.read_bytes(), types.get(target.suffix, 'application/octet-stream'))

        def do_POST(self):
            if not self.valid_host() or self.headers.get('X-WenLint-Token') != token:
                return self.send(403, b'{}')
            method = self.path.removeprefix('/api/')
            if method not in {'app_info', 'static_scan', 'start_agent_review', 'agent_review_status', 'cancel_agent_review'}:
                return self.send(404, b'{}')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 2_000_000:
                    return self.send(413, b'{}')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError()
                if method == 'start_agent_review':
                    payload['demo'] = True
                result = getattr(api, method)() if method == 'app_info' else getattr(api, method)(payload)
                if method == 'app_info':
                    result['browserDemo'] = True
                self.send(200, json.dumps(result, ensure_ascii=False).encode())
            except (ValueError, TypeError):
                self.send(400, b'{"ok":false}')

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='WenLint 离线浏览器演示，不调用模型')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print(f'WenLint offline demo: http://127.0.0.1:{server.server_port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
