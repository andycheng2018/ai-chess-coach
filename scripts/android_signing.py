#!/usr/bin/env python3
"""Create a persistent local key, or restore its encrypted CI secret. Never print key material."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local' / 'android-signing'


def initialize():
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle = LOCAL / 'github-secret.json'
    if bundle.exists():
        print('Existing signing identity retained. No new key generated.')
        return
    keystore = LOCAL / 'chessbuddy-release.p12'
    if keystore.exists():
        raise RuntimeError('Keystore already exists without its bundle. Recover it; do not replace the key.')
    password_file = LOCAL / 'password'
    password_file.write_text(secrets.token_urlsafe(48)); password_file.chmod(0o600)
    with tempfile.TemporaryDirectory(dir=LOCAL) as temp:
        private, certificate = Path(temp) / 'key.pem', Path(temp) / 'certificate.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-days', '10000',
                        '-nodes', '-subj', '/CN=Chess Buddy Android Release/', '-keyout', str(private),
                        '-out', str(certificate)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['openssl', 'pkcs12', '-export', '-name', 'chessbuddy', '-inkey', str(private),
                        '-in', str(certificate), '-out', str(keystore), '-passout', 'file:' + str(password_file)], check=True)
        (LOCAL / 'certificate.pem').write_bytes(certificate.read_bytes())
    keystore.chmod(0o600)
    bundle.write_text(json.dumps({'keystore': base64.b64encode(keystore.read_bytes()).decode(), 'password': password_file.read_text()}))
    bundle.chmod(0o600)
    print('Permanent signing identity created in .local/android-signing (Git ignored).')
    print('Back up this private folder securely. It is required for every future Android update.')


def restore():
    supplied = os.environ.get('ANDROID_SIGNING_BUNDLE', '')
    if not supplied:
        raise RuntimeError('Set the ANDROID_SIGNING_BUNDLE GitHub Actions secret before building releases.')
    data = json.loads(supplied)
    password = data['password']
    if not isinstance(password, str) or not password or '\n' in password or '\r' in password:
        raise ValueError('Invalid signing bundle password.')
    target = Path(os.environ['RUNNER_TEMP']) / 'chessbuddy-release.p12'
    target.write_bytes(base64.b64decode(data['keystore'], validate=True)); target.chmod(0o600)
    # The decoded password must be masked as well as the complete JSON secret.
    print('::add-mask::' + password)
    with open(os.environ['GITHUB_ENV'], 'a') as environment:
        environment.write(f'ANDROID_KEYSTORE_PATH={target}\nANDROID_KEYSTORE_PASSWORD={password}\n')
    print('Persistent signing identity restored for this runner.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['init', 'restore'])
    arguments = parser.parse_args()
    if arguments.operation == 'init':
        initialize()
    else:
        restore()
