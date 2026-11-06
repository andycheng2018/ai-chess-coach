#!/usr/bin/env python3
"""Face and motion session for VBOT Studio. Default invocation is an offline preview.

One process owns the dog's controller lock, so a show can mix expressions with
head and body presets without handing the dog between helpers. Cues are strictly
serial: a face never overlaps a running preset, because presets drive the display
themselves (see the vendor control-paths guide, "Do not mix control owners"). Before
any preset starts, a face this session put on screen is released first, and a
failed release refuses the motion.

Motion goes through robot_action.py's guarded path unchanged: fresh readiness before
every cue, the static probe where required, durable request records, the
unresolved-action lock, terminal-result and postflight checks. This file adds no
scheduler and sends nothing the one-shot helper could not send. Motion needs both
--motion and --confirm-motion, which the operator gives after the onsite checks.
Every command identity is recorded before it acts and is never replayed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import pwd
import re
import select
import signal
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import robot_action as action  # noqa: E402
import robot_face as face  # noqa: E402

PROTOCOL = 2
MOTION_REPLY_SECONDS = 150
RESCAN_SECONDS = 30


def emit(**fields):
    print(json.dumps(fields), flush=True)


def validate_motion(command, *, session_id, lease, presets, now_ms):
    """Returns (code, reason) to refuse, or None. Checked on the dog, not just upstream."""
    if command.get("sessionId") != session_id or command.get("leaseGeneration") != lease:
        return "stale_lease", "This command belongs to an earlier connection."
    expires = command.get("expiresAtMs")
    if not face.is_int(expires) or expires <= now_ms:
        return "expired", "This command expired before it reached the dog."
    if expires - now_ms > face.MAX_COMMAND_TTL_MS:
        return "expired", "This command's expiry is too far ahead. Check the dog's clock."
    if command.get("preset") not in presets:
        return "unsupported_preset", "That preset is not available to this session."
    return None


def classify(result):
    """Maps a guarded-path result to (event, fields). Only a clean terminal result continues a show."""
    if not isinstance(result, dict):
        return "unknown", {"reason": "The motion path gave no result."}
    if result.get("event") == "not_ready":
        # rescan_cue only returns this when no goal was submitted for this cue.
        return "rejected", {"code": result.get("code") or "not_ready",
                            "reason": result.get("reason") or "The dog was not ready, so nothing moved."}
    clean = (result.get("event") == "terminal" and result.get("status") == "SUCCEEDED"
             and result.get("errorCategory") == 0 and result.get("readyForNext") is True
             and not result.get("stopRequested"))
    if clean:
        return "completed", {"durationMs": result.get("durationMs")}
    return "failed", {"status": result.get("status"), "reason": result.get("postflightReason")
                      or "The preset did not finish cleanly. Inspect the dog before another cue."}


class MotionCore:
    """Motion protocol with injected face core, ledger and runner. No SDK imports."""

    def __init__(self, *, ledger, face_core, run_cue, unresolved, session_id, lease, presets,
                 now_ms=lambda: int(time.time() * 1000)):
        self.ledger, self.face_core, self.run_cue, self.unresolved = ledger, face_core, run_cue, unresolved
        self.session_id, self.lease, self.presets, self.now_ms = session_id, lease, presets, now_ms

    def handle(self, command, canceled):
        """Returns (result frame, keep_going). Anything but a clean completion ends the session."""
        command_id = command.get("commandId")
        if not isinstance(command_id, str) or not face.COMMAND_ID.fullmatch(command_id):
            raise ValueError("Invalid motion frame")
        refused = validate_motion(command, session_id=self.session_id, lease=self.lease,
                                  presets=self.presets, now_ms=self.now_ms())
        if refused is None and self.unresolved():
            refused = ("unresolved_action", "An unresolved robot action needs onsite inspection first.")
        fields = {"commandId": command_id, "op": "motion", "preset": command.get("preset")}
        prior = self.ledger.reserve(command_id, fields)
        if prior is not None:
            outcome = prior.get("outcome")
            return ({"event": "duplicate", "commandId": command_id,
                     "outcome": "unknown" if outcome == "reserved" else outcome,
                     "code": prior.get("code"), "reason": prior.get("reason")}, True)
        if refused:
            self.ledger.finish(command_id, {**fields, "outcome": "rejected", "code": refused[0], "reason": refused[1]})
            return {"event": "rejected", "commandId": command_id, "code": refused[0], "reason": refused[1]}, True
        # The preset owns the display while it runs. Hand the screen back first.
        if self.face_core.cleanup() == "failed":
            reason = "The face wasn't released, so the preset was not started."
            self.ledger.finish(command_id, {**fields, "outcome": "rejected", "code": "display_not_released", "reason": reason})
            return {"event": "rejected", "commandId": command_id, "code": "display_not_released", "reason": reason}, True
        try:
            result = self.run_cue(command["preset"], command_id, canceled)
        except Exception:
            self.ledger.finish(command_id, {**fields, "outcome": "unknown"})
            return {"event": "unknown", "commandId": command_id,
                    "reason": "The motion path failed mid-cue. The outcome is unknown and won't be retried."}, False
        event, extra = classify(result)
        self.ledger.finish(command_id, {**fields, "outcome": event, **{k: v for k, v in extra.items() if v is not None}})
        return {"event": event, "commandId": command_id, **extra}, event in {"completed", "rejected"}


def serve(face_core, motion_core, stdin=sys.stdin, *, wait=select.select, clock=time.monotonic):
    """Runs frames until EOF, close, an idle timeout, or a motion result that isn't clean."""
    deadline = clock() + face.SESSION_SECONDS

    def canceled_for(command_id):
        def canceled():
            if not wait([stdin], [], [], 0)[0]:
                return False
            frame = stdin.readline(face.FRAME_LIMIT + 1)
            if not frame:
                return True
            if len(frame) > face.FRAME_LIMIT or not frame.endswith("\n"):
                raise ValueError("Invalid cancellation frame")
            value = json.loads(frame)
            if isinstance(value, dict) and (value.get("op") == "close"
                                            or (value.get("op") == "cancel" and value.get("commandId") == command_id)):
                return True
            raise ValueError("Only cancellation may interrupt a pending cue; pipelining is forbidden")
        return canceled
    for _ in range(face.MAX_FRAMES):
        remaining = deadline - clock()
        if remaining <= 0 or not wait([stdin], [], [], min(face.IDLE_SECONDS, remaining))[0]:
            return 0
        line = stdin.readline(face.FRAME_LIMIT + 1)
        if not line:
            return 0
        if len(line) > face.FRAME_LIMIT or not line.endswith("\n"):
            raise ValueError("Invalid session frame")
        command = json.loads(line)
        if not isinstance(command, dict):
            raise ValueError("Invalid session frame")
        op = command.get("op")
        if op == "close":
            return 0
        if op == "motion":
            if motion_core is None:
                emit(event="rejected", commandId=command.get("commandId"), code="motion_off",
                     reason="Motion wasn't enabled for this session.")
                continue
            result, keep_going = motion_core.handle(command, canceled_for(command.get("commandId")))
            emit(**result)
            if not keep_going:
                return 1
            continue
        emit(**face_core.handle(command))
    return 0


