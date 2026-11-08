"""VBOT Studio's controls on the hosted server, so Studio can reach the dog from anywhere.

This is the same controller a computer runs locally, so faces, presets and shows keep
every rule they already have, including the onsite confirmations before motion. Two
things are stricter here. Hold-to-drive is off, because a tunnel's delay is wrong for
it. And the session ends if Studio stops checking in, since nobody may be watching.
"""
from __future__ import annotations

import threading
import time

ACTIONS = {'connect', 'disconnect', 'submit', 'cancel'}
PRESENCE_SECONDS = 15
WATCH_SECONDS = 3
ACTIVE = {'connected', 'connecting'}
NO_DRIVE = 'Hold-to-drive needs a direct connection. Cloud control is too delayed for it.'
GONE = 'Disconnected because Studio stopped checking in.'


class CloudStudio:
    def __init__(self, demo, controller=None, clock=time.monotonic, watch_seconds=WATCH_SECONDS, presence_seconds=PRESENCE_SECONDS):
        self.demo, self._controller, self.clock = demo, controller, clock
        self.watch_seconds, self.presence_seconds = watch_seconds, presence_seconds
        self.lock = threading.Lock()
        self.last_seen = clock()
        self.watcher = None

    @property
    def controller(self):
        with self.lock:
            if self._controller is None:
                # Imported here: the tablet's own backend doesn't ship this controller.
                from vbot_app_control import AppController
                self._controller = AppController()
            return self._controller

    def _seen(self):
        with self.lock:
            self.last_seen = self.clock()
            if self.watcher is None:
                self.watcher = threading.Thread(target=self._watch, daemon=True, name='vbot-cloud-studio')
                self.watcher.start()

    def _view(self, snapshot):
        """Studio shows the reason next to the control, so the rule is never a mystery."""
        capabilities = snapshot.get('capabilities')
        if isinstance(capabilities, dict):
            capabilities['drive'] = {'available': False, 'reason': NO_DRIVE}
            capabilities['driveLimits'] = None
        return snapshot

    def status(self):
        self._seen()
        return self._view(self.controller.status())

    def handle(self, action, payload):
        """Returns (HTTP status, body), matching the local controller."""
        from vbot_app_control import route
        if action not in ACTIONS:
            return 404, {'message': 'Unknown route.'}
        self._seen()
        if action == 'connect':
            # The address is the server's own link to the dog, never something a client picks.
            if not self.demo.target:
                return 400, {'state': 'rejected', 'duplicate': False, 'code': 'not_connected', 'reason': 'No robot address is configured on this server.'}
            payload = {**payload, 'target': self.demo.target}
        code, body = route(self.controller, action, payload)
        return code, self._view(body) if action != 'submit' and code == 200 else body

    def _watch(self):
        wait = threading.Event()
        while not wait.wait(self.watch_seconds):
            self.check_presence()

    def check_presence(self):
        """A closed tab must not leave a show running, or the dog locked, with nobody watching."""
        with self.lock:
            gone = self.clock() - self.last_seen > self.presence_seconds
            controller = self._controller
        if not gone or controller is None or controller.connection not in ACTIVE:
            return False
        controller.disconnect()
        with controller.lock:
            controller.detail = GONE
        return True
