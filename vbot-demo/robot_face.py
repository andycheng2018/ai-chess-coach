#!/usr/bin/env python3
"""Face-only session for the VBOT app. Default invocation is an offline preview.

This helper can only reach the display service, so a face cue has no route to a
head, body or navigation command. It shares robot_action.py's controller lock and
unresolved-action guard, which stops the app and a chess show from owning the dog
at once. Every command is single-use: identities are recorded before the display
call and survive reconnects and restarts. An uncertain outcome is never replayed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib.metadata
import json
import os
from pathlib import Path
import re
import select
import signal
import sys
import threading
import time
import uuid

SESSION = "/opt/vita/aorta/edu/edu_session.json5"
VERSIONS = {"aorta-sdk": "2026.9.23", "aorta-msgs": "2026.9.23", "vbot-edu-msgs": "2026.9.24", "flatbuffers": "25.12.19"}
PLAY_ROUTE = "/display_node/play_emotion"
SUPPORTED_ROUTE = "/display_node/get_supported_emotions"
PROTOCOL = 1
MIN_DURATION_MS, MAX_DURATION_MS = 500, 30000
MAX_COMMAND_TTL_MS = 120000
FRAME_LIMIT = 4096
SESSION_SECONDS, IDLE_SECONDS, MAX_FRAMES = 900, 180, 512
HEALTH_MAX_AGE_SECONDS = 3
CALL_TIMEOUT_MS = 3000
# Charging and diagnostic indications must not be simulated (SDK expression docs).
RESTRICTED_IDS = frozenset({66, 67, 80, 89, 90, 91, 92, 93, 95})
RESTRICTED_NAME = re.compile(r"charge|eye_test|test_ever", re.I)
COMMAND_ID = re.compile(r"[a-f0-9]{32}")
SESSION_ID = re.compile(r"[a-f0-9]{32}")


def emit(**fields):
    print(json.dumps(fields), flush=True)


def text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def is_int(value):
    return type(value) is int


def asset_ids(names):
    """Installed asset IDs. Restricted ones are dropped, so nothing can select them."""
    found = set()
    for name in names:
        match = re.match(r"(\d{3})_", name)
        if match and int(match[1]) not in RESTRICTED_IDS and not RESTRICTED_NAME.search(name):
            found.add(int(match[1]))
    return found


class CommandLedger:
    """Durable command identities and the lease high-water mark."""

    def __init__(self, directory: Path):
        self.requests = directory / "requests"
        self.lease_path = directory / "face-lease.json"

    def _path(self, command_id):
        return self.requests / f"face-{command_id}.json"

    def claim_lease(self, generation, session_id):
        """Refuse a controller whose lease predates one this dog has already seen."""
        try:
            current = json.loads(self.lease_path.read_text()).get("generation", 0)
        except (OSError, ValueError, AttributeError):
            current = 0
        if not is_int(current) or generation < current:
            return False
        self._replace(self.lease_path, {"generation": generation, "sessionId": session_id})
        return True

    def reserve(self, command_id, fields):
        """Exclusive create. The record exists BEFORE the display is called."""
        self.requests.mkdir(mode=0o700, exist_ok=True)
        try:
            with self._path(command_id).open("x") as record:
                json.dump({**fields, "outcome": "reserved"}, record)
            return None
        except FileExistsError:
            return self.read(command_id)

    def read(self, command_id):
        try:
            return json.loads(self._path(command_id).read_text())
        except (OSError, ValueError):
            return {"outcome": "unknown"}

    def finish(self, command_id, fields):
        self._replace(self._path(command_id), fields)

    @staticmethod
    def _replace(path, fields):
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(fields, file)
        os.replace(temporary, path)


def validate(command, *, session_id, lease, supported, now_ms):
    """Returns (code, reason) to refuse, or None. Checked on the dog, not just upstream."""
    if command.get("sessionId") != session_id or command.get("leaseGeneration") != lease:
        return "stale_lease", "This command belongs to an earlier connection."
    expires = command.get("expiresAtMs")
    if not is_int(expires) or expires <= now_ms:
        return "expired", "This command expired before it reached the dog."
    if expires - now_ms > MAX_COMMAND_TTL_MS:
        return "expired", "This command's expiry is too far ahead. Check the dog's clock."
    if command.get("op") == "face_release":
        return None
    asset, duration = command.get("assetId"), command.get("durationMs")
    if not is_int(asset) or asset not in supported:
        return "unsupported_face", "This dog doesn't offer that expression."
    if not is_int(duration) or not MIN_DURATION_MS <= duration <= MAX_DURATION_MS:
        return "invalid_duration", "Expression duration is out of bounds."
    return None


class HealthWatch:
    """Latest system and battery state. Ordinary faces must not cover a warning."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.system_at = self.battery_at = None
        self.system_ok = self.battery_ok = False

    def on_system(self, severity):
        with self.lock:
            self.system_at, self.system_ok = self.clock(), severity == 0

    def on_battery(self, alarm):
        with self.lock:
            self.battery_at, self.battery_ok = self.clock(), alarm == 0

    def wait_for_first_state(self, timeout, *, pause=time.sleep):
        """True once both topics have reported. Each face still checks their freshness and content."""
        deadline = self.clock() + timeout
        while True:
            with self.lock:
                if self.system_at is not None and self.battery_at is not None:
                    return True
            if self.clock() >= deadline:
                return False
            pause(0.05)

    def problem(self):
        now = self.clock()
        with self.lock:
            for seen in (self.system_at, self.battery_at):
                if seen is None or now - seen > HEALTH_MAX_AGE_SECONDS:
                    return "Fresh system and battery state aren't arriving, so the face wasn't changed."
            if not self.system_ok or not self.battery_ok:
                return "The dog is reporting a warning. Its indication stays on screen."
        return None


