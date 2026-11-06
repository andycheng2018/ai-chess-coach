#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -x .venv/bin/python || ! -x node_modules/.bin/vite ]] || ! command -v npm >/dev/null 2>&1; then
  echo "VBOT Studio needs Node.js, its npm dependencies, and the project's .venv. Set them up in this folder first."
  read -r -p "Press Return to close this window. " </dev/tty
  exit 1
fi

.venv/bin/python - <<'PY'
import os
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

web_url = 'http://localhost:5180'
controller_url = 'http://127.0.0.1:8791/api/app/status'
started = []


def ready(url, marker):
    try:
        with urlopen(url, timeout=1) as response:
            return marker(response, response.read())
    except (OSError, URLError):
        return False


def controller_ready():
    return ready(controller_url, lambda response, body: response.headers.get('Server', '').startswith('VbotApp/1 '))


def web_ready():
    return ready(web_url, lambda response, body: b'<title>VBOT Studio</title>' in body)


def stop(_signal, _frame):
    raise KeyboardInterrupt


for event in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(event, stop)

try:
    print('Opening VBOT Studio…', flush=True)
    if not controller_ready():
        env = os.environ.copy()
        env['VBOT_APP_PORT'] = '8791'
        started.append(subprocess.Popen(['.venv/bin/python', 'server/vbot_app_server.py'], env=env, start_new_session=True))
    if not web_ready():
        started.append(subprocess.Popen(['npm', 'run', 'vbot:dev', '--', '--host', '127.0.0.1'], start_new_session=True))

    deadline = time.monotonic() + 60
    while not (controller_ready() and web_ready()):
        if any(process.poll() is not None for process in started):
            raise RuntimeError('A server could not start. Check the messages above; ports 5180 and 8791 must be available.')
        if time.monotonic() >= deadline:
            raise RuntimeError('Startup timed out. Check the messages above.')
        time.sleep(0.25)

    subprocess.run(['open', web_url], check=True)
    print(f'VBOT Studio: {web_url}', flush=True)
    if started:
        print('Keep this window open while using VBOT Studio. Press Control-C to stop the servers it started.', flush=True)
        while True:
            if any(process.poll() is not None for process in started):
                raise RuntimeError('A server stopped. Double-click the launcher to start it again.')
            time.sleep(0.5)
except KeyboardInterrupt:
    print('\nClosing VBOT Studio servers…', flush=True)
except Exception as error:
    print(f'\nCould not open VBOT Studio: {error}', file=sys.stderr, flush=True)
    sys.exit(1)
finally:
    for process in started:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    for process in started:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
PY
status=$?
if [[ "$status" -ne 0 ]]; then
  read -r -p "Press Return to close this window. " </dev/tty
fi
exit "$status"
