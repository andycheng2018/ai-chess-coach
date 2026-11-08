"""Have the dog say text in its own voice.

This goes straight to the dog's speech service, so the dog's onboard model is not
involved and the words spoken are exactly the words shown. It cannot move the robot.
"""
from __future__ import annotations

import json
import re
import shlex
import threading

from diagnostics import run_on_robot, ssh_failure
from vbot_ssh import REMOTE_ROOT

MAX_SPOKEN = 400
SSH_FAILED = 255
_speaking = threading.Lock()


def spoken_text(raw) -> str:
    """Matches the dog-side cleanup, so what the page shows is what the dog says."""
    text = re.sub(r'<think>.*?(</think>|$)', ' ', str(raw), flags=re.S | re.I)
    text = re.sub(r'[*_`#]+', '', text)
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', text)
    return ' '.join(text.split())[:MAX_SPOKEN].strip()


def say(demo, payload: dict) -> dict:
    text = spoken_text(payload.get('text') or '')
    if not text:
        raise ValueError('There is nothing to say yet.')
    if demo.armed or demo.busy:
        return {'ok': False, 'reason': 'Turn robot reactions off before making the dog talk.'}
    if not _speaking.acquire(blocking=False):
        return {'ok': False, 'reason': 'The dog is already being asked to speak.'}
    try:
        remote = shlex.join([REMOTE_ROOT + '/.venv/bin/python', '-I', REMOTE_ROOT + '/robot_speak.py'])
        done, problem = run_on_robot(demo, remote, 40, stdin=text)
    finally:
        _speaking.release()
    if problem:
        return {'ok': False, 'reason': problem}
    if done.returncode == SSH_FAILED:
        return {'ok': False, 'reason': ssh_failure(done.stderr)}
    for line in done.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('event') == 'speak_result':
            if item.get('ok'):
                return {'ok': True, 'text': text}
            return {'ok': False, 'reason': f"The dog's speech service refused: {item.get('message') or item.get('errorCode')}"}
        if isinstance(item, dict) and item.get('event') == 'speak_refused':
            return {'ok': False, 'reason': item.get('reason') or 'The dog refused to speak.'}
    return {'ok': False, 'reason': 'The speech helper did not answer. It may not be installed on this dog.'}