class FaceCore:
    """Protocol behavior with injected display, ledger and clock. No SDK imports."""

    def __init__(self, *, ledger, display, health, session_id, lease, supported, now_ms=lambda: int(time.time() * 1000)):
        self.ledger, self.display, self.health = ledger, display, health
        self.session_id, self.lease, self.supported, self.now_ms = session_id, lease, supported, now_ms
        self.showing = False
        self.uncertain = False

    def handle(self, command):
        """Handles one frame and returns its one result frame."""
        op, command_id = command.get("op"), command.get("commandId")
        if op not in {"face", "face_release"} or not isinstance(command_id, str) or not COMMAND_ID.fullmatch(command_id):
            raise ValueError("Invalid face frame")
        refused = validate(command, session_id=self.session_id, lease=self.lease, supported=self.supported, now_ms=self.now_ms())
        if refused is None and op == "face":
            problem = self.health.problem()
            if problem:
                refused = ("device_warning", problem)
        fields = {"commandId": command_id, "op": op, "assetId": command.get("assetId"), "durationMs": command.get("durationMs")}
        prior = self.ledger.reserve(command_id, fields)
        if prior is not None:
            # A repeat never reaches the display. A record with no outcome means
            # the earlier attempt's result was lost, which is unknown, not failed.
            outcome = prior.get("outcome")
            return {"event": "duplicate", "commandId": command_id,
                    "outcome": "unknown" if outcome == "reserved" else outcome, "code": prior.get("code"), "reason": prior.get("reason")}
        if refused:
            self.ledger.finish(command_id, {**fields, "outcome": "rejected", "code": refused[0], "reason": refused[1]})
            return {"event": "rejected", "commandId": command_id, "code": refused[0], "reason": refused[1]}
        try:
            if op == "face":
                status, error_code, message = self.display.play(command["assetId"], command["durationMs"], command_id)
            else:
                status, error_code, message = self.display.release(command_id)
        except Exception:
            self.uncertain = True
            self.ledger.finish(command_id, {**fields, "outcome": "unknown"})
            return {"event": "unknown", "commandId": command_id,
                    "reason": "The display service gave no answer. This command won't be retried."}
        if status != 0 or error_code != 0:
            self.ledger.finish(command_id, {**fields, "outcome": "rejected", "code": "display_refused", "reason": message})
            return {"event": "rejected", "commandId": command_id, "code": "display_refused",
                    "reason": "The display refused this expression."}
        self.showing = op == "face"
        outcome = "started" if op == "face" else "released"
        self.ledger.finish(command_id, {**fields, "outcome": outcome})
        # SUCCESS confirms that playback started, not that it visibly finished.
        return {"event": outcome, "commandId": command_id}

    def cleanup(self):
        """Hands the screen back on every exit path, without taking a command identity."""
        if not (self.showing or self.uncertain):
            return None
        try:
            status, error_code, _ = self.display.release(uuid.uuid4().hex)
            self.showing = self.uncertain = False
            return "released" if status == 0 and error_code == 0 else "failed"
        except Exception:
            return "failed"


