"""Qwen voice mode: the dog hears you, Qwen answers, the dog says it.

The server owns one SSH session to vbot-demo/robot_voice.py. If that link drops, the
helper turns the dog's own chat back on by itself. The on/off choice is saved, so the
mode comes back after a restart and stays on with every app closed. Conversations are
kept in memory only. Qwen can only produce words here; it has no route to movement.
"""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import shlex
import subprocess
import threading
import time
import uuid

from diagnostics import ssh_failure
from vbot_speech import spoken_text
from vbot_ssh import REMOTE_ROOT, ssh_argv

JOIN_SECONDS = 1.2           # One thought often arrives as several transcripts.
HISTORY_TURNS = 6
HISTORY_IDLE_SECONDS = 120
KEEPALIVE_SECONDS = 20
CLOSE_WAIT_SECONDS = 10
BACKOFF_SECONDS = (5, 10, 20, 30)
FALLBACK_REPLY = "Sorry, my thoughts got tangled. Could you say that again?"
INSTRUCTIONS = (
    'You are a friendly robot dog talking out loud with someone. Their words come from imperfect speech recognition, '
    'so they may be garbled, split up, or contain sound-alike mistakes. Use the sounds of the words and the conversation '
    'so far to work out what they most likely meant. If you are reasonably sure, answer what they meant in at most two '
    'short spoken sentences. If you cannot tell, do not guess and do not just say you did not understand: ask one short '
    'clarifying question that offers your best guess, such as "Did you ask about my dances?". Reply in the language they '
    'used, defaulting to English. Use plain spoken words with no lists, markdown, emoji or stage directions. Never '
    'mention speech recognition or transcripts. You cannot move your body from this conversation, so never promise to. '
    'Fill in three fields. "understood" is one short restatement of what they asked, never your answer. "clarifying" is '
    'true only when your reply is a question asking what they meant. "reply" is exactly what you say out loud.')
REPLY_FORMAT = {'format': {'type': 'json_schema', 'name': 'voice_reply', 'strict': True, 'schema': {
    'type': 'object', 'additionalProperties': False, 'required': ['understood', 'clarifying', 'reply'],
    'properties': {'understood': {'type': 'string'}, 'clarifying': {'type': 'boolean'}, 'reply': {'type': 'string'}}}}}


def ask_qwen(history, heard, rejected):
    from coach.qwen_adapter import QwenClient
    hint = ' (The recognizer was unsure about this one.)' if rejected else ''
    messages = [*history, {'role': 'user', 'content': f'They said: "{heard}"{hint}'}]
    result = QwenClient(timeout=45).create(
        model=os.getenv('QWEN_MODEL', 'qwen3.8-27b:latest'), instructions=INSTRUCTIONS, input=messages,
        text=REPLY_FORMAT, max_output_tokens=500)
    data = json.loads(result.output_text)
    return {'understood': spoken_text(data.get('understood', '')), 'clarifying': data.get('clarifying') is True,
            'reply': spoken_text(data.get('reply', ''))}


