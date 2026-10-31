#!/usr/bin/env python3
"""Single-command local Chess Buddy/Qwen demo with managed Cloudflare SSH forwarding.
Does not touch robot motion or persist credentials.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
HOST = 'ssh-macstudio.urbot.ai'
SSH_USER = 'urbot'
LOCAL_PORT = 18000
REMOTE_PORT = 11434
BACKEND_PORT = int(os.environ.get('PORT') or os.environ.get('CHESS_SERVER_PORT') or 8765)
STARTED_SSH = None
STOP = threading.Event()


def get_json(url: str, timeout: float = 2):
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (OSError, ValueError, TimeoutError):
        return None


def model_reachable() -> bool:
    info = get_json(f'http://127.0.0.1:{LOCAL_PORT}/api/tags', timeout=3)
    if not isinstance(info, dict) or not isinstance(info.get('models'), list):
        return False
    return any('qwen3.8-27b' in m.get('name', '') for m in info['models'] if isinstance(m, dict))


def load_env() -> dict[str, str]:
    result = dict(os.environ)
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key in ('LLM_PROVIDER', 'QWEN_BASE_URL', 'QWEN_MODEL'):
                result[key] = value
    result.update({
        'LLM_PROVIDER': 'qwen',
        'QWEN_BASE_URL': f'http://127.0.0.1:{LOCAL_PORT}/v1',
        'QWEN_MODEL': 'qwen3.8-27b:latest',
    })
    return result


def start_tunnel():
    global STARTED_SSH
    if model_reachable():
        print('✓ Qwen tunnel already works — reusing it.', flush=True)
        return
    cloudflared = shutil.which('cloudflared')
    ssh = shutil.which('ssh')
    if not ssh or not cloudflared:
        raise RuntimeError('Missing ssh or cloudflared. Install cloudflared and verify it is in PATH.')
    cmd = [ssh, '-N', '-L', f'127.0.0.1:{LOCAL_PORT}:127.0.0.1:{REMOTE_PORT}',
           '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
           '-o', 'ServerAliveCountMax=3',
           '-o', f'ProxyCommand={cloudflared} access ssh --hostname %h',
           f'{SSH_USER}@{HOST}']
    print('Connecting to Mac Studio via Cloudflare Access...', flush=True)
    STARTED_SSH = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    for _ in range(24):
        if model_reachable():
            print('✓ Mac Studio Qwen model is reachable.', flush=True)
            return
        if STARTED_SSH.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError('Could not establish Qwen tunnel. Check Cloudflare Access login and the SSH output above.')


def check_backend():
    url = f'http://127.0.0.1:{BACKEND_PORT}/api/health'
    health = get_json(url)
    if health is None:
        return
    if not health.get('vbotDemo'):
        raise RuntimeError(f'An existing backend is listening on {BACKEND_PORT} without VBOT demo mode. Stop its Terminal first.')
    # The existing launcher reuses a live backend. It cannot update that process's environment.
    if not health.get('coach', {}).get('configured'):
        raise RuntimeError(f'An OLD backend is running on port {BACKEND_PORT} with coach.configured=false. Stop its Terminal (Ctrl+C) and rerun this launcher.')
    print('ℹ Existing Chess Buddy backend found; it reports an LLM configured. Ensure it is the Qwen-configured backend.', flush=True)


def keep_tunnel_running():
    global STARTED_SSH
    while not STOP.wait(5):
        if model_reachable():
            continue
        # Only restart tunnels owned by this launcher; never interfere with an external one.
        if STARTED_SSH is not None:
            if STARTED_SSH.poll() is None:
                STARTED_SSH.terminate()
                try:
                    STARTED_SSH.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    STARTED_SSH.kill()
            print('⚠ Qwen tunnel disconnected; attempting reconnection...', flush=True)
            try:
                start_tunnel()
            except Exception as err:
                print(f'⚠ Reconnection pending: {err}', flush=True)


def main():
    global STARTED_SSH
    if not (ROOT / 'Open VBOT Chess Demo.command').exists():
        raise RuntimeError('Place this launcher and scripts/ folder in the ai-chess-coach repository root.')
    if not (ROOT / 'server/coach/qwen_adapter.py').exists():
        raise RuntimeError('Qwen integration patch not found; apply v3 first.')
    if not (ROOT / '.venv/bin/python').exists():
        raise RuntimeError('Missing .venv; run setup_mac.sh first.')
    check_backend()
    start_tunnel()
    env = load_env()
    print('✓ Qwen environment configured for the app.', flush=True)
    monitor = threading.Thread(target=keep_tunnel_running, daemon=True)
    monitor.start()
    try:
        return subprocess.call(['bash', str(ROOT / 'Open VBOT Chess Demo.command')], cwd=ROOT, env=env)
    finally:
        STOP.set()
        if STARTED_SSH is not None and STARTED_SSH.poll() is None:
            STARTED_SSH.terminate()
            try:
                STARTED_SSH.wait(timeout=3)
            except subprocess.TimeoutExpired:
                STARTED_SSH.kill()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, KeyboardInterrupt) as exc:
        print(f'\nDemo startup stopped: {exc}', file=sys.stderr, flush=True)
        print('No robot controls were changed.', file=sys.stderr, flush=True)
        sys.exit(1)
