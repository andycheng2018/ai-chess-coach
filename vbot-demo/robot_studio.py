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
import math
import signal
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import robot_action as action  # noqa: E402
import robot_face as face  # noqa: E402

PROTOCOL = 4
MOTION_REPLY_SECONDS = 150
RESCAN_SECONDS = 30

# Bounded basic moves, sent as one BaseActionCommand each. The dog enforces these amounts;
# the app and controller only name them. They are deliberately small and ours, not vendor
# limits: the docs publish none. Distances are metres, turns are signed radians.
# The docs leave the sign of ROTATE to the provider. LEFT_TURN_SIGN = +1 (counterclockwise positive) was
# confirmed onsite on Nov 5 2026: the left 30 degree turn went counterclockwise on this dog.
LEFT_TURN_SIGN = 1.0
MOVES = {
    "step_forward": ("MOVE_FORWARD", 0.25),
    "step_back": ("MOVE_BACKWARD", 0.25),
    "step_left": ("MOVE_LEFT", 0.2),
    "step_right": ("MOVE_RIGHT", 0.2),
    "turn_left_30": ("ROTATE", LEFT_TURN_SIGN * 0.5236),
    "turn_right_30": ("ROTATE", -LEFT_TURN_SIGN * 0.5236),
    "turn_left_90": ("ROTATE", LEFT_TURN_SIGN * 1.5708),
    "turn_right_90": ("ROTATE", -LEFT_TURN_SIGN * 1.5708),
    # Small turns for press-and-hold. The app repeats one of these only while a button is held, one command
    # at a time, so the most a release can overshoot is the single turn already in flight.
    "turn_left_10": ("ROTATE", LEFT_TURN_SIGN * 0.1745),
    "turn_right_10": ("ROTATE", -LEFT_TURN_SIGN * 0.1745),
}
# Steps go through the vendor's own parameterized preset, not a graph of ours. A typed MOVE_* command
# was accepted and reported SUCCEEDED on Nov 5 2026 while the dog did not move (four attempts), while the
# typed ROTATE did turn the dog. The preset owns the display, so a step can't carry a face.
STEP_TEMPLATE = "atom/move_param.json"
STEP_TASKS = {
    "step_forward": "base_action.MOVE_FORWARD",
    "step_back": "base_action.MOVE_BACKWARD",
    "step_left": "base_action.MOVE_LEFT",
    "step_right": "base_action.MOVE_RIGHT",
}
FACELESS_MOVES = frozenset(STEP_TASKS)
# The graph's move node is bounded, so a stuck move can't hold the dog.
MOVE_TIMEOUT_MS = 20000


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


def validate_move(command, *, session_id, lease, moves, supported, now_ms):
    """Returns (code, reason) to refuse, or None. The face rules match robot_face.validate."""
    stale = validate_motion({**command, "preset": "move"}, session_id=session_id, lease=lease,
                            presets=frozenset({"move"}), now_ms=now_ms)
    if stale:
        return stale
    if command.get("move") not in moves:
        return "unsupported_move", "That move is not available to this session."
    face_id = command.get("faceId")
    if face_id is not None and command.get("move") in FACELESS_MOVES:
        return "face_not_supported", "A step runs the vendor's own preset, which controls the screen. Turns can carry a face."
    if face_id is not None:
        if not face.is_int(face_id) or face_id not in supported or face_id in face.RESTRICTED_IDS:
            return "unsupported_face", "That face can't be shown during a move."
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


