"""VBOT app controller and face helper, using fake streams only. No robot I/O."""
import ast
import http.client
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import vbot_app_control as control  # noqa: E402
from vbot_app_control import AppController, FaceSession, OutcomeUnknown, Rejected, read_identity, validate_score  # noqa: E402
from vbot_app_server import make_server  # noqa: E402
from vbot_performance import performance_plan  # noqa: E402

spec = importlib.util.spec_from_file_location('robot_face', ROOT / 'vbot-demo' / 'robot_face.py')
face = importlib.util.module_from_spec(spec)
sys.modules['robot_face'] = face
spec.loader.exec_module(face)

FIXTURES = json.loads((ROOT / 'tests' / 'fixtures' / 'vbot_app_scores.json').read_text())
DEVICE = 'ssh-host-key:SHA256:test'


def score(**over):
    return {'schemaVersion': 1, 'id': 'show', 'title': 'Show', 'notes': '', 'origin': 'custom', 'revision': 1, 'repeat': 1,
            'createdAt': 1, 'updatedAt': 1,
            'cues': [{'id': 'a', 'type': 'face', 'assetId': 86, 'durationMs': 4500},
                     {'id': 'b', 'type': 'wait', 'durationMs': 100},
                     {'id': 'c', 'type': 'face', 'assetId': 70, 'durationMs': 500}], **over}


class FakeSession:
    def __init__(self):
        self.supported = ['086_THINK', '070_EXCITED']
        self.calls, self.closed = [], False
        self.play_results, self.release_result = [], {'event': 'released'}

    def play(self, asset, duration):
        self.calls.append(('play', asset, duration))
        result = self.play_results.pop(0) if self.play_results else {'event': 'started'}
        if isinstance(result, Exception):
            raise result
        return result

    def release(self):
        self.calls.append(('release',))
        if isinstance(self.release_result, Exception):
            raise self.release_result
        return self.release_result

    def close(self):
        self.closed = True


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.journal = Path(self.dir.name) / 'journal' / 'commands.jsonl'
        self.session = FakeSession()
        self.now = 10_000_000
        self.gate = None
        self.controller = self.make()

    def make(self):
        def waiter(cancel, seconds):
            if self.gate is not None:
                self.gate.wait(2)
            return cancel.is_set()
        return AppController(journal_path=self.journal, session_factory=lambda *args: self.session,
                             identity_reader=lambda target: {'anchor': 'alias', 'deviceId': DEVICE},
                             wall_ms=lambda: self.now, waiter=waiter)

    def connect(self, controller=None):
        controller = controller or self.controller
        return controller.connect({'target': 'vbot@192.168.1.20'})

    def envelope(self, status=None, **over):
        status = status or self.controller.status()
        return {'v': 1, 'commandId': 'a' * 32, 'deviceId': status['device']['id'] if status['device'] else DEVICE,
                'sessionId': status['sessionId'], 'leaseGeneration': status['leaseGeneration'], 'issuedAt': self.now,
                'expiresAt': self.now + 30000, 'kind': 'run-score', 'score': score(), **over}

    def finish(self, controller=None):
        controller = controller or self.controller
        if controller.thread:
            controller.thread.join(5)
            self.assertFalse(controller.thread.is_alive())