class Display:
    """The only service routes this helper can call."""

    def __init__(self, node, sdk, schema, response_type):
        self.node, self.sdk, self.schema, self.response_type = node, sdk, schema, response_type

    def _call(self, target_state, mode, duration_ms, request_id):
        schema = self.schema

        def fill(builder, header):
            identifier = builder.CreateString(request_id)
            schema.PlayEmotionRequestStart(builder)
            schema.PlayEmotionRequestAddAortaHeader(builder, header)
            schema.PlayEmotionRequestAddTargetState(builder, target_state)
            schema.PlayEmotionRequestAddReqId(builder, identifier)
            schema.PlayEmotionRequestAddPreCheck(builder, False)
            schema.PlayEmotionRequestAddMode(builder, mode)
            schema.PlayEmotionRequestAddDurationMs(builder, duration_ms)
            return schema.PlayEmotionRequestEnd(builder)
        options = self.sdk.ClientOptions(timeout_ms=CALL_TIMEOUT_MS, enforce_single_provider=True, allow_retry=False)
        with self.node.create_client_typed(PLAY_ROUTE, self.response_type.GetRootAs, request_schema_meta=schema, options=options) as client:
            response = client.call(fill).decode()
        return response.Status(), response.ErrorCode(), text(response.Message())[:300]

    def play(self, asset_id, duration_ms, request_id):
        return self._call(1, asset_id, duration_ms, request_id)

    def release(self, request_id):
        return self._call(0, 0, 0, request_id)


def supported_faces(node, sdk):
    import get_supported_emotions_schema_meta as schema
    from aorta.services.peripheral.GetSupportedEmotionsResponse import GetSupportedEmotionsResponse

    def fill(builder, header):
        schema.GetSupportedEmotionsRequestStart(builder)
        schema.GetSupportedEmotionsRequestAddAortaHeader(builder, header)
        return schema.GetSupportedEmotionsRequestEnd(builder)
    options = sdk.ClientOptions(timeout_ms=CALL_TIMEOUT_MS, enforce_single_provider=True, allow_retry=False)
    with node.create_client_typed(SUPPORTED_ROUTE, GetSupportedEmotionsResponse.GetRootAs, request_schema_meta=schema, options=options) as client:
        response = client.call(fill).decode()
    if response.Status() != 0:
        raise RuntimeError("The display did not list its expressions.")
    return [text(response.SupportedEmotions(i)) for i in range(min(response.SupportedEmotionsLength(), 512))]