def make_move_goal(name, face_id, request_id):
    """One bounded move as a custom graph: an optional face held in the background, one finite
    BaseActionCommand, and a barrier that releases the face. The face is a DAEMON node, so the
    move doesn't wait on it, and the display is its own resource, so nothing here competes with a
    preset's display nodes. Built before any record is written, so a bad build leaves no lock."""
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.services.rcp.BarrierCommand import BarrierCommandT
    from aorta.services.rcp.BaseActionCommand import BaseActionCommandT
    from aorta.services.rcp.BaseActionMethod import BaseActionMethod
    from aorta.services.rcp.DagInput import DagInput
    from aorta.services.rcp.DagNode import DagNodeT
    from aorta.services.rcp.DagSpec import DagSpecT
    from aorta.services.rcp.DisplayLayer import DisplayLayer
    from aorta.services.rcp.EmotionCommand import EmotionCommandT
    from aorta.services.rcp.EmotionMethod import EmotionMethod
    from aorta.services.rcp.NodeCommand import NodeCommand
    from aorta.services.rcp.NodeLifecycle import NodeLifecycle
    from aorta.services.rcp.ResourceId import ResourceId
    if name in STEP_TASKS:
        if face_id is not None:
            raise ValueError("A step can't carry a face.")
        return make_step_goal(name, request_id)
    method_name, amount = MOVES[name]
    method = getattr(BaseActionMethod, method_name)
    command = BaseActionCommandT(method=method, angleRad=amount if method_name == "ROTATE" else 0.0,
                                 distanceM=0.0 if method_name == "ROTATE" else amount)
    nodes, resources, after = [], [ResourceId.LEGS], []
    if face_id is not None:
        resources.append(ResourceId.SCREEN)
        after = ["face"]
        # emotion_id 0 can't be selected by id (it overrides the alias only when nonzero), so use BLINK_ONCE.
        nodes.append(DagNodeT(id="face", dependencies=[], lifecycle=NodeLifecycle.DAEMON,
                              commandType=NodeCommand.EmotionCommand,
                              command=EmotionCommandT(method=EmotionMethod.BLINK_ONCE if face_id == 0 else EmotionMethod.UNSPECIFIED,
                                                      emotionId=face_id, layer=DisplayLayer.INTERACTION)))
    nodes.append(DagNodeT(id="move", dependencies=after, executionTimeoutMs=MOVE_TIMEOUT_MS,
                          lifecycle=NodeLifecycle.NORMAL, commandType=NodeCommand.BaseActionCommand, command=command))
    if face_id is not None:
        nodes.append(DagNodeT(id="release", dependencies=["move"], lifecycle=NodeLifecycle.BARRIER,
                              commandType=NodeCommand.BarrierCommand, command=BarrierCommandT()))
    return ExecuteTaskGoalT(source="vbot-studio-move", inputType=DagInput.DagSpec,
                            input=DagSpecT(taskId="studio-move-" + request_id, skipBatchPreCheck=False, requiresStatic=False,
                                           requiredResources=resources, optionalResources=[], nodes=nodes))


def make_step_goal(name, request_id):
    """One step as the vendor's documented atom/move_param.json template (a whole-goal preset)."""
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.services.rcp.DagInput import DagInput
    from aorta.services.rcp.DagPresetRef import DagPresetRefT
    from aorta.services.rcp.TemplateArg import TemplateArgT
    values = {"task_id": "studio-step-" + request_id, "base_action_task": STEP_TASKS[name],
              "distance_m": MOVES[name][1], "tts": "confirm"}
    return ExecuteTaskGoalT(source="vbot-studio-step", inputType=DagInput.DagPresetRef,
                            input=DagPresetRefT(relativePath=STEP_TEMPLATE,
                                                templateArgs=[TemplateArgT(name=key, valueJson=json.dumps(value))
                                                              for key, value in values.items()]))


# --- hold-to-drive ---------------------------------------------------------------------------------
# A held button streams velocity frames; THIS process publishes them to the dog and owns the stop. The vendor
# docs say a direct publisher doesn't inherit the ROS bridge's timeout protection and that no zero-on-dead-man
# is configured, so the dead-man lives here: the command is published only while fresh frames keep arriving, and
# every way a drive can end (release, stale frames, the per-press cap, a violation, EOF, SIGTERM, an error)
# publishes a burst of zeros. These caps and times are ours. The docs give no units or limits for Twist;
# m/s and rad/s are ASSUMED, which is why the first test is slow and supervised.
VELOCITY_TOPIC = "/locomotion/velocity_command"
DRIVE_MAX = {"vx": 0.15, "vy": 0.10, "wz": 0.40}
DRIVE_TICK_S = 0.05            # publish rate while a fresh command is held (20 Hz)
DRIVE_FRESH_S = 0.5            # a command older than this is stale: zero and end
DRIVE_FIRST_FRAME_S = 1.5      # grace after the start reply for the first frame to arrive
DRIVE_MAX_S = 8.0              # one press can drive at most this long; a fresh press continues
ZERO_BURST, ZERO_GAP_S = 5, 0.05
DRIVE_LIMITS = {**DRIVE_MAX, "freshMs": int(DRIVE_FRESH_S * 1000), "maxMs": int(DRIVE_MAX_S * 1000)}


