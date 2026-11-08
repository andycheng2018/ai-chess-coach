"""Local controller for the independent VBOT app: face cues, waits and, when armed, presets.

A connection is face-only unless the operator confirms the onsite checks when
connecting. Only then does it run robot_studio.py, whose guarded motion path is
robot_action.py's. Motion is serial with faces and time-limited to that one
connection. Commands are single-use and journaled before they act. A restart turns
any in-flight command into `unknown` and never resumes it. Nothing here imports
chess, Lichess or the motion dispatcher. Exclusive ownership across products comes
from the dog-side controller lock that robot_face.py, robot_studio.py and
robot_action.py share.
"""
from __future__ import annotations

from collections import OrderedDict, deque
import hashlib
import math
import json
import os
from pathlib import Path
import re
import shlex
import threading
import time
import uuid

from vbot_networks import normalize_target
from vbot_ssh import REMOTE_ROOT, known_host_fingerprints, ssh_argv

ROOT = Path(os.environ.get('CHESS_DATA_HOME', Path(__file__).resolve().parents[1]))
JOURNAL_PATH = ROOT / '.local' / 'vbot-app' / 'commands.jsonl'
PROFILE_PATH = ROOT / 'vbot-demo' / 'device-verification.local.json'

TERMINAL = {'completed', 'rejected', 'cancelled', 'unknown'}
COMMAND_ID = re.compile(r'[a-f0-9]{32}')
MAX_TTL_MS, CUE_TTL_MS = 120000, 30000
READY_TIMEOUT, ACK_TIMEOUT = 25, 8
# A preset blocks until its terminal result and post-action checks, so it gets a long window.
MOTION_REPLY_TIMEOUT = 150
# Hold-to-drive. The caps mirror robot_studio.DRIVE_MAX (a test keeps them equal); the dog enforces them and refuses,
# never clamps. A drive start waits for the dog's readiness and publisher checks. The stop reply is quick.
DRIVE_MAX = {'vx': 0.15, 'vy': 0.10, 'wz': 0.40}
DRIVE_START_TIMEOUT, DRIVE_STOP_TIMEOUT = 20, 8
DRIVE_START_EVENTS = {'drive_started', 'rejected', 'duplicate'}
DRIVE_STOP_EVENTS = {'drive_stopped', 'drive_ended'}
DRIVE_SESSION_ENDERS = {'violation', 'error', 'eof', 'interrupted'}
# The dog ends a session after 15 minutes, so motion enabled at connect lapses with it.
MOTION_SESSION_MS = 15 * 60 * 1000
IDLE_CLOSE_SECONDS = 150
COMMAND_MEMORY = 4096
MAX_BODY = 256 * 1024

LIMITS = dict(maxCues=64, maxExpanded=128, maxRepeat=5, maxTotalMs=15 * 60 * 1000,
              faceMin=500, faceMax=30000, waitMin=100, waitMax=60000, motionBoundMs=60000, title=80, notes=500, caption=140, idLength=64)
SCORE_KEYS = {'schemaVersion', 'id', 'title', 'notes', 'origin', 'revision', 'repeat', 'createdAt', 'updatedAt', 'cues'}
CUE_KEYS = {'face': {'id', 'type', 'assetId', 'durationMs', 'caption'}, 'wait': {'id', 'type', 'durationMs', 'caption'},
            'head': {'id', 'type', 'preset', 'caption'}, 'body': {'id', 'type', 'preset', 'caption'},
            'move': {'id', 'type', 'move', 'faceId', 'caption'}}
# Mirrors robot_action.PRESETS (a test keeps them equal). The controller never imports dog-side code.
MOTION_PRESETS = ('actions/ROCKYOU.json', 'actions/CHEER_R.json', 'actions/WAVE.json', 'atom/look_left.json', 'atom/look_right.json',
                  'atom/look_forward.json', 'atom/look_up.json', 'atom/look_down.json', 'actions/SHAKEHAND.json',
                  'actions/SHAKEHAND_L.json', 'actions/HIGH_FIVE_R.json', 'actions/HIGH_FIVE_L.json', 'actions/SAYYES.json',
                  'actions/GRIEVANCE.json', 'actions/HAPPY_LITTLE_JUMP.json', 'actions/HAPPY_JUMP.json', 'actions/JUMP_IN_PLACE.json',
                  'actions/RHYTHM.json', 'actions/RHYTHMIC_SWING.json', 'actions/RELAXED_SWING.json', 'actions/TWIST_BUTT.json',
                  'actions/GUITAR.json', 'actions/PIANO.json', 'actions/DRUM.json', 'actions/DRUMER.json', 'actions/SAXOPHONE.json',
                  'actions/VIOLIN.json', 'actions/CONDUCT.json', 'actions/HAPPY_BOUNCE_B.json', 'actions/EXCITED.json',
                  'actions/CHEER_L.json', 'actions/ENJOY.json')
