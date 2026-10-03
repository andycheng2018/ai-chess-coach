#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1

# Finder's Terminal session may not include Homebrew in PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -x .venv/bin/python || ! -d node_modules ]] || ! command -v npm >/dev/null 2>&1; then
  echo "Chess Coach needs its dependencies. Run ./setup_mac.sh in this folder first."
  read -r -p "Press Return to close this window. " </dev/tty
  exit 1
fi

./.venv/bin/python - <<'PY'
import json
import os
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv

load_dotenv('.env')
backend_port = int(os.environ.get('PORT') or os.environ.get('CHESS_SERVER_PORT') or '8765')
web_port = int(os.environ.get('CHESS_WEB_PORT') or '5173')
backend_url = f'http://127.0.0.1:{backend_port}'
web_url = f'http://localhost:{web_port}'
started = []


def backend_ready():
    try:
        with urlopen(f'{backend_url}/api/health', timeout=1) as response:
            data = json.load(response)
        return data.get('ok') is True and 'coachAnalysisProfiles' in data
    except (OSError, URLError, ValueError):
        return False


def web_ready():
    try:
        with urlopen(web_url, timeout=1) as response:
            html = response.read().decode('utf-8')
        return '<title>AI Chess Coach</title>' in html
    except (OSError, URLError, ValueError):
        return False


def stop(_signal, _frame):
    raise KeyboardInterrupt


for event in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(event, stop)

try:
    print('Opening Chess Coach…', flush=True)
    if not backend_ready():
        started.append(subprocess.Popen(['./run_backend.sh'], start_new_session=True))
    if not web_ready():
        started.append(subprocess.Popen(
            ['./run_web.sh', '--port', str(web_port), '--strictPort'], start_new_session=True,
        ))

    deadline = time.monotonic() + 60
    while not (backend_ready() and web_ready()):
        if any(process.poll() is not None for process in started):
            raise RuntimeError('An app server exited during startup. See the message above.')
        if time.monotonic() >= deadline:
            raise RuntimeError('The app did not become ready within 60 seconds. See the messages above.')
        time.sleep(0.25)

    subprocess.run(['open', web_url], check=True)
    print(f'Chess Coach: {web_url}', flush=True)
    print(f'Audit Studio: {backend_url}/audit', flush=True)
    if started:
        print('Keep this Terminal window open while using the app. Press Control-C to stop it.', flush=True)
        while True:
            if any(process.poll() is not None for process in started):
                raise RuntimeError('An app server stopped. Double-click the launcher to start it again.')
            time.sleep(0.5)
except KeyboardInterrupt:
    print('\nChess Coach stopped.', flush=True)
except Exception as error:
    print(f'\nCould not open Chess Coach: {error}', file=sys.stderr, flush=True)
    sys.exit(1)
finally:
    # Each server has its own process group, including npm's Vite child.
    # Only groups created by this launcher are stopped.
    for process in started:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in started:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
PY

launcher_status=$?
if [[ "$launcher_status" -ne 0 ]]; then
  read -r -p "Press Return to close this window. " </dev/tty
fi
exit "$launcher_status"
