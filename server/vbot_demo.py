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

from vbot_networks import NetworkBook, normalize_target
from capture_practice import PRACTICE_ID, exercise as capture_exercise, assess_capture
from vbot_policy import CelebrationPolicy, GOOD_LABELS, SMALL_PRESETS, HEAD_PRESETS, SAD_PRESET, RULES, MAX_SMALL_DURATION_MS, JUMP_PRESETS

PRESETS = ("actions/ROCKYOU.json", "actions/CHEER_R.json", *SMALL_PRESETS, SAD_PRESET)
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


def ssh_command(target: str, preset: str, request_id: str, *, host_key_alias=None) -> list[str]:
    if not re.fullmatch(r"(?:vbot@)?[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", target):
        raise ValueError("Use an SSH alias or vbot@hostname/IP, without spaces or options.")
    if preset not in PRESETS or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("Invalid preset or request identity.")
    if host_key_alias is not None:
        host_key_alias=normalize_target(host_key_alias).removeprefix("vbot@")
    remote = shlex.join([
        REMOTE_ROOT + "/.venv/bin/python", "-I", REMOTE_ROOT + "/robot_action.py",
        "--execute", "--confirm-motion", "--request-id", request_id, "--preset", preset,
    ])
    return ["ssh", "-T", "-l", "vbot", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "-o", "ControlPath=none", "-o", "ForwardAgent=no",
            *(["-o", "HostKeyAlias="+host_key_alias] if host_key_alias else []), target, remote]


def send_dance(target: str, preset: str, request_id: str, *, host_key_alias=None) -> dict:
    # A timeout or a lost SSH stream can leave a task running. Never retry it.
    result = subprocess.run(ssh_command(target, preset, request_id, host_key_alias=host_key_alias), capture_output=True,
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


def check_robot(target: str, *, host_key_alias=None) -> dict:
    """Explicit read-only probe using the same strict SSH identity as dispatch."""
    request_id = uuid.uuid4().hex
    command = ssh_command(target, PRESETS[0], request_id, host_key_alias=host_key_alias)
    command[-1] = shlex.join([REMOTE_ROOT + "/.venv/bin/python", "-I",
                             REMOTE_ROOT + "/robot_action.py", "--check-ready",
                             "--request-id", request_id])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=25, check=False)
    except subprocess.TimeoutExpired:
        return {"ready": False, "code": "timeout", "reason": "Robot readiness check timed out. Check its power and Wi-Fi."}
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("requestId") == request_id and item.get("event") == "readiness":
            if isinstance(item.get("ready"), bool):
                return {"ready": item["ready"] and result.returncode == 0,
                        "code": item.get("code", "ready" if item["ready"] else "not_ready"),
                        "reason": item.get("reason")}
    error = result.stderr.lower()
    if "host key verification failed" in error or "remote host identification has changed" in error:
        reason = "SSH host identity could not be verified. Inspect the saved host key; do not bypass verification."
    elif "permission denied" in error:
        reason = "SSH authentication failed. Check this Mac's existing public-key access."
    else:
        reason = "Robot readiness could not be verified. Check power, Wi-Fi, SSH access, and the deployed helper."
    return {"ready": False, "code": "unavailable", "reason": reason}