# Bounded basic moves. The amounts live on the dog (robot_studio.MOVES); a test keeps these names equal.
MOVES = ('step_forward', 'step_back', 'step_left', 'step_right', 'turn_left_30', 'turn_right_30', 'turn_left_90', 'turn_right_90',
         'turn_left_10', 'turn_right_10')
# Steps run the vendor's own preset, which controls the screen, so they can't carry a face. A test keeps this equal to the dog's.
FACELESS_MOVES = ('step_forward', 'step_back', 'step_left', 'step_right')
MOTION_CONFIRMATIONS = ('onsite', 'standing', 'clear')
FACE_EVENTS = {'started', 'released', 'rejected', 'unknown', 'duplicate'}
MOTION_EVENTS = {'completed', 'rejected', 'unknown', 'failed', 'duplicate'}
ENVELOPE_KEYS = {'v', 'commandId', 'deviceId', 'sessionId', 'leaseGeneration', 'issuedAt', 'expiresAt', 'kind', 'score'}
RESTRICTED_FACES = {66, 67, 80, 89, 90, 91, 92, 93, 95}
SAFE_ID = re.compile(r'[A-Za-z0-9_-]+')

SPEECH_MISSING = 'No speech backend has been verified on this dog.'
NAVIGATION_MISSING = 'Navigation has no demonstrated live provider. The schema exists, but that does not prove it works.'
MOTION_MISSING = 'Motion is off for this connection. Reconnect with motion enabled, after the onsite checks.'
MOTION_EXPIRED = 'Motion enabled for this connection has lapsed. Reconnect after the onsite checks.'
CONFIRM_MISSING = 'Motion needs every onsite confirmation: someone is with the dog, it is standing, and the area is clear.'
NOT_CONNECTED = 'Connect to a dog first.'
SESSION_FAILED = "Couldn't start the face session. Check the dog's power and Wi-Fi, its SSH trust, and that robot_face.py is deployed."


