#!/usr/bin/env python3
"""Opt-in host companion. Pairing material stays in ignored, owner-only logs/."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))


def pairing_key(path):
    path.parent.mkdir(exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Pairing file must be a regular local file.')
    if path.exists():
        data = json.loads(path.read_text())
        token = data.get('token', '')
        if not isinstance(token, str) or len(token) < 40:
            raise RuntimeError('Invalid pairing file. Rename it to rotate the tablet key.')
        path.chmod(0o600)
        return token
    token = secrets.token_urlsafe(32)
    with open(path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump({'token': token}, stream)
    return token


def main():
    os.chdir(ROOT)
    from vbot_networks import detect_network
    address = os.environ.get('CHESS_TABLET_HOST_IP') or detect_network().get('localIp')
    try:
        ip = ipaddress.ip_address(address)
        if ip.version != 4 or not ip.is_private or ip.is_loopback:
            raise ValueError()
    except (TypeError, ValueError):
        raise SystemExit('Mac LAN address unavailable. Set CHESS_TABLET_HOST_IP to its Wi-Fi IPv4 address and try again.')
    port = int(os.environ.get('PORT', os.environ.get('CHESS_SERVER_PORT', '8765')))
    url = f'http://{address}:{port}'
    local = f'http://127.0.0.1:{port}'
    token = pairing_key(ROOT / 'logs' / 'tablet-pairing.local.json')
    try:
        with urllib.request.urlopen(local + '/api/health', timeout=2) as response:
            current = json.load(response)
        if current.get('tabletPairing'):
            webbrowser.open(local + '/tablet')
            print('An existing tablet backend is running. Its pairing page was opened on this Mac.')
            return
        raise SystemExit('The ordinary backend is already running. Stop its Terminal with Control-C, then reopen Open Chess Buddy Tablet.command. No server was stopped automatically.')
    except (OSError, TimeoutError):
        pass
    environment = {**os.environ, 'HOST': '0.0.0.0', 'CHESS_TABLET_TOKEN': token, 'CHESS_TABLET_URL': url}
    process = subprocess.Popen([str(ROOT / '.venv' / 'bin' / 'python'), str(ROOT / 'server' / 'app.py')], env=environment)
    def open_when_ready():
        import time
        for _ in range(40):
            if process.poll() is not None: return
            try:
                with urllib.request.urlopen(local + '/api/health', timeout=1) as response:
                    if json.load(response).get('tabletPairing'):
                        webbrowser.open(local + '/tablet'); return
            except OSError: pass
            time.sleep(.25)
    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f'Chess Buddy tablet backend: {url}\nPairing page opens only on this Mac. Keep this Terminal open; Control-C stops this backend.')
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill()


if __name__ == '__main__':
    main()
