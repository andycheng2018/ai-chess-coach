"""A show-scoped transport for the existing one-cue dispatcher. Never reconnects."""
import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time


class ProcessStream:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = queue.Queue(maxsize=128)
        def read():
            try:
                while True:
                    line = self.process.stdout.readline(65537)
                    if not line:
                        break
                    if len(line) > 65536:
                        break
                    try: self.lines.put_nowait(line)
                    except queue.Full: break
            finally:
                try: self.lines.put_nowait(None)
                except queue.Full: pass
        threading.Thread(target=read, daemon=True).start()

    def writeLine(self, line):
        self.process.stdin.write(line + '\n')
        self.process.stdin.flush()

    def readLine(self, timeout):
        try: line = self.lines.get(timeout=timeout / 1000)
        except queue.Empty: return ''
        if line is None:
            raise RuntimeError('Robot session closed; no reconnect or replay.')
        return line

    def close(self):
        try: self.process.stdin.close()
        except (OSError, ValueError): pass
        try: self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
        self.process.stdout.close()


class CueSession:
    def __init__(self, target, run_id, anchor, *, read_only=False, stream_factory=None):
        from vbot_demo import ssh_command
        self.target = target
        self.failed = False
        self.cancel = None
        self.on_rescan = None
        self.active_request = None
        self.cancel_sent = False
        self.seen = set()
        self.closed = False
        command = ssh_command(target, 'actions/ROCKYOU.json', run_id, host_key_alias=anchor)
        if read_only:
            # Explicit no-motion mode used for device/protocol checks.
            from vbot_demo import REMOTE_ROOT
            command[-1] = shlex.join([REMOTE_ROOT + '/.venv/bin/python', '-I', REMOTE_ROOT + '/robot_action.py',
                                     '--serve', '--check-ready', '--request-id', run_id])
        else:
            command[-1] += ' --serve'
        if stream_factory is not None:
            self.stream = stream_factory(command)
        elif os.environ.get('CHESS_ANDROID') == '1':
            from android_backend import native
            self.stream = native().openSshStream(target, command[-1])
        else:
            self.stream = ProcessStream(command)
        try:
            ready = self._receive(run_id, {'session_ready'}, 25)
            if ready.get('protocol') != 1 or ready.get('rescanProtocol') != 1 or ready.get('ready') is not True:
                raise RuntimeError('Robot does not support a ready persistent cue session. No show started.')
        except BaseException:
            self.close()
            raise

    def _receive(self, request_id, events, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active_request == request_id and self.cancel is not None and self.cancel.is_set() and not self.cancel_sent:
                self.cancel_sent = True
                self.stream.writeLine(json.dumps({'op': 'cancel', 'requestId': request_id}))
            line = str(self.stream.readLine(250))
            if not line: continue
            if len(line) > 65536:
                raise RuntimeError('Oversized session frame; inspect the robot, do not replay.')
            try: item = json.loads(line)
            except ValueError: continue  # Non-protocol SDK diagnostics never authorize another cue.
            if isinstance(item, dict) and item.get('requestId') == request_id:
                if item.get('event') == 'rescan' and self.on_rescan:
                    self.on_rescan(item)
                elif item.get('event') in events:
                    return item
        raise TimeoutError('Robot session outcome unconfirmed. No reconnect or automatic retry.')

    def send(self, target, preset, request_id):
        from vbot_demo import PRESETS, RobotNotReady, RobotRejected
        if self.closed or self.failed or target != self.target or not re.fullmatch('[a-f0-9]{32}', request_id) or request_id in self.seen or preset not in PRESETS:
            raise ValueError('Closed session, repeated cue identity, or unlisted preset.')
        if self.cancel is not None and self.cancel.is_set():
            raise RobotNotReady('Stopped before submitting the cue.')
        self.active_request = request_id
        self.cancel_sent = False
        self.seen.add(request_id)  # Record BEFORE writing, including uncertain/lost writes.
        try:
            self.stream.writeLine(json.dumps({'op': 'cue', 'preset': preset, 'requestId': request_id}))
            result = self._receive(request_id, {'not_ready', 'terminal'}, 155)
            if result['event'] == 'not_ready':
                raise RobotNotReady(result.get('reason') or 'The robot is not ready. No next cue submitted.')
            if result.get('status') in {'ABORTED', 'CANCELED'}:
                raise RobotRejected('Robot action rejected or canceled. Inspect it onsite.')
            if result.get('status') != 'SUCCEEDED' or result.get('errorCategory') != 0:
                raise RuntimeError('Robot did not confirm successful completion. No retry.')
            if result.get('readyForNext') is not True:
                self.failed = True
            return {'status': 'completed', 'goalId': result.get('goalId'), 'durationMs': result.get('durationMs'),
                    'readyForNext': result.get('readyForNext') is True, 'postflightReason': result.get('postflightReason'),
                    'attemptCount': result.get('attemptCount', 1), 'rescanCount': result.get('rescanCount', 1)}
        except BaseException:
            self.failed = True
            raise
        finally:
            self.active_request = None

    def close(self):
        if not self.closed:
            self.closed = True
            # EOF exits the idle helper. It cannot enqueue any next movement.
            self.stream.close()
