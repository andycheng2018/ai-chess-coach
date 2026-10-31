import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('verify_android_signature', Path(__file__).resolve().parents[1] / 'scripts/verify_android_signature.py')
signature = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signature)
DIGEST = 'ab' * 32


class AndroidSignatureTests(unittest.TestCase):
    def test_accepts_legacy_and_scheme_labeled_reports(self):
        for label in ['Signer #1', 'V2 Signer:', 'V3.1 Signer:']:
            signature.verify(f'Number of signers: 1\n{label} certificate SHA-256 digest: {DIGEST}\n', DIGEST)

    def test_rejects_wrong_or_additional_certificate(self):
        report = f'Number of signers: 1\nV2 Signer: certificate SHA-256 digest: {DIGEST}\n'
        with self.assertRaises(ValueError):
            signature.verify(report, 'cd' * 32)
        with self.assertRaises(ValueError):
            signature.verify(report + 'Signer #2 certificate SHA-256 digest: ' + 'cd' * 32 + '\n', DIGEST)

    def test_rejects_missing_cert_or_multiple_signers(self):
        for report in ['', 'Number of signers: 1\n', f'Number of signers: 2\nSigner #1 certificate SHA-256 digest: {DIGEST}\n']:
            with self.assertRaises(ValueError):
                signature.verify(report, DIGEST)

    def test_case_insensitive_digest_and_repeated_same_certificate(self):
        report = f'Number of signers: 1\nV2 Signer: certificate SHA-256 digest: {DIGEST.upper()}\nV3 Signer: certificate SHA-256 digest: {DIGEST}\n'
        signature.verify(report, DIGEST + '\n')