def drive_violation(frame):
    """Returns a reason string if a drive frame must end the drive, else None. Refuses; never clamps."""
    for axis, cap in DRIVE_MAX.items():
        value = frame.get(axis)
        # bool is an int in Python, and NaN/inf compare falsely, so check both explicitly.
        if type(value) not in (int, float) or not math.isfinite(value):
            return f"{axis} is not a finite number"
        if abs(value) > cap:
            return f"{axis} is over the cap"
    return None


class DriveCore:
    """Hold-to-drive state machine. No SDK imports: `publish(vx, vy, wz)` is injected. Thread-safe."""

    def __init__(self, *, ledger, publish, ready, matched, unresolved_path, session_id, lease, emit,
                 clock=time.monotonic, sleep=time.sleep, now_ms=lambda: int(time.time() * 1000)):
        self.ledger, self.publish, self.ready, self.matched = ledger, publish, ready, matched
        self.path, self.session_id, self.lease, self.emit = Path(unresolved_path), session_id, lease, emit
        self.clock, self.sleep, self.now_ms = clock, sleep, now_ms
        self.lock = threading.Lock()
        self.active = False
        self.command_id = None
        self.command = (0.0, 0.0, 0.0)
        self.last_seq = -1
        self.last_frame = self.started = 0.0
        self.got_frame = False
        self.reason = None
        self.zeroed = True
        self.session_over = False   # set when an ending means the whole session must stop

    # -- start --------------------------------------------------------------------------------------
    def begin(self, command):
        """Validates and arms one drive. Returns the reply frame. Everything slow happens here, before publishing."""
        command_id = command.get("commandId")
        if not isinstance(command_id, str) or not face.COMMAND_ID.fullmatch(command_id):
            raise ValueError("Invalid drive frame")
        refused = validate_motion({**command, "preset": "drive"}, session_id=self.session_id, lease=self.lease,
                                  presets=frozenset({"drive"}), now_ms=self.now_ms())
        fields = {"commandId": command_id, "op": "drive_start"}
        prior = self.ledger.reserve(command_id, fields)
        if prior is not None:
            outcome = prior.get("outcome")
            return {"event": "duplicate", "commandId": command_id, "outcome": "unknown" if outcome == "reserved" else outcome}
        if refused is None and self.path.exists():
            refused = ("unresolved_action", "An unresolved robot action needs onsite inspection first.")
        if refused is None:
            state = self.ready()
            if not state.get("ready"):
                refused = (state.get("code") or "not_ready", state.get("reason") or "The dog is not ready to drive.")
        if refused is None and not self.matched():
            refused = ("no_consumer", "Nothing is listening for velocity commands on this dog, so nothing was started.")
        if refused is None:
            try:
                with self.path.open("x") as marker:
                    json.dump({"requestId": command_id, "kind": "drive"}, marker)
            except FileExistsError:
                refused = ("unresolved_action", "An unresolved robot action needs onsite inspection first.")
        if refused:
            self.ledger.finish(command_id, {**fields, "outcome": "rejected", "code": refused[0], "reason": refused[1]})
            return {"event": "rejected", "commandId": command_id, "code": refused[0], "reason": refused[1]}
        with self.lock:
            self.active, self.command_id, self.reason = True, command_id, None
            self.command, self.last_seq, self.got_frame, self.zeroed = (0.0, 0.0, 0.0), -1, False, False
            self.started = self.last_frame = self.clock()
        return {"event": "drive_started", "commandId": command_id, "limits": DRIVE_LIMITS}

    # -- input (main thread) ------------------------------------------------------------------------
    def ingest(self, line):
        """One input line while driving. Unknown or malformed input ends the drive: nothing is guessed."""
        try:
            frame = json.loads(line)
        except ValueError:
            return self.end("violation", "unreadable frame")
        if not isinstance(frame, dict):
            return self.end("violation", "frame is not an object")
        op = frame.get("op")
        if op == "drive_stop":
            stop_id = frame.get("commandId")
            if not isinstance(stop_id, str) or not face.COMMAND_ID.fullmatch(stop_id):
                return self.end("violation", "stop needs a command id", over=True)
            return self.end("stopped", None, stop_id=stop_id)
        if op == "close":
            return self.end("closed", None, over=True)
        if op != "drive":
            return self.end("violation", f"unexpected {op!r} frame during a drive", over=True)
        problem = drive_violation(frame)
        seq = frame.get("seq")
        if problem is None and (type(seq) is not int or seq < 0):
            problem = "seq is not a non-negative integer"
        if problem:
            return self.end("violation", problem, over=True)
        with self.lock:
            if not self.active or seq <= self.last_seq:
                return  # out of order or too late: ignored, never applied
            self.last_seq, self.command = seq, (float(frame["vx"]), float(frame["vy"]), float(frame["wz"]))
            self.last_frame, self.got_frame = self.clock(), True

    # -- watchdog + publisher (own thread in production) --------------------------------------------
    def tick(self):
        now = self.clock()
        with self.lock:
            if not self.active:
                return
            age = now - self.last_frame
            over = now - self.started > DRIVE_MAX_S
            stale = age > (DRIVE_FRESH_S if self.got_frame else DRIVE_FIRST_FRAME_S)
            command = self.command
        if over:
            return self.end("limit", None)
        if stale:
            return self.end("timeout", None)
        if self.got_frame:
            try:
                self.publish(*command)
            except Exception:
                self.end("error", "the velocity publisher failed", over=True)

    # -- every ending -------------------------------------------------------------------------------
    def end(self, reason, detail, *, stop_id=None, over=False):
        """Idempotent. Publishes a burst of zeros on every path, then clears the marker only if that succeeded."""
        with self.lock:
            if not self.active:
                return
            self.active, self.reason = False, reason
            command_id = self.command_id
        zeroed = True
        try:
            for index in range(ZERO_BURST):
                self.publish(0.0, 0.0, 0.0)
                if index < ZERO_BURST - 1:
                    self.sleep(ZERO_GAP_S)
        except Exception:
            zeroed = False
        self.zeroed = zeroed
        if zeroed:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        # A failed stop leaves the unresolved-action marker, so nothing else runs until someone inspects the dog.
        clean = zeroed and reason in {"stopped", "timeout", "limit", "closed"}
        self.session_over = over or not zeroed or reason in {"error", "violation", "eof", "interrupted"}
        self.ledger.finish(command_id, {"commandId": command_id, "op": "drive_start", "outcome": "completed" if clean else "failed",
                                        "reason": detail or reason, "zeroed": zeroed})
        self.emit(event="drive_stopped" if stop_id else "drive_ended", commandId=stop_id or command_id, startId=command_id,
                  reason=reason, detail=detail, zeroed=zeroed)