class AdmissionTests(ControllerCase):
    def test_a_show_runs_in_order_then_hands_the_screen_back(self):
        self.connect()
        receipt = self.controller.submit(self.envelope())
        self.assertEqual(receipt['state'], 'accepted')
        self.finish()
        self.assertEqual(self.session.calls, [('play', 86, 4500), ('play', 70, 500), ('release',)])
        run = self.controller.status()['run']
        self.assertEqual((run['state'], run['completedCues'], run['cleanup']), ('completed', 3, 'released'))

    def test_motion_cues_are_rejected_and_never_reach_the_session(self):
        self.connect()
        for kind, preset in (('body', 'actions/ROCKYOU.json'), ('head', 'atom/look_left.json')):
            with self.subTest(kind=kind):
                command_id = (kind[0] * 32).replace('h', 'd').replace('b', 'c')
                receipt = self.controller.submit(self.envelope(commandId=command_id, score=score(cues=[{'id': 'a', 'type': kind, 'preset': preset}])))
                self.assertEqual(receipt['code'], 'capability_unavailable')
        self.assertEqual(self.session.calls, [])

    def test_a_mixed_show_runs_nothing(self):
        self.connect()
        cues = [{'id': 'a', 'type': 'face', 'assetId': 86, 'durationMs': 4500}, {'id': 'b', 'type': 'body', 'preset': 'actions/WAVE.json'}]
        self.assertEqual(self.controller.submit(self.envelope(score=score(cues=cues)))['state'], 'rejected')
        self.assertEqual(self.session.calls, [])

    def test_rehearsed_motion_is_not_a_capability_of_this_adapter(self):
        capabilities = self.connect()['capabilities']
        self.assertTrue(capabilities['face']['available'])
        for kind in ('head', 'body', 'speech', 'navigation'):
            self.assertFalse(capabilities[kind]['available'])
            self.assertTrue(capabilities[kind]['reason'])
        self.assertEqual(capabilities['rehearsedPresets'], [])

    def test_expired_command(self):
        self.connect()
        self.assertEqual(self.controller.submit(self.envelope(expiresAt=self.now))['code'], 'expired')
        self.assertEqual(self.controller.submit(self.envelope(commandId='b' * 32, expiresAt=self.now + control.MAX_TTL_MS + 1))['code'], 'expired')
        self.assertEqual(self.session.calls, [])

    def test_stale_lease_session_and_device(self):
        self.connect()
        stale = self.envelope()
        self.now += 1
        self.connect()
        self.assertEqual(self.controller.submit(stale)['code'], 'stale_lease')
        self.assertEqual(self.controller.submit(self.envelope(commandId='b' * 32, deviceId='other'))['code'], 'wrong_device')
        self.assertEqual(self.session.calls, [])

    def test_not_connected(self):
        status = self.controller.status()
        receipt = self.controller.submit(self.envelope(status, sessionId='x'))
        self.assertEqual(receipt['code'], 'not_connected')

    def test_face_this_dog_does_not_list(self):
        self.connect()
        cues = [{'id': 'a', 'type': 'face', 'assetId': 4, 'durationMs': 4500}]
        self.assertEqual(self.controller.submit(self.envelope(score=score(cues=cues)))['code'], 'capability_unavailable')

    def test_busy_controller(self):
        self.gate = threading.Event()
        self.connect()
        self.controller.submit(self.envelope())
        self.assertEqual(self.controller.submit(self.envelope(commandId='b' * 32))['code'], 'busy')
        self.gate.set()
        self.finish()

    def test_invalid_command_identity_raises(self):
        with self.assertRaises(Rejected):
            self.controller.submit({'commandId': 'not-hex'})
        with self.assertRaises(Rejected):
            self.controller.submit([])  # type: ignore[arg-type]


class IdentityTests(ControllerCase):
    def test_duplicate_returns_recorded_state_without_rerunning(self):
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        self.finish()
        calls = list(self.session.calls)
        again = self.controller.submit(envelope)
        self.assertEqual((again['duplicate'], again['state']), (True, 'completed'))
        self.assertEqual(self.session.calls, calls)

    def test_reused_identity_with_different_content_conflicts(self):
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        self.finish()
        conflict = self.controller.submit({**envelope, 'score': score(title='Other')})
        self.assertEqual(conflict['code'], 'identity_conflict')

    def test_deduplication_survives_restart(self):
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        self.finish()
        restarted = self.make()
        self.connect(restarted)
        again = restarted.submit(envelope)
        self.assertTrue(again['duplicate'])
        self.assertEqual(again['state'], 'completed')

    def test_restart_marks_in_flight_commands_unknown_and_does_not_resume(self):
        self.gate = threading.Event()
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        calls = list(self.session.calls)
        restarted = self.make()
        self.assertIsNone(restarted.status()['run'])
        self.assertEqual(restarted.commands[envelope['commandId']]['state'], 'unknown')
        self.assertIn('not resumed', restarted.commands[envelope['commandId']]['reason'])
        self.connect(restarted)
        again = restarted.submit(envelope)
        self.assertEqual((again['state'], again['duplicate']), ('unknown', True))
        self.gate.set()
        self.finish()
        self.assertLessEqual(len(calls), len(self.session.calls))

    def test_journal_records_identity_without_targets_or_keys(self):
        self.connect()
        self.controller.submit(self.envelope())
        self.finish()
        text = self.journal.read_text()
        self.assertNotIn('192.168', text)
        self.assertNotIn('SHA256', text)
        self.assertEqual([json.loads(line)['state'] for line in text.splitlines()], ['received', 'accepted', 'running', 'completed'])

    def test_torn_journal_line_is_ignored(self):
        self.connect()
        self.controller.submit(self.envelope())
        self.finish()
        with self.journal.open('a') as journal:
            journal.write('{"commandId": "bbb')
        restarted = self.make()
        self.assertEqual(restarted.commands['a' * 32]['state'], 'completed')

    def test_leases_increase_across_restart_even_if_the_clock_goes_back(self):
        self.connect()
        lease = self.controller.status()['leaseGeneration']
        self.controller.submit(self.envelope())
        self.finish()
        self.now -= 5000
        restarted = self.make()
        self.assertGreater(self.connect(restarted)['leaseGeneration'], lease)


