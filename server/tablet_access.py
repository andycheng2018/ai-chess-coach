"""Explicit, opt-in tablet pairing. Never substitutes for robot admission checks.

On a Mac this is a LAN pairing: the private-address check is a second factor. On a
hosted server behind a tunnel (the Mac Studio in Docker) every request arrives from a
private proxy address, so the pairing key is the only credential. That deployment must
stay behind the Docker port proxy: run natively behind a tunnel, requests come from
127.0.0.1 and the loopback exemption in app.py would skip the key for ordinary API calls.
"""
import html
import ipaddress
import json
import re
import secrets
from io import BytesIO

TABLET_ORIGIN = 'https://localhost'
TABLET_HEADER = 'X-Chess-Buddy-Token'
_ORIGIN = re.compile(r'(?:https?|capacitor)://(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[::1\])(?::\d{1,5})?')


def parse_origins(value):
    """Comma-separated browser origins allowed to present the pairing key.

    Origins are CSRF hygiene, not authentication: any non-browser client can send one.
    """
    origins = set()
    for item in str(value or '').split(','):
        item = item.strip().rstrip('/')
        if not item:
            continue
        if not _ORIGIN.fullmatch(item):
            raise ValueError(f'CHESS_TABLET_ORIGINS has an invalid origin: {item!r}')
        origins.add(item)
    return origins


class TabletAccess:
    def __init__(self, token='', url='', origins=()):
        self.token = token
        self.url = url
        # The Android app's WebView origin is always accepted.
        self.origins = frozenset(origins) | {TABLET_ORIGIN}

    @property
    def enabled(self):
        return len(self.token) >= 40

    def authorized(self, address, origin, token):
        try:
            local = ipaddress.ip_address(address).is_private
        except ValueError:
            local = False
        return bool(self.enabled and local and origin in self.origins
                    and isinstance(token, str) and secrets.compare_digest(token.encode(), self.token.encode()))

    def page(self):
        import qrcode
        import qrcode.image.svg
        payload = json.dumps({'type': 'chessbuddy-tablet-v1', 'url': self.url, 'token': self.token})
        image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=7, border=4)
        output = BytesIO(); image.save(output)
        svg = output.getvalue().decode().replace('<?xml version=\'1.0\' encoding=\'UTF-8\'?>', '')
        hosted = self.url.startswith('https://')
        intro = ('<p>On your tablet, open Chess Buddy, tap <strong>Tablet settings</strong>, then <strong>Use a Chess Buddy server</strong> and scan this code.</p>'
                 if hosted else '<p>Keep the Mac backend running. On your tablet, open Chess Buddy and tap <strong>Scan Mac pairing QR</strong>.</p>')
        scope = ('This server is on the Internet: the key is the only credential. Anyone holding it can control the robot from anywhere.'
                 if hosted else 'Use the same trusted Wi-Fi.')
        return f'''<!doctype html><html><head><meta charset="utf-8"><title>Chess Buddy · Pair tablet</title>
        <style>body{{background:#191817;color:#e8e6e3;font:18px system-ui;max-width:720px;margin:40px auto;padding:24px}}svg{{background:white;max-width:100%;height:auto}}code{{overflow-wrap:anywhere}}h1{{color:#aade7c}}</style></head>
        <body><h1>Pair your Chess Buddy tablet</h1>{intro}
        {svg}<p>Server address: <code>{html.escape(self.url)}</code></p><details><summary>Enter the key manually</summary><code>{html.escape(self.token)}</code></details>
        <p>{scope} This pairing key authorizes coaching, bot accounts and robot controls; keep it private. Existing robot checks and onsite confirmation still apply.</p>
        <p>Closing the backend stops service to the tablet. Turn robot reactions off in Chess Buddy before closing.</p></body></html>'''.encode()