class FdLineReader:
    """Reads complete lines from a file descriptor without ever blocking on a half-delivered frame."""

    def __init__(self, fd, *, wait=select.select, read=os.read):
        self.fd, self.wait, self.read, self.buffer, self.eof = fd, wait, read, b"", False

    def poll(self, timeout):
        if not self.eof and self.wait([self.fd], [], [], timeout)[0]:
            data = self.read(self.fd, 4096)
            if data:
                self.buffer += data
            else:
                self.eof = True
        lines = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            lines.append(line.decode("utf-8", "replace"))
        if len(self.buffer) > face.FRAME_LIMIT:
            raise ValueError("Invalid drive frame")
        return lines, self.eof


def run_drive(core, reader, *, threaded=True):
    """Runs one drive to its end. The publisher/watchdog is its own thread, so a stalled read can't stop the zeros."""
    stop = threading.Event()
    pump = None
    if threaded:
        def loop():
            while not stop.is_set():
                core.tick()
                stop.wait(DRIVE_TICK_S)
        pump = threading.Thread(target=loop, daemon=True)
        pump.start()
    try:
        while core.active:
            lines, eof = reader.poll(DRIVE_TICK_S)
            for line in lines:
                core.ingest(line)
            if eof:
                core.end("eof", None, over=True)
            if not threaded:
                core.tick()
        if reader.buffer:
            raise ValueError("Unexpected input after a drive ended")
    finally:
        core.end("interrupted", None, over=True)  # no-op unless an exception left the drive running
        stop.set()
        if pump:
            pump.join(timeout=2)