class OutcomeTests(ControllerCase):
    def test_unknown_outcome_stops_future_cues_and_is_not_retried(self):
        self.connect()
        self.session.play_results = [OutcomeUnknown('No answer.')]
        self.controller.submit(self.envelope())
        self.finish()
        status = self.controller.status()
        self.assertEqual(status['run']['state'], 'unknown')
        self.assertEqual(self.session.calls, [('play', 86, 4500)])
        self.assertEqual(status['connection'], 'lost')
        self.assertTrue(self.session.closed)
        self.assertFalse(status['capabilities']['face']['available'])

    def test_helper_reported_unknown_is_also_terminal(self):
        self.connect()
        self.session.play_results = [{'event': 'unknown', 'reason': 'No display answer.'}]
        self.controller.submit(self.envelope())
        self.finish()
        self.assertEqual(self.controller.status()['run']['state'], 'unknown')
        self.assertEqual(len(self.session.calls), 1)

    def test_helper_duplicate_of_unresolved_is_not_treated_as_success(self):
        self.connect()
        self.session.play_results = [{'event': 'duplicate', 'outcome': 'unknown'}]
        self.controller.submit(self.envelope())
        self.finish()
        self.assertEqual(self.controller.status()['run']['state'], 'unknown')

    def test_dog_refusal_stops_the_show_and_restores_the_screen(self):
        self.connect()
        self.session.play_results = [{'event': 'started'}, {'event': 'rejected', 'code': 'device_warning', 'reason': 'Warning showing.'}]
        self.controller.submit(self.envelope())
        self.finish()
        run = self.controller.status()['run']
        self.assertEqual((run['state'], run['reason'], run['cleanup']), ('rejected', 'Warning showing.', 'released'))
        self.assertEqual(self.controller.status()['connection'], 'connected')

    def test_cancel_stops_future_cues_and_restores_the_screen(self):
        self.gate = threading.Event()
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        for _ in range(100):
            if self.session.calls:
                break
            time.sleep(.01)
        self.controller.cancel_future({'commandId': envelope['commandId']})
        self.gate.set()
        self.finish()
        run = self.controller.status()['run']
        self.assertEqual((run['state'], run['cleanup']), ('cancelled', 'released'))
        self.assertEqual(self.session.calls, [('play', 86, 4500), ('release',)])

    def test_cancel_with_the_wrong_identity_does_nothing(self):
        self.gate = threading.Event()
        self.connect()
        self.controller.submit(self.envelope())
        self.controller.cancel_future({'commandId': 'f' * 32})
        self.assertFalse(self.controller.cancel.is_set())
        self.gate.set()
        self.finish()

    def test_failed_release_is_reported(self):
        self.connect()
        self.session.release_result = OutcomeUnknown('No answer.')
        self.controller.submit(self.envelope())
        self.finish()
        status = self.controller.status()
        self.assertEqual((status['run']['state'], status['run']['cleanup']), ('completed', 'failed'))
        self.assertTrue(any('release' in event['message'] for event in status['events']))

    def test_wait_only_show_needs_no_session_call(self):
        self.connect()
        self.controller.submit(self.envelope(score=score(cues=[{'id': 'a', 'type': 'wait', 'durationMs': 100}])))
        self.finish()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.controller.status()['run']['cleanup'], 'not-needed')

    def test_running_snapshot_ignores_later_changes_to_the_payload(self):
        self.gate = threading.Event()
        self.connect()
        envelope = self.envelope()
        self.controller.submit(envelope)
        envelope['score']['title'] = 'Changed'
        envelope['score']['cues'][0]['assetId'] = 1
        self.assertEqual(self.controller.status()['run']['score']['title'], 'Show')
        self.gate.set()
        self.finish()
        self.assertEqual(self.session.calls[0], ('play', 86, 4500))


