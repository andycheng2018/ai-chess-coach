"""Studio face+motion session with fakes only. No SDK, no robot I/O."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vbot-demo'))

import robot_action as action  # noqa: E402
import robot_face as face  # noqa: E402
import robot_studio as studio  # noqa: E402

SESSION, LEASE, NOW = 'a' * 32, 7, 1_000_000
PRESET = 'actions/WAVE.json'


def cid(n):
    return f'{n:032x}'


class FakeDisplay:
    def __init__(self, log):
        self.log, self.release_status = log, 0

    def play(self, asset_id, duration_ms, request_id):
        self.log.append(('face', asset_id))
        return 0, 0, ''

    def release(self, request_id):
        self.log.append(('release',))
        return self.release_status, 0, ''


class Healthy:
    def problem(self):
        return None


class StdinFeed:
    """A scripted stdin whose readiness we control, so no real select() is involved."""

    def __init__(self, lines):
        self.lines = [line if line.endswith('\n') else line + '\n' for line in lines]

    def readline(self, _limit=-1):
        return self.lines.pop(0) if self.lines else ''


def ready(stream):
    return lambda readers, *_: (readers, [], []) if stream.lines else ([], [], [])


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.log = []
        self.display = FakeDisplay(self.log)
        self.ledger = face.CommandLedger(self.dir)
        self.face_core = face.FaceCore(ledger=self.ledger, display=self.display, health=Healthy(), session_id=SESSION,
                                       lease=LEASE, supported={86, 70}, now_ms=lambda: NOW)
        self.result = {'event': 'terminal', 'status': 'SUCCEEDED', 'errorCategory': 0, 'readyForNext': True, 'durationMs': 7000}
        self.unresolved = False

        def run_cue(preset, logical_id, canceled, move=None):
            self.log.append(('move', preset, logical_id, move) if move else ('motion', preset, logical_id))
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        self.core = studio.MotionCore(ledger=self.ledger, face_core=self.face_core, run_cue=run_cue,
                                      unresolved=lambda: self.unresolved, session_id=SESSION, lease=LEASE,
                                      presets=frozenset(action.PRESETS), moves=frozenset(studio.MOVES), now_ms=lambda: NOW)

    def move(self, n=1, **over):
        return {'op': 'move', 'commandId': cid(n), 'sessionId': SESSION, 'leaseGeneration': LEASE,
                'expiresAtMs': NOW + 30000, 'move': 'step_forward', **over}

    def motion(self, n=1, **over):
        return {'op': 'motion', 'commandId': cid(n), 'sessionId': SESSION, 'leaseGeneration': LEASE,
                'expiresAtMs': NOW + 30000, 'preset': PRESET, **over}

    def face_cue(self, n=100):
        return {'op': 'face', 'commandId': cid(n), 'sessionId': SESSION, 'leaseGeneration': LEASE,
                'expiresAtMs': NOW + 30000, 'assetId': 86, 'durationMs': 4500}

    def cue(self, command):
        return self.core.handle(command, lambda: False)


class ClassifyTests(unittest.TestCase):
    def test_only_a_clean_terminal_result_completes(self):
        clean = {'event': 'terminal', 'status': 'SUCCEEDED', 'errorCategory': 0, 'readyForNext': True, 'durationMs': 5}
        self.assertEqual(studio.classify(clean)[0], 'completed')
        for change in [{'status': 'ABORTED'}, {'status': 'CANCELED'}, {'errorCategory': 3}, {'readyForNext': False},
                       {'readyForNext': None}, {'stopRequested': True}, {'event': 'cleanup'}]:
            self.assertNotEqual(studio.classify({**clean, **change})[0], 'completed', change)

    def test_not_ready_means_nothing_moved(self):
        event, fields = studio.classify({'event': 'not_ready', 'code': 'posture', 'reason': 'Stand it.'})
        self.assertEqual((event, fields['code']), ('rejected', 'posture'))

    def test_garbage_is_unknown(self):
        self.assertEqual(studio.classify(None)[0], 'unknown')
        self.assertEqual(studio.classify('x')[0], 'unknown')


class MotionCoreTests(Harness):
    def test_clean_cue_completes_and_continues(self):
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], keep_going), ('completed', True))
        self.assertEqual(self.log, [('motion', PRESET, cid(1))])

    def test_a_showing_face_is_released_before_the_preset_starts(self):
        self.face_core.handle(self.face_cue())
        self.cue(self.motion())
        self.assertEqual([entry[0] for entry in self.log], ['face', 'release', 'motion'])

    def test_a_failed_release_refuses_the_motion(self):
        self.face_core.handle(self.face_cue())
        self.display.release_status = 1
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], frame['code'], keep_going), ('rejected', 'display_not_released', True))
        self.assertNotIn('motion', [entry[0] for entry in self.log])

    def test_no_release_call_when_no_face_is_showing(self):
        self.cue(self.motion())
        self.assertEqual([entry[0] for entry in self.log], ['motion'])

    def test_unknown_preset_stale_lease_and_expiry_never_run(self):
        for number, (change, code) in enumerate([({'preset': 'actions/ROCKYOU.json.evil'}, 'unsupported_preset'),
                             ({'preset': 'safety/is_robot_static'}, 'unsupported_preset'),
                             ({'leaseGeneration': LEASE - 1}, 'stale_lease'),
                             ({'sessionId': 'b' * 32}, 'stale_lease'),
                             ({'expiresAtMs': NOW}, 'expired'),
                             ({'expiresAtMs': NOW + 10 ** 9}, 'expired')], start=50):
            frame, keep_going = self.cue(self.motion(n=number, **change))
            self.assertEqual((frame['event'], frame['code'], keep_going), ('rejected', code, True), change)
        self.assertEqual(self.log, [])

    def test_unresolved_action_blocks_motion(self):
        self.unresolved = True
        frame, _ = self.cue(self.motion())
        self.assertEqual(frame['code'], 'unresolved_action')
        self.assertEqual(self.log, [])

    def test_a_repeated_command_never_reaches_the_robot_again(self):
        self.cue(self.motion())
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], frame['outcome'], keep_going), ('duplicate', 'completed', True))
        self.assertEqual(len([entry for entry in self.log if entry[0] == 'motion']), 1)

    def test_a_lost_result_replays_as_unknown_not_failed(self):
        self.ledger.reserve(cid(1), {'commandId': cid(1)})  # reserved, never finished
        frame, _ = self.cue(self.motion())
        self.assertEqual((frame['event'], frame['outcome']), ('duplicate', 'unknown'))
        self.assertEqual(self.log, [])

    def test_a_readiness_refusal_rejects_and_ends_the_session_like_robot_action(self):
        self.result = {'event': 'not_ready', 'code': 'posture', 'reason': 'Stand it first.'}
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], frame['code'], frame['sessionEnded'], keep_going), ('rejected', 'posture', True, False))

    def test_protocol_refusals_keep_the_session(self):
        frame, keep_going = self.cue(self.motion(preset='safety/is_robot_static'))
        self.assertEqual((frame['event'], keep_going, 'sessionEnded' in frame), ('rejected', True, False))

    def test_a_dirty_terminal_result_ends_the_session(self):
        self.result = {'event': 'terminal', 'status': 'ABORTED', 'errorCategory': 2, 'readyForNext': False}
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], frame['sessionEnded'], keep_going), ('failed', True, False))

    def test_an_exception_is_unknown_and_ends_the_session(self):
        self.result = RuntimeError('provider gone')
        frame, keep_going = self.cue(self.motion())
        self.assertEqual((frame['event'], keep_going), ('unknown', False))
        self.assertNotIn('provider gone', json.dumps(frame))
        self.assertEqual(self.ledger.read(cid(1))['outcome'], 'unknown')

    def test_malformed_identity_is_a_protocol_error(self):
        with self.assertRaises(ValueError):
            self.cue(self.motion(commandId='nope'))


class ServeTests(Harness):
    def serve(self, lines, core=True):
        stream = StdinFeed([json.dumps(line) if isinstance(line, dict) else line for line in lines])
        out = io.StringIO()
        with patch('sys.stdout', out):
            code = studio.serve(self.face_core, self.core if core else None, stream, wait=ready(stream), clock=lambda: 0)
        return code, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_faces_and_motion_share_one_session_in_order(self):
        code, frames = self.serve([self.face_cue(), self.motion(), {'op': 'close'}])
        self.assertEqual(code, 0)
        self.assertEqual([frame['event'] for frame in frames], ['started', 'completed'])

    def test_motion_is_refused_when_the_session_was_not_armed(self):
        code, frames = self.serve([self.motion()], core=False)
        self.assertEqual((code, frames[0]['code']), (0, 'motion_off'))
        self.assertEqual(self.log, [])

    def test_a_failed_motion_ends_the_session_with_an_error_code(self):
        self.result = {'event': 'terminal', 'status': 'ABORTED', 'errorCategory': 1, 'readyForNext': False}
        code, frames = self.serve([self.motion(), self.face_cue()])
        self.assertEqual((code, [frame['event'] for frame in frames]), (1, ['failed']))
        self.assertEqual([entry[0] for entry in self.log], ['motion'])

    def test_an_uncertain_display_result_ends_the_session_before_any_motion(self):
        def broken(*_args):
            raise RuntimeError('display gone')
        self.display.play = broken
        code, frames = self.serve([self.face_cue(), self.motion()])
        self.assertEqual((code, [frame['event'] for frame in frames]), (1, ['unknown']))
        self.assertNotIn('motion', [entry[0] for entry in self.log])

    def test_a_readiness_refusal_ends_the_session_so_a_later_cue_cannot_run(self):
        self.result = {'event': 'not_ready', 'code': 'posture', 'reason': 'Stand it first.'}
        code, frames = self.serve([self.motion(), self.face_cue()])
        self.assertEqual((code, [frame['event'] for frame in frames]), (1, ['rejected']))
        self.assertNotIn('face', [entry[0] for entry in self.log])

    def test_eof_returns_cleanly(self):
        self.assertEqual(self.serve([])[0], 0)

    def test_oversized_and_unterminated_frames_are_protocol_errors(self):
        stream = StdinFeed([])
        stream.lines = ['{"op":"close"}']  # no newline
        with self.assertRaises(ValueError):
            studio.serve(self.face_core, self.core, stream, wait=ready(stream), clock=lambda: 0)

    def test_cancellation_is_the_only_frame_allowed_during_a_cue(self):
        seen = {}

        def run_cue(preset, logical_id, canceled):
            seen['cancel'] = canceled()
            return self.result
        self.core.run_cue = run_cue
        stream = StdinFeed([json.dumps(self.motion()), json.dumps({'op': 'cancel', 'commandId': cid(1)})])
        out = io.StringIO()
        with patch('sys.stdout', out):
            studio.serve(self.face_core, self.core, stream, wait=lambda r, *_: (r, [], []) if stream.lines else ([], [], []),
                         clock=lambda: 0)
        self.assertTrue(seen['cancel'])

    def test_a_pipelined_frame_during_a_cue_ends_the_session_as_unknown(self):
        def run_cue(preset, logical_id, canceled):
            canceled()
        self.core.run_cue = run_cue
        code, frames = self.serve([self.motion(), self.face_cue()])
        self.assertEqual((code, [frame['event'] for frame in frames]), (1, ['unknown']))
        self.assertNotIn('face', [entry[0] for entry in self.log])


class CommandLineTests(unittest.TestCase):
    def test_default_is_an_offline_preview_and_lists_no_motion_route(self):
        out = io.StringIO()
        with patch('sys.stdout', out):
            self.assertEqual(studio.main([]), 0)
        event = json.loads(out.getvalue())
        self.assertEqual((event['event'], event['motion']), ('preview', False))
        self.assertNotIn('/rcp/execute_task', event['routes'])

    def test_motion_requires_the_onsite_confirmation_flag(self):
        with self.assertRaises(SystemExit) as raised, patch('sys.stderr', io.StringIO()):
            studio.main(['--serve', '--motion', '--lease', '5'])
        self.assertEqual(raised.exception.code, 2)

    def test_serve_requires_a_positive_lease(self):
        with self.assertRaises(SystemExit) as raised, patch('sys.stderr', io.StringIO()):
            studio.main(['--serve'])
        self.assertEqual(raised.exception.code, 2)

    def test_motion_is_refused_off_the_robot(self):
        with self.assertRaisesRegex(RuntimeError, 'ARM64 robot'):
            studio.main(['--serve', '--motion', '--confirm-motion', '--lease', '5'])


class MoveCoreTests(Harness):
    def test_a_move_completes_through_the_same_guarded_runner(self):
        frame, keep_going = self.cue(self.move())
        self.assertEqual((frame['event'], keep_going), ('completed', True))
        self.assertEqual(self.log, [('move', 'move/step_forward', cid(1), ('step_forward', None))])

    def test_a_face_rides_along_and_the_screen_is_handed_back_after(self):
        self.cue(self.move(move='turn_left_30', faceId=86))
        self.assertEqual([entry[0] for entry in self.log], ['move', 'release'])
        self.assertEqual(self.log[0][3], ('turn_left_30', 86))
        self.assertFalse(self.face_core.uncertain)

    def test_a_shown_face_is_released_before_a_move_starts(self):
        self.face_core.handle(self.face_cue())
        self.cue(self.move())
        self.assertEqual([entry[0] for entry in self.log], ['face', 'release', 'move'])

    def test_a_failed_release_after_a_move_ends_the_session(self):
        self.display.release_status = 1
        frame, keep_going = self.cue(self.move(move='turn_left_30', faceId=86))
        self.assertEqual((frame['event'], keep_going, frame['sessionEnded']), ('failed', False, True))
        self.assertIn('screen', frame['reason'])

    def test_a_move_that_dies_mid_cue_is_unknown_and_leaves_the_screen_marked_for_release(self):
        self.result = RuntimeError('boom')
        frame, keep_going = self.cue(self.move(move='turn_left_30', faceId=86))
        self.assertEqual((frame['event'], keep_going), ('unknown', False))
        self.assertTrue(self.face_core.uncertain)  # the session's exit path will release it

    def test_refusals_never_run_anything(self):
        counter = iter(range(100))
        for name, command in {
            'unknown move': self.move(move='backflip'),
            'a preset smuggled in as a move': self.move(move='actions/WAVE.json'),
            'stale lease': self.move(leaseGeneration=LEASE + 1),
            'expired': self.move(expiresAtMs=NOW - 1),
            'unlisted face': self.move(move='turn_left_30', faceId=3),
            'restricted face': self.move(move='turn_left_30', faceId=66),
            'non-integer face': self.move(move='turn_left_30', faceId='86'),
            'boolean face': self.move(move='turn_left_30', faceId=True),
        }.items():
            with self.subTest(name):
                self.log.clear()
                frame, keep_going = self.cue({**command, 'commandId': cid(500 + next(counter))})
                self.assertEqual((frame['event'], keep_going), ('rejected', True))
                self.assertEqual(self.log, [])

    def test_a_step_with_a_face_is_refused_before_anything_runs(self):
        for name in studio.FACELESS_MOVES:
            self.log.clear()
            frame, keep_going = self.cue(self.move(700 + sorted(studio.FACELESS_MOVES).index(name), move=name, faceId=86))
            self.assertEqual((frame['event'], frame['code'], keep_going), ('rejected', 'face_not_supported', True))
            self.assertEqual(self.log, [])

    def test_an_unresolved_action_blocks_a_move(self):
        self.unresolved = True
        frame, _ = self.cue(self.move())
        self.assertEqual(frame['code'], 'unresolved_action')
        self.assertEqual(self.log, [])

    def test_a_repeat_identity_is_never_replayed(self):
        self.cue(self.move())
        frame, _ = self.cue(self.move())
        self.assertEqual(frame['event'], 'duplicate')
        self.assertEqual(len([e for e in self.log if e[0] == 'move']), 1)

    def test_a_dirty_result_ends_the_session(self):
        self.result = {'event': 'terminal', 'status': 'ABORTED', 'errorCategory': 3, 'readyForNext': False}
        frame, keep_going = self.cue(self.move())
        self.assertEqual((frame['event'], keep_going, frame['sessionEnded']), ('failed', False, True))

    def test_a_readiness_refusal_disarms_like_a_preset(self):
        self.result = {'event': 'not_ready', 'code': 'posture', 'reason': 'Stand it first.'}
        frame, keep_going = self.cue(self.move())
        self.assertEqual((frame['event'], frame['code'], keep_going, frame['sessionEnded']), ('rejected', 'posture', False, True))

    def test_serve_routes_move_frames_to_the_motion_core(self):
        out = io.StringIO()
        feed = StdinFeed([json.dumps(self.move(1)), json.dumps({'op': 'close'})])
        with patch('sys.stdout', out):
            code = studio.serve(self.face_core, self.core, feed, wait=ready(feed))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])['event'], 'completed')

    def test_serve_refuses_moves_when_motion_is_off(self):
        out = io.StringIO()
        feed = StdinFeed([json.dumps(self.move(1))])
        with patch('sys.stdout', out):
            studio.serve(self.face_core, None, feed, wait=ready(feed))
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])['code'], 'motion_off')


class MoveTableTests(unittest.TestCase):
    def test_amounts_are_small_finite_and_signed_only_for_turns(self):
        self.assertEqual(set(studio.MOVES), {'step_forward', 'step_back', 'step_left', 'step_right',
                                             'turn_left_30', 'turn_right_30', 'turn_left_90', 'turn_right_90',
                                             'turn_left_10', 'turn_right_10'})
        for name, (method, amount) in studio.MOVES.items():
            if method == 'ROTATE':
                self.assertLessEqual(abs(amount), 1.5708 + 1e-6, name)
                self.assertGreater(abs(amount), 0, name)
            else:
                self.assertTrue(0 < amount <= 0.25, name)
        self.assertEqual(studio.MOVES['turn_left_30'][1], -studio.MOVES['turn_right_30'][1])
        self.assertEqual(studio.MOVES['turn_left_90'][1], -studio.MOVES['turn_right_90'][1])

    def test_the_move_node_has_a_finite_timeout(self):
        self.assertTrue(0 < studio.MOVE_TIMEOUT_MS <= 30000)


try:
    import flatbuffers
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    HAVE_SDK = True
except ImportError:  # the generated classes live in the vendor SDK, not this repo
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, 'needs the vendor aorta classes (run with vbot-lab/.venv/bin/python -I)')
class MoveGoalTests(unittest.TestCase):
    def roundtrip(self, name, face_id):
        goal = studio.make_move_goal(name, face_id, 'c' * 32)
        builder = flatbuffers.Builder(256)
        builder.Finish(goal.Pack(builder))
        return ExecuteTaskGoalT.InitFromPackedBuf(bytes(builder.Output()), 0).input

    @staticmethod
    def text(value):
        return value.decode() if isinstance(value, bytes) else value

    def test_every_graph_move_builds_and_survives_serialization(self):
        for name in studio.MOVES:
            if name in studio.FACELESS_MOVES:
                continue
            for face_id in (None, 0, 86):
                spec = self.roundtrip(name, face_id)
                ids = [self.text(node.id) for node in spec.nodes]
                self.assertEqual(ids, ['move'] if face_id is None else ['face', 'move', 'release'], (name, face_id))

    def test_every_step_is_the_vendor_template_with_exactly_the_documented_arguments(self):
        import json as _json
        for name, task in studio.STEP_TASKS.items():
            spec = self.roundtrip(name, None)
            self.assertEqual(self.text(spec.relativePath), 'atom/move_param.json')
            args = {self.text(a.name): _json.loads(self.text(a.valueJson)) for a in spec.templateArgs}
            self.assertEqual(set(args), {'task_id', 'base_action_task', 'distance_m', 'tts'})
            self.assertEqual((args['base_action_task'], args['distance_m'], args['tts']), (task, studio.MOVES[name][1], 'confirm'))
            self.assertTrue(args['task_id'].startswith('studio-step-'))

    def test_a_step_can_never_be_built_with_a_face(self):
        for name in studio.FACELESS_MOVES:
            with self.assertRaises(ValueError):
                studio.make_move_goal(name, 86, 'c' * 32)

    def test_the_wire_values_match_the_table(self):
        from aorta.services.rcp.BaseActionMethod import BaseActionMethod
        for name, (method, amount) in studio.MOVES.items():
            if name in studio.FACELESS_MOVES:
                continue
            command = [n for n in self.roundtrip(name, None).nodes if self.text(n.id) == 'move'][0].command
            self.assertEqual(command.method, getattr(BaseActionMethod, method))
            self.assertAlmostEqual(command.angleRad if method == 'ROTATE' else command.distanceM, amount, places=4)
            self.assertEqual(command.distanceM if method == 'ROTATE' else command.angleRad, 0.0)

    def test_a_face_is_a_background_node_released_by_a_barrier(self):
        from aorta.services.rcp.NodeLifecycle import NodeLifecycle
        from aorta.services.rcp.ResourceId import ResourceId
        spec = self.roundtrip('turn_left_30', 86)
        face_node, move_node, release = spec.nodes
        self.assertEqual(face_node.lifecycle, NodeLifecycle.DAEMON)
        self.assertEqual(face_node.command.emotionId, 86)
        self.assertEqual(move_node.lifecycle, NodeLifecycle.NORMAL)
        self.assertEqual([self.text(d) for d in move_node.dependencies], ['face'])
        self.assertEqual(release.lifecycle, NodeLifecycle.BARRIER)
        self.assertEqual(sorted(spec.requiredResources), [ResourceId.LEGS, ResourceId.SCREEN])

    def test_a_move_without_a_face_asks_for_the_legs_only_and_never_for_setup(self):
        from aorta.services.rcp.ResourceId import ResourceId
        spec = self.roundtrip('turn_left_30', None)
        self.assertEqual(list(spec.requiredResources), [ResourceId.LEGS])
        self.assertFalse(spec.requiresStatic)
        self.assertEqual(spec.nodes[0].executionTimeoutMs, studio.MOVE_TIMEOUT_MS)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DriveHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.clock = FakeClock()
        self.published, self.events = [], []
        self.fail_publish = False
        self.state = {'ready': True}
        self.consumer = True
        self.marker = self.dir / 'unresolved-action.json'
        self.core = studio.DriveCore(
            ledger=face.CommandLedger(self.dir), publish=self.publish, ready=lambda: self.state, matched=lambda: self.consumer,
            unresolved_path=self.marker, session_id=SESSION, lease=LEASE, emit=lambda **f: self.events.append(f),
            clock=self.clock, sleep=self.clock.sleep, now_ms=lambda: NOW)

    def publish(self, vx, vy, wz):
        if self.fail_publish:
            raise RuntimeError('publisher down')
        self.published.append((vx, vy, wz))

    def start(self, n=1, **over):
        return self.core.begin({'op': 'drive_start', 'commandId': cid(n), 'sessionId': SESSION, 'leaseGeneration': LEASE,
                                'expiresAtMs': NOW + 30000, **over})

    def frame(self, seq, vx=0.0, vy=0.0, wz=0.0, **over):
        return json.dumps({'op': 'drive', 'seq': seq, 'vx': vx, 'vy': vy, 'wz': wz, **over})

    def zeros_at_end(self):
        tail = self.published[-studio.ZERO_BURST:]
        return len(tail) == studio.ZERO_BURST and all(v == (0.0, 0.0, 0.0) for v in tail)


class DriveStartTests(DriveHarness):
    def test_a_start_arms_the_drive_and_takes_the_marker(self):
        reply = self.start()
        self.assertEqual(reply['event'], 'drive_started')
        self.assertEqual(reply['limits'], studio.DRIVE_LIMITS)
        self.assertTrue(self.core.active and self.marker.exists())
        self.assertEqual(self.published, [])  # arming publishes nothing

    def test_refusals_publish_nothing_and_leave_no_marker(self):
        for number, (name, setup, over) in enumerate([
            ('stale lease', lambda: None, {'leaseGeneration': LEASE + 1}),
            ('expired', lambda: None, {'expiresAtMs': NOW - 1}),
            ('not ready', lambda: self.state.update(ready=False, code='posture', reason='Stand it first.'), {}),
            ('no consumer', lambda: setattr(self, 'consumer', False), {}),
            ('marker present', lambda: self.marker.write_text('{}'), {}),
        ]):
            with self.subTest(name):
                self.state, self.consumer = {'ready': True}, True
                self.marker.unlink(missing_ok=True)
                self.core.active = False
                setup()
                reply = self.start(900 + number, **over)
                self.assertEqual(reply['event'], 'rejected', name)
                self.assertFalse(self.core.active)
                self.assertEqual(self.published, [])
                if name != 'marker present':
                    self.assertFalse(self.marker.exists())

    def test_a_repeated_identity_is_a_duplicate_not_a_second_drive(self):
        self.start()
        self.core.end('stopped', None)
        self.assertEqual(self.start()['event'], 'duplicate')
        self.assertFalse(self.core.active)

    def test_a_malformed_id_is_a_protocol_error(self):
        with self.assertRaises(ValueError):
            self.core.begin({'op': 'drive_start', 'commandId': 'nope'})


class DriveRunTests(DriveHarness):
    def setUp(self):
        super().setUp()
        self.start()

    def test_fresh_frames_are_published_each_tick_and_nothing_before_the_first(self):
        self.core.tick()
        self.assertEqual(self.published, [])
        self.core.ingest(self.frame(1, vx=0.1, wz=-0.2))
        self.clock.now += 0.05
        self.core.tick(); self.core.tick()
        self.assertEqual(self.published, [(0.1, 0.0, -0.2)] * 2)

    def test_old_or_repeated_sequence_numbers_are_ignored(self):
        self.core.ingest(self.frame(5, vx=0.1))
        self.core.ingest(self.frame(4, vx=0.15))
        self.core.ingest(self.frame(5, vx=0.15))
        self.core.tick()
        self.assertEqual(self.published, [(0.1, 0.0, 0.0)])

    def test_release_publishes_a_burst_of_zeros_and_clears_the_marker(self):
        self.core.ingest(self.frame(1, vx=0.1))
        self.core.ingest(json.dumps({'op': 'drive_stop', 'commandId': cid(2)}))
        self.assertFalse(self.core.active)
        self.assertTrue(self.zeros_at_end())
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.events[-1]['event'], self.events[-1]['reason'], self.events[-1]['zeroed']), ('drive_stopped', 'stopped', True))
        self.assertFalse(self.core.session_over)

    def test_stale_frames_stop_the_dog_without_any_further_input(self):
        self.core.ingest(self.frame(1, vx=0.1))
        self.clock.now += studio.DRIVE_FRESH_S + 0.01
        self.core.tick()
        self.assertFalse(self.core.active)
        self.assertTrue(self.zeros_at_end())
        self.assertEqual(self.events[-1]['reason'], 'timeout')
        self.assertFalse(self.marker.exists())

    def test_no_first_frame_within_the_grace_ends_the_drive(self):
        self.clock.now += studio.DRIVE_FIRST_FRAME_S + 0.01
        self.core.tick()
        self.assertEqual(self.events[-1]['reason'], 'timeout')
        self.assertTrue(self.zeros_at_end())

    def test_the_per_press_cap_ends_a_drive_even_while_frames_keep_coming(self):
        seq = 0
        while self.clock.now - self.core.started <= studio.DRIVE_MAX_S:
            seq += 1
            self.core.ingest(self.frame(seq, vx=0.1))
            self.clock.now += 0.1
            self.core.tick()
        self.assertFalse(self.core.active)
        self.assertEqual(self.events[-1]['reason'], 'limit')
        self.assertTrue(self.zeros_at_end())
        self.assertFalse(self.core.session_over)  # routine: a fresh press continues

    def test_over_cap_and_bad_values_end_the_drive_and_never_publish_the_value(self):
        bad = [dict(vx=studio.DRIVE_MAX['vx'] + 0.001), dict(vy=-studio.DRIVE_MAX['vy'] - 0.001), dict(wz=1.0),
               dict(vx=float('nan')), dict(wz=float('inf')), dict(vx=True), dict(vx='0.1'), dict(vx=None)]
        for over in bad:
            with self.subTest(over=over):
                self.setUp()
                self.core.ingest(self.frame(1, **over))
                self.assertFalse(self.core.active)
                self.assertTrue(all(v == (0.0, 0.0, 0.0) for v in self.published), self.published)
                self.assertTrue(self.zeros_at_end())
                self.assertEqual(self.events[-1]['reason'], 'violation')
                self.assertTrue(self.core.session_over)

    def test_a_missing_axis_or_bad_seq_is_a_violation(self):
        for text in [json.dumps({'op': 'drive', 'seq': 1, 'vx': 0.1}), self.frame(-1), self.frame(1.5), self.frame(True), 'not json', '[]',
                     json.dumps({'op': 'move', 'move': 'step_forward'}), json.dumps({'op': 'motion'})]:
            with self.subTest(text=text):
                self.setUp()
                self.core.ingest(text)
                self.assertFalse(self.core.active)
                self.assertTrue(self.zeros_at_end())

    def test_eof_a_close_frame_and_an_interrupt_each_publish_zeros(self):
        for ending in ['eof', 'closed', 'interrupted']:
            with self.subTest(ending):
                self.setUp()
                self.core.ingest(self.frame(1, vx=0.1))
                if ending == 'closed':
                    self.core.ingest(json.dumps({'op': 'close'}))
                else:
                    self.core.end(ending, None, over=True)
                self.assertTrue(self.zeros_at_end())
                self.assertTrue(self.core.session_over)

    def test_a_failing_publisher_ends_the_drive_and_keeps_the_lock(self):
        self.core.ingest(self.frame(1, vx=0.1))
        self.fail_publish = True
        self.core.tick()
        self.assertFalse(self.core.active)
        self.assertFalse(self.core.zeroed)
        self.assertTrue(self.marker.exists(), 'a stop that could not be confirmed must leave the unresolved-action lock')
        self.assertTrue(self.core.session_over)
        self.assertFalse(self.events[-1]['zeroed'])

    def test_ending_twice_publishes_one_burst(self):
        self.core.ingest(self.frame(1, vx=0.1))
        self.core.end('stopped', None)
        count = len(self.published)
        self.core.end('timeout', None)
        self.assertEqual(len(self.published), count)

    def test_zeros_are_exactly_the_burst_length_and_spaced(self):
        started = self.clock.now
        self.core.end('stopped', None)
        self.assertEqual(self.published, [(0.0, 0.0, 0.0)] * studio.ZERO_BURST)
        self.assertAlmostEqual(self.clock.now - started, studio.ZERO_GAP_S * (studio.ZERO_BURST - 1))


class FakeFd:
    """A file descriptor stand-in: each poll hands back the next chunk of bytes, then EOF."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def wait(self, readers, *_):
        return (readers, [], [])  # always readable: an exhausted fd reads b'' which is EOF

    def read(self, _fd, _n):
        return self.chunks.pop(0) if self.chunks else b''