class MotionCore:
    """Motion protocol with injected face core, ledger and runner. No SDK imports."""

    def __init__(self, *, ledger, face_core, run_cue, unresolved, session_id, lease, presets,
                 moves=frozenset(), now_ms=lambda: int(time.time() * 1000)):
        self.ledger, self.face_core, self.run_cue, self.unresolved = ledger, face_core, run_cue, unresolved
        self.session_id, self.lease, self.presets, self.now_ms = session_id, lease, presets, now_ms
        self.moves = frozenset(moves)

    def handle(self, command, canceled):
        """Returns (result frame, keep_going). Anything but a clean completion ends the session."""
        command_id = command.get("commandId")
        if not isinstance(command_id, str) or not face.COMMAND_ID.fullmatch(command_id):
            raise ValueError("Invalid motion frame")
        is_move = command.get("op") == "move"
        if is_move:
            refused = validate_move(command, session_id=self.session_id, lease=self.lease, moves=self.moves,
                                    supported=self.face_core.supported, now_ms=self.now_ms())
            fields = {"commandId": command_id, "op": "move", "move": command.get("move"), "faceId": command.get("faceId")}
        else:
            refused = validate_motion(command, session_id=self.session_id, lease=self.lease,
                                      presets=self.presets, now_ms=self.now_ms())
            fields = {"commandId": command_id, "op": "motion", "preset": command.get("preset")}
        if refused is None and self.unresolved():
            refused = ("unresolved_action", "An unresolved robot action needs onsite inspection first.")
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
        face_id = command.get("faceId") if is_move else None
        if face_id is not None:
            # The move's own graph puts this face up and releases it. Until the display is seen
            # clean afterwards, treat it as possibly held, so every exit path hands the screen back.
            self.face_core.uncertain = True
        try:
            if is_move:
                result = self.run_cue("move/" + command["move"], command_id, canceled, (command["move"], face_id))
            else:
                result = self.run_cue(command["preset"], command_id, canceled)
        except Exception:
            self.ledger.finish(command_id, {**fields, "outcome": "unknown"})
            return {"event": "unknown", "commandId": command_id,
                    "reason": "The motion path failed mid-cue. The outcome is unknown and won't be retried."}, False
        event, extra = classify(result)
        if face_id is not None and self.face_core.cleanup() == "failed" and event == "completed":
            event, extra = "failed", {"status": None, "reason": "The move finished but the face wasn't released. Check the dog's screen."}
        self.ledger.finish(command_id, {**fields, "outcome": event, **{k: v for k, v in extra.items() if v is not None}})
        # Like robot_action.py's session, a readiness refusal disarms: the operator must inspect and re-arm.
        keep_going = event == "completed"
        return {"event": event, "commandId": command_id, **extra, **({} if keep_going else {"sessionEnded": True})}, keep_going


def serve(face_core, motion_core, stdin=sys.stdin, *, wait=select.select, clock=time.monotonic, drive_core=None, make_reader=None):
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
        if op == "drive_start":
            if drive_core is None:
                emit(event="rejected", commandId=command.get("commandId"), code="drive_off", reason="Driving wasn't enabled for this session.")
                continue
            reply = drive_core.begin(command)
            emit(**reply)
            if reply["event"] == "drive_started":
                run_drive(drive_core, make_reader())
                if drive_core.session_over:
                    return 1
            continue
        if op == "drive_stop":
            # Idempotent: the drive may already have ended on its own (a stale command or the press cap).
            if not isinstance(command.get("commandId"), str) or not face.COMMAND_ID.fullmatch(command["commandId"]):
                raise ValueError("Invalid drive frame")
            emit(event="drive_stopped", commandId=command.get("commandId"), reason="already-ended", zeroed=True)
            continue
        if op in {"motion", "move"}:
            if motion_core is None:
                emit(event="rejected", commandId=command.get("commandId"), code="motion_off",
                     reason="Motion wasn't enabled for this session.")
                continue
            result, keep_going = motion_core.handle(command, canceled_for(command.get("commandId")))
            emit(**result)
            if not keep_going:
                return 1
            continue
        result = face_core.handle(command)
        emit(**result)
        if result["event"] == "unknown":
            return 1  # robot_face.py ends the session on an uncertain display result, and so does this.
    return 0


