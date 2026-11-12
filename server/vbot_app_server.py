#!/usr/bin/env python3
"""Local HTTP surface for the VBOT app. Binds to loopback; never expose it publicly."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vbot_app_control import AppController, MAX_BODY, route  # noqa: E402

PORT = int(os.environ.get('VBOT_APP_PORT', '8791'))
CLOUD_VOICE_PATH = '/api/vbot/voice'
VOICE_ACTIONS = {'voice/session/new', 'voice/session/continue', 'voice/message', 'voice/demo-mode'}
CLOUD_ORIGIN = 'http://localhost:5173'  # One of the origins the cloud server accepts for this key.
DIST = Path(__file__).resolve().parents[1] / 'vbot-app' / 'dist'
DEV_ORIGINS = {'http://localhost:5180', 'http://127.0.0.1:5180'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'VbotApp/1'
    controller: AppController

    def log_message(self, *_args):
        pass  # The command journal is the audit record.

    def _local(self):
        port = self.server.server_port
        hosts = {f'localhost:{port}', f'127.0.0.1:{port}', f'[::1]:{port}'}
        origins = {f'http://localhost:{port}', f'http://127.0.0.1:{port}', '', *DEV_ORIGINS}
        return (self.client_address[0] in {'127.0.0.1', '::1'} and self.headers.get('Host', '') in hosts
                and self.headers.get('Origin', '') in origins)

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local():
            return self._json(403, {'message': 'Local requests only.'})
        path = self.path.split('?', 1)[0]
        if path == '/api/app/status':
            return self._json(200, self.controller.status())
        if path == '/api/app/voice':
            return self._json(*cloud_voice())
        return self._static(path)

    def _static(self, path):
        root = DIST.resolve()
        candidate = (root / path.lstrip('/')).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            candidate = root / 'index.html'
        if not candidate.is_file():
            return self._json(404, {'message': 'Build the app first: npm run vbot:build'})
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._local() or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self._json(403, {'message': 'Local JSON requests only.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= MAX_BODY:
                return self._json(413, {'message': 'Request too large.'})
            payload = json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {'message': 'Invalid JSON.'})
        path = self.path.removeprefix('/api/app/') if self.path.startswith('/api/app/') else ''
        if path == 'voice':
            return self._json(*cloud_voice(payload))
        if path in VOICE_ACTIONS:
            return self._json(*cloud_voice(payload, path.removeprefix('voice')))
        return self._json(*route(self.controller, path, payload))


def _cloud_settings():
    try:
        from dotenv import dotenv_values
        saved = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    except ImportError:
        saved = {}
    url = os.environ.get('CHESS_CLOUD_URL') or saved.get('CHESS_CLOUD_URL') or ''
    token = os.environ.get('CHESS_CLOUD_TOKEN') or saved.get('CHESS_CLOUD_TOKEN') or ''
    return url.rstrip('/'), token


def cloud_voice(payload=None, action=''):
    """Studio's voice switch. The key stays on this Mac; the page never sees it."""
    url, token = _cloud_settings()
    if not url or not token:
        return 200, {'available': False, 'enabled': False, 'state': 'off', 'turns': [], 'linked': False,
                     'reason': 'Studio is not linked to the cloud server yet. Add CHESS_CLOUD_URL and CHESS_CLOUD_TOKEN to .env.'}
    import requests
    headers = {'X-Chess-Buddy-Token': token, 'Origin': CLOUD_ORIGIN}
    try:
        if payload is None:
            response = requests.get(url + CLOUD_VOICE_PATH, headers=headers, timeout=10, allow_redirects=False)
        else:
            response = requests.post(url + CLOUD_VOICE_PATH + action, json=payload, headers=headers, timeout=70, allow_redirects=False)
        return response.status_code, response.json()
    except (requests.RequestException, ValueError):
        return 502, {'message': 'Could not reach the cloud server.'}


def make_server(controller, port=PORT):
    handler = type('BoundHandler', (Handler,), {'controller': controller})
    return ThreadingHTTPServer(('127.0.0.1', port), handler)


def main():
    controller = AppController()
    server = make_server(controller)
    print(f'VBOT app controller on http://127.0.0.1:{server.server_port} (face control only)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.disconnect()
        server.server_close()


if __name__ == '__main__':
    main()
