"""Hosted-server operator login: configurable pairing origins and operator presence.

All robot I/O is replaced with test doubles. Nothing here moves a robot.
"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'tests'))
import app
from tablet_access import TabletAccess, TABLET_HEADER, TABLET_ORIGIN, parse_origins
from vbot_demo import VbotDemo, operator_timeout_seconds
import test_vbot_performance as performance_tests

TOKEN = 'Abc_-' + 'x' * 38  # token_urlsafe(32) shape: 43 URL-safe characters
WEB = 'http://localhost:5173'
DOCKER_GATEWAY = '192.168.65.1'


class OriginTests(unittest.TestCase):
    def test_origins_are_validated_and_trailing_slashes_dropped(self):
        self.assertEqual(parse_origins(f' {WEB}/ , https://localhost,capacitor://localhost '),
                         {WEB, 'https://localhost', 'capacitor://localhost'})
        self.assertEqual(parse_origins(''), set())
        for bad in ('https://x.example/path', 'javascript:alert(1)', 'https://a b', 'ftp://x.example', '*'):
            with self.assertRaises(ValueError):
                parse_origins(bad)

    def test_android_origin_is_always_accepted_and_others_only_when_configured(self):
        plain = TabletAccess(TOKEN)
        self.assertTrue(plain.authorized(DOCKER_GATEWAY, TABLET_ORIGIN, TOKEN))
        self.assertFalse(plain.authorized(DOCKER_GATEWAY, WEB, TOKEN))
        hosted = TabletAccess(TOKEN, 'https://chess-api.example', {WEB})
        self.assertTrue(hosted.authorized(DOCKER_GATEWAY, WEB, TOKEN))
        self.assertTrue(hosted.authorized(DOCKER_GATEWAY, TABLET_ORIGIN, TOKEN))
        self.assertFalse(hosted.authorized(DOCKER_GATEWAY, 'https://evil.example', TOKEN))
        self.assertFalse(hosted.authorized(DOCKER_GATEWAY, WEB, TOKEN[:-1] + 'y'))

    def test_hosted_pairing_page_says_the_key_is_the_only_credential(self):
        hosted = TabletAccess(TOKEN, 'https://chess-api.example').page().decode()
        self.assertIn('only credential', hosted)
        self.assertIn('Use a Chess Buddy server', hosted)
        self.assertNotIn('<script', hosted)
        lan = TabletAccess(TOKEN, 'http://192.168.0.20:8765').page().decode()
        self.assertIn('same trusted Wi-Fi', lan)


class HostedGateTests(unittest.TestCase):
    """Requests reach the container from Docker's private gateway with the public Host header."""

    def handler(self, *, token=TOKEN, origin=WEB, path='/api/vbot/status'):
        handler = object.__new__(app.Handler)
        handler.client_address = (DOCKER_GATEWAY, 40000)
        handler.server = SimpleNamespace(server_port=8765)
        handler.headers = {'Host': 'chess-api.example', 'Origin': origin, TABLET_HEADER: token}
        handler.path = path
        handler._send = Mock()
        return handler

    def hosted(self):
        return patch.object(app, 'tablet_access', TabletAccess(TOKEN, 'https://chess-api.example', {WEB}))

    def test_paired_device_unlocks_robot_and_account_controls(self):
        with self.hosted():
            paired = self.handler()
            self.assertFalse(paired._tablet_api_denied())
            self.assertTrue(paired._vbot_local_request())

    def test_unpaired_or_wrong_origin_requests_are_refused(self):
        with self.hosted():
            for handler in (self.handler(token=''), self.handler(origin='https://evil.example'), self.handler(token='z' * 43)):
                self.assertFalse(handler._vbot_local_request())
                self.assertTrue(handler._tablet_api_denied())
                self.assertEqual(handler._send.call_args.args[0], 403)

    def test_configured_origin_drives_cors_only_while_pairing_is_on(self):
        ops = 'https://ops.example'  # not in the server's built-in CORS list
        with patch.object(app, 'tablet_access', TabletAccess(TOKEN, 'https://chess-api.example', {ops})):
            self.assertEqual(self.handler(origin=ops)._cors_origin(), ops)
        with patch.object(app, 'tablet_access', TabletAccess('', '', {ops})):
            self.assertNotEqual(self.handler(origin=ops)._cors_origin(), ops)

    def test_only_an_authorized_status_poll_counts_as_operator_presence(self):
        with self.hosted(), patch.object(app, 'vbot_demo') as demo:
            demo.status.return_value = {}
            self.handler().do_GET()
            demo.touch_operator.assert_called_once()
            demo.touch_operator.reset_mock()
            self.handler(token='').do_GET()
            demo.touch_operator.assert_not_called()