def serve(core, stdin=sys.stdin, *, wait=select.select, clock=time.monotonic):
    """Runs frames until EOF, close, an idle timeout, or an uncertain result."""
    deadline = clock() + SESSION_SECONDS
    for _ in range(MAX_FRAMES):
        remaining = deadline - clock()
        if remaining <= 0 or not wait([stdin], [], [], min(IDLE_SECONDS, remaining))[0]:
            return 0
        line = stdin.readline(FRAME_LIMIT + 1)
        if not line:
            return 0
        if len(line) > FRAME_LIMIT or not line.endswith("\n"):
            raise ValueError("Invalid session frame")
        command = json.loads(line)
        if not isinstance(command, dict):
            raise ValueError("Invalid session frame")
        if command.get("op") == "close":
            return 0
        result = core.handle(command)
        emit(**result)
        if result["event"] == "unknown":
            return 1
    return 0


def run_session(args, directory):
    import fcntl
    os.environ["ZENOH_SESSION_CONFIG_URI"] = SESSION
    import aorta as sdk
    import play_emotion_schema_meta as play_schema
    from aorta.services.peripheral.PlayEmotionResponse import PlayEmotionResponse
    from bms.BmsState import BmsState
    from sm.SmStatus import SmStatus

    def refuse(code, reason):
        emit(event="session_refused", requestId=args.session_id, code=code, reason=reason)
        return 1
    with ExitStack() as resources:
        lock = resources.enter_context((directory / "controller.lock").open("a"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return refuse("busy", "Another controller, such as a chess reaction or show, owns the dog.")
        if (directory / "unresolved-action.json").exists():
            return refuse("unresolved_action", "An unresolved robot action needs onsite inspection first.")
        ledger = CommandLedger(directory)
        if not ledger.claim_lease(args.lease, args.session_id):
            return refuse("stale_lease", "A newer controller has already connected to this dog.")
        node = resources.enter_context(sdk.Node("edu_sdk"))
        health = HealthWatch()

        def on_system(payload, _context):
            message = SmStatus.GetRootAs(bytes(payload), 0)
            if message.Category() == 0:
                health.on_system(message.Severity())

        def on_battery(payload, _context):
            health.on_battery(BmsState.GetRootAs(bytes(payload), 0).Alarm())
        options = sdk.SubscriberOptions(receive_depth=16)
        resources.enter_context(node.create_subscriber("/system/sm_status", on_system, options=options))
        resources.enter_context(node.create_subscriber("/bms_state", on_battery, options=options))
        names = supported_faces(node, sdk)
        supported = asset_ids(names)
        # These topics publish about once a second. Ready means a first face can be judged.
        if not health.wait_for_first_state(HEALTH_MAX_AGE_SECONDS):
            return refuse("backend_unavailable", "The dog isn't reporting its system and battery state yet. Try connecting again.")
        core = FaceCore(ledger=ledger, display=Display(node, sdk, play_schema, PlayEmotionResponse), health=health,
                        session_id=args.session_id, lease=args.lease, supported=supported)
        emit(event="session_ready", requestId=args.session_id, protocol=PROTOCOL, faceOnly=True,
             supportedFaces=[name for name in names if re.match(r"\d{3}_", name) and int(name[:3]) in supported])
        try:
            return serve(core)
        finally:
            emit(event="session_closed", requestId=args.session_id, cleanup=core.cleanup())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Face-only session over stdin")
    parser.add_argument("--session-id", default=uuid.uuid4().hex)
    parser.add_argument("--lease", type=int, default=0)
    args = parser.parse_args(argv)
    if not SESSION_ID.fullmatch(args.session_id):
        parser.error("session-id must be a lowercase 32-character hex string")
    if not args.serve:
        emit(event="preview", execute=False, routes=[PLAY_ROUTE, SUPPORTED_ROUTE], protocol=PROTOCOL)
        return 0
    if args.lease < 1:
        parser.error("--serve requires a positive --lease")
    if not os.access(SESSION, os.R_OK):
        raise RuntimeError("The documented EDU session file is unavailable.")
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"Install the documented SDK pairing: {name}=={version}")

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    return run_session(args, Path(__file__).resolve().parent)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        # Never expose SDK configuration or arbitrary provider messages.
        emit(event="error", error=type(error).__name__, message="The face session failed. Check the SDK setup on the dog.")
        raise SystemExit(1)