class ConnectionTests(ControllerCase):
    def test_reconnect_after_loss_replays_nothing(self):
        self.connect()
        self.session.play_results = [OutcomeUnknown('Lost.')]
        envelope = self.envelope()
        self.controller.submit(envelope)
        self.finish()
        first = self.session
        self.session = FakeSession()
        status = self.connect()
        self.assertEqual(status['connection'], 'connected')
        self.assertEqual(status['run']['commandId'], envelope['commandId'])
        self.assertEqual(status['run']['state'], 'unknown')
        self.assertEqual(self.session.calls, [])
        self.assertEqual(len(first.calls), 1)

    def test_refused_session_explains_itself_and_stays_unconnected(self):
        def refuse(*_args):
            raise Rejected('busy', 'Another controller owns the dog.')
        self.controller.session_factory = refuse
        status = self.connect()
        self.assertEqual((status['connection'], status['detail']), ('unavailable', 'Another controller owns the dog.'))
        self.assertFalse(status['capabilities']['face']['available'])

    def test_unexpected_session_failure_gives_a_generic_reason(self):
        def boom(*_args):
            raise OSError('/secret/path/key')
        self.controller.session_factory = boom
        status = self.connect()
        self.assertEqual(status['connection'], 'unavailable')
        self.assertNotIn('secret', status['detail'])

    def test_bad_target_is_refused_before_any_session(self):
        for target in ('-oProxyCommand=evil', 'vbot@8.8.8.8', 'a b', ''):
            with self.subTest(target=target):
                status = self.controller.connect({'target': target})
                self.assertEqual(status['connection'], 'unavailable')
        self.assertEqual(self.session.calls, [])

    def test_connect_is_refused_during_a_show(self):
        self.gate = threading.Event()
        self.connect()
        self.controller.submit(self.envelope())
        session_id = self.controller.session_id
        self.connect()
        self.assertEqual(self.controller.session_id, session_id)
        self.gate.set()
        self.finish()

    def test_only_one_connect_runs_at_a_time(self):
        opening, release, opened = threading.Event(), threading.Event(), []
        def slow(*_args):
            opened.append(1)
            opening.set()
            release.wait(5)
            return self.session
        self.controller.session_factory = slow
        worker = threading.Thread(target=self.connect)
        worker.start()
        self.assertTrue(opening.wait(5))
        self.assertEqual(self.connect()['connection'], 'connecting')
        release.set()
        worker.join(5)
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.controller.status()['connection'], 'connected')

    def test_disconnect_during_connect_wins(self):
        opening, release = threading.Event(), threading.Event()
        def slow(*_args):
            opening.set()
            release.wait(5)
            return self.session
        self.controller.session_factory = slow
        worker = threading.Thread(target=self.connect)
        worker.start()
        self.assertTrue(opening.wait(5))
        self.controller.disconnect()
        release.set()
        worker.join(5)
        self.assertEqual(self.controller.status()['connection'], 'disconnected')
        self.assertTrue(self.session.closed)

    def test_idle_session_closes_so_other_controllers_can_use_the_dog(self):
        clock = [0.0]
        controller = AppController(journal_path=self.journal, session_factory=lambda *args: self.session,
                                   identity_reader=lambda target: {'anchor': None, 'deviceId': DEVICE},
                                   wall_ms=lambda: self.now, mono=lambda: clock[0])
        self.connect(controller)
        clock[0] = control.IDLE_CLOSE_SECONDS + 1
        status = controller.status()
        self.assertEqual(status['connection'], 'disconnected')
        self.assertTrue(self.session.closed)

    def test_disconnect_cancels_a_running_show(self):
        self.gate = threading.Event()
        self.connect()
        self.controller.submit(self.envelope())
        for _ in range(100):
            if self.session.calls:
                break
            time.sleep(.01)
        self.gate.set()
        status = self.controller.disconnect()
        self.assertEqual(status['connection'], 'disconnected')
        self.assertEqual(status['run']['state'], 'cancelled')


class ScoreValidationTests(unittest.TestCase):
    def test_shared_accepted_fixtures(self):
        for item in FIXTURES['accepted']:
            validate_score(item)

    def test_shared_rejected_fixtures(self):
        for item in FIXTURES['rejected']:
            with self.subTest(item['why']), self.assertRaises(Rejected):
                validate_score(item['score'])

    def test_bundled_face_show_is_accepted(self):
        shows = json.loads((ROOT / 'vbot-app/src/domain/cannedShows.json').read_text())
        validate_score(next(show for show in shows if show['id'] == 'canned-mood-swing'))

    def test_bundled_motion_show_is_refused(self):
        shows = json.loads((ROOT / 'vbot-app/src/domain/cannedShows.json').read_text())
        with self.assertRaises(Rejected) as caught:
            validate_score(next(show for show in shows if show['id'] == 'canned-midnight-mischief'))
        self.assertEqual(caught.exception.code, 'capability_unavailable')

    def test_midnight_mischief_stays_in_step_with_the_authored_score(self):
        shows = json.loads((ROOT / 'vbot-app/src/domain/cannedShows.json').read_text())
        show = next(show for show in shows if show['id'] == 'canned-midnight-mischief')
        plan = performance_plan({'dances': 1, 'pace': 'flow'}, lambda preset: {'durationMs': 1000})
        self.assertEqual([cue['preset'] for cue in show['cues'] if cue['type'] != 'wait'], [cue['preset'] for cue in plan['cues']])
        self.assertEqual([cue['caption'] for cue in show['cues'] if cue['type'] != 'wait'], [cue['caption'] for cue in plan['cues']])


class IdentityReaderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.profile = Path(self.dir.name) / 'profile.json'

    def test_saved_identity_must_match_known_hosts(self):
        self.profile.write_text(json.dumps({'target': 'vbot@172.20.10.5', 'hostKeyFingerprint': 'SHA256:abc'}))
        identity = read_identity('vbot@192.168.1.5', profile_path=self.profile, fingerprints=lambda target: {'SHA256:abc'})
        self.assertEqual(identity, {'anchor': '172.20.10.5', 'deviceId': 'ssh-host-key:SHA256:abc'})
        with self.assertRaises(Rejected):
            read_identity('vbot@192.168.1.5', profile_path=self.profile, fingerprints=lambda target: {'SHA256:changed'})

    def test_unknown_host_is_refused_rather_than_trusted(self):
        with self.assertRaises(Rejected):
            read_identity('vbot@192.168.1.5', profile_path=self.profile, fingerprints=lambda target: set())

    def test_known_host_without_a_profile_uses_its_key_as_identity(self):
        identity = read_identity('vbot@192.168.1.5', profile_path=self.profile, fingerprints=lambda target: {'SHA256:z', 'SHA256:a'})
        self.assertEqual(identity, {'anchor': None, 'deviceId': 'ssh-host-key:SHA256:a'})


class FakeStream:
    def __init__(self, reply):
        self.reply, self.written, self.lines, self.closed = reply, [], [], False

    def writeLine(self, line):
        self.written.append(json.loads(line))
        self.lines.extend(self.reply(self.written[-1]))

    def readLine(self, _timeout):
        if self.lines:
            return json.dumps(self.lines.pop(0)) if not isinstance(self.lines[0], str) else self.lines.pop(0)
        return ''

    def close(self):
        self.closed = True


