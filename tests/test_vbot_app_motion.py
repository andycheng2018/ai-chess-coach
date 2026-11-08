"""Studio motion through the app controller, with fake sessions and streams. No robot I/O."""
import json
import threading
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


MOVE = {'id': 'v', 'type': 'move', 'move': 'step_forward'}
TURN_WITH_FACE = {'id': 'w', 'type': 'move', 'move': 'turn_left_30', 'faceId': 86}


class MotionSession(base.FakeSession):
    motion = True
    drive_limits = dict(control.DRIVE_MAX)

    def __init__(self):
        super().__init__()
        self.motion_results = []

    drive_start_result = {'event': 'drive_started'}
    drive_stop_result = {'event': 'drive_stopped', 'reason': 'stopped', 'zeroed': True}

    def drive_start(self):
        self.calls.append(('drive_start',))
        if isinstance(self.drive_start_result, Exception):
            raise self.drive_start_result
        return self.drive_start_result

    def drive_frame(self, seq, vx, vy, wz):
        self.calls.append(('drive_frame', seq, vx, vy, wz))
        if getattr(self, 'frame_error', None):
            raise self.frame_error

    def drive_stop(self):
        self.calls.append(('drive_stop',))
        if isinstance(self.drive_stop_result, Exception):
            raise self.drive_stop_result
        return self.drive_stop_result

    def play_move(self, move, face_id=None):
        self.calls.append(('move', move, face_id))
        result = self.motion_results.pop(0) if self.motion_results else {'event': 'completed'}
        if isinstance(result, Exception):
            raise result
        return result

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
    READY = {'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 4, 'faceOnly': False, 'motion': True,
             'motionPresets': list(robot_action.PRESETS), 'moves': list(control.MOVES), 'drive': dict(control.DRIVE_MAX),
             'supportedFaces': ['086_THINK']}

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
        for ready in [{**self.READY, 'protocol': 1}, {**self.READY, 'protocol': 2}, {**self.READY, 'faceOnly': True},
                      {**self.READY, 'motion': False}, {k: v for k, v in self.READY.items() if k != 'motion'},
                      {k: v for k, v in self.READY.items() if k != 'moves'}, {**self.READY, 'protocol': 3},
                      {k: v for k, v in self.READY.items() if k != 'drive'}, {**self.READY, 'drive': {**control.DRIVE_MAX, 'vx': 0.3}},
                      {**self.READY, 'drive': {'vx': 0.15, 'vy': 0.10}}, {**self.READY, 'drive': None},
                      {**self.READY, 'moves': control.MOVES[:-1]}]:
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


