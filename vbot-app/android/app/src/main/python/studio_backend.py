"""Hosts the app's controller inside the APK. It has no network listener: the
screens reach it only through StudioPlugin. Dog traffic goes over StudioHost's
pinned SSH stream, and the controller's rules are the same ones used on a computer.
"""
import json
from pathlib import Path
import re
import threading

from vbot_app_control import AppController, FaceSession, MAX_BODY, Rejected, route

REFUSAL = re.compile(r'vbot-refusal: ([^\n]+)')
_lock = threading.Lock()
_controller = None


def native():
    from java import jclass
    return jclass('com.andy.vbotstudio.StudioHost')


def read_identity(_target):
    """A dog is identified by its pinned key, because its address changes between networks."""
    fingerprint = native().trustedFingerprint()
    if not fingerprint:
        raise Rejected('not_connected', 'Pair this app with the dog first. Unknown keys are never accepted automatically.')
    return {'anchor': None, 'deviceId': 'ssh-host-key:' + str(fingerprint)}


def open_stream(command):
    # command comes from vbot_ssh.ssh_argv, which ends with the target and the remote command.
    try:
        return native().openSshStream(command[-2], command[-1])
    except Exception as error:
        refusal = REFUSAL.search(str(error))
        if refusal:
            raise Rejected('not_connected', refusal[1]) from None
        raise


def open_session(target, session_id, lease, anchor):
    return FaceSession(target, session_id, lease, anchor, stream_factory=open_stream)


def start(data_home):
    global _controller
    with _lock:
        if _controller is None:
            directory = Path(str(data_home))
            directory.mkdir(parents=True, exist_ok=True)
            _controller = AppController(journal_path=directory / 'commands.jsonl', session_factory=open_session, identity_reader=read_identity)
    return True


def can_pair():
    """Trust doesn't change underneath an open session."""
    if _controller.status()['connection'] in {'connected', 'connecting'}:
        raise ValueError('vbot-refusal: Disconnect from the dog before pairing again.')
    return True


def call(path, body=''):
    """Returns the HTTP surface's status and JSON body, so the app's adapter is the same on both."""
    path, body = str(path), str(body or '')
    if path == 'status':
        return json.dumps({'status': 200, 'body': _controller.status()})
    try:
        if len(body) > MAX_BODY:
            raise ValueError
        payload = json.loads(body or '{}')
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        return json.dumps({'status': 400, 'body': {'message': 'Invalid request.'}})
    status, reply = route(_controller, path, payload)
    return json.dumps({'status': status, 'body': reply})