class FaceSessionTests(unittest.TestCase):
    def open(self, ready=None, reply=lambda frame: [{'event': 'started', 'commandId': frame['commandId']}]):
        self.commands = []
        def factory(command):
            self.commands.append(command)
            stream = FakeStream(reply)
            stream.lines.append('SDK diagnostic noise')
            stream.lines.append(ready or {'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 1, 'faceOnly': True, 'supportedFaces': ['086_THINK']})
            self.stream = stream
            return stream
        return FaceSession('vbot@192.168.1.5', 's' * 32, 7, 'alias', stream_factory=factory, wall_ms=lambda: 1000)

    def test_command_is_strict_ssh_to_the_face_helper_only(self):
        session = self.open()
        command = self.commands[0]
        self.assertIn('StrictHostKeyChecking=yes', command)
        self.assertIn('HostKeyAlias=alias', command)
        self.assertIn('robot_face.py', command[-1])
        self.assertNotIn('robot_action', command[-1])
        self.assertNotIn('--confirm-motion', command[-1])
        self.assertEqual(session.supported, ['086_THINK'])

    def test_refusal_surfaces_the_reason_and_closes(self):
        with self.assertRaises(Rejected) as caught:
            self.open(ready={'event': 'session_refused', 'requestId': 's' * 32, 'code': 'busy', 'reason': 'Owned.'})
        self.assertEqual(caught.exception.code, 'busy')
        self.assertTrue(self.stream.closed)

    def test_helper_with_another_protocol_is_refused(self):
        with self.assertRaises(Rejected):
            self.open(ready={'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 2, 'faceOnly': True})
        with self.assertRaises(Rejected):
            self.open(ready={'event': 'session_ready', 'requestId': 's' * 32, 'protocol': 1})

    def test_each_cue_gets_a_fresh_identity_and_bounded_expiry(self):
        session = self.open()
        session.play(86, 4500)
        session.play(86, 4500)
        first, second = self.stream.written
        self.assertNotEqual(first['commandId'], second['commandId'])
        self.assertEqual(first['expiresAtMs'], 1000 + control.CUE_TTL_MS)
        self.assertEqual((first['leaseGeneration'], first['sessionId']), (7, 's' * 32))

    def test_a_broken_stream_is_an_unknown_outcome(self):
        session = self.open()
        def broken(_line):
            raise BrokenPipeError()
        self.stream.writeLine = broken
        with self.assertRaises(OutcomeUnknown):
            session.play(86, 4500)

    def test_silence_is_an_unknown_outcome(self):
        session = self.open(reply=lambda frame: [])
        with patch.object(control, 'ACK_TIMEOUT', .05), self.assertRaises(OutcomeUnknown):
            session.play(86, 4500)


class FakeDisplay:
    def __init__(self):
        self.calls, self.result = [], (0, 0, 'ok')

    def play(self, asset, duration, request_id):
        self.calls.append(('play', asset, duration))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def release(self, request_id):
        self.calls.append(('release',))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Healthy:
    problem_text = None

    def problem(self):
        return self.problem_text


class FaceHelperTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name)
        self.display, self.health, self.now = FakeDisplay(), Healthy(), 1000
        self.core = self.make_core()

    def make_core(self, lease=5):
        return face.FaceCore(ledger=face.CommandLedger(self.path), display=self.display, health=self.health,
                             session_id='s' * 32, lease=lease, supported={86, 70}, now_ms=lambda: self.now)

    def frame(self, **over):
        return {'op': 'face', 'commandId': 'a' * 32, 'sessionId': 's' * 32, 'leaseGeneration': 5,
                'expiresAtMs': self.now + 30000, 'assetId': 86, 'durationMs': 4500, **over}

    def test_face_plays_and_reports_startup_only(self):
        self.assertEqual(self.core.handle(self.frame()), {'event': 'started', 'commandId': 'a' * 32})
        self.assertEqual(self.display.calls, [('play', 86, 4500)])

    def test_repeat_identity_never_reaches_the_display_even_after_restart(self):
        self.core.handle(self.frame())
        restarted = self.make_core()
        result = restarted.handle(self.frame())
        self.assertEqual((result['event'], result['outcome']), ('duplicate', 'started'))
        self.assertEqual(len(self.display.calls), 1)

    def test_record_exists_before_the_display_is_called(self):
        def play(_asset, _duration, _id):
            record = json.loads((self.path / 'requests' / ('face-' + 'a' * 32 + '.json')).read_text())
            self.assertEqual(record['outcome'], 'reserved')
            return 0, 0, 'ok'
        self.display.play = play
        self.assertEqual(self.core.handle(self.frame())['event'], 'started')

    def test_crash_during_the_call_reports_unknown_on_replay(self):
        ledger = face.CommandLedger(self.path)
        ledger.reserve('a' * 32, {'commandId': 'a' * 32})
        result = self.core.handle(self.frame())
        self.assertEqual((result['event'], result['outcome']), ('duplicate', 'unknown'))
        self.assertEqual(self.display.calls, [])

    def test_refusals_at_the_dog(self):
        cases = [(dict(leaseGeneration=4), 'stale_lease'), (dict(sessionId='t' * 32), 'stale_lease'),
                 (dict(expiresAtMs=self.now), 'expired'), (dict(expiresAtMs=self.now + 999999), 'expired'),
                 (dict(assetId=4), 'unsupported_face'), (dict(assetId=66), 'unsupported_face'), (dict(assetId=True), 'unsupported_face'),
                 (dict(durationMs=499), 'invalid_duration'), (dict(durationMs=30001), 'invalid_duration')]
        for index, (over, code) in enumerate(cases):
            with self.subTest(over=over):
                command_id = format(index, '032x')
                self.assertEqual(self.core.handle(self.frame(commandId=command_id, **over))['code'], code)
        self.assertEqual(self.display.calls, [])

    def test_only_face_operations_are_understood(self):
        for frame in (self.frame(op='cue', preset='actions/ROCKYOU.json'), self.frame(commandId='nope'), self.frame(op=None)):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                self.core.handle(frame)
        self.assertEqual(self.display.calls, [])

    def test_a_dog_warning_keeps_the_screen(self):
        self.health.problem_text = 'A warning is showing.'
        result = self.core.handle(self.frame())
        self.assertEqual((result['event'], result['code']), ('rejected', 'device_warning'))
        self.assertEqual(self.display.calls, [])

    def test_display_refusal_is_not_treated_as_success(self):
        self.display.result = (1, 0, 'bad')
        self.assertEqual(self.core.handle(self.frame())['code'], 'display_refused')
        self.display.result = (0, 7, 'bad')
        self.assertEqual(self.core.handle(self.frame(commandId='b' * 32))['code'], 'display_refused')

    def test_uncertain_call_reports_unknown_and_cleanup_still_releases(self):
        self.display.result = TimeoutError()
        result = self.core.handle(self.frame())
        self.assertEqual(result['event'], 'unknown')
        self.display.result = (0, 0, 'ok')
        self.assertEqual(self.core.cleanup(), 'released')
        self.assertEqual(self.display.calls[-1], ('release',))

    def test_cleanup_only_when_something_was_shown_and_reports_failure(self):
        self.assertIsNone(self.core.cleanup())
        self.assertEqual(self.display.calls, [])
        self.core.handle(self.frame())
        self.display.result = TimeoutError()
        self.assertEqual(self.core.cleanup(), 'failed')

    def test_explicit_release_clears_cleanup(self):
        self.core.handle(self.frame())
        result = self.core.handle(self.frame(op='face_release', commandId='b' * 32, assetId=None, durationMs=None))
        self.assertEqual(result['event'], 'released')
        self.assertIsNone(self.core.cleanup())

    def test_restricted_assets_are_dropped_from_the_supported_set(self):
        names = ['086_THINK', '066_CHARGE', '089_CHARGE_A', '067_EYE_TEST', '080_TEST_EVERYTHING', '130_CHARGE_X', 'bad', '140_NEW']
        self.assertEqual(face.asset_ids(names), {86, 140})

    def test_lease_high_water_survives_restart(self):
        ledger = face.CommandLedger(self.path)
        self.assertTrue(ledger.claim_lease(5, 's' * 32))
        self.assertFalse(face.CommandLedger(self.path).claim_lease(4, 't' * 32))
        self.assertTrue(face.CommandLedger(self.path).claim_lease(6, 't' * 32))

    def test_health_watch_fails_closed(self):
        clock = [0.0]
        watch = face.HealthWatch(clock=lambda: clock[0])
        self.assertIsNotNone(watch.problem())
        watch.on_system(0)
        self.assertIsNotNone(watch.problem())
        watch.on_battery(0)
        self.assertIsNone(watch.problem())
        watch.on_system(2)
        self.assertIn('warning', watch.problem())
        watch.on_system(0)
        clock[0] = face.HEALTH_MAX_AGE_SECONDS + 1
        self.assertIn("aren't arriving", watch.problem())

    def test_ready_waits_for_first_state_and_refuses_without_it(self):
        clock = [0.0]

        def advance(seconds):
            clock[0] += seconds
        watch = face.HealthWatch(clock=lambda: clock[0])
        self.assertFalse(watch.wait_for_first_state(1, pause=advance))
        self.assertGreaterEqual(clock[0], 1)
        watch.on_system(0)
        self.assertFalse(watch.wait_for_first_state(1, pause=advance))
        calls = []

        def arrives(seconds):
            calls.append(seconds)
            watch.on_battery(0)
        self.assertTrue(watch.wait_for_first_state(1, pause=arrives))
        self.assertEqual(len(calls), 1)
        # Reporting a warning still counts as reporting. The per-face check handles it.
        watch.on_system(2)
        self.assertTrue(watch.wait_for_first_state(1, pause=advance))
        self.assertIn('warning', watch.problem())
        source = (ROOT / 'vbot-demo' / 'robot_face.py').read_text()
        body = source[source.index('def run_session'):]
        self.assertLess(body.index('health.wait_for_first_state'), body.index('event="session_ready"'))

    def test_session_loop_ends_on_close_eof_and_unknown(self):
        def run(text, result=None):
            core = self.make_core()
            if result is not None:
                self.display.result = result
            with patch('builtins.print'):
                return face.serve(core, io.StringIO(text), wait=lambda r, w, x, t: (r, [], []))
        self.assertEqual(run(''), 0)
        self.assertEqual(run(json.dumps({'op': 'close'}) + '\n'), 0)
        self.assertEqual(run(json.dumps(self.frame(commandId='c' * 32)) + '\n', TimeoutError()), 1)
        self.display.result = (0, 0, 'ok')
        with self.assertRaises(ValueError):
            run('x' * (face.FRAME_LIMIT + 2))

    def test_session_idle_timeout_ends_the_session(self):
        with patch('builtins.print'):
            self.assertEqual(face.serve(self.make_core(), io.StringIO(''), wait=lambda r, w, x, t: ([], [], [])), 0)

    def test_helper_source_has_no_route_to_motion(self):
        source = (ROOT / 'vbot-demo' / 'robot_face.py').read_text()
        for forbidden in ('/rcp', 'execute_task', '/locomotion', 'velocity', '/function/', 'lowlevel', 'set_run_mode', 'robot_action import', 'import robot_action', 'create_action_client', 'create_publisher'):
            self.assertNotIn(forbidden, source, forbidden)
        routes = {node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith('/')}
        self.assertEqual(routes - {'/opt/vita/aorta/edu/edu_session.json5'},
                         {'/display_node/play_emotion', '/display_node/get_supported_emotions', '/system/sm_status', '/bms_state'})

    def test_default_invocation_is_an_offline_preview(self):
        with patch('builtins.print') as printed:
            self.assertEqual(face.main([]), 0)
        self.assertEqual(json.loads(printed.call_args[0][0])['execute'], False)

    def test_controller_and_helper_agree_on_restricted_faces(self):
        self.assertEqual(control.RESTRICTED_FACES, set(face.RESTRICTED_IDS))
        catalog = (ROOT / 'vbot-app/src/domain/catalog.ts').read_text()
        for asset in face.RESTRICTED_IDS:
            self.assertRegex(catalog.split('RESTRICTED_FACE_IDS')[1].split(';')[0], rf'\b{asset}\b')


WHEELHOUSE = ROOT / 'vbot-demo' / 'wheelhouse'


@unittest.skipUnless(list(WHEELHOUSE.glob('vbot_edu_msgs-*.whl')) and list(WHEELHOUSE.glob('flatbuffers-*.whl')), 'Local SDK wheels not staged.')
class RealSchemaTests(unittest.TestCase):
    """Encodes with the real generated schema from the SDK wheels. No aorta runtime and no robot."""

    def setUp(self):
        wheels = [str(next(WHEELHOUSE.glob(pattern))) for pattern in ('vbot_edu_msgs-*.whl', 'aorta_msgs-*.whl', 'flatbuffers-*.whl')]
        sys.path[:0] = wheels
        self.addCleanup(lambda: [sys.path.remove(wheel) for wheel in wheels])

    def encode(self, fill):
        import flatbuffers
        builder = flatbuffers.Builder(256)
        builder.Finish(fill(builder, 0))
        return bytes(builder.Output())

    def display(self, sent):
        import play_emotion_schema_meta as schema
        test = self
        class Client:
            def __enter__(self): return self
            def __exit__(self, *_exc): return False
            def call(self, fill):
                sent.append(test.encode(fill))
                class Reply:
                    def decode(self):
                        return type('Response', (), {'Status': lambda s: 0, 'ErrorCode': lambda s: 0, 'Message': lambda s: b'ok'})()
                return Reply()
        routes = []
        node = type('Node', (), {'create_client_typed': lambda s, route, decoder, request_schema_meta, options: routes.append((route, request_schema_meta)) or Client()})()
        sdk = type('Sdk', (), {'ClientOptions': staticmethod(lambda **kwargs: kwargs)})
        self.routes = routes
        return face.Display(node, sdk, schema, type('Response', (), {'GetRootAs': None})), schema

    def decode(self, payload):
        from aorta.services.peripheral.PlayEmotionRequest import PlayEmotionRequest
        return PlayEmotionRequest.GetRootAs(payload, 0)

    def test_play_matches_the_contract_exercised_on_the_dog(self):
        sent = []
        display, schema = self.display(sent)
        self.assertEqual(display.play(86, 4500, 'a' * 32), (0, 0, 'ok'))
        request = self.decode(sent[0])
        self.assertEqual((request.TargetState(), request.Mode(), request.DurationMs(), request.PreCheck()), (1, 86, 4500, False))
        self.assertEqual(request.ReqId(), b'a' * 32)
        self.assertEqual(self.routes, [('/display_node/play_emotion', schema)])

    def test_release_turns_playback_off(self):
        sent = []
        display, _schema = self.display(sent)
        display.release('b' * 32)
        request = self.decode(sent[0])
        self.assertEqual((request.TargetState(), request.Mode()), (0, 0))

    def test_supported_query_uses_the_real_schema(self):
        from aorta.services.peripheral.GetSupportedEmotionsRequest import GetSupportedEmotionsRequest
        test, payloads = self, []
        class Client:
            def __enter__(self): return self
            def __exit__(self, *_exc): return False
            def call(self, fill):
                payloads.append(test.encode(fill))
                response = type('Response', (), {'Status': lambda s: 0, 'SupportedEmotionsLength': lambda s: 2, 'SupportedEmotions': lambda s, i: [b'086_THINK', b'070_EXCITED'][i]})()
                return type('Reply', (), {'decode': lambda s: response})()
        node = type('Node', (), {'create_client_typed': lambda s, route, decoder, request_schema_meta, options: Client()})()
        sdk = type('Sdk', (), {'ClientOptions': staticmethod(lambda **kwargs: kwargs)})
        self.assertEqual(face.supported_faces(node, sdk), ['086_THINK', '070_EXCITED'])
        GetSupportedEmotionsRequest.GetRootAs(payloads[0], 0)

    def test_sdk_pairing_matches_the_motion_helper(self):
        pairing = re.compile(r'^VERSIONS = .*$', re.M)
        action = (ROOT / 'vbot-demo' / 'robot_action.py').read_text()
        helper = (ROOT / 'vbot-demo' / 'robot_face.py').read_text()
        self.assertEqual(pairing.search(action)[0], pairing.search(helper)[0])


class HttpSurfaceTests(ControllerCase):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.controller, port=0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, headers=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=None if body is None else json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_status_and_submit_round_trip(self):
        self.assertEqual(self.request('/api/app/status')[1]['connection'], 'disconnected')
        status = self.request('/api/app/connect', {'target': 'vbot@192.168.1.20'})[1]
        self.assertEqual(status['connection'], 'connected')
        code, receipt = self.request('/api/app/submit', self.envelope(status))
        self.assertEqual((code, receipt['state']), (200, 'accepted'))
        self.finish()

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_foreign_origin_or_host_is_refused(self):
        self.assertEqual(self.request('/api/app/status', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/app/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/app/connect', {'target': 'x'}, headers={'Origin': 'https://evil.example'})[0], 403)

    def test_post_requires_json(self):
        self.assertEqual(self.request('/api/app/connect', {'target': 'x'}, headers={'Content-Type': 'text/plain'})[0], 403)

    def test_static_path_traversal_cannot_escape(self):
        for path in ('/../../server/app.py', '/..%2f..%2fserver/app.py', '/../vbot_demo.py'):
            with self.subTest(path=path):
                connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
                self.addCleanup(connection.close)
                connection.putrequest('GET', path, skip_host=True)
                connection.putheader('Host', f'127.0.0.1:{self.port}')
                connection.endheaders()
                body = connection.getresponse().read()
                self.assertNotIn(b'import ', body)
                self.assertNotIn(b'BaseHTTPRequestHandler', body)

    def test_unknown_route(self):
        self.assertEqual(self.request('/api/app/motion', {})[0], 404)
        self.assertEqual(self.session.calls, [])


if __name__ == '__main__':
    unittest.main()