class MoveTests(MotionCase):
    def test_the_move_names_are_exactly_the_dog_side_table(self):
        import robot_studio
        self.assertEqual(control.MOVES, tuple(robot_studio.MOVES))

    def test_an_armed_connection_advertises_the_moves_and_a_plain_one_does_not(self):
        self.assertEqual(self.connect()['capabilities']['armedMoves'], [])
        self.controller.disconnect()
        self.assertEqual(self.arm()['capabilities']['armedMoves'], list(control.MOVES))

    def test_the_move_capability_itself_is_reported_and_follows_arming(self):
        plain = self.connect()['capabilities']
        self.assertFalse(plain['move']['available'])
        self.assertTrue(plain['move']['reason'])
        self.controller.disconnect()
        armed = self.arm()['capabilities']
        self.assertEqual(armed['move'], {'available': True, 'reason': None})
        self.now += control.MOTION_SESSION_MS
        self.assertFalse(self.controller.status()['capabilities']['move']['available'])
        self.assertEqual(self.controller.status()['capabilities']['armedMoves'], [])

    def test_the_faceless_steps_are_exactly_the_dogs(self):
        import robot_studio
        self.assertEqual(set(control.FACELESS_MOVES), set(robot_studio.FACELESS_MOVES))

    def test_a_step_cannot_carry_a_face_but_a_turn_can(self):
        for step in control.FACELESS_MOVES:
            with self.assertRaises(Rejected, msg=step):
                validate_score(base.score(cues=[{'id': 'a', 'type': 'move', 'move': step, 'faceId': 86}]), motion=True)
            validate_score(base.score(cues=[{'id': 'a', 'type': 'move', 'move': step}]), motion=True)
        validate_score(base.score(cues=[{'id': 'a', 'type': 'move', 'move': 'turn_left_30', 'faceId': 86}]), motion=True)

    def test_moves_are_refused_unless_armed(self):
        with self.assertRaises(Rejected) as caught:
            validate_score(base.score(cues=[MOVE]))
        self.assertEqual(caught.exception.code, 'capability_unavailable')
        self.connect()
        receipt = self.controller.submit(self.show(MOVE))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'capability_unavailable'))
        self.assertEqual([c for c in self.session.calls if c[0] == 'move'], [])

    def test_unapproved_or_malformed_moves_are_rejected_even_when_armed(self):
        for cue in [{'id': 'a', 'type': 'move'}, {'id': 'a', 'type': 'move', 'move': 'backflip'},
                    {'id': 'a', 'type': 'move', 'move': 'actions/WAVE.json'}, {'id': 'a', 'type': 'move', 'move': 7},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'distance': 5},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'angle': 1},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'durationMs': 1000},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'faceId': 66},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'faceId': 256},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'faceId': -1},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'faceId': '86'},
                    {'id': 'a', 'type': 'move', 'move': 'step_forward', 'faceId': True}]:
            with self.subTest(cue=cue), self.assertRaises(Rejected):
                validate_score(base.score(cues=[cue]), motion=True)

    def test_every_listed_move_validates_with_and_without_a_face(self):
        for name in control.MOVES:
            validate_score(base.score(cues=[{'id': 'a', 'type': 'move', 'move': name}]), motion=True)
            if name not in control.FACELESS_MOVES:
                validate_score(base.score(cues=[{'id': 'a', 'type': 'move', 'move': name, 'faceId': 0}]), motion=True)

    def test_moves_count_toward_the_fifteen_minute_bound(self):
        cues = [{'id': f'm{i}', 'type': 'move', 'move': 'step_forward'} for i in range(16)]
        with self.assertRaises(Rejected):
            validate_score(base.score(cues=cues), motion=True)
        validate_score(base.score(cues=cues[:15]), motion=True)

    def test_an_armed_show_runs_moves_in_order_and_passes_the_face(self):
        self.arm()
        receipt = self.controller.submit(self.show(MOVE, TURN_WITH_FACE))
        self.assertEqual(receipt['state'], 'accepted')
        self.finish()
        self.assertEqual([c for c in self.session.calls if c[0] == 'move'], [('move', 'step_forward', None), ('move', 'turn_left_30', 86)])
        self.assertEqual(self.controller.status()['run']['state'], 'completed')

    def test_a_face_the_dog_does_not_list_is_refused_before_any_move(self):
        self.arm()
        receipt = self.controller.submit(self.show(MOVE, {**TURN_WITH_FACE, 'faceId': 3}))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'capability_unavailable'))
        self.assertEqual([c for c in self.session.calls if c[0] == 'move'], [])

    def test_a_refused_move_ends_the_dog_session_and_stops_the_show(self):
        self.arm()
        self.session.motion_results = [{'event': 'rejected', 'code': 'posture', 'reason': 'Stand it first.', 'sessionEnded': True}]
        self.controller.submit(self.show(MOVE, MOVE | {'id': 'v2'}))
        self.finish()
        status = self.controller.status()
        self.assertEqual(status['run']['state'], 'rejected')
        self.assertEqual(status['connection'], 'disconnected')
        self.assertEqual(len([c for c in self.session.calls if c[0] == 'move']), 1)

    def test_an_unknown_move_outcome_loses_the_connection_and_is_never_retried(self):
        self.arm()
        self.session.motion_results = [OutcomeUnknown('The dog stopped answering during this cue.')]
        self.controller.submit(self.show(MOVE, MOVE | {'id': 'v2'}))
        self.finish()
        self.assertEqual(self.controller.status()['run']['state'], 'unknown')
        self.assertEqual(self.controller.status()['connection'], 'lost')
        self.assertEqual(len([c for c in self.session.calls if c[0] == 'move']), 1)


