"""Offline score/dispatch witnesses. All robot I/O is replaced with test doubles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from vbot_demo import VbotDemo, PRESETS
from vbot_performance import performance_plan, DANCE


class Waits:
    def __init__(self, owner, stop_after=None):
        self.owner, self.calls, self.stop_after = owner, [], stop_after
    def is_set(self):
        return self.stop_after is not None and len(self.calls) >= self.stop_after
    def wait(self, seconds):
        self.calls.append(seconds); self.owner.now += seconds
        return self.is_set()


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.fingerprint = 'SHA256:' + 'a' * 43
        self.target = 'vbot@robot.example'
        entries = [dict(preset=p, status='SUCCEEDED', errorCategory=0, movementConfirmed=True,
                        durationMs=40000 if p == DANCE else 1000) for p in PRESETS]
        self.sender = Mock(return_value={'status': 'completed', 'readyForNext': True})
        self.checker = Mock(return_value={'ready': True})
        self.demo = VbotDemo(clock=lambda: self.now, sender=self.sender, checker=self.checker,
            verification={'target': self.target, 'hostKeyFingerprint': self.fingerprint, 'presets': entries},
            fingerprint_reader=lambda _: {self.fingerprint})
        self.demo.readiness = {'ready': True, 'target': self.target, 'probeToken': 'c' * 32}; self.demo.readiness_at = self.now
        self.payload = dict(target=self.target, dances=2, pace='theatrical', requestId='b' * 32,
                            confirmSafeWorkspace=True, confirmHandsetStop=True, readinessProbe='c' * 32)

    def start(self, **changes):
        with patch('vbot_demo.threading.Thread'):
            return self.demo.start_performance({**self.payload, **changes})

    def execute(self, cancel=None):
        self.demo._perform_score(self.payload['requestId'], self.demo.generation, cancel or Waits(self))

    def test_preview_never_probes_arms_or_sends_motion(self):
        preview = self.demo.preview_performance(self.payload)['performancePreview']
        self.assertTrue(preview['allRehearsed'])
        self.assertEqual(sum(c['preset'] == DANCE for c in preview['cues']), 2)
        self.assertFalse(self.demo.armed)
        self.checker.assert_not_called(); self.sender.assert_not_called()

    def test_score_is_bounded_and_rest_is_never_removed_from_body_cues(self):
        for dances in (1, 2, 3):
            plan = performance_plan({'dances': dances, 'pace': 'lively'}, lambda _: {'durationMs': 1000})
            self.assertEqual(sum(c['preset'] == DANCE for c in plan['cues']), dances)
            self.assertTrue(all(c['restSeconds'] >= 20 for c in plan['cues'] if c['preset'] == DANCE))
        for bad in (0, 4, True, '2'):
            with self.assertRaises(ValueError): performance_plan({'dances': bad}, lambda _: None)

    def test_live_requires_confirmations_identity_all_rehearsals_and_fresh_readiness(self):
        for change in ({'confirmHandsetStop': False}, {'confirmSafeWorkspace': False}):
            with self.assertRaises(ValueError): self.start(**change)
        self.demo.readiness_at = self.now - 31
        with self.assertRaises(ValueError): self.start()
        self.demo.readiness_at = self.now
        self.demo.verification['presets'].pop()
        # JUMP_IN_PLACE is not in this score; remove an actual required cue.
        self.demo.verification['presets'] = [p for p in self.demo.verification['presets'] if p['preset'] != 'actions/WAVE.json']
        with self.assertRaises(ValueError): self.start()
        self.sender.assert_not_called()

    def test_all_cues_complete_serially_and_show_disarms(self):
        started = self.start()
        self.assertEqual(started['sessionKind'], 'performance')
        self.assertEqual(started['gameId'], '')
        expected = [c['preset'] for c in started['performance']['cues']]
        self.execute()
        self.assertEqual([call.args[1] for call in self.sender.call_args_list], expected)
        self.assertEqual(self.demo.performance['phase'], 'completed')
        self.assertFalse(self.demo.armed); self.assertFalse(self.demo.busy)
        self.assertGreater(self.demo.last_dance_finished, 100)

    def test_duplicate_start_identity_never_replays_and_cannot_change_show(self):
        self.start(); generation = self.demo.generation
        self.start(); self.assertEqual(generation, self.demo.generation)
        with self.assertRaises(ValueError): self.start(dances=3)
        self.execute()
        count = self.sender.call_count
        self.start(); self.assertEqual(self.sender.call_count, count)
        self.assertFalse(self.demo.armed)

    def test_rejection_unknown_outcome_and_failed_postflight_stop_after_one_cue(self):
        for result in ('unknown', 'not_ready'):
            self.setUp()
            if result == 'unknown': self.sender.side_effect = TimeoutError()
            else: self.sender.return_value = {'status': 'completed', 'readyForNext': False}
            self.start(); self.execute()
            self.assertEqual(self.sender.call_count, 1)
            self.assertFalse(self.demo.armed)
            self.assertEqual(self.demo.performance['phase'], 'stopped')

    def test_stop_during_rest_prevents_all_remaining_cues(self):
        self.start(); self.execute(Waits(self, stop_after=1))
        self.assertEqual(self.sender.call_count, 1)
        self.assertFalse(self.demo.armed)

    def test_disarm_during_motion_never_dispatches_the_next_cue(self):
        def sender(*_):
            self.demo.disarm()
            return {'status': 'completed', 'readyForNext': True}
        self.sender.side_effect = sender
        self.start(); self.execute()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.demo.performance['phase'], 'stopped')

    def test_chess_arming_cannot_steal_the_dispatcher_during_a_show_rest(self):
        self.start()
        with self.assertRaisesRegex(ValueError, 'Stop the standalone performance'):
            self.demo.arm({'gameId': 'AbCd1234'})

    def test_host_identity_is_rechecked_for_every_cue(self):
        self.start()
        self.demo.fingerprint_reader = lambda _: set()
        self.execute()
        self.sender.assert_not_called(); self.assertFalse(self.demo.armed)

    def test_stale_stop_cannot_cancel_a_newer_performance(self):
        self.start(); generation = self.demo.generation
        self.demo.disarm({'gameId': '', 'generation': generation - 1, 'reason': 'operator_off'})
        self.assertTrue(self.demo.armed)
        self.assertFalse(self.demo.performance_cancel.is_set())
        self.demo.disarm({'gameId': '', 'generation': generation, 'reason': 'operator_off'})
        self.assertFalse(self.demo.armed)
        self.assertTrue(self.demo.performance_cancel.is_set())

    def test_execution_deadline_prevents_another_cue(self):
        self.start()
        class LongWait(Waits):
            def wait(self, seconds):
                self.owner.now += 901
                return False
        self.execute(LongWait(self))
        self.assertEqual(self.sender.call_count, 1)
        self.assertIn('15-minute', self.demo.performance['stopReason'])

    def test_long_or_unmeasured_short_gestures_cannot_enter_the_live_score(self):
        for duration in (None, True, 0, 10001):
            plan = performance_plan({}, lambda preset: {'durationMs': duration if preset == 'actions/WAVE.json' else 1000})
            self.assertFalse(plan['allRehearsed'])
            self.assertIn('actions/WAVE.json', plan['missingPresets'])

    def test_old_start_cannot_bind_to_a_new_readiness_probe_after_cache_or_restart(self):
        self.start(); self.demo.disarm(); self.demo.performance_requests.clear()
        self.demo.check_device({'target': self.target})
        with self.assertRaisesRegex(ValueError, 'readiness check changed'):
            self.start()
        self.sender.assert_not_called()