class DriveLoopTests(DriveHarness):
    def reader(self, chunks):
        fd = FakeFd(chunks)
        return studio.FdLineReader(7, wait=fd.wait, read=fd.read)

    def test_a_frame_split_across_reads_is_assembled_and_never_blocks(self):
        reader = self.reader([b'{"op": "drive", "seq": 1, "vx": 0.1,', b' "vy": 0.0, "wz": 0.0}\n'])
        self.assertEqual(reader.poll(0.05), ([], False))
        lines, _ = reader.poll(0.05)
        self.assertEqual(len(lines), 1)

    def test_an_oversized_unterminated_frame_is_an_error(self):
        reader = self.reader([b'x' * (face.FRAME_LIMIT + 10)])
        with self.assertRaises(ValueError):
            reader.poll(0.05)

    def test_run_drive_follows_a_hold_to_its_release(self):
        self.start()
        stop = json.dumps({'op': 'drive_stop', 'commandId': cid(9)}).encode()
        reader = self.reader([self.frame(1, vx=0.1).encode() + b'\n', self.frame(2, vx=0.1).encode() + b'\n', stop + b'\n'])
        studio.run_drive(self.core, reader, threaded=False)
        self.assertFalse(self.core.active)
        self.assertTrue(self.zeros_at_end())
        self.assertEqual(self.events[-1]['event'], 'drive_stopped')
        self.assertEqual(self.events[-1]['commandId'], cid(9))

    def test_run_drive_treats_a_closed_stream_as_a_stop(self):
        self.start()
        studio.run_drive(self.core, self.reader([self.frame(1, vx=0.1).encode() + b'\n']), threaded=False)
        self.assertTrue(self.zeros_at_end())
        self.assertTrue(self.core.session_over)
        self.assertEqual(self.events[-1]['reason'], 'eof')

    def test_input_left_over_after_a_drive_is_a_protocol_error(self):
        self.start()
        chunk = json.dumps({'op': 'drive_stop', 'commandId': cid(9)}).encode() + b'\n' + b'{"op": "face"'
        with self.assertRaises(ValueError):
            studio.run_drive(self.core, self.reader([chunk]), threaded=False)
        self.assertTrue(self.zeros_at_end())

    def test_serve_runs_a_drive_then_goes_back_to_ordinary_frames(self):
        out = io.StringIO()
        motion = studio.MotionCore(ledger=self.core.ledger, face_core=face.FaceCore(
            ledger=self.core.ledger, display=FakeDisplay([]), health=Healthy(), session_id=SESSION, lease=LEASE, supported={86}, now_ms=lambda: NOW),
            run_cue=lambda *a, **k: None, unresolved=lambda: False, session_id=SESSION, lease=LEASE, presets=frozenset(), now_ms=lambda: NOW)
        start = json.dumps({'op': 'drive_start', 'commandId': cid(1), 'sessionId': SESSION, 'leaseGeneration': LEASE, 'expiresAtMs': NOW + 30000})
        feed = StdinFeed([start, json.dumps({'op': 'drive_stop', 'commandId': cid(2)}), json.dumps({'op': 'close'})])
        reader = self.reader([self.frame(1, vx=0.1).encode() + b'\n', json.dumps({'op': 'drive_stop', 'commandId': cid(3)}).encode() + b'\n'])
        with patch('sys.stdout', out):
            code = studio.serve(motion.face_core, motion, feed, wait=ready(feed), drive_core=self.core, make_reader=lambda: reader)
        self.assertEqual(code, 0)
        self.assertTrue(self.zeros_at_end())

    def test_serve_refuses_a_drive_when_driving_is_off(self):
        out = io.StringIO()
        feed = StdinFeed([json.dumps({'op': 'drive_start', 'commandId': cid(1)})])
        face_core = face.FaceCore(ledger=face.CommandLedger(self.dir), display=FakeDisplay([]), health=Healthy(), session_id=SESSION,
                                  lease=LEASE, supported={86}, now_ms=lambda: NOW)
        with patch('sys.stdout', out):
            studio.serve(face_core, None, feed, wait=ready(feed))
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])['code'], 'drive_off')

    def test_a_stop_with_nothing_running_is_acknowledged(self):
        out = io.StringIO()
        feed = StdinFeed([json.dumps({'op': 'drive_stop', 'commandId': cid(5)}), json.dumps({'op': 'close'})])
        face_core = face.FaceCore(ledger=face.CommandLedger(self.dir), display=FakeDisplay([]), health=Healthy(), session_id=SESSION,
                                  lease=LEASE, supported={86}, now_ms=lambda: NOW)
        with patch('sys.stdout', out):
            studio.serve(face_core, None, feed, wait=ready(feed))
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])['event'], 'drive_stopped')


