"""Embedded host for the existing chess backend. Binds only tablet loopback."""
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from types import SimpleNamespace

_server = None
_app = None
_state = None


def native():
    from java import jclass
    return jclass('com.andy.chessbuddy.StandaloneHost')


def settings():
    return json.loads(str(native().readSettings()))


def trusted_fingerprints(target):
    data = settings()
    expected = data.get('robotTarget', '').removeprefix('vbot@')
    if target.removeprefix('vbot@') != expected:
        return set()
    return {data['robotFingerprint']} if data.get('robotFingerprint') else set()


def ssh_run(command, timeout=125):
    # Only commands admitted by vbot_demo.ssh_command reach this bridge.
    target = command[-2]
    result = json.loads(str(native().runSsh(target, command[-1], int(timeout * 1000))))
    return SimpleNamespace(returncode=result['exitCode'], stdout=result['stdout'], stderr=result['stderr'])


def apply_settings():
    data = settings()
    for field, variable in [('openaiKey', 'OPENAI_API_KEY'), ('model', 'OPENAI_MODEL'),
                            ('botToken', 'LICHESS_BOT_TOKEN'), ('botUsername', 'LICHESS_BOT_USERNAME'),
                            ('elevenLabsKey', 'ELEVENLABS_API_KEY'), ('voiceId', 'ELEVENLABS_VOICE_ID')]:
        os.environ[variable] = data.get(field, '')
    os.environ['OPENAI_MODEL'] = data.get('model') or 'gpt-4.1-mini'
    os.environ['VBOT_SSH_TARGET'] = data.get('robotTarget', '')
    profile = data.get('robotProfile')
    if profile:
        value = json.loads(profile)
        value['target'] = data.get('robotTarget', value.get('target', ''))
        if value.get('hostKeyFingerprint') != data.get('robotFingerprint'):
            raise ValueError('Robot profile fingerprint must match the explicitly trusted robot fingerprint.')
        path = Path(os.environ['CHESS_DATA_HOME']) / 'vbot-demo' / 'device-verification.local.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(value, stream)


def start(data_home, engine_path):
    global _server, _app, _state
    if _server is not None:
        return json.dumps(_state)
    import server
    sys.path.insert(0, str(Path(server.__file__).parent))
    os.environ['CHESS_ANDROID'] = '1'
    os.environ['CHESS_DATA_HOME'] = str(data_home)
    os.environ['STOCKFISH_PATH'] = str(engine_path)
    os.environ['HOST'] = '127.0.0.1'
    Path(data_home).mkdir(parents=True, exist_ok=True)
    apply_settings()
    import app
    from coach.analysis_search import AnalysisSearches
    from http.server import ThreadingHTTPServer
    from tablet_access import TabletAccess
    token = secrets.token_urlsafe(32)
    _server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    _server.daemon_threads = True
    url = f'http://127.0.0.1:{_server.server_port}'
    app.tablet_access = TabletAccess(token, url)
    app.analysis_searches.close()
    app.analysis_searches = AnalysisSearches()
    _app = app
    _state = {'url': url, 'token': token, 'standalone': True}
    threading.Thread(target=_server.serve_forever, name='tablet-chess-backend', daemon=True).start()
    if os.environ.get('LICHESS_BOT_TOKEN'):
        threading.Thread(target=app.bootstrap_bot, daemon=True).start()
    return json.dumps(_state)


def can_configure():
    if _app is not None and (_app.vbot_demo.armed or _app.vbot_demo.busy):
        raise ValueError('Turn robot reactions off and wait for the current action before changing tablet settings.')
    return True


def reconfigure():
    can_configure()
    apply_settings()
    if _app is not None:
        from vbot_demo import VbotDemo
        _app.runtime.stop()
        _app._llm_coach = None
        _app.ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
        _app.ELEVENLABS_VOICE_ID = os.environ.get('ELEVENLABS_VOICE_ID', '')
        _app.vbot_demo = VbotDemo(network_book=None)
        if os.environ.get('LICHESS_BOT_TOKEN'):
            threading.Thread(target=_app.bootstrap_bot, daemon=True).start()
    return True


def stop():
    global _server, _state
    if _app is not None:
        _app.vbot_demo.disarm({'reason': 'server_shutdown'})
        _app.runtime.stop()
        _app.analysis_searches.close()
        _app.reset_analyzer()
    if _server is not None:
        _server.shutdown(); _server.server_close()
    _server = None; _state = None
