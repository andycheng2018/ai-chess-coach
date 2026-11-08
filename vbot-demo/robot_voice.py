#!/usr/bin/env python3
"""Qwen voice mode session. Started and owned by the server over SSH.

While this runs the dog's built-in chat is off. Transcripts heard after the wake word
go up as JSON lines on stdout, and replies come back on stdin to be spoken. Chat is put
back the way it was on every way out: a close frame, a lost link, a signal or an error.

The only things this can do are read speech events, switch chat, and speak. It has no
route to a head, body or navigation command.
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import robot_speak  # noqa: E402

SESSION = "/opt/vita/aorta/edu/edu_session.json5"
AORTA = "/opt/vita/aorta/bin/aorta"
LISTEN_SECONDS = 20
ECHO_SECONDS = 25
ECHO_SIMILARITY = 0.72
AFTER_SPEECH_SECONDS = 0.6
MAX_SPEAKING_SECONDS = 60
ALIVE_SECONDS = 15
SILENT_SERVER_SECONDS = 60
FRAME_LIMIT = 4096
REQUEST_SET_CHAT, REQUEST_QUERY_CHAT = 4, 2


class VoiceGate:
    """Decides which final transcripts count. Pure, so it can be tested from real logs."""

    def __init__(self):
        self.window_until = float("-inf")
        self.speaking_since = None
        self.quiet_until = float("-inf")
        self.own_speech_pending = False
        self.said = []

    def on_wake(self, now):
        self.window_until = now + LISTEN_SECONDS

    def on_speech_start(self, now):
        self.speaking_since = now

    def on_speech_end(self, now):
        self.speaking_since = None
        self.quiet_until = now + AFTER_SPEECH_SECONDS
        if self.own_speech_pending:
            # Lets someone answer a clarifying question without saying the wake word again.
            self.own_speech_pending = False
            self.window_until = now + LISTEN_SECONDS

    def before_speaking(self, text, now):
        self.own_speech_pending = True
        self.said = [(when, words) for when, words in self.said if now - when <= ECHO_SECONDS] + [(now, self._plain(text))]

    def decide(self, text, now):
        if self.speaking_since is not None and now - self.speaking_since > MAX_SPEAKING_SECONDS:
            self.speaking_since = None  # A lost end-of-speech event must not deafen the dog.
        if now > self.window_until:
            return "no_wake"
        if self.speaking_since is not None or now < self.quiet_until:
            return "dog_speaking"
        plain = self._plain(text)
        if not plain:
            return "empty"
        for when, words in self.said:
            if now - when <= ECHO_SECONDS and (plain in words or difflib.SequenceMatcher(None, plain, words).ratio() >= ECHO_SIMILARITY):
                return "echo"
        return "accept"

    @staticmethod
    def _plain(text):
        return re.sub(r"[^\w]+", " ", text or "").strip().lower()


def speech_control(request_type, enable):
    """The SDK on the dog has no bindings for this service, so use the vendor's own CLI."""
    payload = json.dumps({"request_type": request_type, "enable": enable, "mode": 0})
    done = subprocess.run([AORTA, "service", "call", "/speech_control", payload, "-t", "5"],
                          capture_output=True, text=True, timeout=12, check=False)
    state = re.search(r"chat_function_status:\s*(true|false)", done.stdout)
    if done.returncode != 0 or "status: SUCCESS" not in done.stdout or not state:
        raise RuntimeError("The dog's speech settings did not respond.")
    return state.group(1) == "true"


class Chat:
    """Switches chat off once and always restores it. A marker survives a hard crash."""

    def __init__(self, directory):
        self.marker = directory / "voice-original.json"
        self.original = None

    def turn_off(self):
        try:
            self.original = bool(json.loads(self.marker.read_text())["chat"])  # Left by a crashed session.
        except (OSError, ValueError, KeyError, TypeError):
            self.original = speech_control(REQUEST_QUERY_CHAT, False)
            self.marker.write_text(json.dumps({"chat": self.original}))
        if speech_control(REQUEST_SET_CHAT, False):
            raise RuntimeError("The dog would not turn its chat off.")

    def restore(self):
        if self.original is None:
            return True
        try:
            restored = speech_control(REQUEST_SET_CHAT, self.original) == self.original
        except Exception:
            return False
        if restored:
            self.marker.unlink(missing_ok=True)
            self.original = None
        return restored