class DriveThreadTests(unittest.TestCase):
    def test_the_watchdog_stops_the_dog_even_while_the_reader_is_stuck(self):
        import threading, time
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stamps = {}
        published = []

        def publish(vx, vy, wz):
            published.append((vx, vy, wz))
            if (vx, vy, wz) == (0.0, 0.0, 0.0):
                stamps.setdefault('zero', time.monotonic())
        core = studio.DriveCore(ledger=face.CommandLedger(Path(tmp.name)), publish=publish, ready=lambda: {'ready': True},
                                matched=lambda: True, unresolved_path=Path(tmp.name) / 'unresolved-action.json', session_id=SESSION,
                                lease=LEASE, emit=lambda **f: None, sleep=lambda s: None, now_ms=lambda: NOW)

        class StuckReader:
            buffer = b''

            def __init__(self):
                self.calls = 0

            def poll(self, timeout):
                self.calls += 1
                if self.calls == 1:
                    core.ingest(json.dumps({'op': 'drive', 'seq': 1, 'vx': 0.1, 'vy': 0.0, 'wz': 0.0}))
                    time.sleep(0.6)      # a half-delivered frame: the read side is stuck for far longer than the deadline
                    stamps['unstuck'] = time.monotonic()
                    return [], False
                return [], True
        with patch.object(studio, 'DRIVE_FRESH_S', 0.1), patch.object(studio, 'DRIVE_TICK_S', 0.02):
            self.assertEqual(core.begin({'op': 'drive_start', 'commandId': cid(1), 'sessionId': SESSION, 'leaseGeneration': LEASE,
                                         'expiresAtMs': NOW + 30000})['event'], 'drive_started')
            studio.run_drive(core, StuckReader(), threaded=True)
        self.assertEqual(core.reason, 'timeout')
        self.assertLess(stamps['zero'], stamps['unstuck'] - 0.2, 'zeros must go out while the reader is still stuck')
        self.assertTrue(all(v == (0.0, 0.0, 0.0) for v in published[-studio.ZERO_BURST:]))


