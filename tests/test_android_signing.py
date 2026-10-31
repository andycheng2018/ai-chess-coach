import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('android_signing', Path(__file__).resolve().parents[1] / 'scripts/android_signing.py')
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class AndroidSigningTests(unittest.TestCase):
    def test_missing_identity_fails_instead_of_generating_another_key(self):
        with patch.dict(os.environ, {'ANDROID_SIGNING_BUNDLE': ''}):
            with self.assertRaisesRegex(RuntimeError, 'ANDROID_SIGNING_BUNDLE'):
                signing.restore()

    def test_restore_preserves_key_bytes_masks_password_and_limits_file_access(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / 'environment'
            supplied = json.dumps({'keystore': 'a2V5LWJ5dGVz', 'password': 'test-password'})
            output = io.StringIO()
            with patch.dict(os.environ, {'ANDROID_SIGNING_BUNDLE': supplied, 'RUNNER_TEMP': directory, 'GITHUB_ENV': str(environment)}), contextlib.redirect_stdout(output):
                signing.restore()
            keystore = Path(directory) / 'chessbuddy-release.p12'
            self.assertEqual(keystore.read_bytes(), b'key-bytes')
            self.assertEqual(keystore.stat().st_mode & 0o777, 0o600)
            self.assertIn('::add-mask::test-password', output.getvalue())
            self.assertIn('ANDROID_KEYSTORE_PASSWORD=test-password\n', environment.read_text())

    def test_newline_in_password_cannot_inject_runner_environment(self):
        supplied = json.dumps({'keystore': 'a2V5', 'password': 'bad\nOTHER_SECRET=value'})
        with patch.dict(os.environ, {'ANDROID_SIGNING_BUNDLE': supplied}):
            with self.assertRaisesRegex(ValueError, 'Invalid signing bundle password'):
                signing.restore()

    def test_init_never_regenerates_existing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            bundle = local / 'github-secret.json'
            bundle.write_text('existing')
            with patch.object(signing, 'LOCAL', local), patch.object(signing.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
                signing.initialize()
            run.assert_not_called()
            self.assertEqual(bundle.read_text(), 'existing')
