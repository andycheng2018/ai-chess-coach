"""Explicit, opt-in tablet pairing. Never substitutes for robot admission checks."""
import html
import ipaddress
import json
import secrets
from io import BytesIO

TABLET_ORIGIN = 'https://localhost'
TABLET_HEADER = 'X-Chess-Buddy-Token'


class TabletAccess:
    def __init__(self, token='', url=''):
        self.token = token
        self.url = url

    @property
    def enabled(self):
        return len(self.token) >= 40

    def authorized(self, address, origin, token):
        try:
            local = ipaddress.ip_address(address).is_private
        except ValueError:
            local = False
        return bool(self.enabled and local and origin == TABLET_ORIGIN
                    and isinstance(token, str) and secrets.compare_digest(token.encode(), self.token.encode()))

    def page(self):
        import qrcode
        import qrcode.image.svg
        payload = json.dumps({'type': 'chessbuddy-tablet-v1', 'url': self.url, 'token': self.token})
        image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=7, border=4)
        output = BytesIO(); image.save(output)
        svg = output.getvalue().decode().replace('<?xml version=\'1.0\' encoding=\'UTF-8\'?>', '')
        return f'''<!doctype html><html><head><meta charset="utf-8"><title>Chess Buddy · Pair tablet</title>
        <style>body{{background:#191817;color:#e8e6e3;font:18px system-ui;max-width:720px;margin:40px auto;padding:24px}}svg{{background:white;max-width:100%;height:auto}}code{{overflow-wrap:anywhere}}h1{{color:#aade7c}}</style></head>
        <body><h1>Pair your Chess Buddy tablet</h1><p>Keep the Mac backend running. On your tablet, open Chess Buddy and tap <strong>Scan Mac pairing QR</strong>.</p>
        {svg}<p>Mac address: <code>{html.escape(self.url)}</code></p><details><summary>Enter the key manually</summary><code>{html.escape(self.token)}</code></details>
        <p>Use the same trusted Wi-Fi. This pairing key authorizes coaching and robot controls; keep it private. Existing robot checks and onsite confirmation still apply.</p>
        <p>Closing the backend stops service to the tablet. Turn robot reactions off in Chess Buddy before closing.</p></body></html>'''.encode()
