"""Local demo controller. No robot connection until explicitly armed in live mode."""
from __future__ import annotations

from collections import OrderedDict, deque
import json
import os
from pathlib import Path
import re
import random
import shlex
import subprocess
import threading
import time
import uuid

from vbot_policy import CelebrationPolicy, GOOD_LABELS, SMALL_PRESETS, HEAD_PRESETS, RULES

PRESETS = ("actions/ROCKYOU.json", "actions/CHEER_R.json", *SMALL_PRESETS)
REMOTE_ROOT = "/userdata/vbot/chess-demo"
SCHEMA_HASH = "a8584e3f6c005fea6579d699c6991f97b2482e01df228a537e3d89e1323eb818"
PROFILE_PATH = Path(__file__).resolve().parents[1] / "vbot-demo" / "device-verification.local.json"


class RobotNotReady(RuntimeError):
    """The helper positively reports that no goal was submitted."""


class RobotRejected(RuntimeError):
    """A matching terminal result reports rejection/cancellation."""


def load_verification(path=PROFILE_PATH) -> dict | None:
    try:
        if path.stat().st_size > 16384:
            return None
        profile = json.loads(path.read_text())
        if (profile.get("schemaVersion") != 1 or profile.get("actionSchemaHash") != SCHEMA_HASH or
                not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", profile.get("hostKeyFingerprint", ""))):
            return None
        verified = [item for item in profile.get("presets", []) if isinstance(item, dict) and
                    item.get("preset") in PRESETS and item.get("status") == "SUCCEEDED" and
                    item.get("errorCategory") == 0 and item.get("movementConfirmed") is True]
        if not verified:
            return None
        return {**profile, "presets": verified}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def known_host_fingerprints(target: str) -> set[str]:
    host = target.removeprefix("vbot@")
    found = subprocess.run(["ssh-keygen", "-F", host], capture_output=True, text=True, timeout=3, check=False)
    keys = "\n".join(line for line in found.stdout.splitlines() if line and not line.startswith("#"))
    if found.returncode != 0 or not keys:
        return set()
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=keys + "\n", capture_output=True,
                            text=True, timeout=3, check=False)
    return {line.split()[1] for line in result.stdout.splitlines()
            if len(line.split()) > 1 and line.split()[1].startswith("SHA256:")}


def ssh_command(target: str, preset: str, request_id: str) -> list[str]:
    if not re.fullmatch(r"(?:vbot@)?[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", target):
        raise ValueError("Use an SSH alias or vbot@hostname/IP, without spaces or options.")
    if preset not in PRESETS or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("Invalid preset or request identity.")
    remote = shlex.join([
        REMOTE_ROOT + "/.venv/bin/python", "-I", REMOTE_ROOT + "/robot_action.py",
        "--execute", "--confirm-motion", "--request-id", request_id, "--preset", preset,
    ])
    return ["ssh", "-T", "-l", "vbot", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "-o", "ControlPath=none", "-o", "ForwardAgent=no", target, remote]


def send_dance(target: str, preset: str, request_id: str) -> dict:
    # A timeout or a lost SSH stream can leave a task running. Never retry it.
    result = subprocess.run(ssh_command(target, preset, request_id), capture_output=True,
                            text=True, timeout=125, check=False)
    terminal = None
    not_ready = None
    submitted = False
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("requestId") != request_id:
            continue
        if item.get("event") == "submitting":
            submitted = True
        if item.get("event") == "not_ready":
            not_ready = item
        if item.get("event") == "terminal":
            terminal = item
    if not_ready and not submitted and not terminal:
        raise RobotNotReady(str(not_ready.get("reason", "Robot is not ready; no goal submitted.")))
    if terminal and terminal.get("status") in {"ABORTED", "CANCELED"}:
        raise RobotRejected("Robot returned " + terminal["status"] + ". Check the handset and saved device result before rearming.")
    if result.returncode != 0 or not terminal:
        raise RuntimeError("Robot outcome unknown or unsuccessful. Check the handset and device task; do not retry automatically.")
    if terminal.get("status") != "SUCCEEDED" or terminal.get("errorCategory") != 0:
        raise RuntimeError("The robot did not report a successful terminal action result.")
    return {"status": "completed", "goalId": terminal.get("goalId"),
            "durationMs": terminal.get("durationMs"), "readyForNext": terminal.get("readyForNext", False),
            "postflightReason": terminal.get("postflightReason")}


