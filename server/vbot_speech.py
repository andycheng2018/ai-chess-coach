"""Ask Qwen from the server, then have the dog say the answer in its own voice.

This goes straight to the dog's speech service, so the dog's onboard model is not
involved and the words spoken are exactly the words shown. It cannot move the robot.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import threading

from diagnostics import run_on_robot, ssh_failure
from vbot_ssh import REMOTE_ROOT

MAX_QUESTION = 1000
MAX_SPOKEN = 400
SSH_FAILED = 255
INSTRUCTIONS = ('You are a friendly robot dog answering out loud. Reply in at most two short sentences of plain '
                'spoken words. No lists, markdown, emoji or stage directions.')
_speaking = threading.Lock()


def spoken_text(raw) -> str:
    """Matches the dog-side cleanup, so what the page shows is what the dog says."""
    text = re.sub(r'<think>.*?(</think>|$)', ' ', str(raw), flags=re.S | re.I)
    text = re.sub(r'[*_`#]+', '', text)
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', text)
    return ' '.join(text.split())[:MAX_SPOKEN].strip()


def ask_qwen(payload: dict) -> dict:
    question = str(payload.get('question') or '').strip()
    if not 1 <= len(question) <= MAX_QUESTION:
        raise ValueError(f'Type a question of up to {MAX_QUESTION} characters.')
    if os.getenv('LLM_PROVIDER', 'openai').lower() != 'qwen':
        raise ValueError('This server is not set to use Qwen.')
    from coach.qwen_adapter import QwenClient
    model = os.getenv('QWEN_MODEL', 'qwen3.8-27b:latest')
    result = QwenClient(timeout=80).create(model=model, instructions=INSTRUCTIONS, input=question, max_output_tokens=400)
    answer = spoken_text(result.output_text)
    if not answer:
        raise ValueError('Qwen returned nothing that can be spoken. Try asking again.')
    return {'answer': answer, 'model': model}


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
