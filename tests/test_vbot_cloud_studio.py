"""VBOT Studio through the hosted server. The controller is replaced; nothing reaches a robot."""
from pathlib import Path
import sys
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import vbot_app_control
import vbot_cloud_studio
from vbot_cloud_studio import CloudStudio


class FakeController:
    def __init__(self):
        self.connection = 'disconnected'
        self.detail = None
        self.lock = threading.Lock()
        self.status = Mock(side_effect=lambda: {'connection': self.connection, 'capabilities': {'drive': {'available': True}, 'driveLimits': {'vx': 1}}})
        self.disconnect = Mock(side_effect=self._disconnect)

    def _disconnect(self):
        self.connection = 'disconnected'
        return {'connection': 'disconnected', 'capabilities': {'drive': {'available': True}, 'driveLimits': {'vx': 1}}}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(target='vbot-remote'):
    clock, controller = Clock(), FakeController()
    studio = CloudStudio(SimpleNamespace(target=target), controller=controller, clock=clock, watch_seconds=3600)
    return studio, controller, clock


class RouteTests(unittest.TestCase):
    def test_connect_always_uses_the_servers_own_link_to_the_dog(self):
        studio, controller, _ = make()
        controller.connect = Mock(return_value={'capabilities': {}})
        studio.handle('connect', {'target': 'vbot@8.8.8.8'})
        self.assertEqual(controller.connect.call_args.args[0]['target'], 'vbot-remote')

    def test_drive_is_not_reachable(self):
        studio, controller, _ = make()
        controller.drive = Mock()
        self.assertEqual(studio.handle('drive', {'action': 'start'})[0], 404)
        controller.drive.assert_not_called()

    def test_snapshots_say_drive_is_off_and_why(self):
        studio, _, _ = make()
        capabilities = studio.status()['capabilities']
        self.assertFalse(capabilities['drive']['available'])
        self.assertIn('direct connection', capabilities['drive']['reason'])
        self.assertIsNone(capabilities['driveLimits'])

    def test_motion_still_needs_every_onsite_confirmation(self):
        controller = vbot_app_control.AppController(journal_path=Path('/nonexistent/journal.jsonl'))
        studio = CloudStudio(SimpleNamespace(target='vbot-remote'), controller=controller, watch_seconds=3600)
        code, body = studio.handle('connect', {'motion': {'onsite': True, 'standing': True, 'clear': False}})
        self.assertEqual(code, 400)
        self.assertEqual(body['code'], 'motion_not_confirmed')

    def test_a_server_without_a_robot_explains_itself(self):
        studio, _, _ = make(target='')
        code, body = studio.handle('connect', {})
        self.assertEqual(code, 400)
        self.assertIn('No robot address', body['reason'])


class PresenceTests(unittest.TestCase):
    def test_session_ends_when_studio_stops_checking_in(self):
        studio, controller, clock = make()
        controller.connection = 'connected'
        studio.status()
        clock.now += vbot_cloud_studio.PRESENCE_SECONDS + 1
        self.assertTrue(studio.check_presence())
        controller.disconnect.assert_called_once()
        self.assertEqual(controller.detail, vbot_cloud_studio.GONE)

    def test_a_polling_studio_keeps_its_session(self):
        studio, controller, clock = make()
        controller.connection = 'connected'
        for _ in range(10):
            clock.now += vbot_cloud_studio.PRESENCE_SECONDS - 1
            studio.status()
            self.assertFalse(studio.check_presence())
        controller.disconnect.assert_not_called()

    def test_nothing_to_stop_when_disconnected(self):
        studio, controller, clock = make()
        studio.status()
        clock.now += 1000
        self.assertFalse(studio.check_presence())
        controller.disconnect.assert_not_called()


class AccessTests(unittest.TestCase):
    def handler(self, path, authorized):
        import app
        sent = []
        instance = app.Handler.__new__(app.Handler)
        instance.path = path
        instance._tablet_api_denied = Mock(return_value=False)
        instance._vbot_local_request = Mock(return_value=authorized)
        instance._send = lambda status, body: sent.append((status, body))
        return app, instance, sent

    def test_status_needs_a_paired_device(self):
        app, instance, sent = self.handler('/api/vbot/studio/status', False)
        with patch.object(app, 'cloud_studio') as studio:
            instance.do_GET()
        self.assertEqual(sent[0][0], 403)
        studio.status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
