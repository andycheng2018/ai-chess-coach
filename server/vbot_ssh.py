"""Strict SSH identity shared by every VBOT controller. No chess dependencies."""
from __future__ import annotations

import os
import subprocess

REMOTE_ROOT = "/userdata/vbot/chess-demo"


def ssh_argv(target: str, remote: str, *, host_key_alias=None) -> list[str]:
    """Never accepts an unknown or changed host key and never prompts."""
    return ["ssh", "-T", "-l", "vbot", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "-o", "ControlPath=none", "-o", "ForwardAgent=no",
            *(["-o", "HostKeyAlias=" + host_key_alias] if host_key_alias else []), target, remote]


def known_host_fingerprints(target: str) -> set[str]:
    if os.environ.get('CHESS_ANDROID') == '1':
        from android_backend import trusted_fingerprints
        return trusted_fingerprints(target)
    host = target.removeprefix("vbot@")
    found = subprocess.run(["ssh-keygen", "-F", host], capture_output=True, text=True, timeout=3, check=False)
    keys = "\n".join(line for line in found.stdout.splitlines() if line and not line.startswith("#"))
    if found.returncode != 0 or not keys:
        return set()
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=keys + "\n", capture_output=True,
                            text=True, timeout=3, check=False)
    return {line.split()[1] for line in result.stdout.splitlines()
            if len(line.split()) > 1 and line.split()[1].startswith("SHA256:")}
