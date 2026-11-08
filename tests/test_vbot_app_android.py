"""The APK's embedded controller and packaging, without Android, a network or a robot."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
ANDROID = ROOT / 'vbot-app' / 'android'
BACKEND_PATH = ANDROID / 'app' / 'src' / 'main' / 'python' / 'studio_backend.py'
GRADLE = (ANDROID / 'app' / 'build.gradle').read_text()
PACKAGED = re.search(r"from\('\.\./\.\./\.\./server'\) \{ include (.+?) \}", GRADLE)[1]
PACKAGED_MODULES = re.findall(r"'(\w+)\.py'", PACKAGED)
FINGERPRINT = 'SHA256:' + 'A' * 43

spec = importlib.util.spec_from_file_location('studio_backend', BACKEND_PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class FakeStream:
    """Answers like robot_face.py over the native SSH stream."""

    def __init__(self, command):
        remote = shlex.split(command)
        self.session_id = remote[remote.index('--session-id') + 1]
        self.lines = [json.dumps({'event': 'session_ready', 'requestId': self.session_id, 'protocol': 1, 'faceOnly': True,
                                  'supportedFaces': ['086_THINK']})]
        self.written, self.closed = [], False

    def writeLine(self, line):
        frame = json.loads(line)
        self.written.append(frame)
        event = 'started' if frame['op'] == 'face' else 'released'
        self.lines.append(json.dumps({'event': event, 'commandId': frame['commandId']}))

    def readLine(self, _timeout):
        return self.lines.pop(0) if self.lines else ''

    def close(self):
        self.closed = True


class FakeHost:
    def __init__(self, fingerprint=FINGERPRINT, failure=None):
        self.fingerprint, self.failure = fingerprint, failure
        self.opened, self.streams = [], []

    def trustedFingerprint(self):
        return self.fingerprint

    def openSshStream(self, target, command):
        self.opened.append(target)
        if self.failure:
            raise self.failure
        stream = FakeStream(command)
        self.streams.append(stream)
        return stream


class BackendCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name) / 'vbot-app'
        self.host = FakeHost()
        self.original_native, backend.native = backend.native, lambda: self.host
        backend._controller = None
        backend.start(self.home)
        self.addCleanup(self.restore)

    def restore(self):
        backend.native = self.original_native
        backend._controller.disconnect()
        backend._controller = None

    def call(self, path, payload=None):
        reply = json.loads(backend.call(path, json.dumps(payload) if payload is not None else ''))
        return reply['status'], reply['body']

    def envelope(self, status, cue):
        now = int(backend._controller.wall_ms())
        return {'v': 1, 'commandId': 'a' * 32, 'deviceId': status['device']['id'], 'sessionId': status['sessionId'],
                'leaseGeneration': status['leaseGeneration'], 'issuedAt': now, 'expiresAt': now + 30000, 'kind': 'run-score',
                'score': {'schemaVersion': 1, 'id': 'show', 'title': 'Show', 'notes': '', 'origin': 'custom', 'revision': 1, 'repeat': 1,
                          'createdAt': now, 'updatedAt': now, 'cues': [cue]}}


class IdentityTests(BackendCase):
    def test_an_unpaired_app_refuses_before_opening_ssh(self):
        self.host.fingerprint = ''
        _status, body = self.call('connect', {'target': '192.168.1.5'})
        self.assertEqual(body['connection'], 'unavailable')
        self.assertIn('Pair this app', body['detail'])
        self.assertEqual(self.host.opened, [])

    def test_the_device_id_comes_from_the_pinned_key_not_the_address(self):
        ids = set()
        for address in ('192.168.1.5', '172.20.10.5'):
            _status, body = self.call('connect', {'target': address})
            self.assertEqual(body['connection'], 'connected')
            ids.add(body['device']['id'])
            self.call('disconnect', {})
        self.assertEqual(ids, {'ssh-host-key:' + FINGERPRINT})

    def test_a_changed_key_shows_the_native_refusal_and_never_connects(self):
        message = "This dog presented ssh-rsa SHA256:xyz, not the paired fingerprint. Don't accept it blindly."
        self.host.failure = RuntimeError('java.io.IOException: vbot-refusal: ' + message + '\n\tat com.andy.vbotstudio.StudioHost')
        _status, body = self.call('connect', {'target': '192.168.1.5'})
        self.assertEqual(body['connection'], 'unavailable')
        self.assertEqual(body['detail'], message)

    def test_other_native_errors_stay_generic(self):
        self.host.failure = RuntimeError('java.io.IOException: secret internal detail')
        _status, body = self.call('connect', {'target': '192.168.1.5'})
        self.assertEqual(body['connection'], 'unavailable')
        self.assertNotIn('secret', body['detail'])

    def test_options_cannot_be_smuggled_through_the_address(self):
        _status, body = self.call('connect', {'target': '-oProxyCommand=evil'})
        self.assertEqual(body['connection'], 'unavailable')
        self.assertEqual(self.host.opened, [])


class CommandTests(BackendCase):
    def connect(self):
        _status, body = self.call('connect', {'target': '192.168.1.5'})
        self.assertEqual(body['connection'], 'connected')
        return body

    def wait_finished(self):
        for _ in range(200):
            _status, body = self.call('status')
            if body['run'] and body['run']['state'] in {'completed', 'rejected', 'cancelled', 'unknown'}:
                return body
            __import__('time').sleep(0.01)
        self.fail('The show did not finish.')

    def test_a_face_runs_through_the_same_controller_and_journal(self):
        status = self.connect()
        cue = {'id': 'one', 'type': 'face', 'assetId': 86, 'durationMs': 500}
        code, receipt = self.call('submit', self.envelope(status, cue))
        self.assertEqual((code, receipt['state']), (200, 'accepted'))
        body = self.wait_finished()
        self.assertEqual(body['run']['state'], 'completed')
        self.assertEqual(body['run']['cleanup'], 'released')
        frames = self.host.streams[0].written
        self.assertEqual([frame['op'] for frame in frames], ['face', 'face_release'])
        journal = (self.home / 'commands.jsonl').read_text()
        self.assertIn('a' * 32, journal)
        self.assertNotIn('192.168', journal)

    def test_a_repeat_submit_does_not_replay(self):
        status = self.connect()
        cue = {'id': 'one', 'type': 'face', 'assetId': 86, 'durationMs': 500}
        envelope = self.envelope(status, cue)
        self.call('submit', envelope)
        self.wait_finished()
        _code, receipt = self.call('submit', envelope)
        self.assertTrue(receipt['duplicate'])
        self.assertEqual(sum(frame['op'] == 'face' for frame in self.host.streams[0].written), 1)

    def test_motion_is_refused_and_never_reaches_the_stream(self):
        status = self.connect()
        for cue_type in ('head', 'body'):
            cue = {'id': 'one', 'type': cue_type, 'preset': 'x', 'durationMs': 1000}
            envelope = self.envelope(status, cue)
            envelope['commandId'] = (cue_type[0] * 32).replace('h', 'b').replace('b', 'c' if cue_type == 'head' else 'd')
            _code, receipt = self.call('submit', envelope)
            self.assertEqual((receipt['state'], receipt['code']), ('rejected', 'capability_unavailable'))
        self.assertEqual(self.host.streams[0].written, [])

    def test_pairing_is_refused_while_connected(self):
        self.connect()
        with self.assertRaisesRegex(ValueError, 'vbot-refusal: Disconnect'):
            backend.can_pair()
        self.call('disconnect', {})
        self.assertTrue(backend.can_pair())

    def test_bad_requests_and_unknown_routes_change_nothing(self):
        self.assertEqual(self.call('connect', ['not', 'an', 'object'])[0], 400)
        self.assertEqual(json.loads(backend.call('connect', 'x' * (backend.MAX_BODY + 1)))['status'], 400)
        self.assertEqual(json.loads(backend.call('connect', '{broken'))['status'], 400)
        self.assertEqual(self.call('head', {})[0], 404)
        self.assertEqual(self.host.opened, [])


class PackagingTests(unittest.TestCase):
    def imports(self, path):
        names = set()
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split('.')[0])
        return names

    def test_the_backend_imports_from_only_the_packaged_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in [BACKEND_PATH, *(ROOT / 'server' / f'{name}.py' for name in PACKAGED_MODULES)]:
                shutil.copy(path, directory)
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import studio_backend; "
                    "loaded = sorted(n for n in sys.modules if n.startswith(('vbot', 'robot', 'chess', 'app'))); print(loaded)")
            result = subprocess.run([sys.executable, '-I', '-c', code, directory], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(sorted(PACKAGED_MODULES)))

    def test_the_identity_is_separate_from_chess_buddy(self):
        self.assertIn('applicationId "com.andy.vbotstudio"', GRADLE)
        self.assertNotIn('applicationId "com.andy.chessbuddy"', GRADLE)
        self.assertIn('applicationId "com.andy.chessbuddy"', (ROOT / 'android' / 'app' / 'build.gradle').read_text())
        self.assertNotIn('chessbuddy', (ROOT / 'vbot-app' / 'capacitor.config.ts').read_text().split('appId')[1].split('\n')[0])

    def test_the_apk_carries_only_the_controller_and_no_chess_or_listener(self):
        self.assertEqual(sorted(PACKAGED_MODULES), ['vbot_app_control', 'vbot_networks', 'vbot_ssh'])
        allowed_local = {*PACKAGED_MODULES, 'studio_backend'}
        paths = [BACKEND_PATH, *(ROOT / 'server' / f'{name}.py' for name in PACKAGED_MODULES)]
        forbidden = {'chess', 'requests', 'http', 'socket', 'socketserver', 'app', 'vbot_demo', 'vbot_app_server', 'robot_action', 'robot_face'}
        for path in paths:
            found = self.imports(path)
            self.assertFalse(found & forbidden, f'{path.name}: {found & forbidden}')
            self.assertTrue({name for name in found if name.startswith('vbot_')} <= allowed_local, path.name)

    def test_the_manifest_asks_only_for_network_and_blocks_backup(self):
        namespace = '{http://schemas.android.com/apk/res/android}'
        root = ElementTree.parse(ANDROID / 'app' / 'src' / 'main' / 'AndroidManifest.xml').getroot()
        self.assertEqual([item.get(namespace + 'name') for item in root.findall('uses-permission')], ['android.permission.INTERNET'])
        application = root.find('application')
        self.assertEqual(application.get(namespace + 'allowBackup'), 'false')
        self.assertIsNone(application.get(namespace + 'usesCleartextTraffic'))
        self.assertEqual(application.findall('service'), [])

    def test_native_ssh_never_accepts_an_unknown_key_or_logs_secrets(self):
        source = (ANDROID / 'app' / 'src' / 'main' / 'java' / 'com' / 'andy' / 'vbotstudio' / 'StudioHost.java').read_text()
        self.assertIn('setConfig("StrictHostKeyChecking", "yes")', source)
        self.assertNotIn('"StrictHostKeyChecking", "no"', source)
        self.assertIn('Automatic host-key acceptance is disabled', source)
        self.assertNotIn('Log.', source)
        plugin = (ANDROID / 'app' / 'src' / 'main' / 'java' / 'com' / 'andy' / 'vbotstudio' / 'StudioPlugin.java').read_text()
        self.assertNotIn('Log.', plugin)
        self.assertNotIn('sshPrivateKey', plugin)
        # Trust is written once, and only after the dog accepted this app's key.
        self.assertEqual(source.count('data.put("robotFingerprint"'), 1)
        self.assertLess(source.index('channel.getExitStatus() != 0'), source.index('data.put("robotFingerprint"'))

    def test_release_requires_validated_build_and_scopes_publish_permissions(self):
        import yaml
        workflow = (ROOT / '.github' / 'workflows' / 'vbot-studio-apk.yml').read_text()
        data = yaml.safe_load(workflow)
        self.assertEqual(data['permissions'], {'contents': 'read'})
        self.assertEqual(data['jobs']['publish']['needs'], 'apk')
        self.assertEqual(data['jobs']['publish']['permissions'], {'contents': 'write'})
        build = data['jobs']['apk']
        self.assertNotIn('permissions', build)
        self.assertIn('connectedReleaseAndroidTest', workflow)
        self.assertIn('scripts/verify_android_signature.py apk/signature.txt android/signing-certificate.sha256', workflow)
        self.assertEqual(set(re.findall(r'secrets\.(\w+)', workflow)), {'ANDROID_SIGNING_BUNDLE'})
        self.assertIn('vbot-studio-v$code', workflow)
        self.assertNotIn('codex/android-standalone', workflow)
        # Only the public installable artifacts are uploaded, not the restored key.
        uploads = [step for step in build['steps'] if step.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(uploads[0]['with']['path'], 'apk/')
        package = next(step['run'] for step in build['steps'] if step.get('name') == 'Package')
        self.assertNotIn('ANDROID_KEYSTORE_PATH', package)
        self.assertIn('signingConfig signingConfigs.persistent', GRADLE)
        self.assertIn("testBuildType 'release'", GRADLE)
        self.assertIn("if (!releaseSigningReady) throw new GradleException", GRADLE)


if __name__ == '__main__':
    unittest.main()