def run_session(args, directory):
    import fcntl
    os.environ["ZENOH_SESSION_CONFIG_URI"] = face.SESSION
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
        ledger = face.CommandLedger(directory)
        if not ledger.claim_lease(args.lease, args.session_id):
            return refuse("stale_lease", "A newer controller has already connected to this dog.")
        node = resources.enter_context(sdk.Node("edu_sdk"))
        health = face.HealthWatch()

        def on_system(payload, _context):
            message = SmStatus.GetRootAs(bytes(payload), 0)
            if message.Category() == 0:
                health.on_system(message.Severity())

        def on_battery(payload, _context):
            health.on_battery(BmsState.GetRootAs(bytes(payload), 0).Alarm())
        options = sdk.SubscriberOptions(receive_depth=16)
        resources.enter_context(node.create_subscriber("/system/sm_status", on_system, options=options))
        resources.enter_context(node.create_subscriber("/bms_state", on_battery, options=options))
        names = face.supported_faces(node, sdk)
        supported = face.asset_ids(names)
        if not health.wait_for_first_state(face.HEALTH_MAX_AGE_SECONDS):
            return refuse("backend_unavailable", "The dog isn't reporting its system and battery state yet. Try connecting again.")
        face_core = face.FaceCore(ledger=ledger, display=face.Display(node, sdk, play_schema, PlayEmotionResponse),
                                  health=health, session_id=args.session_id, lease=args.lease, supported=supported)
        motion_core = build_motion(args, directory, resources, node, sdk, ledger, face_core) if args.motion else None
        emit(event="session_ready", requestId=args.session_id, protocol=PROTOCOL, faceOnly=False,
             motion=motion_core is not None,
             motionPresets=list(action.PRESETS) if motion_core is not None else [],
             supportedFaces=[name for name in names if re.match(r"\d{3}_", name) and int(name[:3]) in supported])
        try:
            return serve(face_core, motion_core)
        finally:
            emit(event="session_closed", requestId=args.session_id, cleanup=face_core.cleanup())