class VbotDemo:
    def __init__(self, *, sender=send_dance, clock=time.monotonic, verification=None,
                 fingerprint_reader=known_host_fingerprints, chooser=random.choice):
        self.sender, self.clock, self.chooser = sender, clock, chooser
        self.policy = CelebrationPolicy()
        self.stream_line = ()
        self.last_small_preset = None
        self.last_dance_finished = float("-inf")
        self.verification = verification if verification is not None else load_verification()
        self.fingerprint_reader = fingerprint_reader
        self.lock = threading.RLock()
        self.armed = False
        self.mode = "rehearsal"
        self.game_id = ""
        self.target = os.environ.get("VBOT_SSH_TARGET", "").strip() or (self.verification or {}).get("target", "")
        self.preset = PRESETS[0]
        self.cooldown = 20.0
        self.armed_at = float("inf")
        self.last_started = float("-inf")
        self.last_finished = float("-inf")
        self.compatibility = {"basis": "not-armed", "applicationVersion": None}
        self.busy = False
        self.generation = 0
        self.records = OrderedDict()
        self.seen = OrderedDict()
        self.events = deque(maxlen=80)

    def _event(self, status: str, **fields) -> dict:
        event = {"time": int(time.time() * 1000), "status": status, **fields}
        self.events.appendleft(event)
        return event

    def remember(self, record: dict) -> None:
        """Only called with a freshly computed server-side engine result."""
        with self.lock:
            record_id = record.get("recordId")
            if not record_id or not record.get("gameId"):
                return
            self.records[record_id] = (self.clock(), {key: record.get(key) for key in (
                "recordId", "gameId", "ply", "playerColor", "playedMoveUci", "playedMove", "classification", "fenBefore", "savedAt", "evaluationAfter",
                "engineDiagnostics", "opponentReplyUci")})
            while len(self.records) > 256:
                self.records.popitem(last=False)

    def status(self) -> dict:
        with self.lock:
            return {"armed": self.armed, "mode": self.mode, "gameId": self.game_id,
                    "target": self.target, "preset": self.preset, "presets": PRESETS,
                    "cooldownSeconds": self.cooldown, "busy": self.busy,
                    "cooldownRemaining": max(0, round(self.cooldown - (self.clock() - max(self.last_started, self.last_finished)), 1)),
                    "events": list(self.events), "deviceVerified": False,
                    "compatibility": self.compatibility,
                    "verification": self.verification, "policy": RULES,
                    "smallPresets": self._small_presets(self.target),
                    "danceCooldownRemaining": max(0, round(RULES["danceIntervalSeconds"] - (self.clock()-self.last_dance_finished), 1))}

    def _verified_entry(self, target: str, preset: str) -> dict | None:
        profile = self.verification or {}
        canonical = target if target.startswith("vbot@") else "vbot@" + target
        if canonical != profile.get("target"):
            return None
        return next((item for item in profile.get("presets", []) if item.get("preset") == preset and
                     item.get("status") == "SUCCEEDED" and item.get("errorCategory") == 0 and
                     item.get("movementConfirmed") is True), None)

    def _small_presets(self, target):
        return [preset for preset in SMALL_PRESETS if self._verified_entry(target, preset)]

    def _identity_matches(self, target: str) -> bool:
        try:
            return (self.verification or {}).get("hostKeyFingerprint") in self.fingerprint_reader(target)
        except (OSError, subprocess.SubprocessError):
            return False

    def arm(self, payload: dict) -> dict:
        mode = payload.get("mode", "rehearsal")
        game_id = str(payload.get("gameId", "")).strip()
        preset = payload.get("preset", PRESETS[0])
        target = str(payload.get("target", self.target)).strip()
        compatibility = {"basis": "rehearsal", "applicationVersion": None}
        if mode not in {"rehearsal", "live"} or preset not in PRESETS:
            raise ValueError("Choose a listed mode and preset.")
        if not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
            raise ValueError("Enter the eight-character Lichess game ID.")
        if mode == "live":
            if payload.get("confirmSafeWorkspace") is not True or payload.get("confirmHandsetStop") is not True:
                raise ValueError("Confirm clear space and an onsite handset stopping procedure before live motion.")
            ssh_command(target, preset, uuid.uuid4().hex)
            if payload.get("applicationVersion") == "V1.6.0":
                compatibility = {"basis": "application-version", "applicationVersion": "V1.6.0"}
            else:
                if not self._verified_entry(target, preset) or not self._identity_matches(target):
                    raise ValueError("Application version is unverified and no matching local preset rehearsal/SSH host key was found.")
                compatibility = {"basis": "tested-preset", "applicationVersion": None,
                                 "target": target, "preset": preset}
        with self.lock:
            if self.busy:
                raise ValueError("Wait for the current action to finish before changing the demo.")
            self.mode, self.game_id, self.target, self.preset = mode, game_id, target, preset
            self.compatibility = compatibility
            self.armed = True
            self.armed_at = self.clock()
            self.policy = CelebrationPolicy()
            self.stream_line = ()
            self.last_small_preset = None
            self.generation += 1
            self._event("armed", mode=mode, gameId=game_id, preset=preset)
            return self.status()

    def disarm(self) -> dict:
        with self.lock:
            self.armed = False
            self.generation += 1
            self._event("disarmed", message="Future dances disabled. An action already running must finish or be stopped onsite.")
            return self.status()

    def celebrate(self, payload: dict, game: dict | None) -> dict:
        if not isinstance(payload.get("recordId"), str):
            raise ValueError("A server recordId is required.")
        with self.lock:
            entry = self.records.get(payload.get("recordId"))
            if not entry:
                return self._event("skipped", reason="No fresh server engine result.")
            created, record = entry
            reason = None
            if self.clock() - created > 30 or created < self.armed_at:
                reason = "Analysis is stale or predates arming."
            elif record["gameId"] != payload.get("gameId") or record["playerColor"] != payload.get("playerColor"):
                reason = "Game or player does not match the engine result."
            elif not game or game.get("state", {}).get("status") not in {"started", "created"}:
                reason = "No active game in the existing Lichess bot stream."
            elif not isinstance(game.get("updatedAt"), (int, float)) or time.time() * 1000 - game["updatedAt"] > 30000:
                reason = "The cached Lichess stream is stale."
            elif game.get("botColor") not in {"white", "black"} or game["botColor"] == record["playerColor"]:
                reason = "Only the human player's moves can celebrate."
            else:
                # Reconstruct the exact engine position from the authoritative bot stream.
                import chess
                try:
                    board = chess.Board() if game.get("initialFen") in {None, "", "startpos"} else chess.Board(game["initialFen"])
                    moves = game["state"].get("moves", "").split()
                    target_ply = record["ply"] - board.ply() - 1
                    if not 0 <= target_ply < len(moves):
                        raise ValueError("Move not yet in stream")
                    for uci in moves[:target_ply]:
                        board.push_uci(uci)
                    if (moves[target_ply] != record["playedMoveUci"] or
                            ("white" if board.turn else "black") != record["playerColor"]):
                        raise ValueError("Different move or player")
                    # The cache also includes this private comparison field below.
                    if board.fen() != record.get("fenBefore"):
                        raise ValueError("Different position")
                except (ValueError, TypeError, KeyError):
                    reason = "Move/position not confirmed by the existing Lichess stream."
            if reason:
                return self._event("skipped", reason=reason, gameId=record["gameId"], ply=record["ply"])
            if not self.armed or record["gameId"] != self.game_id:
                return self._submit(record)
            current_line = tuple(game["state"].get("moves", "").split())
            common = min(len(current_line), len(self.stream_line))
            if self.stream_line and (len(current_line) < len(self.stream_line) or current_line[:common] != self.stream_line[:common]):
                self.policy = CelebrationPolicy()
            self.stream_line = current_line
            # Classify only stream-confirmed records, once per human ply. Out-of-order or
            # replayed positions cannot contaminate a later baseline.
            policy_key = (record["gameId"], record["playerColor"], record["ply"])
            if policy_key in self.seen:
                return self._event("skipped", reason="This ply was already handled.", gameId=record["gameId"], ply=record["ply"])
            if self.policy.identity == (record["gameId"], record["playerColor"]) and self.policy.last_ply is not None and record["ply"] <= self.policy.last_ply:
                return self._event("skipped", reason="Out-of-order analysis cannot update the celebration baseline.")
            decision = self.policy.observe(record, game)
            return self._submit(record, decision)

    def rehearse(self, classification: str, scenario="ordinary") -> dict:
        if classification not in {"good", "inaccuracy", "mistake", "blunder"}:
            raise ValueError("Choose a real coach classification.")
        if scenario not in {"ordinary", "major"}:
            raise ValueError("Choose an ordinary or major synthetic example.")
        with self.lock:
            if self.mode != "rehearsal":
                raise ValueError("Synthetic moves are restricted to rehearsal mode.")
            return self._submit({"gameId": self.game_id, "ply": uuid.uuid4().hex,
                                 "playerColor": "white", "classification": classification,
                                 "playedMove": "e4", "synthetic": True},
                                {"tier":"major" if scenario == "major" else "small",
                                 "reason":"Synthetic tier example; not a real engine/material signal.", "briefOnly":False})

    def _submit(self, record: dict, decision=None) -> dict:
        fields = {key: record.get(key) for key in ("gameId", "ply", "playedMove", "classification", "synthetic")}
        if not self.armed:
            return self._event("skipped", reason="Demo is disarmed.", **fields)
        if record["gameId"] != self.game_id:
            return self._event("skipped", reason="Another game is selected.", **fields)
        if record["classification"] not in GOOD_LABELS:
            return self._event("skipped", reason="Coach did not label this move good.", **fields)
        key = (record["gameId"], record["playerColor"], record["ply"])
        if key in self.seen:
            return self._event("skipped", reason="This ply was already handled.", **fields)
        # Mark busy/cooldown moves handled too: a delayed request must never queue a later dance.
        self.seen[key] = True
        while len(self.seen) > 4096:
            self.seen.popitem(last=False)
        if self.busy or self.clock() - max(self.last_started, self.last_finished) < self.cooldown:
            return self._event("skipped", reason="Action busy or within cooldown; not queued.", **fields)
        decision = decision or {"tier":"small", "reason":"Ordinary good move.", "briefOnly":False}
        tier = decision["tier"]
        pace_reason = decision.get("paceReason")
        if tier == "major" and (decision.get("briefOnly") or self.clock()-self.last_dance_finished < RULES["danceIntervalSeconds"]):
            tier = "small"
            pace_reason = pace_reason or "Full dance is within its three-minute interval; using a brief acknowledgment."
        preset = self.preset
        if tier == "small":
            pool = self._small_presets(self.target) if self.mode == "live" else list(SMALL_PRESETS)
            if decision.get("briefOnly"):
                pool = [p for p in pool if p in HEAD_PRESETS]
            options = [p for p in pool if p != self.last_small_preset] or pool
            if not options:
                return self._event("skipped", reason="No rehearsed brief preset is available for this pace/target.", tier=tier, **fields)
            preset = self.chooser(options)
            self.last_small_preset = preset
        self.cooldown = RULES["danceRestSeconds"] if tier == "major" else RULES["smallRestSeconds"]
        self.last_started = self.clock()
        context = {"tier":tier, "reason":decision["reason"], "paceReason":pace_reason,
                   "metrics":decision.get("metrics"), "preset":preset, **fields}
        if self.mode == "rehearsal":
            if tier == "major": self.last_dance_finished = self.clock()
            return self._event("rehearsed", message="Would request this acknowledgment; no robot contacted.", **context)
        self.busy = True
        request_id = uuid.uuid4().hex
        generation = self.generation
        self._event("requested", requestId=request_id, **context)
        threading.Thread(target=self._run, args=(self.target, preset, request_id, generation, tier), daemon=True).start()
        return {"status":"requested", "requestId":request_id, "tier":tier, "preset":preset}

    def _run(self, target, preset, request_id, generation, tier="small"):
        try:
            with self.lock:
                if not self.armed or generation != self.generation:
                    self._event("skipped", requestId=request_id, reason="Disarmed before dispatch.")
                    return
                verify_identity = self.compatibility.get("basis") == "tested-preset"
            if verify_identity and (not self._verified_entry(target, preset) or not self._identity_matches(target)):
                raise RobotNotReady("The saved SSH host key no longer matches the rehearsed robot. No goal submitted.")
            outcome = self.sender(target, preset, request_id)
            with self.lock:
                self._event(outcome["status"], requestId=request_id, **{k: v for k, v in outcome.items() if k != "status"})
                if outcome.get("readyForNext") is False:
                    self.armed = False
                    self._event("not_ready", requestId=request_id,
                                reason=outcome.get("postflightReason") or "Robot is not ready for another action. Inspect and rearm onsite.")
        except (RobotNotReady, RobotRejected) as error:
            with self.lock:
                self.armed = False
                self._event("not_ready" if isinstance(error, RobotNotReady) else "rejected",
                            requestId=request_id, reason=str(error))
        except Exception:
            with self.lock:
                self.armed = False
                self._event("unknown", requestId=request_id,
                            message="Robot action not confirmed. Demo disarmed; inspect the robot before rearming. No automatic retry.")
        finally:
            with self.lock:
                self.busy = False
                self.last_finished = self.clock()
                if tier == "major": self.last_dance_finished = self.clock()


demo = VbotDemo()