class Rejected(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code, self.reason = code, reason


class OutcomeUnknown(RuntimeError):
    """The dog may or may not have acted. Report it and never retry."""


def route(controller, path, payload):
    """The one command dispatch, shared by the HTTP surface and the Android plugin."""
    try:
        if path == 'connect':
            return 200, controller.connect(payload)
        if path == 'disconnect':
            return 200, controller.disconnect()
        if path == 'submit':
            return 200, controller.submit(payload)
        if path == 'cancel':
            return 200, controller.cancel_future(payload)
        if path == 'drive':
            return 200, controller.drive(payload)
    except Rejected as error:
        return 400, {'state': 'rejected', 'duplicate': False, 'code': error.code, 'reason': error.reason}
    return 404, {'message': 'Unknown route.'}


def is_int(value):
    return type(value) is int


def validate_score(score, motion=False):
    """Trust-boundary copy of the app's score schema, kept in sync by shared fixtures."""
    def bad(reason):
        raise Rejected('invalid_score', reason)
    if not isinstance(score, dict) or set(score) - SCORE_KEYS or score.get('schemaVersion') != 1:
        bad('Unsupported score shape or version.')
    if not isinstance(score.get('id'), str) or not SAFE_ID.fullmatch(score['id']) or len(score['id']) > LIMITS['idLength']:
        bad('The score needs a stable ID.')
    title, notes = score.get('title'), score.get('notes')
    if not isinstance(title, str) or not title.strip() or len(title) > LIMITS['title']:
        bad('Invalid score title.')
    if not isinstance(notes, str) or len(notes) > LIMITS['notes']:
        bad('Invalid score notes.')
    if score.get('origin') not in {'custom', 'canned'} or not is_int(score.get('revision')) or score['revision'] < 1:
        bad('Invalid score origin or revision.')
    if not is_int(score.get('createdAt')) or not is_int(score.get('updatedAt')):
        bad('Invalid score timestamps.')
    repeat, cues = score.get('repeat'), score.get('cues')
    if not is_int(repeat) or not 1 <= repeat <= LIMITS['maxRepeat']:
        bad('Repeat is out of bounds.')
    if not isinstance(cues, list) or len(cues) > LIMITS['maxCues'] or len(cues) * repeat > LIMITS['maxExpanded']:
        bad('Too many cues.')
    seen, total = set(), 0
    for cue in cues:
        if not isinstance(cue, dict):
            bad('Invalid cue.')
        kind = cue.get('type')
        if kind in {'head', 'body', 'move'} and not motion:
            raise Rejected('capability_unavailable', MOTION_MISSING)
        if kind not in CUE_KEYS or set(cue) - CUE_KEYS[kind]:
            bad('Unsupported cue type or fields.')
        cue_id = cue.get('id')
        if not isinstance(cue_id, str) or not SAFE_ID.fullmatch(cue_id) or len(cue_id) > LIMITS['idLength'] or cue_id in seen:
            bad('Cue IDs must be stable and unique.')
        seen.add(cue_id)
        caption = cue.get('caption')
        if caption is not None and (not isinstance(caption, str) or len(caption) > LIMITS['caption']):
            bad('Invalid cue caption.')
        if kind == 'move':
            if cue.get('move') not in MOVES:
                bad('That move is not approved.')
            face_id = cue.get('faceId')
            if face_id is not None and cue['move'] in FACELESS_MOVES:
                bad('A step runs the vendor preset, which controls the screen, so it cannot carry a face.')
            if face_id is not None and (not is_int(face_id) or not 0 <= face_id <= 255 or face_id in RESTRICTED_FACES):
                bad('That face asset is not allowed.')
            total += LIMITS['motionBoundMs']
            continue
        if kind in {'head', 'body'}:
            preset = cue.get('preset')
            if not isinstance(preset, str) or preset not in MOTION_PRESETS:
                bad('That preset is not approved.')
            if kind != ('head' if preset.startswith('atom/') else 'body'):
                bad('That preset is the other kind of motion.')
            total += LIMITS['motionBoundMs']
            continue
        duration = cue.get('durationMs')
        low, high = (LIMITS['faceMin'], LIMITS['faceMax']) if kind == 'face' else (LIMITS['waitMin'], LIMITS['waitMax'])
        if not is_int(duration) or not low <= duration <= high:
            bad('Cue duration is out of bounds.')
        if kind == 'face':
            asset = cue.get('assetId')
            if not is_int(asset) or not 0 <= asset <= 255 or asset in RESTRICTED_FACES:
                bad('That face asset is not allowed.')
        total += duration
    if total * repeat > LIMITS['maxTotalMs']:
        bad('The show is longer than the 15-minute limit.')
    return score


def validate_envelope(envelope):
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_KEYS or envelope.get('v') != 1 or envelope.get('kind') != 'run-score':
        raise Rejected('invalid_score', 'Unsupported command shape or version.')
    if not is_int(envelope.get('leaseGeneration')) or not is_int(envelope.get('expiresAt')) or not is_int(envelope.get('issuedAt')):
        raise Rejected('invalid_score', 'Invalid command fields.')
    if not isinstance(envelope.get('deviceId'), str) or not isinstance(envelope.get('sessionId'), str):
        raise Rejected('invalid_score', 'Invalid command identity.')


def read_identity(target, *, profile_path=PROFILE_PATH, fingerprints=known_host_fingerprints):
    """Pins to a host key the operator already trusts. A private IP is not an identity."""
    profile = {}
    try:
        profile = json.loads(profile_path.read_text())
    except (OSError, ValueError):
        pass
    anchor = profile.get('target') if isinstance(profile, dict) else None
    trusted = profile.get('hostKeyFingerprint') if isinstance(profile, dict) else None
    if anchor and trusted:
        anchor = normalize_target(anchor)
        if trusted not in fingerprints(anchor):
            raise Rejected('not_connected', "This dog's saved SSH identity is missing or changed. Inspect it. Host-key checks won't be bypassed.")
        return {'anchor': anchor.removeprefix('vbot@'), 'deviceId': 'ssh-host-key:' + trusted}
    known = sorted(fingerprints(target))
    if not known:
        raise Rejected('not_connected', "This Mac doesn't trust a host key for that address yet. Pair with the dog first. Unknown keys are never accepted automatically.")
    return {'anchor': None, 'deviceId': 'ssh-host-key:' + known[0]}


class FaceSession:
    """Line protocol to vbot-demo/robot_face.py. It never reconnects or replays."""

    def __init__(self, target, session_id, lease, anchor, stream_factory=None, wall_ms=None, motion=False):
        self.session_id, self.lease = session_id, lease
        self.wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self.closed = False
        self.motion = bool(motion)
        self.drive_limits = None
        # A motion connection runs the combined helper, and only after explicit confirmation.
        helper = ['robot_studio.py', '--serve', '--motion', '--confirm-motion'] if motion else ['robot_face.py', '--serve']
        remote = shlex.join([REMOTE_ROOT + '/.venv/bin/python', '-I', REMOTE_ROOT + '/' + helper[0], *helper[1:],
                             '--session-id', session_id, '--lease', str(lease)])
        command = ssh_argv(target, remote, host_key_alias=anchor)
        if stream_factory is None:
            # A computer's ssh process. The APK passes its own stream and doesn't carry this module.
            from vbot_session import ProcessStream
            stream_factory = ProcessStream
        self.stream = stream_factory(command)
        try:
            ready = self._receive('requestId', session_id, {'session_ready', 'session_refused'}, READY_TIMEOUT)
            if ready['event'] == 'session_refused':
                raise Rejected(ready.get('code') or 'not_connected', ready.get('reason') or SESSION_FAILED)
            if motion:
                if (ready.get('protocol') != 4 or ready.get('motion') is not True or ready.get('faceOnly') is not False
                        or not set(MOVES) <= set(ready.get('moves') or [])):
                    raise Rejected('backend_unavailable', "The dog's helper doesn't support motion sessions. Deploy robot_studio.py.")
                limits = ready.get('drive')
                # The dog must enforce exactly the caps this controller validates against.
                if not isinstance(limits, dict) or any(limits.get(axis) != cap for axis, cap in DRIVE_MAX.items()):
                    raise Rejected('backend_unavailable', "The dog's helper has different driving limits. Deploy the matching robot_studio.py.")
                self.drive_limits = {axis: limits[axis] for axis in DRIVE_MAX}
            elif ready.get('protocol') != 1 or ready.get('faceOnly') is not True:
                raise Rejected('backend_unavailable', "The dog's helper doesn't support this face protocol.")
            names = ready.get('supportedFaces')
            self.supported = [name for name in names if isinstance(name, str)][:512] if isinstance(names, list) else []
        except BaseException:
            self.close()
            raise

    def _receive(self, key, value, events, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = str(self.stream.readLine(250))
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue  # SDK diagnostics are never protocol results.
            if isinstance(item, dict) and item.get(key) == value and item.get('event') in events:
                return item
        raise TimeoutError('No answer from the dog.')

    def _command(self, op, events=FACE_EVENTS, timeout=ACK_TIMEOUT, **fields):
        command_id = uuid.uuid4().hex
        frame = {'op': op, 'commandId': command_id, 'sessionId': self.session_id, 'leaseGeneration': self.lease,
                 'expiresAtMs': self.wall_ms() + CUE_TTL_MS, **fields}
        try:
            self.stream.writeLine(json.dumps(frame))
            return self._receive('commandId', command_id, events, timeout)
        except Exception as error:
            raise OutcomeUnknown('The dog stopped answering during this cue.') from error

    def play(self, asset_id, duration_ms):
        return self._command('face', assetId=asset_id, durationMs=duration_ms)

    def play_motion(self, preset):
        """Blocks until the dog reports the preset's terminal result. Never retried."""
        return self._command('motion', MOTION_EVENTS, MOTION_REPLY_TIMEOUT, preset=preset)

    def play_move(self, move, face_id=None):
        """One bounded move, with an optional face held for its duration. Never retried."""
        fields = {'move': move, **({'faceId': face_id} if face_id is not None else {})}
        return self._command('move', MOTION_EVENTS, MOTION_REPLY_TIMEOUT, **fields)

    def drive_start(self):
        """Arms one hold-to-drive on the dog. It publishes nothing until frames arrive."""
        return self._command('drive_start', DRIVE_START_EVENTS, DRIVE_START_TIMEOUT)

    def drive_frame(self, seq, vx, vy, wz):
        """One velocity frame. Fire-and-forget: the dog's watchdog, not a reply, is what keeps this safe."""
        try:
            self.stream.writeLine(json.dumps({'op': 'drive', 'seq': seq, 'vx': vx, 'vy': vy, 'wz': wz}))
        except Exception as error:
            raise OutcomeUnknown('The dog stopped answering during a drive.') from error

    def drive_stop(self):
        return self._command('drive_stop', DRIVE_STOP_EVENTS, DRIVE_STOP_TIMEOUT)

    def release(self):
        return self._command('face_release')

    def close(self):
        if not self.closed:
            self.closed = True
            # EOF makes the helper hand the screen back and release the controller lock.
            self.stream.close()


def _default_wait(cancel, seconds):
    return cancel.wait(seconds)


class AppController:
    def __init__(self, *, journal_path=JOURNAL_PATH, session_factory=FaceSession, identity_reader=read_identity,
                 wall_ms=None, mono=time.monotonic, waiter=_default_wait):
        self.journal_path, self.session_factory, self.identity_reader = Path(journal_path), session_factory, identity_reader
        self.wall_ms, self.mono, self.waiter = wall_ms or (lambda: int(time.time() * 1000)), mono, waiter
        self.lock = threading.RLock()
        self.commands = OrderedDict()
        self.events = deque(maxlen=80)
        self.connection, self.detail = 'disconnected', None
        self.device, self.session, self.session_id = None, None, None
        self.lease = 0
        self.motion_until = 0
        self.drive_lock = threading.Lock()
        self.drive_state, self.drive_seq = None, -1
        self.target = ''
        self.run, self.cancel, self.thread = None, None, None
        self.last_activity = mono()
        self._load_journal()

    # --- journal ---------------------------------------------------------
    def _load_journal(self):
        try:
            lines = self.journal_path.read_text().splitlines()
        except OSError:
            return
        for line in lines:
            try:
                item = json.loads(line)
                self.commands[item['commandId']] = item
                self.commands.move_to_end(item['commandId'])
                self.lease = max(self.lease, item.get('lease', 0))
            except (ValueError, KeyError, TypeError):
                continue  # A torn final line can't authorize anything.
        for command_id, item in list(self.commands.items()):
            if item.get('state') not in TERMINAL:
                self._record(command_id, 'unknown', fingerprint=item.get('fingerprint'), scoreId=item.get('scoreId'),
                             reason='The controller restarted during this command. It was not resumed or replayed.')
        self._trim()

    def _trim(self):
        while len(self.commands) > COMMAND_MEMORY:
            self.commands.popitem(last=False)

    def _record(self, command_id, state, **fields):
        """Durable before acting. Stores identity and outcome, never secrets or targets."""
        item = {'time': self.wall_ms(), 'commandId': command_id, 'state': state, 'actor': 'local-operator', 'lease': self.lease,
                **{key: value for key, value in fields.items() if value is not None}}
        self.commands[command_id] = item
        self.commands.move_to_end(command_id)
        self._trim()
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open('a') as journal:
            journal.write(json.dumps(item) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
        return item

    def _event(self, message, **fields):
        self.events.appendleft({'time': self.wall_ms(), 'message': message, **fields})

    # --- status ----------------------------------------------------------
    def _capabilities(self):
        connected = self.connection == 'connected'
        reason = None if connected else (self.detail if self.connection == 'lost' and self.detail else NOT_CONNECTED)
        face = {'available': connected, 'reason': reason}
        armed = connected and getattr(self.session, 'motion', False) and self.wall_ms() < self.motion_until
        lapsed = connected and getattr(self.session, 'motion', False) and not armed
        motion = {'available': armed, 'reason': None if armed else (MOTION_EXPIRED if lapsed else MOTION_MISSING if connected else reason)}
        ids = None
        if connected and self.session is not None:
            ids = sorted({int(name[:3]) for name in self.session.supported if re.match(r'\d{3}_', name)})
        can_drive = bool(armed and getattr(self.session, 'drive_limits', None))
        drive = {'available': can_drive, 'reason': None if can_drive else (MOTION_EXPIRED if lapsed else MOTION_MISSING if connected else reason)}
        return {'face': face, 'head': motion, 'body': motion, 'move': motion, 'drive': drive,
                'driveLimits': dict(DRIVE_MAX) if can_drive else None,
                'speech': {'available': False, 'reason': SPEECH_MISSING},
                'navigation': {'available': False, 'reason': NAVIGATION_MISSING},
                'supportedFaceIds': ids, 'rehearsedPresets': [],
                'armedPresets': list(MOTION_PRESETS) if armed else [],
                'armedMoves': list(MOVES) if armed else []}

    def status(self):
        with self.lock:
            active = self.run is not None and self.run['state'] not in TERMINAL
            if (self.connection == 'connected' and not active and self.drive_state is None
                    and self.mono() - self.last_activity > IDLE_CLOSE_SECONDS):
                # An idle face session must not keep chess or a show locked out.
                self._close_session()
                self.connection, self.detail = 'disconnected', 'Disconnected after idling, so other controllers can use the dog.'
                self.device, self.session_id = None, None
                self._event('Idle session closed.')
            return {'connection': self.connection, 'detail': self.detail, 'device': self.device,
                    'sessionId': self.session_id, 'leaseGeneration': self.lease, 'capabilities': self._capabilities(),
                    'supportedFaces': list(self.session.supported) if self.session is not None and self.connection == 'connected' else None,
                    'driving': self.drive_state is not None,
                    'run': dict(self.run) if self.run else None, 'events': list(self.events)}

    def _close_session(self):
        self.drive_state = None  # closing the stream is EOF to the dog, which publishes zeros and ends any drive
        session, self.session = self.session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    # --- connection ------------------------------------------------------
    @staticmethod
    def _motion_requested(payload):
        """Motion is armed only by every onsite confirmation being exactly true."""
        asked = payload.get('motion')
        if asked is None or asked is False:
            return False
        if not isinstance(asked, dict) or any(asked.get(key) is not True for key in MOTION_CONFIRMATIONS):
            raise Rejected('motion_not_confirmed', CONFIRM_MISSING)
        return True

    def connect(self, payload):
        motion = self._motion_requested(payload)
        with self.lock:
            if self.run is not None and self.run['state'] not in TERMINAL:
                self.detail = 'Stop the current show before reconnecting.'
                return self.status()
            if self.connection == 'connecting':
                return self.status()
            self._close_session()
            self.connection, self.detail = 'connecting', None
            self.device, self.session_id = None, None
            # Monotonic across controller restarts, so the dog can refuse older leases.
            self.lease = max(self.lease + 1, self.wall_ms())
            lease = self.lease
        session_id = uuid.uuid4().hex
        try:
            target = normalize_target(payload.get('target'))
            identity = self.identity_reader(target)
            session = (self.session_factory(target, session_id, lease, identity['anchor'], motion=True) if motion
                       else self.session_factory(target, session_id, lease, identity['anchor']))
        except Rejected as error:
            return self._connect_failed(error.reason)
        except ValueError as error:
            return self._connect_failed(str(error))
        except Exception:
            return self._connect_failed(SESSION_FAILED)
        with self.lock:
            if self.connection != 'connecting' or self.lease != lease:
                # Disconnected while the session was opening. Don't take over.
                session.close()
                return self.status()
            self.session, self.session_id, self.target = session, session_id, target
            self.device = {'id': identity['deviceId'], 'label': 'VBOT'}
            self.connection = 'connected'
            self.detail = 'Faces and approved presets, one at a time. Motion lapses with this connection.' if motion else 'Face control only. Motion stays off.'
            self.motion_until = self.wall_ms() + MOTION_SESSION_MS if motion else 0
            self.last_activity = self.mono()
            self._event('Connected. Faces and motion, after the onsite confirmations.' if motion else 'Connected. Face control only.')
            return self.status()

    def _connect_failed(self, reason):
        with self.lock:
            self.connection, self.detail = 'unavailable', reason
            self._event(reason)
            return self.status()

    def disconnect(self):
        with self.lock:
            if self.cancel is not None:
                self.cancel.set()
            thread = self.thread
        if thread is not None:
            thread.join(timeout=ACK_TIMEOUT * 2)
        with self.lock:
            self._close_session()
            self.connection, self.detail = 'disconnected', None
            self.device, self.session_id = None, None
            self._event('Disconnected. The dog restores its normal face when the session closes.')
            return self.status()

    # --- commands --------------------------------------------------------
    def submit(self, envelope):
        command_id = envelope.get('commandId') if isinstance(envelope, dict) else None
        if not isinstance(command_id, str) or not COMMAND_ID.fullmatch(command_id):
            raise Rejected('invalid_score', 'A unique command identity is required.')
        fingerprint = hashlib.sha256(json.dumps(envelope, sort_keys=True, default=str).encode()).hexdigest()
        with self.lock:
            prior = self.commands.get(command_id)
            if prior is not None:
                if prior.get('fingerprint') != fingerprint:
                    return {'commandId': command_id, 'state': 'rejected', 'duplicate': True, 'code': 'identity_conflict',
                            'reason': 'This command ID already belongs to a different show.'}
                return {'commandId': command_id, 'state': prior['state'], 'duplicate': True,
                        **({'code': prior['code']} if prior.get('code') else {}),
                        **({'reason': prior['reason']} if prior.get('reason') else {})}
            score = envelope.get('score') if isinstance(envelope.get('score'), dict) else {}
            score_id = score.get('id') if isinstance(score.get('id'), str) else None
            self._record(command_id, 'received', fingerprint=fingerprint, scoreId=score_id, revision=score.get('revision'))
            try:
                validate_envelope(envelope)
                self._admit(envelope)
                validate_score(envelope['score'], motion=self._motion_enabled())
                self._check_supported(envelope['score'])
            except Rejected as error:
                self._record(command_id, 'rejected', fingerprint=fingerprint, scoreId=score_id, code=error.code, reason=error.reason)
                self._event('Rejected: ' + error.reason, commandId=command_id, state='rejected')
                return {'commandId': command_id, 'state': 'rejected', 'duplicate': False, 'code': error.code, 'reason': error.reason}
            self._record(command_id, 'accepted', fingerprint=fingerprint, scoreId=score_id)
            # Runs own a deep copy, so nothing later can alter this show.
            snapshot = json.loads(json.dumps(envelope['score']))
            has_face = any(cue['type'] == 'face' for cue in snapshot['cues'])
            self.run = {'commandId': command_id, 'state': 'running', 'score': snapshot, 'cueIndex': 0, 'completedCues': 0,
                        'cueAck': 'idle', 'cueEndsAt': None, 'reason': None, 'cleanup': 'pending' if has_face else 'not-needed',
                        'startedAt': self.wall_ms(), 'finishedAt': None}
            self.cancel = cancel = threading.Event()
            self._record(command_id, 'running', fingerprint=fingerprint, scoreId=score_id)
            self._event(f"Started “{snapshot['title']}”.", commandId=command_id, state='running')
            self.thread = threading.Thread(target=self._perform, args=(command_id, snapshot, cancel, self.session, fingerprint, score_id), daemon=True)
            self.thread.start()
            return {'commandId': command_id, 'state': 'accepted', 'duplicate': False}

    def _admit(self, envelope):
        if self.connection != 'connected' or self.session is None:
            raise Rejected('not_connected', 'No dog is connected.')
        if envelope['deviceId'] != (self.device or {}).get('id'):
            raise Rejected('wrong_device', 'This command is for a different dog.')
        if envelope['sessionId'] != self.session_id or envelope['leaseGeneration'] != self.lease:
            raise Rejected('stale_lease', 'This command is from an earlier connection.')
        now = self.wall_ms()
        if envelope['expiresAt'] <= now or envelope['expiresAt'] - now > MAX_TTL_MS:
            raise Rejected('expired', 'This command expired before it was received.')
        if self.run is not None and self.run['state'] not in TERMINAL:
            raise Rejected('busy', 'The controller is busy with another show.')
        if self.drive_state is not None:
            raise Rejected('busy', 'A drive is in progress. Let go of the drive button first.')

    # --- hold-to-drive ---------------------------------------------------
    def drive(self, payload):
        action = payload.get('action') if isinstance(payload, dict) else None
        if action == 'start':
            return self._drive_start()
        if action == 'frame':
            return self._drive_frame(payload)
        if action == 'stop':
            return self._drive_stop()
        raise Rejected('invalid_drive', 'Unknown drive action.')

    def _drive_lost(self, session, reason):
        """The link or the dog stopped answering mid-drive. Closing the stream is EOF to the dog, which publishes zeros."""
        with self.lock:
            self.drive_state = None
            if self.session is session:
                self._close_session()
                self.connection, self.detail = 'lost', reason
                self.device, self.session_id = None, None
                self._event(reason)

    def _drive_start(self):
        with self.lock:
            if self.connection != 'connected' or self.session is None:
                raise Rejected('not_connected', NOT_CONNECTED)
            if not self._motion_enabled():
                raise Rejected('capability_unavailable', MOTION_EXPIRED if getattr(self.session, 'motion', False) else MOTION_MISSING)
            if not getattr(self.session, 'drive_limits', None):
                raise Rejected('capability_unavailable', "This dog's helper doesn't support driving.")
            if self.run is not None and self.run['state'] not in TERMINAL:
                raise Rejected('busy', 'A show is running. Wait for it to finish before driving.')
            if self.drive_state is not None:
                raise Rejected('busy', 'A drive is already in progress.')
            self.drive_state, self.drive_seq = 'starting', -1
            session = self.session
        try:
            reply = session.drive_start()
        except Exception:
            self._drive_lost(session, 'The connection to the dog was lost while starting a drive. Reconnect to check status.')
            raise Rejected('unknown', 'The dog stopped answering while starting a drive. The connection was closed, which stops any drive.')
        with self.lock:
            if reply.get('event') != 'drive_started':
                self.drive_state = None
                raise Rejected(reply.get('code') or 'rejected', reply.get('reason') or 'The dog did not start a drive.')
            self.drive_state = 'on'
            self.last_activity = self.mono()
            self._event('Driving.')
        return {'state': 'started', 'limits': dict(DRIVE_MAX)}

    @staticmethod
    def _drive_values(payload):
        seq = payload.get('seq')
        if type(seq) is not int or seq < 0:
            raise Rejected('invalid_drive', 'A drive frame needs a sequence number.')
        values = {}
        for axis, cap in DRIVE_MAX.items():
            value = payload.get(axis)
            # bool is an int in Python, and NaN fails every comparison, so test both explicitly.
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > cap:
                raise Rejected('invalid_drive', f'{axis} must be a number within ±{cap}.')
            values[axis] = float(value)
        return seq, values

    def _drive_frame(self, payload):
        seq, values = self._drive_values(payload)
        with self.drive_lock:
            session = self.session
            if self.drive_state != 'on' or session is None:
                return {'state': 'ignored'}   # a frame that lost the race with a stop is dropped, never sent late
            if seq <= self.drive_seq:
                return {'state': 'ignored'}
            self.drive_seq = seq
            try:
                session.drive_frame(seq, values['vx'], values['vy'], values['wz'])
            except Exception:
                failed = True
            else:
                failed = False
        if failed:
            self._drive_lost(session, 'The connection to the dog was lost during a drive. The dog stops by itself when frames stop.')
            raise Rejected('unknown', 'The link to the dog dropped during a drive. The dog stops by itself when frames stop.')
        self.last_activity = self.mono()
        return {'state': 'sent'}

    def _drive_stop(self):
        with self.drive_lock:
            if self.drive_state is None or self.session is None:
                return {'state': 'stopped', 'reason': 'not-driving'}
            self.drive_state = 'stopping'   # frames after this are dropped; the stop is written after every earlier frame
            session = self.session
        try:
            reply = session.drive_stop()
        except Exception:
            self._drive_lost(session, 'The stop was not confirmed. The connection was closed, which stops the dog. Check the dog.')
            raise Rejected('unknown', 'The stop was not confirmed. The connection was closed, which stops the dog. Check the dog.')
        reason = reply.get('reason')
        with self.lock:
            self.drive_state = None
            self.last_activity = self.mono()
            unclean = reply.get('zeroed') is not True or reason in DRIVE_SESSION_ENDERS
        if unclean:
            self._drive_lost(session, f"The dog ended the drive abnormally ({reason}). Inspect it, then reconnect.")
            raise Rejected('unknown', f"The dog ended the drive abnormally ({reason}). Inspect it, then reconnect.")
        return {'state': 'stopped', 'reason': reason}

    def _motion_enabled(self):
        return bool(getattr(self.session, 'motion', False)) and self.wall_ms() < self.motion_until

    def _check_supported(self, score):
        supported = {int(name[:3]) for name in self.session.supported if re.match(r'\d{3}_', name)}
        for cue in score['cues']:
            if cue['type'] in {'head', 'body', 'move'} and not self._motion_enabled():
                raise Rejected('capability_unavailable', MOTION_EXPIRED if getattr(self.session, 'motion', False) else MOTION_MISSING)
            face_id = cue['assetId'] if cue['type'] == 'face' else cue.get('faceId') if cue['type'] == 'move' else None
            if face_id is not None and face_id not in supported:
                raise Rejected('capability_unavailable', f"This dog doesn't list face {face_id}.")

    def _update(self, command_id, **change):
        with self.lock:
            if self.run and self.run['commandId'] == command_id:
                self.run.update(change)

    def _perform(self, command_id, score, cancel, session, fingerprint, score_id):
        items = [cue for _ in range(score['repeat']) for cue in score['cues']]
        state, reason, started_face, session_lost, session_ended = 'completed', None, False, False, False
        try:
            for index, cue in enumerate(items):
                if cancel.is_set():
                    state, reason = 'cancelled', 'Future cues cancelled.'
                    break
                if cue['type'] == 'face':
                    self._update(command_id, cueIndex=index, cueAck='sent', cueEndsAt=None)
                    result = session.play(cue['assetId'], cue['durationMs'])
                    outcome = result.get('outcome') if result['event'] == 'duplicate' else result['event']
                    if outcome == 'rejected':
                        state, reason = 'rejected', result.get('reason') or 'The dog refused this cue.'
                        break
                    if outcome != 'started':
                        session_lost = True
                        state, reason = 'unknown', result.get('reason') or "This cue's outcome is unknown. It won't be retried."
                        break
                    started_face = True
                    self._update(command_id, cueAck='started', cueEndsAt=self.wall_ms() + cue['durationMs'])
                elif cue['type'] in {'head', 'body', 'move'}:
                    # The dog answers when the preset or move has finished and settled, so there is no timer to wait out.
                    self._update(command_id, cueIndex=index, cueAck='sent', cueEndsAt=None)
                    result = (session.play_move(cue['move'], cue.get('faceId')) if cue['type'] == 'move'
                              else session.play_motion(cue['preset']))
                    outcome = result.get('outcome') if result['event'] == 'duplicate' else result['event']
                    if outcome == 'rejected':
                        state, reason = 'rejected', result.get('reason') or 'The dog did not start this preset.'
                        # A readiness refusal ends the dog's session, as robot_action.py's does. Re-arm to continue.
                        session_ended = result.get('sessionEnded') is True
                        break
                    if outcome != 'completed':
                        session_lost = True
                        state, reason = 'unknown', result.get('reason') or "This preset didn't finish cleanly. Inspect the dog. It won't be retried."
                        break
                    self._update(command_id, completedCues=index + 1, cueAck='finished', cueEndsAt=None)
                    continue
                else:
                    self._update(command_id, cueIndex=index, cueAck='waiting', cueEndsAt=self.wall_ms() + cue['durationMs'])
                if self.waiter(cancel, cue['durationMs'] / 1000):
                    state, reason = 'cancelled', 'Future cues cancelled.'
                    break
                self._update(command_id, completedCues=index + 1, cueAck='finished', cueEndsAt=None)
        except OutcomeUnknown as error:
            session_lost, state, reason = True, 'unknown', f"{error} This cue's outcome is unknown and it won't be retried."
        except Exception:
            session_lost, state, reason = True, 'unknown', "The show stopped unexpectedly. The last cue's outcome is unknown."
        if session_ended:
            # The dog released any face before it refused, but this controller never sees that confirmed.
            cleanup = 'failed' if started_face else 'not-needed'
        else:
            cleanup = 'not-needed' if not (started_face or session_lost) else self._cleanup(session, session_lost)
        with self.lock:
            self._update(command_id, state=state, reason=reason, cleanup=cleanup, cueEndsAt=None, finishedAt=self.wall_ms())
            self._record(command_id, state, fingerprint=fingerprint, scoreId=score_id, reason=reason)
            self._event('Show complete.' if state == 'completed' else reason, commandId=command_id, state=state)
            if cleanup == 'failed':
                self._event("The display release wasn't confirmed. Check the dog's screen.", commandId=command_id)
            self.last_activity = self.mono()
            if session_ended:
                self._close_session()
                self.connection, self.motion_until = 'disconnected', 0
                self.detail = 'The dog ended its motion session after refusing a preset. Inspect it, then reconnect with the onsite confirmations.'
                self.device, self.session_id = None, None
            if session_lost:
                # Reconnect means a new lease and a status check. Nothing is drained.
                self._close_session()
                self.connection = 'lost'
                self.detail = 'The connection to the dog was lost. Reconnect to check status. Nothing will be replayed.'
                self.device, self.session_id = None, None

    def _cleanup(self, session, session_lost):
        if session_lost:
            # robot_face.py releases the display itself when its stream ends. That can't be confirmed here.
            return 'failed'
        try:
            result = session.release()
            return 'released' if result.get('event') == 'released' else 'failed'
        except Exception:
            return 'failed'

    def cancel_future(self, payload):
        with self.lock:
            if (self.run and self.run['commandId'] == payload.get('commandId') and self.run['state'] not in TERMINAL
                    and self.cancel is not None):
                self.cancel.set()
                self._event('Stopping future cues.', commandId=self.run['commandId'])
            return self.status()