class VoiceMode:
    def __init__(self, demo, data_home=None, ask=ask_qwen, popen=subprocess.Popen):
        self.demo, self.ask, self.popen = demo, ask, popen
        home = Path(data_home or os.environ.get('CHESS_DATA_HOME') or Path(__file__).resolve().parents[1])
        self.path = home / 'vbot-voice.json'
        self.lock = threading.RLock()
        self.enabled = False
        self.state, self.message = 'off', ''
        self.chat_restored = None
        self.process = None
        self.wake = threading.Event()
        self.turns = deque(maxlen=20)
        self.history = deque(maxlen=HISTORY_TURNS * 2)
        self.last_turn_at = 0.0
        self.heard = queue.Queue()
        self.supervisor = None
        self.worker = None
        self.closed = threading.Event()

    # --- public surface -----------------------------------------------------------------------
    def available(self):
        if os.environ.get('CHESS_ANDROID') == '1':
            return False, 'Voice mode runs from a hosted server, not the tablet.'
        if os.getenv('LLM_PROVIDER', 'openai').lower() != 'qwen':
            return False, 'This server is not set to use Qwen.'
        if not self.demo.target:
            return False, 'No robot address is configured on this server.'
        return True, ''

    def status(self):
        usable, reason = self.available()
        with self.lock:
            return {'available': usable, 'reason': reason, 'enabled': self.enabled, 'state': self.state, 'message': self.message,
                    'chatRestored': self.chat_restored, 'turns': list(self.turns)}

    def resume(self):
        """Called at server start, so a saved 'on' survives restarts."""
        try:
            wanted = json.loads(self.path.read_text()).get('enabled') is True
        except (OSError, ValueError, AttributeError):
            wanted = False
        if wanted and self.available()[0]:
            self._start()

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled must be true or false.')
        if enabled:
            usable, reason = self.available()
            if not usable:
                raise ValueError(reason)
            self._save(True)
            self._start()
        else:
            self._save(False)
            self._stop()
        return self.status()

    # --- session ------------------------------------------------------------------------------
    def _save(self, enabled):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'enabled': enabled}))
        temporary.replace(self.path)

    def _start(self):
        with self.lock:
            if self.enabled:
                return
            self.enabled = True
            self.chat_restored = None
            self._set_state('connecting', 'Connecting to the dog…')
            self.heard = queue.Queue()  # Fresh each time, so a leftover shutdown marker can't end the new worker.
            self.supervisor = threading.Thread(target=self._supervise, daemon=True, name='vbot-voice')
            self.worker = threading.Thread(target=self._answer_loop, args=(self.heard,), daemon=True, name='vbot-voice-turns')
            self.supervisor.start()
            self.worker.start()

    def _stop(self):
        with self.lock:
            if not self.enabled:
                return
            self.enabled = False
            process = self.process
            connected = process is not None
            self.closed.clear()
            self._write({'op': 'close'})
        self.wake.set()
        self.heard.put(None)
        if connected and not self.closed.wait(CLOSE_WAIT_SECONDS):
            with self.lock:
                if self.process is not None:
                    self.process.terminate()
                self._set_state('off', "The dog didn't confirm. Its chat should come back on its own when the link closes.")
            return
        with self.lock:
            if not connected:
                self._set_state('off', '')

    def _set_state(self, state, message):
        self.state, self.message = state, message

    def _write(self, frame):
        process = self.process
        if process is None or process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps(frame, ensure_ascii=False) + '\n')
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def _spawn(self):
        alias = self.demo._ssh_identity_anchor().removeprefix('vbot@') if self.demo.network_book is not None else None
        remote = shlex.join([REMOTE_ROOT + '/.venv/bin/python', '-I', REMOTE_ROOT + '/robot_voice.py', '--serve'])
        return self.popen(ssh_argv(self.demo.target, remote, host_key_alias=alias), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, bufsize=1)

    def _supervise(self):
        failures = 0
        while self.enabled:
            ready = self._run_once()
            if not self.enabled:
                break
            failures = 0 if ready else failures + 1
            delay = BACKOFF_SECONDS[min(failures, len(BACKOFF_SECONDS) - 1)]
            self.wake.wait(delay)
            self.wake.clear()
        self.wake.clear()

    def _run_once(self):
        try:
            process = self._spawn()
        except (OSError, ValueError) as error:
            with self.lock:
                self._set_state('error', f'Could not start the link to the dog: {error}')
            return False
        tail = deque(maxlen=8)
        threading.Thread(target=lambda: [tail.append(line) for line in process.stderr], daemon=True).start()
        with self.lock:
            self.process = process
        keepalive = threading.Event()
        threading.Thread(target=self._keep_alive, args=(keepalive,), daemon=True).start()
        ready = False
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    ready = self._on_event(event) or ready
        finally:
            keepalive.set()
            code = process.wait()
            with self.lock:
                self.process = None
                if self.enabled:
                    if code == 255:
                        self._set_state('error', ssh_failure(''.join(tail)))
                    elif self.state != 'error':
                        self._set_state('connecting', 'Lost the dog. Reconnecting…')
                else:
                    self._set_state('off', '' if self.chat_restored else "The dog didn't confirm its chat is back on.")
            self.closed.set()
        return ready

    def _keep_alive(self, stop):
        while not stop.wait(KEEPALIVE_SECONDS):
            with self.lock:
                self._write({'op': 'ping'})

    def _on_event(self, event):
        kind = event.get('event')
        with self.lock:
            if kind == 'ready':
                self.chat_restored = None
                self._set_state('listening', 'Say the wake word, then talk.')
                return True
            if kind == 'closed':
                self.chat_restored = event.get('chatRestored') is True
            elif kind == 'refused':
                self._set_state('error', str(event.get('reason') or 'The dog refused the session.'))
            elif kind == 'error':
                self._set_state('error', 'The voice helper failed on the dog. Is it installed?')
            elif kind == 'said':
                self._record_spoken(event)
        if kind == 'heard' and isinstance(event.get('text'), str):
            self.heard.put(event)
        return False

    def _record_spoken(self, event):
        for turn in reversed(self.turns):
            if turn['id'] == event.get('id'):
                turn['spoken'] = event.get('ok') is True
                if not turn['spoken']:
                    self._add_error(turn, str(event.get('reason') or 'The dog did not speak.')[:200])
                return

    @staticmethod
    def _add_error(turn, problem):
        turn['error'] = f"{turn['error']} {problem}" if turn.get('error') else problem

    # --- answering ----------------------------------------------------------------------------
    @staticmethod
    def _next_utterance(heard):
        """Waits for speech, then joins what follows closely. None means shut down."""
        first = heard.get()
        if first is None:
            return None
        words, rejected = [first['text']], first.get('rejected') is True
        while True:
            try:
                more = heard.get(timeout=JOIN_SECONDS)
            except queue.Empty:
                return ' '.join(words), rejected
            if more is None:
                return None
            words.append(more['text'])
            rejected = rejected or more.get('rejected') is True

    def _answer_loop(self, heard):
        while True:
            utterance = self._next_utterance(heard)
            if utterance is None or not self.enabled:
                return
            self._answer(*utterance)

    def _answer(self, heard, rejected):
        turn = {'id': uuid.uuid4().hex, 'at': round(time.time()), 'heard': heard, 'rejected': rejected,
                'understood': '', 'clarifying': False, 'reply': '', 'spoken': None}
        with self.lock:
            if self.demo.armed or self.demo.busy:
                turn['error'] = 'Paused while chess reactions or a show are running.'
                turn['spoken'] = False
                self.turns.append(turn)
                return
            if time.monotonic() - self.last_turn_at > HISTORY_IDLE_SECONDS:
                self.history.clear()
            history = list(self.history)
            self.turns.append(turn)
            self._set_state('thinking', 'Qwen is thinking…')
        try:
            answer = self.ask(history, heard, rejected)
            reply = answer['reply'] or FALLBACK_REPLY
        except Exception as error:
            answer, reply = {'understood': '', 'clarifying': False}, FALLBACK_REPLY
            turn['error'] = f'Qwen did not answer ({type(error).__name__}).'
            print(f'Voice mode: Qwen failed: {type(error).__name__}: {str(error)[:200]}', flush=True)
        with self.lock:
            turn.update(understood=answer['understood'], clarifying=answer['clarifying'], reply=reply)
            self.history.extend([{'role': 'user', 'content': f'They said: "{heard}"'}, {'role': 'assistant', 'content': reply}])
            self.last_turn_at = time.monotonic()
            if self.enabled and self.state == 'thinking':
                self._set_state('listening', 'Say the wake word, then talk.')
            if not self._write({'op': 'say', 'id': turn['id'], 'text': reply}):
                turn['spoken'] = False
                self._add_error(turn, 'The link to the dog dropped before it could answer.')