def build_motion(args, directory, resources, node, sdk, ledger, face_core):
    """Wires the guarded motion path. This mirrors robot_action.py's session cue handling."""
    from aorta.action.rcp.ExecuteTaskResult import ExecuteTaskResultT
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.action.rcp.ExecuteTaskFeedbackData import ExecuteTaskFeedbackDataT
    codec = sdk.FlatbuffersActionCodec(goal=ExecuteTaskGoalT, result=ExecuteTaskResultT, feedback=ExecuteTaskFeedbackDataT)
    client = resources.enter_context(node.create_action_client(
        "/rcp/execute_task", codec, options=sdk.ActionClientOptions(control_timeout_ms=3000, info_timeout_ms=3000)))

    def provider_ready():
        info = client.info()
        if info is None or not info.supports_cancel or info.schema_hash_hex != action.SCHEMA_HASH:
            raise RuntimeError("A cancellable RCP provider with the exact client schema is required.")
    provider_ready()
    live = resources.enter_context(action.LiveReadiness(node, sdk, action.readiness_topics()))

    def run_cue(preset, logical_id, canceled):
        # Reserve the logical identity before ANY probe or movement.
        requests = directory / "requests"
        requests.mkdir(mode=0o700, exist_ok=True)
        logical_path = requests / ("logical-" + logical_id + ".json")
        logical = {"requestId": logical_id, "preset": preset, "attemptIds": [], "probeIds": []}
        with logical_path.open("x") as record:
            json.dump(logical, record)

        def static_check():
            provider_ready()
            probe_id = uuid.uuid4().hex
            logical["probeIds"].append(probe_id)
            probe = argparse.Namespace(request_id=probe_id, preset="safety/is_robot_static", logical_request_id=logical_id)
            result = action.execute_preset(probe, node, sdk, client, codec, ExecuteTaskResultT, live.check,
                                           goal_factory=lambda _: action.make_static_probe(probe_id), publish=False, action_timeout=3)
            if result and result["status"] == "SUCCEEDED" and result["errorCategory"] == 0:
                return {"ready": result["readyForNext"], "code": "ready" if result["readyForNext"] else "probe_postflight",
                        "reason": result.get("postflightReason")}
            if result is None:
                current = live.check(timeout=1, detailed=True)
                return current if not current["ready"] else {"ready": False, "code": "not_static",
                        "reason": "Static probe was not submitted; rescanning before any movement."}
            if action.precondition_refusal(result, "chess-static-probe-" + probe_id):
                return {"ready": False, "code": "not_static", "reason": "Waiting for the provider to confirm is_robot_static."}
            return {"ready": False, "code": "probe_failed", "reason": "The non-motion static-condition probe failed. Inspect the saved probe result."}

        def perform():
            provider_ready()
            attempt_id = uuid.uuid4().hex
            logical["attemptIds"].append(attempt_id)
            cue = argparse.Namespace(request_id=attempt_id, preset=preset, logical_request_id=logical_id)
            return action.execute_preset(cue, node, sdk, client, codec, ExecuteTaskResultT, live.check, publish=False)
        result = action.rescan_cue(preset, live.check, static_check, perform, canceled,
                                   lambda frame: emit(event="rescan", commandId=logical_id, **frame), timeout=RESCAN_SECONDS)
        logical["result"] = result
        temporary = logical_path.with_suffix(".complete.tmp")
        with temporary.open("x") as record:
            json.dump(logical, record)
        os.replace(temporary, logical_path)
        return result
    return MotionCore(ledger=ledger, face_core=face_core, run_cue=run_cue,
                      unresolved=lambda: (directory / "unresolved-action.json").exists(),
                      session_id=args.session_id, lease=args.lease, presets=frozenset(action.PRESETS))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Face and optional motion session over stdin")
    parser.add_argument("--motion", action="store_true", help="Also accept guarded preset cues")
    parser.add_argument("--confirm-motion", action="store_true", help="Required with --motion, after onsite checks")
    parser.add_argument("--session-id", default=uuid.uuid4().hex)
    parser.add_argument("--lease", type=int, default=0)
    args = parser.parse_args(argv)
    if not face.SESSION_ID.fullmatch(args.session_id):
        parser.error("session-id must be a lowercase 32-character hex string")
    if args.motion and not args.confirm_motion:
        parser.error("--motion also requires --confirm-motion after onsite checks")
    if not args.serve:
        emit(event="preview", execute=False, motion=args.motion, protocol=PROTOCOL,
             routes=[face.PLAY_ROUTE, face.SUPPORTED_ROUTE] + (["/rcp/execute_task"] if args.motion else []))
        return 0
    if args.lease < 1:
        parser.error("--serve requires a positive --lease")
    if args.motion and (pwd.getpwuid(os.geteuid()).pw_name != "vbot" or platform.system() != "Linux"
                        or platform.machine() not in {"aarch64", "arm64"}):
        raise RuntimeError("Motion runs only on the ARM64 robot as vbot. Use the default offline preview on a Mac.")
    if not os.access(face.SESSION, os.R_OK):
        raise RuntimeError("The documented EDU session file is unavailable.")
    for name, version in face.VERSIONS.items():
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
        emit(event="error", error=type(error).__name__, message="The studio session failed. Check the SDK setup on the dog.")
        raise SystemExit(1)
