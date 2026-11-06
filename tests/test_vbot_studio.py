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

        def run_cue(preset, logical_id, canceled):
            self.log.append(('motion', preset, logical_id))
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        self.core = studio.MotionCore(ledger=self.ledger, face_core=self.face_core, run_cue=run_cue,
                                      unresolved=lambda: self.unresolved, session_id=SESSION, lease=LEASE,
                                      presets=frozenset(action.PRESETS), now_ms=lambda: NOW)

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


class SourceInvariantTests(unittest.TestCase):
    source = (ROOT / 'vbot-demo' / 'robot_studio.py').read_text()

    def test_motion_reuses_the_guarded_path_rather_than_a_second_scheduler(self):
        for needed in ['action.rescan_cue(', 'action.execute_preset(', 'action.LiveReadiness(',
                       'action.make_static_probe(', 'action.precondition_refusal(', 'frozenset(action.PRESETS)']:
            self.assertIn(needed, self.source)
        for forbidden in ['send_goal_with_id', 'lowlevel_action', 'DagSpecT(', 'set_run_mode']:
            self.assertNotIn(forbidden, self.source)

    def test_the_face_only_helper_stays_face_only(self):
        helper = (ROOT / 'vbot-demo' / 'robot_face.py').read_text()
        self.assertNotIn('execute_task', helper)
        self.assertNotIn('import robot_action', helper)


if __name__ == '__main__':
    unittest.main()