class DriveInvariantTests(unittest.TestCase):
    source = (ROOT / 'vbot-demo' / 'robot_studio.py').read_text()

    def test_there_is_exactly_one_velocity_publisher_and_one_publish_site(self):
        self.assertEqual(self.source.count('create_publisher_typed('), 1)
        self.assertEqual(self.source.count('publish_typed('), 1)
        self.assertEqual(self.source.count('VELOCITY_TOPIC'), 2)  # the constant and its one use
        self.assertNotIn('joy', self.source.lower().replace('enjoy', ''))

    def test_the_caps_are_small_and_finite(self):
        self.assertTrue(all(0 < cap <= 0.4 for cap in studio.DRIVE_MAX.values()))
        self.assertLessEqual(studio.DRIVE_FRESH_S, 0.5)
        self.assertLessEqual(studio.DRIVE_MAX_S, 10)
        self.assertGreaterEqual(studio.ZERO_BURST, 3)

    def test_every_non_zero_publish_comes_from_the_tick_and_the_rest_are_zeros(self):
        publishes = [line.strip() for line in self.source.splitlines() if 'self.publish(' in line]
        self.assertEqual(sorted(publishes), ['self.publish(*command)', 'self.publish(0.0, 0.0, 0.0)'])

    def test_the_watchdog_runs_off_the_reading_thread(self):
        self.assertIn('threading.Thread(target=loop', self.source)
        self.assertIn('select.select', self.source)  # reads are select-gated and never a bare readline during a drive