class MoveWireTests(unittest.TestCase):
    READY = MotionSessionWireTests.READY
    open = MotionSessionWireTests.open

    def test_play_move_sends_one_bounded_frame_with_the_optional_face(self):
        session = self.open()
        self.assertEqual(session.play_move('turn_right_90', 86)['event'], 'completed')
        frame = self.stream.written[-1]
        self.assertEqual((frame['op'], frame['move'], frame['faceId']), ('move', 'turn_right_90', 86))
        self.assertEqual(frame['expiresAtMs'], 1000 + control.CUE_TTL_MS)
        session.play_move('step_back')
        self.assertNotIn('faceId', self.stream.written[-1])
        self.assertEqual(set(self.stream.written[-1]), {'op', 'commandId', 'sessionId', 'leaseGeneration', 'expiresAtMs', 'move'})

    def test_a_silent_dog_during_a_move_is_unknown(self):
        session = self.open(reply=lambda frame: [])
        session.stream.readLine = lambda _timeout: ''
        original = control.MOTION_REPLY_TIMEOUT
        control.MOTION_REPLY_TIMEOUT = 0.01
        try:
            with self.assertRaises(OutcomeUnknown):
                session.play_move('step_forward')
        finally:
            control.MOTION_REPLY_TIMEOUT = original


def frame(seq, vx=0.0, vy=0.0, wz=0.0):
    return {'action': 'frame', 'seq': seq, 'vx': vx, 'vy': vy, 'wz': wz}


