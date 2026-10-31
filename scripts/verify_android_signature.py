#!/usr/bin/env python3
"""Check certificate continuity after apksigner has verified the APK signature."""
import argparse
from pathlib import Path
import re


def verify(report, expected):
    expected = expected.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Expected certificate digest must contain 64 hexadecimal characters.')
    if re.findall(r'^Number of signers:\s*(\d+)\s*$', report, re.MULTILINE) != ['1']:
        raise ValueError('Exactly one APK signer is required.')
    # Older tools print "Signer #1 certificate ..."; newer tools print
    # "V2 Signer: certificate ..." (possibly once per verified scheme).
    certificates = re.findall(r'^[^\n]*certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\s*$', report, re.MULTILINE)
    if not certificates or {digest.lower() for digest in certificates} != {expected}:
        raise ValueError('APK signing certificate does not match the permanent release identity.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('expected', type=Path)
    arguments = parser.parse_args()
    verify(arguments.report.read_text(), arguments.expected.read_text())
    print('Permanent Android signing certificate verified.')