class PresenceTests(unittest.TestCase):
    def test_timeout_is_off_by_default_and_clamped(self):
        self.assertEqual(operator_timeout_seconds('0'), 0)
        self.assertEqual(operator_timeout_seconds(''), 0)
        self.assertEqual(operator_timeout_seconds('nope'), 0)
        self.assertEqual(operator_timeout_seconds('2'), 5)
        self.assertEqual(operator_timeout_seconds('15'), 15)
        self.assertEqual(operator_timeout_seconds('9000'), 300)

    def demo(self):
        self.now = 1000.0
        demo = VbotDemo(clock=lambda: self.now, verification={}, sender=Mock(), checker=Mock())
        demo.armed, demo.game_id = True, 'game1'
        return demo

    def record(self):
        return {'gameId': 'game1', 'playerColor': 'white', 'ply': 7, 'playedMove': 'Nf3', 'classification': 'best'}

    def test_server_started_motion_is_disarmed_when_the_operator_device_goes_quiet(self):
        demo = self.demo()
        demo.operator_timeout = 15
        demo.touch_operator()
        self.now += 16
        result = demo._submit(self.record())
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('stopped checking in', result['reason'])
        self.assertFalse(demo.armed)
        self.assertTrue(any(e.get('reasonCode') == 'operator_offline' for e in demo.events))
        demo.sender.assert_not_called()

    def test_recent_operator_and_local_mac_mode_do_not_disarm(self):
        demo = self.demo()
        demo.operator_timeout = 15
        demo.touch_operator()
        self.now += 10
        self.assertFalse(demo._operator_absent())
        local = self.demo()  # VBOT_OPERATOR_TIMEOUT_S unset: never seen, never absent
        self.assertEqual(local.operator_timeout, 0)
        self.assertFalse(local._operator_absent())


class PerformancePresenceTests(unittest.TestCase):
    def setUp(self):
        performance_tests.PerformanceTests.setUp(self)

    start = performance_tests.PerformanceTests.start
    execute = performance_tests.PerformanceTests.execute

    def test_show_submits_no_cue_after_the_operator_device_goes_quiet(self):
        self.demo.operator_timeout = 15
        self.demo.touch_operator()
        self.start()
        self.now += 20
        self.execute()
        self.sender.assert_not_called()
        self.assertIn('stopped checking in', self.demo.performance['stopReason'])
        self.assertFalse(self.demo.armed)

    def test_show_continues_while_the_device_keeps_polling(self):
        self.demo.operator_timeout = 15
        self.demo.touch_operator()
        self.start()

        class Polling(performance_tests.Waits):
            def wait(inner, seconds):
                stopped = super().wait(seconds)
                self.demo.touch_operator()
                return stopped
        self.execute(Polling(self))
        self.assertGreater(self.sender.call_count, 1)
        self.assertEqual(self.demo.performance['phase'], 'completed')


class TargetFallbackTests(unittest.TestCase):
    def test_hosted_server_keeps_the_configured_robot_target(self):
        book = Mock()
        book.current.return_value = {'id': None, 'message': 'No physical LAN default route detected.'}
        book.snapshot.return_value = {'suggestedTarget': None, 'current': {'id': None}}
        with patch.dict(os.environ, {'VBOT_SSH_TARGET': 'vbot-remote'}):
            demo = VbotDemo(network_book=book, verification={}, sender=Mock(), checker=Mock())
            self.assertEqual(demo.status()['target'], 'vbot-remote')

    def test_remembered_address_still_wins_on_a_known_network(self):
        book = Mock()
        book.current.return_value = {'id': 'a' * 64, 'subnet': '192.168.0.0/24', 'gateway': '192.168.0.1'}
        book.snapshot.return_value = {'suggestedTarget': 'vbot@192.168.0.170', 'current': {'id': 'a' * 64}}
        with patch.dict(os.environ, {'VBOT_SSH_TARGET': 'vbot-remote'}):
            demo = VbotDemo(network_book=book, verification={}, sender=Mock(), checker=Mock())
            self.assertEqual(demo.status()['target'], 'vbot@192.168.0.170')


if __name__ == '__main__':
    unittest.main()