class DriveTests(MotionCase):
    def driving(self):
        self.arm()
        self.controller.drive({'action': 'start'})

    def sent(self, kind):
        return [call for call in self.session.calls if call[0] == kind]

    def test_the_caps_are_exactly_the_dogs(self):
        import robot_studio
        self.assertEqual(control.DRIVE_MAX, robot_studio.DRIVE_MAX)

    def test_driving_is_offered_only_to_an_armed_connection_and_lapses_with_it(self):
        self.assertFalse(self.connect()['capabilities']['drive']['available'])
        self.controller.disconnect()
        armed = self.arm()['capabilities']
        self.assertEqual((armed['drive']['available'], armed['driveLimits']), (True, control.DRIVE_MAX))
        self.now += control.MOTION_SESSION_MS
        self.assertFalse(self.controller.status()['capabilities']['drive']['available'])
        with self.assertRaises(Rejected):
            self.controller.drive({'action': 'start'})

    def test_start_needs_motion_a_connection_and_an_idle_controller(self):
        with self.assertRaises(Rejected) as caught:
            self.controller.drive({'action': 'start'})
        self.assertEqual(caught.exception.code, 'not_connected')
        self.connect()
        with self.assertRaises(Rejected) as caught:
            self.controller.drive({'action': 'start'})
        self.assertEqual(caught.exception.code, 'capability_unavailable')
        self.assertEqual(self.sent('drive_start'), [])

    def test_a_show_in_progress_blocks_a_drive_and_a_drive_blocks_a_show(self):
        self.arm()
        self.gate = threading.Event()
        entered = threading.Event()
        def wait_for_release(cancel, seconds):
            entered.set()
            self.gate.wait(10)
            return cancel.is_set()
        # MotionCase's default waiter completes immediately. Explicitly hold this
        # show so the exclusion assertion doesn't depend on thread scheduling.
        self.controller.waiter = wait_for_release
        self.controller.submit(self.show({**FACE, 'durationMs': 5000}))
        try:
            self.assertTrue(entered.wait(2), 'Show did not reach its waiting cue')
            with self.assertRaises(Rejected) as caught:
                self.controller.drive({'action': 'start'})
            self.assertEqual(caught.exception.code, 'busy')
        finally:
            self.gate.set()
            self.finish()
        self.controller.drive({'action': 'start'})
        receipt = self.controller.submit(self.show(FACE, commandId='c' * 32))
        self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'busy'))
        self.assertTrue(self.controller.status()['driving'])

    def test_a_second_start_while_driving_is_refused(self):
        self.driving()
        with self.assertRaises(Rejected) as caught:
            self.controller.drive({'action': 'start'})
        self.assertEqual(caught.exception.code, 'busy')
        self.assertEqual(len(self.sent('drive_start')), 1)

    def test_the_dogs_refusal_reaches_the_user_and_leaves_nothing_armed(self):
        self.arm()
        self.session.drive_start_result = {'event': 'rejected', 'code': 'posture', 'reason': 'Stand it first.'}
        with self.assertRaises(Rejected) as caught:
            self.controller.drive({'action': 'start'})
        self.assertEqual((caught.exception.code, caught.exception.reason), ('posture', 'Stand it first.'))
        self.assertFalse(self.controller.status()['driving'])
        self.assertEqual(self.controller.drive(frame(0, 0.1))['state'], 'ignored')

    def test_frames_reach_the_dog_in_order_and_stale_ones_are_dropped(self):
        self.driving()
        self.assertEqual(self.controller.drive(frame(1, 0.1))['state'], 'sent')
        self.assertEqual(self.controller.drive(frame(3, 0.1, wz=0.2))['state'], 'sent')
        self.assertEqual(self.controller.drive(frame(2, 0.15))['state'], 'ignored')   # arrived late
        self.assertEqual(self.controller.drive(frame(3, 0.15))['state'], 'ignored')   # repeated
        self.assertEqual([call[1] for call in self.sent('drive_frame')], [1, 3])

    def test_out_of_range_or_malformed_frames_are_rejected_before_the_dog_sees_them(self):
        self.driving()
        for bad in [frame(1, vx=0.151), frame(1, vy=-0.101), frame(1, wz=0.41), frame(1, vx=float('nan')), frame(1, wz=float('inf')),
                    frame(1, vx=True), frame(1, vx='0.1'), frame(1, vx=None), frame(True), frame(-1), frame('1'), {'action': 'frame', 'seq': 1, 'vx': 0.1}]:
            with self.subTest(bad=bad), self.assertRaises(Rejected) as caught:
                self.controller.drive(bad)
            self.assertEqual(caught.exception.code, 'invalid_drive')
        self.assertEqual(self.sent('drive_frame'), [])
        self.assertTrue(self.controller.status()['driving'])

    def test_frames_with_no_drive_are_ignored_not_sent(self):
        self.arm()
        self.assertEqual(self.controller.drive(frame(1, 0.1))['state'], 'ignored')
        self.assertEqual(self.sent('drive_frame'), [])

    def test_stop_comes_after_every_earlier_frame_and_later_frames_are_dropped(self):
        self.driving()
        self.controller.drive(frame(1, 0.1))
        self.assertEqual(self.controller.drive({'action': 'stop'})['state'], 'stopped')
        self.assertEqual(self.controller.drive(frame(2, 0.1))['state'], 'ignored')
        kinds = [call[0] for call in self.session.calls if call[0].startswith('drive')]
        self.assertEqual(kinds, ['drive_start', 'drive_frame', 'drive_stop'])
        self.assertFalse(self.controller.status()['driving'])

    def test_stop_is_idempotent_when_nothing_is_running(self):
        self.arm()
        self.assertEqual(self.controller.drive({'action': 'stop'}), {'state': 'stopped', 'reason': 'not-driving'})
        self.assertEqual(self.sent('drive_stop'), [])

    def test_a_dog_that_ended_the_drive_itself_is_a_clean_stop_when_it_zeroed(self):
        self.driving()
        self.session.drive_stop_result = {'event': 'drive_stopped', 'reason': 'already-ended', 'zeroed': True}
        self.assertEqual(self.controller.drive({'action': 'stop'})['state'], 'stopped')
        self.assertEqual(self.controller.status()['connection'], 'connected')

    def test_an_unconfirmed_zero_or_an_abnormal_end_drops_the_connection(self):
        for result in [{'event': 'drive_stopped', 'reason': 'stopped', 'zeroed': False},
                       {'event': 'drive_ended', 'reason': 'violation', 'zeroed': True}, OutcomeUnknown('silent')]:
            with self.subTest(result=result):
                self.setUp()
                self.driving()
                self.session.drive_stop_result = result
                with self.assertRaises(Rejected) as caught:
                    self.controller.drive({'action': 'stop'})
                self.assertEqual(caught.exception.code, 'unknown')
                status = self.controller.status()
                self.assertEqual(status['connection'], 'lost')
                self.assertTrue(self.session.closed)   # closing the stream is EOF, which makes the dog publish zeros
                self.assertFalse(status['driving'])

    def test_a_write_failure_mid_drive_closes_the_connection(self):
        self.driving()
        self.session.frame_error = OutcomeUnknown('gone')
        with self.assertRaises(Rejected) as caught:
            self.controller.drive(frame(1, 0.1))
        self.assertEqual(caught.exception.code, 'unknown')
        self.assertEqual(self.controller.status()['connection'], 'lost')
        self.assertTrue(self.session.closed)

    def test_an_unknown_start_closes_the_connection(self):
        self.arm()
        self.session.drive_start_result = OutcomeUnknown('silent')
        with self.assertRaises(Rejected) as caught:
            self.controller.drive({'action': 'start'})
        self.assertEqual(caught.exception.code, 'unknown')
        self.assertTrue(self.session.closed)

    def test_disconnecting_or_reconnecting_ends_the_drive_by_closing_the_stream(self):
        self.driving()
        self.controller.disconnect()
        self.assertTrue(self.session.closed)
        self.assertFalse(self.controller.status()['driving'])

    def test_an_idle_drive_is_not_closed_as_an_idle_session(self):
        self.driving()
        self.controller.mono = lambda: 10 ** 9
        self.assertEqual(self.controller.status()['connection'], 'connected')

    def test_unknown_drive_actions_are_refused(self):
        self.arm()
        for payload in [{}, {'action': 'go'}, {'action': 7}, None, []]:
            with self.subTest(payload=payload), self.assertRaises(Rejected):
                self.controller.drive(payload)

    def test_the_http_route_returns_a_400_with_the_reason(self):
        self.arm()
        status, body = route(self.controller, 'drive', {'action': 'frame', 'seq': 0, 'vx': 9, 'vy': 0, 'wz': 0})
        self.assertEqual((status, body['code']), (400, 'invalid_drive'))
        self.assertEqual(route(self.controller, 'drive', {'action': 'stop'})[0], 200)