class Session:
    def __init__(self, directory, session_id):
        self.directory, self.session_id = directory, session_id
        self.gate = VoiceGate()
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def emit(self, **fields):
        try:
            print(json.dumps(fields, ensure_ascii=False), flush=True)
        except (BrokenPipeError, ValueError):
            self.stop.set()  # The server is gone; the main loop restores chat and exits.

    def on_voice(self, payload, _context):
        from aorta.voice.AsrEvent import AsrEvent
        from aorta.voice.VoiceEvent import VoiceEvent
        from aorta.voice.VoiceEventPayload import VoiceEventPayload as Kind
        event = VoiceEvent.GetRootAs(bytes(payload), 0)
        kind, table, now = event.PayloadType(), event.Payload(), time.monotonic()
        with self.lock:
            if kind == Kind.WakeUpEvent:
                self.gate.on_wake(now)
                self.emit(event="wake")
            elif kind == Kind.TtsStartEvent:
                self.gate.on_speech_start(now)
            elif kind == Kind.TtsPlaybackCompleteEvent:
                self.gate.on_speech_end(now)
            elif kind == Kind.AsrEvent and table:
                asr = AsrEvent()
                asr.Init(table.Bytes, table.Pos)
                if asr.IsFinal():
                    words = robot_speak.text_of(asr.Text())
                    decision = self.gate.decide(words, now)
                    if decision == "accept":
                        # A recognizer rejection is only a hint. The server decides what it meant.
                        self.emit(event="heard", text=words[:600], rejected=bool(asr.IsReject()))

    def say(self, node, command):
        text = robot_speak.clean(str(command.get("text") or ""))
        reference = str(command.get("id") or "")[:64]
        if not text:
            return self.emit(event="said", id=reference, ok=False, reason="empty")
        with self.lock:
            self.gate.before_speaking(text, time.monotonic())
        try:
            status, error_code, message = robot_speak.speak(text, False, uuid.uuid4().hex, node=node)
            self.emit(event="said", id=reference, ok=status == 0 and error_code == 0, reason=message)
        except Exception as error:  # One failed reply must not end the session.
            with self.lock:
                self.gate.own_speech_pending = False
            self.emit(event="said", id=reference, ok=False, reason=f"The dog could not speak ({type(error).__name__}).")

    def serve(self, node, stdin_fd):
        """Reads the fd directly: buffered text IO would hide frames that arrive together."""
        heard_from_server = time.monotonic()
        next_alive = heard_from_server + ALIVE_SECONDS
        pending = b""
        while not self.stop.is_set():
            now = time.monotonic()
            if now - heard_from_server > SILENT_SERVER_SECONDS:
                return "server_silent"
            if now >= next_alive:
                self.emit(event="alive")
                next_alive = now + ALIVE_SECONDS
            if not select.select([stdin_fd], [], [], 0.5)[0]:
                continue
            chunk = os.read(stdin_fd, FRAME_LIMIT)
            if not chunk:
                return "link_closed"
            heard_from_server = time.monotonic()
            pending += chunk
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                command = json.loads(raw)
                if not isinstance(command, dict) or command.get("op") == "close":
                    return "closed"
                if command.get("op") == "say":
                    self.say(node, command)
            if len(pending) > FRAME_LIMIT:
                return "bad_frame"
        return "link_closed"


def run(directory, session_id):
    os.environ["ZENOH_SESSION_CONFIG_URI"] = SESSION
    import aorta as sdk
    session = Session(directory, session_id)
    with (directory / "voice.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            session.emit(event="refused", reason="Another voice session is already running on this dog.")
            return 1
        chat = Chat(directory)
        reason, restored = "error", False
        try:
            with sdk.Node("edu_sdk") as node:
                options = sdk.SubscriberOptions(receive_depth=32)
                with node.create_subscriber("/voice/event", session.on_voice, options=options):
                    chat.turn_off()
                    session.emit(event="ready", requestId=session_id)
                    reason = session.serve(node, sys.stdin.fileno())
        finally:
            restored = chat.restore()
            session.emit(event="closed", reason=reason, chatRestored=restored)
    return 0 if restored else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Run a session over stdin and stdout")
    args = parser.parse_args(argv)
    if not args.serve:
        print(json.dumps({"event": "preview", "execute": False}), flush=True)
        return 0
    for name, version in robot_speak.VERSIONS.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"Install the documented SDK pairing: {name}=={version}")

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    return run(Path(__file__).resolve().parent, uuid.uuid4().hex)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        try:
            print(json.dumps({"event": "error", "error": type(error).__name__, "message": str(error)[:200]}), flush=True)
        except (BrokenPipeError, ValueError):
            pass
        raise SystemExit(1)
