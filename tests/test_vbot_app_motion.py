"""Studio motion through the app controller, with fake sessions and streams. No robot I/O."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'vbot-demo'))

import test_vbot_app_control as base  # noqa: E402
import robot_action  # noqa: E402
import vbot_app_control as control  # noqa: E402
from vbot_app_control import AppController, FaceSession, OutcomeUnknown, Rejected, route, validate_score  # noqa: E402

CONFIRMED = {'onsite': True, 'standing': True, 'clear': True}
WAVE = {'id': 'm', 'type': 'body', 'preset': 'actions/WAVE.json'}
LOOK = {'id': 'l', 'type': 'head', 'preset': 'atom/look_left.json'}
FACE = {'id': 'f', 'type': 'face', 'assetId': 86, 'durationMs': 4500}
FACE2 = {'id': 'g', 'type': 'face', 'assetId': 70, 'durationMs': 500}


class MotionSession(base.FakeSession):
    motion = True

    def __init__(self):
        super().__init__()
        self.motion_results = []

    def play_motion(self, preset):
        self.calls.append(('motion', preset))
        result = self.motion_results.pop(0) if self.motion_results else {'event': 'completed'}
        if isinstance(result, Exception):
            raise result
        return result


class MotionCase(base.ControllerCase):
    def setUp(self):
        super().setUp()
        self.made = []
        self.session = MotionSession()

        def factory(target, session_id, lease, anchor, **options):
            self.made.append(options)
            return self.session
        self.controller = AppController(journal_path=self.journal, session_factory=factory,
                                        identity_reader=lambda target: {'anchor': 'alias', 'deviceId': base.DEVICE},
                                        wall_ms=lambda: self.now, waiter=lambda cancel, seconds: cancel.is_set())

    def arm(self):
        return self.controller.connect({'target': 'vbot@192.168.1.20', 'motion': dict(CONFIRMED)})

    def show(self, *cues, **over):
        return self.envelope(score=base.score(cues=list(cues)), **over)


class ArmingTests(MotionCase):
    def test_the_approved_presets_are_exactly_the_dog_side_list(self):
        self.assertEqual(control.MOTION_PRESETS, robot_action.PRESETS)

    def test_motion_needs_every_confirmation_to_be_exactly_true(self):
        for bad in [{}, {'onsite': True}, {**CONFIRMED, 'clear': False}, {**CONFIRMED, 'standing': 1},
                    {**CONFIRMED, 'onsite': 'true'}, 'yes', True, ['onsite', 'standing', 'clear']]:
            with self.subTest(bad=bad), self.assertRaises(Rejected) as caught:
                self.controller.connect({'target': 'vbot@192.168.1.20', 'motion': bad})
            self.assertEqual(caught.exception.code, 'motion_not_confirmed')
        self.assertEqual(self.made, [])
        self.assertEqual(self.controller.status()['connection'], 'disconnected')

    def test_the_http_route_reports_a_missing_confirmation_as_a_400(self):
        status, body = route(self.controller, 'connect', {'target': 'vbot@192.168.1.20', 'motion': {'onsite': True}})
        self.assertEqual((status, body['code']), (400, 'motion_not_confirmed'))

    def test_an_ordinary_connect_stays_face_only(self):
        status = self.connect()
        self.assertEqual(self.made, [{}])
        self.assertFalse(status['capabilities']['body']['available'])
        self.assertEqual(status['capabilities']['armedPresets'], [])

    def test_a_confirmed_connect_arms_this_connection_only(self):
        status = self.arm()
        self.assertEqual(self.made, [{'motion': True}])
        capabilities = status['capabilities']
        self.assertTrue(capabilities['head']['available'] and capabilities['body']['available'])
        self.assertEqual(capabilities['armedPresets'], list(control.MOTION_PRESETS))
        self.assertEqual(capabilities['rehearsedPresets'], [])  # nothing claims a rehearsal
        self.controller.disconnect()
        self.connect()
        self.assertFalse(self.controller.status()['capabilities']['body']['available'])

    def test_motion_lapses_when_the_dog_session_would_end(self):
        self.arm()
        self.now += control.MOTION_SESSION_MS
        self.assertFalse(self.controller.status()['capabilities']['body']['available'])
        receipt = self.controller.submit(self.show(WAVE))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'capability_unavailable'))
        self.assertNotIn(('motion', 'actions/WAVE.json'), self.session.calls)


class ValidationTests(MotionCase):
    def test_unapproved_or_mismatched_presets_are_rejected_even_when_armed(self):
        for cue in [{'id': 'a', 'type': 'body', 'preset': 'actions/DANCE_ALL_NIGHT.json'},
                    {'id': 'a', 'type': 'body', 'preset': 'safety/is_robot_static'},
                    {'id': 'a', 'type': 'head', 'preset': 'actions/WAVE.json'},
                    {'id': 'a', 'type': 'body', 'preset': 'atom/look_left.json'},
                    {'id': 'a', 'type': 'body', 'preset': 'actions/WAVE.json', 'durationMs': 1000},
                    {'id': 'a', 'type': 'body', 'preset': 'actions/WAVE.json', 'params': {}},
                    {'id': 'a', 'type': 'body'}, {'id': 'a', 'type': 'body', 'preset': 7}]:
            with self.subTest(cue=cue), self.assertRaises(Rejected):
                validate_score(base.score(cues=[cue]), motion=True)

    def test_motion_is_still_refused_by_default(self):
        with self.assertRaises(Rejected) as caught:
            validate_score(base.score(cues=[WAVE]))
        self.assertEqual(caught.exception.code, 'capability_unavailable')

    def test_motion_counts_toward_the_fifteen_minute_bound(self):
        cues = [{'id': f'm{i}', 'type': 'body', 'preset': 'actions/WAVE.json'} for i in range(16)]
        with self.assertRaises(Rejected):
            validate_score(base.score(cues=cues), motion=True)
        validate_score(base.score(cues=cues[:15]), motion=True)

    def test_an_unarmed_connection_refuses_a_motion_show_and_runs_nothing(self):
        self.session = base.FakeSession()
        self.connect()
        receipt = self.controller.submit(self.show(FACE, WAVE))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'capability_unavailable'))
        self.assertEqual(self.session.calls, [])


class RunTests(MotionCase):
    def test_faces_and_motion_run_strictly_in_order(self):
        self.arm()
        self.assertEqual(self.controller.submit(self.show(FACE, WAVE, LOOK, FACE2))['state'], 'accepted')
        self.finish()
        self.assertEqual(self.session.calls, [('play', 86, 4500), ('motion', 'actions/WAVE.json'),
                                              ('motion', 'atom/look_left.json'), ('play', 70, 500), ('release',)])
        run = self.controller.status()['run']
        self.assertEqual((run['state'], run['completedCues'], run['cleanup']), ('completed', 4, 'released'))

    def test_a_motion_only_show_does_not_touch_the_display(self):
        self.arm()
        self.controller.submit(self.show(WAVE))
        self.finish()
        self.assertEqual(self.session.calls, [('motion', 'actions/WAVE.json')])
        self.assertEqual(self.controller.status()['run']['cleanup'], 'not-needed')

    def test_a_readiness_refusal_ends_the_show_and_disarms_the_connection(self):
        self.arm()
        self.session.motion_results = [{'event': 'rejected', 'code': 'posture', 'reason': 'Stand it first.', 'sessionEnded': True}]
        self.controller.submit(self.show(WAVE, FACE))
        self.finish()
        status = self.controller.status()
        self.assertEqual((status['run']['state'], status['run']['reason'], status['connection']), ('rejected', 'Stand it first.', 'disconnected'))
        self.assertIn('reconnect with the onsite confirmations', status['detail'])
        self.assertFalse(status['capabilities']['body']['available'])
        self.assertEqual(self.controller.motion_until, 0)
        self.assertTrue(self.session.closed)
        self.assertEqual(self.session.calls, [('motion', 'actions/WAVE.json')])

    def test_a_protocol_refusal_stops_the_show_but_keeps_the_connection(self):
        self.arm()
        self.session.motion_results = [{'event': 'rejected', 'code': 'expired', 'reason': 'Too late.'}]
        self.controller.submit(self.show(WAVE, FACE))
        self.finish()
        status = self.controller.status()
        self.assertEqual((status['run']['state'], status['connection']), ('rejected', 'connected'))
        self.assertFalse(self.session.closed)

    def test_an_unclean_preset_ends_the_show_and_loses_the_connection(self):
        for result in [{'event': 'failed', 'reason': 'Aborted.'}, {'event': 'unknown'}, OutcomeUnknown('gone'), RuntimeError('boom')]:
            with self.subTest(result=repr(result)):
                self.setUp()
                self.arm()
                self.session.motion_results = [result]
                self.controller.submit(self.show(WAVE, FACE))
                self.finish()
                status = self.controller.status()
                self.assertEqual((status['run']['state'], status['connection']), ('unknown', 'lost'))
                self.assertEqual(self.session.calls, [('motion', 'actions/WAVE.json')])
                self.assertTrue(self.session.closed)

    def test_a_duplicate_answer_is_judged_by_its_recorded_outcome(self):
        self.arm()
        self.session.motion_results = [{'event': 'duplicate', 'outcome': 'unknown'}]
        self.controller.submit(self.show(WAVE))
        self.finish()
        self.assertEqual(self.controller.status()['run']['state'], 'unknown')

    def test_stop_future_cues_between_presets_skips_the_rest(self):
        self.arm()
        original = self.session.play_motion

        def stopping(preset):
            result = original(preset)
            self.controller.cancel_future({'commandId': 'a' * 32})
            return result
        self.session.play_motion = stopping
        self.controller.submit(self.show(WAVE, LOOK))
        self.finish()
        self.assertEqual(self.session.calls, [('motion', 'actions/WAVE.json')])
        self.assertEqual(self.controller.status()['run']['state'], 'cancelled')

    def test_a_second_show_cannot_start_while_a_preset_runs(self):
        self.arm()
        import threading
        entered, release = threading.Event(), threading.Event()
        original = self.session.play_motion

        def blocking(preset):
            entered.set()
            release.wait(2)
            return original(preset)
        self.session.play_motion = blocking
        self.controller.submit(self.show(WAVE))
        entered.wait(2)
        receipt = self.controller.submit(self.show(LOOK, commandId='b' * 32))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'busy'))
        release.set()
        self.finish()


class MotionSessionWireTests(unittest.TestCase):
    READY = {'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 2, 'faceOnly': False, 'motion': True,
             'motionPresets': list(robot_action.PRESETS), 'supportedFaces': ['086_THINK']}

    def open(self, ready=None, reply=None, motion=True):
        self.commands = []
        reply = reply or (lambda frame: [{'event': 'rescan', 'commandId': frame['commandId'], 'phase': 'acting'},
                                         {'event': 'completed', 'commandId': frame['commandId']}])

        def factory(command):
            self.commands.append(command)
            stream = base.FakeStream(reply)
            stream.lines.append(ready or self.READY)
            self.stream = stream
            return stream
        return FaceSession('vbot@192.168.1.5', 's' * 32, 7, 'alias', stream_factory=factory, wall_ms=lambda: 1000, motion=motion)

    def test_a_motion_connection_runs_the_combined_helper_with_the_onsite_flags(self):
        session = self.open()
        remote = self.commands[0][-1]
        self.assertIn('robot_studio.py', remote)
        self.assertIn('--motion', remote)
        self.assertIn('--confirm-motion', remote)
        self.assertNotIn('robot_face.py', remote)
        self.assertTrue(session.motion)

    def test_a_face_connection_never_names_the_motion_flags(self):
        self.commands = []
        stream = base.FakeStream(lambda frame: [])
        stream.lines.append({'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 1, 'faceOnly': True, 'supportedFaces': []})
        FaceSession('vbot@192.168.1.5', 's' * 32, 7, 'alias', stream_factory=lambda command: self.commands.append(command) or stream)
        self.assertIn('robot_face.py', self.commands[0][-1])
        self.assertNotIn('--confirm-motion', self.commands[0][-1])

    def test_a_face_only_helper_cannot_pass_as_a_motion_helper(self):
        for ready in [{**self.READY, 'protocol': 1}, {**self.READY, 'faceOnly': True}, {**self.READY, 'motion': False},
                      {k: v for k, v in self.READY.items() if k != 'motion'}]:
            with self.subTest(ready=ready), self.assertRaises(Rejected):
                self.open(ready=ready)
            self.assertTrue(self.stream.closed)

    def test_play_motion_sends_one_frame_and_skips_progress_lines(self):
        session = self.open()
        result = session.play_motion('actions/WAVE.json')
        self.assertEqual(result['event'], 'completed')
        frame = self.stream.written[0]
        self.assertEqual((frame['op'], frame['preset']), ('motion', 'actions/WAVE.json'))
        self.assertEqual(frame['expiresAtMs'], 1000 + control.CUE_TTL_MS)

    def test_a_silent_dog_is_an_unknown_outcome(self):
        session = self.open(reply=lambda frame: [])
        session.stream.readLine = lambda _timeout: ''
        original = control.MOTION_REPLY_TIMEOUT
        control.MOTION_REPLY_TIMEOUT = 0.01
        try:
            with self.assertRaises(OutcomeUnknown):
                session.play_motion('actions/WAVE.json')
        finally:
            control.MOTION_REPLY_TIMEOUT = original

    def test_the_reply_window_covers_the_dog_side_worst_case_with_margin(self):
        import inspect
        import robot_studio
        execute = inspect.signature(robot_action.execute_preset).parameters['action_timeout'].default
        settle = inspect.signature(robot_action.settle_postflight).parameters['timeout'].default
        worst = robot_studio.RESCAN_SECONDS + 8 + execute + settle
        self.assertGreaterEqual(control.MOTION_REPLY_TIMEOUT, worst + 5)

    def test_the_module_still_imports_no_dog_side_code(self):
        source = (ROOT / 'server' / 'vbot_app_control.py').read_text()
        for forbidden in ['import robot_', 'from robot_', 'import chess', 'vbot_demo']:
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