class VbotDemo:
    def __init__(self, *, sender=send_dance, clock=time.monotonic, verification=None,
                 fingerprint_reader=known_host_fingerprints, chooser=random.choice, checker=check_robot, victory_wait=time.sleep, network_book=None):
        self.sender, self.clock, self.chooser = sender, clock, chooser
        self.victory_wait = victory_wait
        self.network_book = network_book
        self.network_key = None
        self.network_initialized = False
        self.network_needs_target = False
        self.finish_pending = False
        self.victory_pending = False
        self.finish_generation = None
        self.finished_games = OrderedDict()
        self.player_color = None
        self.checker = checker
        # New LAN addresses use the SAME already-trusted robot host key. SSH
        # HostKeyAlias does not accept a new key or modify known_hosts.
        if network_book is not None and sender is send_dance:
            self.sender = lambda target,preset,request_id: send_dance(target,preset,request_id,host_key_alias=self._ssh_identity_anchor())
        if network_book is not None and checker is check_robot:
            self.checker = lambda target: check_robot(target,host_key_alias=self._ssh_identity_anchor())
        self.readiness = None
        self.readiness_at = float("-inf")
        self.probe_generation = 0
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
        self.practice_attempts = OrderedDict()
        self.session_kind = "game"
        self.records = OrderedDict()
        self.seen = OrderedDict()
        self.events = deque(maxlen=80)

    def _event(self, status: str, **fields) -> dict:
        event = {"time": int(time.time() * 1000), "status": status, "gameId": self.game_id, **fields}
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

    def _sync_network(self, force=False):
        if self.network_book is None: return
        network = self.network_book.current(force=force)
        key = (network.get("id"), network.get("subnet"), network.get("gateway"))
        snapshot = self.network_book.snapshot()
        with self.lock:
            changed = self.network_initialized and key != self.network_key
            if not self.network_initialized or changed:
                self.network_initialized = True
                self.network_key = key
                self.network_needs_target = True
                self.readiness = None
                self.readiness_at = float("-inf")
                self.probe_generation += 1
            if changed and self.armed:
                self.disarm({"gameId":self.game_id,"generation":self.generation,"reason":"network_changed"})
            if self.network_needs_target and not self.busy and not self.armed:
                # A remembered address is a candidate, never automatic live arming.
                self.target = snapshot.get("suggestedTarget") or ""
                self.network_needs_target = False

    def remember_network(self, payload):
        if self.network_book is None: raise ValueError("Network memory is unavailable on this controller.")
        self._sync_network(force=True)
        with self.lock:
            if self.armed or self.busy: raise ValueError("Turn reactions off before changing remembered addresses.")
            if not isinstance(payload.get("networkId"),str):
                raise ValueError("Select the current network before remembering an address.")
            target=normalize_target(payload.get("target"))
            snapshot=self.network_book.remember(target,label=payload.get("label",""),
                network_id=payload.get("networkId"))
            self.target=target
            return self.status()

    def status(self) -> dict:
        self._sync_network()
        with self.lock:
            return {"sessionKind": self.session_kind, "companionApiVersion": 1, "generation": self.generation,
                    "network": self.network_book.snapshot() if self.network_book is not None else None,
                    "readiness": self.readiness,
                    "readinessFresh": self.readiness is not None and self.clock() - self.readiness_at <= 30,
                    "armed": self.armed, "mode": self.mode, "gameId": self.game_id,
                    "finishPending": self.finish_pending, "victoryPending": self.victory_pending,
                    "target": self.target, "preset": self.preset, "presets": PRESETS,
                    "cooldownSeconds": self.cooldown, "busy": self.busy,
                    "cooldownRemaining": max(0, round(self.cooldown - (self.clock() - max(self.last_started, self.last_finished)), 1)),
                    "events": list(self.events), "deviceVerified": False,
                    "compatibility": self.compatibility,
                    "verification": self.verification, "policy": RULES,
                    "smallPresets": self._small_presets(self.target),
                    "smallPresetCandidates": list(SMALL_PRESETS),
                    "operatorApprovedPresets": [p for p in SMALL_PRESETS if self._demo_approved(self.target, p) and not self._verified_entry(self.target, p)],
                    "sadPresetVerified": bool(self._verified_entry(self.target, SAD_PRESET)),
                    "danceCooldownRemaining": max(0, round(RULES["danceIntervalSeconds"] - (self.clock()-self.last_dance_finished), 1))}

    def _verified_entry(self, target: str, preset: str) -> dict | None:
        profile = self.verification or {}
        canonical = target if target.startswith("vbot@") else "vbot@" + target
        if canonical != profile.get("target") and not (self.network_book is not None and
                self.network_book.target_verified(canonical,profile.get("hostKeyFingerprint"))):
            return None
        return next((item for item in profile.get("presets", []) if item.get("preset") == preset and
                     item.get("status") == "SUCCEEDED" and item.get("errorCategory") == 0 and
                     item.get("movementConfirmed") is True), None)

    def _demo_approved(self, target, preset):
        approval = (self.verification or {}).get("demoApproval") or {}
        canonical = target if target.startswith("vbot@") else "vbot@" + target
        expiry = approval.get("expiresAt", 0)
        return (approval.get("enabled") is True and preset in SMALL_PRESETS
                and canonical == approval.get("target") == (self.verification or {}).get("target")
                and isinstance(expiry, (int, float)) and expiry > time.time()
                and preset in approval.get("presets", []))

    def _small_presets(self, target):
        result = []
        for preset in SMALL_PRESETS:
            entry = self._verified_entry(target, preset)
            rehearsed_short = (entry and isinstance(entry.get("durationMs"), (int, float))
                               and not isinstance(entry["durationMs"], bool)
                               and 0 < entry["durationMs"] <= MAX_SMALL_DURATION_MS)
            if rehearsed_short or self._demo_approved(target, preset): result.append(preset)
        return result

    def _choose_small(self, pool):
        # Fresh random draw on every eligible event; no shuffle bag, rotation,
        # queued gestures or catch-up. Avoid just the immediately previous choice.
        options = [preset for preset in pool if preset != self.last_small_preset] or pool
        weighted = [preset for preset in options for _ in range(4 if preset in JUMP_PRESETS else 1)]
        preset = self.chooser(weighted)
        self.last_small_preset = preset
        return preset

    def _ssh_identity_anchor(self):
        profile=self.verification or {}
        anchor=profile.get("target")
        if not anchor or profile.get("hostKeyFingerprint") not in self.fingerprint_reader(anchor):
            raise ValueError("The robot's saved SSH host identity is unavailable or changed. Inspect it before connecting.")
        return normalize_target(anchor)

    def _identity_matches(self, target: str) -> bool:
        try:
            anchor=self._ssh_identity_anchor() if self.network_book is not None else target
            return (self.verification or {}).get("hostKeyFingerprint") in self.fingerprint_reader(anchor)
        except (OSError, ValueError, subprocess.SubprocessError):
            return False

    def check_device(self, payload: dict) -> dict:
        self._sync_network(force=True)
        target = str(payload.get("target", self.target)).strip()
        ssh_command(target, PRESETS[0], uuid.uuid4().hex)  # Validate before any subprocess.
        with self.lock:
            if self.busy or self.armed:
                raise ValueError("Turn reactions off before checking the robot.")
            self.probe_generation += 1
            probe, generation = self.probe_generation, self.generation
        fingerprint = (self.verification or {}).get("hostKeyFingerprint")
        network = self.network_book.current() if self.network_book is not None else None
        if self.network_book is not None:
            self._ssh_identity_anchor()  # Strictly pin every candidate to the existing robot identity.
        result = self.checker(target)
        self._sync_network(force=True)
        with self.lock:
            if probe != self.probe_generation or generation != self.generation:
                raise ValueError("The connection changed during this check. Check again before enabling motion.")
            # A positive helper reply proves SSH reached the pinned robot even
            # when battery/posture currently prevents motion. Failures never learn.
            if network and network.get("id") and result.get("code") in {
                    "ready","battery","system","posture","head_fault","head_pending","head_busy","stale","incomplete"}:
                try:
                    self.network_book.remember(target,fingerprint=fingerprint,verified=True,network_id=network["id"])
                except ValueError as error:
                    # Manual connections can use a second/wired LAN; do not save
                    # them against the unrelated default network.
                    result={**result,"rememberWarning":str(error)}
            self.target = target
            self.readiness = {**result, "target": target, "checkedAt": int(time.time() * 1000)}
            self.readiness_at = self.clock()
            return self.status()

    def connect_game(self, payload: dict, game_reader) -> dict:
        game_id = str(payload.get("gameId", ""))
        game = game_reader(game_id)
        if (not game or game.get("gameId") != game_id or
                game.get("state", {}).get("status") not in {"created", "started"} or
                game.get("botColor") not in {"white", "black"}):
            raise ValueError("Reconnect an active training game before enabling reactions.")
        if payload.get("playerColor") not in {"white", "black"} or payload["playerColor"] == game["botColor"]:
            raise ValueError("Only the human player's training game can enable reactions.")
        return self.arm({**payload, "requireReadiness": payload.get("mode") == "live"})

    def connect_practice(self, payload):
        if payload.get("gameId") != PRACTICE_ID or payload.get("playerColor") != "white":
            raise ValueError("Invalid capture-practice session.")
        return self.arm({**payload, "practice":True, "preset":"actions/ROCKYOU.json",
                         "requireReadiness":payload.get("mode")=="live"})

    def start_capture(self, payload):
        lesson=capture_exercise(payload.get("exerciseId"))
        with self.lock:
            token=uuid.uuid4().hex
            self.practice_attempts[token]={"exerciseId":lesson['id'],"created":self.clock(),"result":None}
            while len(self.practice_attempts)>128: self.practice_attempts.popitem(last=False)
            return {"attemptId":token,"exerciseId":lesson['id']}

    def capture_reward(self, payload):
        with self.lock:
            attempt=self.practice_attempts.get(payload.get("attemptId"))
            if not attempt or self.clock()-attempt['created']>1800:
                raise ValueError("Restart this lesson; its practice attempt expired.")
            if attempt['result'] is not None: return attempt['result']
            result=assess_capture(attempt['exerciseId'],payload.get("moveUci"))
            if not result['correct']: return result
            # Only this server-authored lesson channel can request a practice reward.
            # It neither manufactures a coach verdict nor changes a Lichess position.
            if self.session_kind!="capture-practice" or self.game_id!=PRACTICE_ID or not self.armed:
                reward={"status":"skipped","reason":"Correct! Enable live practice rewards for a new attempt to earn a dance."}
            else:
                reward=self._submit({"gameId":PRACTICE_ID,"playerColor":"white","ply":payload['attemptId'],
                    "classification":"good","playedMove":result['san'],"practiceReward":True},
                    {"tier":"major","reason":"Correct big-piece capture in Capture Practice.","briefOnly":False})
            response={**result,"reward":reward}
            attempt['result']=response
            return response

    def arm(self, payload: dict) -> dict:
        self._sync_network(force=True)
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
            if payload.get("requireReadiness"):
                with self.lock:
                    if (not self.readiness or not self.readiness.get("ready") or
                            self.readiness.get("target") != target or self.clock() - self.readiness_at > 30):
                        raise ValueError("Check this robot's readiness again before enabling live reactions.")
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
            self.session_kind = "capture-practice" if payload.get("practice") is True and game_id == PRACTICE_ID else "game"
            self.compatibility = compatibility
            self.player_color = payload.get("playerColor")
            self.finish_pending = self.victory_pending = False
            self.finish_generation = None
            self.armed = True
            self.armed_at = self.clock()
            self.policy = CelebrationPolicy()
            self.stream_line = ()
            self.last_small_preset = None
            self.generation += 1
            self._event("armed", mode=mode, gameId=game_id, preset=preset)
            return self.status()

    def disarm(self, payload=None) -> dict:
        with self.lock:
            if payload and (payload.get("gameId") != self.game_id or payload.get("generation") != self.generation):
                return self.status()  # A stale tab cannot disable a newer arming session.
            self.armed = False
            self.finish_pending = self.victory_pending = False
            self.finish_generation = None
            self.generation += 1
            reasons = {
                "operator_off": "Turned off by the operator.",
                "match_finished": "Match finished; reactions turned off.",
                "match_changed": "Selected match changed; reactions turned off.",
                "match_changed_during_connect": "Match changed while connecting; reactions turned off.",
                "supervised_rehearsal": "Paused for a supervised preset rehearsal.",
                "server_shutdown": "Coach server stopped; reactions turned off.",
                "network_changed": "Mac network changed; reactions turned off. Check the address on this network before enabling again.",
            }
            reason_code = (payload or {}).get("reason", "unspecified")
            if reason_code not in reasons: reason_code = "unspecified"
            self._event("disarmed", reasonCode=reason_code, reason=reasons.get(reason_code),
                        message="Future dances disabled. An action already running must finish or be stopped onsite.")
            return self.status()

    def observe_game_end(self, game: dict, game_reader) -> None:
        """Called from the existing canonical bot stream; no second game watcher."""
        with self.lock:
            if (not self.armed or self.session_kind != "game" or
                    game.get("gameId") != self.game_id or
                    game.get("state", {}).get("status") in {"created", "started"}):
                return
            payload = {"gameId": self.game_id, "generation": self.generation}
        self.finish_game(payload, game_reader)

    def finish_game(self, payload: dict, game_reader) -> dict:
        """A scoped result notification cannot supply or forge the winner.

        Browser and bot streams may report game end in either order. One worker
        briefly awaits the canonical cached result, then handles it exactly once.
        It never retries a robot goal, and Off/game changes cancel any wait.
        """
        with self.lock:
            if (not self.armed or self.session_kind != "game" or
                    payload.get("gameId") != self.game_id or
                    payload.get("generation") != self.generation):
                return self.status()
            if self.finish_generation == self.generation:
                return self.status()
            self.finish_generation = self.generation
            self.finish_pending = True
            self._event("finishing", reason="Confirming the final result from the Lichess bot stream.")
            threading.Thread(target=self._finish_game, args=(self.game_id, self.generation, game_reader), daemon=True).start()
            return self.status()

    def _finish_game(self, game_id, generation, game_reader):
        session = {"gameId": game_id, "generation": generation, "reason": "match_finished"}
        def current():
            return self.armed and self.game_id == game_id and self.generation == generation
        try:
            deadline = self.clock() + 15
            while True:
                with self.lock:
                    if not current(): return
                game = game_reader(game_id)
                state = game.get("state", {}) if isinstance(game, dict) else {}
                if state.get("status") not in {None, "created", "started"}:
                    break
                if self.clock() >= deadline:
                    with self.lock:
                        if current():
                            self._event("skipped", reason="Final result was not confirmed within 15 seconds; no victory dance queued.")
                    return
                self.victory_wait(.05)
            with self.lock:
                if not current(): return
                updated = game.get("updatedAt")
                fresh = (isinstance(updated, (int, float)) and not isinstance(updated, bool)
                         and 0 <= time.time()*1000-updated <= 30000)
                human_win = (game.get("gameId") == game_id and fresh
                             and self.player_color in {"white", "black"}
                             and game.get("botColor") in {"white", "black"}
                             and game["botColor"] != self.player_color
                             and state.get("winner") == self.player_color
                             and state.get("status") in {"mate", "resign", "outoftime", "timeout", "variantEnd", "cheat"})
                if game_id in self.finished_games:
                    return
                self.finished_games[game_id] = True
                while len(self.finished_games) > 256: self.finished_games.popitem(last=False)
                if not human_win:
                    self._event("skipped", reason="No fresh, confirmed human win; no victory dance.")
                    return
                if self.mode == "rehearsal":
                    self._event("rehearsed", preset="actions/ROCKYOU.json", tier="victory",
                                reason="You won! Victory dance preview; no robot motion.")
                    return
                self.victory_pending = True
                self._event("victory_pending", preset="actions/ROCKYOU.json", tier="victory",
                            reason="You won! Rock You will follow the current reaction/rest. Turn reactions off to cancel.")
            # Victory has no running chess clock and bypasses the three-minute
            # major interval, but still waits for completion and normal rest.
            deadline = self.clock() + 120
            while True:
                with self.lock:
                    if not current(): return
                    resting = self.clock()-max(self.last_started, self.last_finished) < self.cooldown
                    if not self.busy and not resting:
                        request_id = uuid.uuid4().hex
                        self.busy = True
                        self.victory_pending = False
                        self.last_started = self.clock()
                        self.cooldown = RULES["danceRestSeconds"]
                        self._event("requested", requestId=request_id, preset="actions/ROCKYOU.json",
                                    tier="victory", reason="Lichess confirmed your win.")
                        target = self.target
                        break
                    if self.clock() >= deadline:
                        self._event("skipped", reason="Victory wait expired; no dance submitted.")
                        return
                self.victory_wait(.1)
            # Use the same SSH identity, helper preflight and terminal-result path.
            self._run(target, "actions/ROCKYOU.json", request_id, generation, "victory")
        except Exception:
            with self.lock:
                if current(): self._event("skipped", reason="Could not verify the final game result; no automatic retry.")
        finally:
            self.disarm(session)  # Scoped: an old worker cannot disarm a newer game.

    def reconcile(self, payload: dict, game_reader, *, timeout=1.5, wait=time.sleep) -> dict:
        """Briefly await the existing bot stream, never retry a robot command.

        Only an otherwise available armed demo may wait. A disarm/rearm, busy
        action, terminal game, mismatch, or deadline ends this observation.
        """
        with self.lock:
            generation = self.generation
            can_wait = (self.armed and payload.get("gameId") == self.game_id and not self.busy
                        and self.clock() - max(self.last_started, self.last_finished) >= self.cooldown)
            deadline = self.clock() + max(0, min(timeout, 1.5))
        while True:
            with self.lock:
                if generation != self.generation:
                    return self._event("skipped", reason="Demo changed while awaiting the game stream; no action queued.")
                if can_wait and self.clock() > deadline:
                    return self._event("skipped", gameId=payload.get("gameId"),
                        reason="Lichess did not confirm this move within the brief sync window; no action queued.")
            game = game_reader(str(payload.get("gameId", "")))
            with self.lock:
                if generation != self.generation:
                    return self._event("skipped", reason="Demo changed while awaiting the game stream; no action queued.")
                if can_wait and self.clock() > deadline:
                    return self._event("skipped", gameId=payload.get("gameId"),
                        reason="Lichess did not confirm this move within the brief sync window; no action queued.")
                outcome = self.celebrate(payload, game, defer_stream=can_wait)
                if outcome.get("status") != "awaiting_stream":
                    return outcome
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return self._event("skipped", gameId=payload.get("gameId"),
                        reason="Lichess did not confirm this move within the brief sync window; no action queued.")
            wait(min(0.05, remaining))

    def celebrate(self, payload: dict, game: dict | None, *, defer_stream=False) -> dict:
        if not isinstance(payload.get("recordId"), str):
            raise ValueError("A server recordId is required.")
        with self.lock:
            entry = self.records.get(payload.get("recordId"))
            if not entry:
                return self._event("skipped", reason="No fresh server engine result.")
            created, record = entry
            reason = None
            stream_pending = False
            if self.clock() - created > 30 or created < self.armed_at:
                reason = "Analysis is stale or predates arming."
            elif record["gameId"] != payload.get("gameId") or record["playerColor"] != payload.get("playerColor"):
                reason = "Game or player does not match the engine result."
            elif not game:
                stream_pending = True
                reason = "No active game in the existing Lichess bot stream."
            elif game.get("state", {}).get("status") not in {"started", "created"}:
                reason = "No active game in the existing Lichess bot stream."
            elif not isinstance(game.get("updatedAt"), (int, float)) or time.time() * 1000 - game["updatedAt"] > 30000:
                stream_pending = True
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
                    if target_ply >= len(moves):
                        stream_pending = True
                        raise ValueError("Move not yet in stream")
                    if target_ply < 0:
                        raise ValueError("Move predates the initial position")
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
                if defer_stream and stream_pending:
                    return {"status": "awaiting_stream"}
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
                                {"tier":"sad" if classification == "blunder" else "major" if scenario == "major" else "small",
                                 "reason":"Synthetic tier example; not a real engine/material signal.", "briefOnly":False})

    def _submit(self, record: dict, decision=None) -> dict:
        fields = {key: record.get(key) for key in ("gameId", "ply", "playedMove", "classification", "synthetic")}
        if not self.armed:
            return self._event("skipped", reason="Demo is disarmed.", **fields)
        if self.finish_pending:
            return self._event("skipped", reason="Match is finishing; move reactions are closed.", **fields)
        if record["gameId"] != self.game_id:
            return self._event("skipped", reason="Another game is selected.", **fields)
        if record["classification"] not in GOOD_LABELS | {"blunder"}:
            return self._event("skipped", reason="No reaction for this coach classification.", **fields)
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
        # Classification comes from the stored server result, never the client.
        tier = "sad" if record["classification"] == "blunder" else decision["tier"]
        if tier not in {"small", "major", "sad"} or (tier == "sad" and record["classification"] != "blunder"):
            return self._event("skipped", reason="No eligible reaction for this verdict.", **fields)
        pace_reason = decision.get("paceReason")
        practice_reward = self.session_kind == "capture-practice" and record.get("practiceReward") is True
        if tier == "major" and not practice_reward and (decision.get("briefOnly") or (
                not decision.get("demoCapture") and self.clock()-self.last_dance_finished < RULES["danceIntervalSeconds"])):
            tier = "small"
            pace_reason = pace_reason or "Full dance is within its three-minute interval; using a brief acknowledgment."
        preset = self.preset
        if tier == "sad":
            # GRIEVANCE includes body movement; never treat it as a brief gesture.
            if decision.get("briefOnly"):
                return self._event("skipped", reason="Sad body performance disabled for fast, low, or unverified clocks.", tier=tier, **fields)
            if self.clock()-self.last_dance_finished < RULES["danceIntervalSeconds"]:
                return self._event("skipped", reason="Sad performance is within the three-minute body-performance interval; not queued.", tier=tier, **fields)
            if self.mode == "live" and not self._verified_entry(self.target, SAD_PRESET):
                return self._event("skipped", reason="Sad reaction needs a supervised GRIEVANCE rehearsal on this robot before live use.", tier=tier, **fields)
            preset = SAD_PRESET
        if tier == "small":
            pool = self._small_presets(self.target) if self.mode == "live" else list(SMALL_PRESETS)
            if decision.get("briefOnly"):
                pool = [p for p in pool if p in HEAD_PRESETS]
            if not pool:
                return self._event("skipped", reason="No rehearsed brief preset is available for this pace/target.", tier=tier, **fields)
            preset = self._choose_small(pool)
        self.cooldown = RULES["danceRestSeconds"] if tier in {"major", "sad"} else RULES["smallRestSeconds"]
        self.last_started = self.clock()
        context = {"tier":tier, "reason":decision["reason"], "paceReason":pace_reason,
                   "metrics":decision.get("metrics"), "preset":preset, **fields}
        if self.mode == "rehearsal":
            if tier in {"major", "sad"}: self.last_dance_finished = self.clock()
            return self._event("rehearsed", message="Would request this acknowledgment; no robot contacted.", **context)
        self.busy = True
        request_id = uuid.uuid4().hex
        generation = self.generation
        self._event("requested", requestId=request_id, **context)
        threading.Thread(target=self._run, args=(self.target, preset, request_id, generation, tier), daemon=True).start()
        return {"status":"requested", "requestId":request_id, "tier":tier, "preset":preset}

    def _run(self, target, preset, request_id, generation, tier="small"):
        try:
            self._sync_network(force=True)
            with self.lock:
                if not self.armed or generation != self.generation:
                    self._event("skipped", requestId=request_id, reason="Disarmed before dispatch.")
                    return
                verify_identity = tier in {"sad", "victory"} or self.compatibility.get("basis") == "tested-preset" or self._demo_approved(target, preset)
            if verify_identity and (not (self._verified_entry(target, preset) or self._demo_approved(target, preset)) or not self._identity_matches(target)):
                raise RobotNotReady("The saved SSH host key no longer matches the rehearsed robot. No goal submitted.")
            with self.lock:
                if not self.armed or generation != self.generation:
                    self._event("skipped",requestId=request_id,reason="Connection/session changed before dispatch.")
                    return
            outcome = self.sender(target, preset, request_id)
            with self.lock:
                self._event(outcome["status"], requestId=request_id, **{"preset":preset, "tier":tier, **{k: v for k, v in outcome.items() if k != "status"}})
                if outcome.get("readyForNext") is False:
                    self.readiness = None
                    self.readiness_at = float("-inf")
                    self.armed = False
                    self._event("not_ready", requestId=request_id,
                                reason=outcome.get("postflightReason") or "Robot is not ready for another action. Inspect and rearm onsite.")
        except (RobotNotReady, RobotRejected) as error:
            with self.lock:
                self.readiness = None
                self.readiness_at = float("-inf")
                self.armed = False
                self._event("not_ready" if isinstance(error, RobotNotReady) else "rejected",
                            requestId=request_id, reason=str(error))
        except Exception:
            with self.lock:
                self.readiness = None
                self.readiness_at = float("-inf")
                self.armed = False
                self._event("unknown", requestId=request_id,
                            message="Robot action not confirmed. Demo disarmed; inspect the robot before rearming. No automatic retry.")
        finally:
            with self.lock:
                self.busy = False
                self.last_finished = self.clock()
                if tier in {"major", "sad"}: self.last_dance_finished = self.clock()


demo = VbotDemo(network_book=NetworkBook())