def twist_fill(vx, vy, wz):
    """The `fill(builder, header)` callback for a typed Twist: forward/left in linear x/y, yaw in angular z."""
    from aorta.topic.navigation import Twist, Vector3

    def fill(builder, header):
        Twist.TwistStart(builder)
        if header is not None:
            Twist.TwistAddAortaHeader(builder, header)
        Twist.TwistAddLinear(builder, Vector3.CreateVector3(builder, float(vx), float(vy), 0.0))
        Twist.TwistAddAngular(builder, Vector3.CreateVector3(builder, 0.0, 0.0, float(wz)))
        return Twist.TwistEnd(builder)
    return fill


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
        built = build_motion(args, directory, resources, node, sdk, ledger, face_core) if args.motion else None
        motion_core, live = built if built else (None, None)
        drive_core = build_drive(args, directory, resources, node, ledger, live) if built else None
        emit(event="session_ready", requestId=args.session_id, protocol=PROTOCOL, faceOnly=False,
             motion=motion_core is not None,
             motionPresets=list(action.PRESETS) if motion_core is not None else [],
             moves=list(MOVES) if motion_core is not None else [],
             drive=DRIVE_LIMITS if drive_core is not None else None,
             supportedFaces=[name for name in names if re.match(r"\d{3}_", name) and int(name[:3]) in supported])
        try:
            return serve(face_core, motion_core, drive_core=drive_core, make_reader=lambda: FdLineReader(sys.stdin.fileno()))
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

    def run_cue(preset, logical_id, canceled, move=None):
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
            if move is None:
                return action.execute_preset(cue, node, sdk, client, codec, ExecuteTaskResultT, live.check, publish=False)
            # Build the graph BEFORE execute_preset writes its records. A construction error here
            # then leaves nothing behind, instead of an unresolved-action lock for a goal never sent.
            goal = make_move_goal(move[0], move[1], attempt_id)
            return action.execute_preset(cue, node, sdk, client, codec, ExecuteTaskResultT, live.check,
                                         goal_factory=lambda _: goal, publish=False)
        result = action.rescan_cue(preset, live.check, static_check, perform, canceled,
                                   lambda frame: emit(event="rescan", commandId=logical_id, **frame), timeout=RESCAN_SECONDS)
        logical["result"] = result
        temporary = logical_path.with_suffix(".complete.tmp")
        with temporary.open("x") as record:
            json.dump(logical, record)
        os.replace(temporary, logical_path)
        return result
    return (MotionCore(ledger=ledger, face_core=face_core, run_cue=run_cue,
                       unresolved=lambda: (directory / "unresolved-action.json").exists(),
                       session_id=args.session_id, lease=args.lease, presets=frozenset(action.PRESETS), moves=frozenset(MOVES)),
            live)


def build_drive(args, directory, resources, node, ledger, live):
    """The one velocity publisher in this file. It is created once per session and only DriveCore publishes to it."""
    import twist_schema_meta as twist_schema
    publisher = node.create_publisher_typed(twist_schema, VELOCITY_TOPIC)
    resources.callback(publisher.close)
    return DriveCore(ledger=ledger, publish=lambda vx, vy, wz: publisher.publish_typed(twist_fill(vx, vy, wz)),
                     ready=lambda: live.check(timeout=3, detailed=True), matched=lambda: bool(publisher.wait_for_matching(1000)),
                     unresolved_path=directory / "unresolved-action.json", session_id=args.session_id, lease=args.lease, emit=emit)


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