class SourceInvariantTests(unittest.TestCase):
    source = (ROOT / 'vbot-demo' / 'robot_studio.py').read_text()

    def test_motion_reuses_the_guarded_path_rather_than_a_second_scheduler(self):
        for needed in ['action.rescan_cue(', 'action.execute_preset(', 'action.LiveReadiness(',
                       'action.make_static_probe(', 'action.precondition_refusal(', 'frozenset(action.PRESETS)']:
            self.assertIn(needed, self.source)
        for forbidden in ['send_goal_with_id', 'lowlevel_action', 'set_run_mode', 'BodyCommand', 'LocomotionCommand',
                          'requiresStatic=True', 'VlnCommand', 'NavigateCommand']:
            self.assertNotIn(forbidden, self.source)

    def test_the_only_custom_graph_is_the_bounded_move_builder(self):
        # A custom graph is allowed for exactly one thing, and it is built inside make_move_goal.
        self.assertEqual(self.source.count('DagSpecT('), 1)
        builder = self.source[self.source.index('def make_move_goal'):self.source.index('class MotionCore')]
        self.assertIn('DagSpecT(', builder)
        self.assertEqual(self.source.count('make_move_goal('), 2)  # its definition and the one call
        self.assertEqual(self.source.count('goal_factory=lambda _: goal'), 1)
        # The goal is built before execute_preset writes any record.
        perform = self.source[self.source.index('def perform'):self.source.index('result = action.rescan_cue')]
        self.assertLess(perform.index('make_move_goal('), perform.index('goal_factory=lambda _: goal'))

    def test_the_face_only_helper_stays_face_only(self):
        helper = (ROOT / 'vbot-demo' / 'robot_face.py').read_text()
        self.assertNotIn('execute_task', helper)
        self.assertNotIn('import robot_action', helper)


if __name__ == '__main__':
    unittest.main()