def drive_reply(frame):
    if frame.get('op') == 'drive_start':
        return [{'event': 'drive_started', 'commandId': frame['commandId']}]
    if frame.get('op') == 'drive_stop':
        return [{'event': 'drive_stopped', 'commandId': frame['commandId'], 'reason': 'stopped', 'zeroed': True}]
    return []


class DriveWireTests(unittest.TestCase):
    READY = MotionSessionWireTests.READY
    open = MotionSessionWireTests.open

    def test_the_frames_are_exactly_the_documented_shape(self):
        session = self.open(reply=drive_reply)
        self.assertEqual(session.drive_start()['event'], 'drive_started')
        self.assertEqual(self.stream.written[-1]['op'], 'drive_start')
        session.drive_frame(4, 0.1, 0.0, -0.2)
        self.assertEqual(self.stream.written[-1], {'op': 'drive', 'seq': 4, 'vx': 0.1, 'vy': 0.0, 'wz': -0.2})
        count = len(self.stream.written)
        self.assertEqual(session.drive_stop()['event'], 'drive_stopped')
        self.assertEqual((len(self.stream.written), self.stream.written[-1]['op']), (count + 1, 'drive_stop'))

    def test_a_frame_never_waits_for_a_reply(self):
        session = self.open(reply=lambda frame: [])
        session.stream.readLine = lambda _timeout: (_ for _ in ()).throw(AssertionError('a frame must not read'))
        session.drive_frame(1, 0.0, 0.0, 0.0)

    def test_a_dead_stream_is_reported_as_unknown(self):
        session = self.open()
        session.stream.writeLine = lambda line: (_ for _ in ()).throw(BrokenPipeError())
        with self.assertRaises(OutcomeUnknown):
            session.drive_frame(1, 0.0, 0.0, 0.0)
