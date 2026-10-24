#!/usr/bin/env python3
"""One bounded, identified VBOT RCP preset. Default invocation is an offline preview."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import pwd
import queue
import re
import signal
import time
import uuid

PRESETS = ("actions/ROCKYOU.json", "actions/CHEER_R.json", "actions/WAVE.json",
           "atom/look_left.json", "atom/look_right.json", "atom/look_forward.json",
           "atom/look_up.json", "atom/look_down.json", "actions/SHAKEHAND.json",
           "actions/SHAKEHAND_L.json", "actions/HIGH_FIVE_R.json", "actions/HIGH_FIVE_L.json",
           "actions/SAYYES.json", "actions/GRIEVANCE.json")
SESSION = "/opt/vita/aorta/edu/edu_session.json5"
VERSIONS = {"aorta-sdk": "2026.9.23", "aorta-msgs": "2026.9.23", "vbot-edu-msgs": "2026.9.24", "flatbuffers": "25.12.19"}
SCHEMA_HASH = "a8584e3f6c005fea6579d699c6991f97b2482e01df228a537e3d89e1323eb818"


def text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def diagnostic(value):
    value = text(value)
    if re.search(r"password|token|secret|authorization|credential|cookie|bearer", value, re.I):
        return "[Credential-like diagnostic omitted.]"
    return value[:1500]


def readiness_details(samples):
    battery, system, body, head = (samples.get(key, []) for key in ("battery", "system", "body", "head"))
    def blocked(code, reason):
        return {"ready": False, "code": code, "reason": reason}
    if len(battery) < 2 or len(system) < 2 or len(body) < 3 or len(head) < 2:
        return blocked("incomplete", "Fresh robot telemetry is incomplete.")
    if len({m["heartbeat"] for m in system}) < 2 or len({m["heartbeat"] for m in body}) < 3:
        return blocked("stale", "Robot state heartbeats are not advancing.")
    if any(m["soc"] < 50 or m["charger"] or m["alarm"] != 0 for m in battery):
        return blocked("battery", "Battery must be at least 50%, unplugged, and reporting no BMS alarm.")
    if any(m["powerSaving"] or not m["active"] or m["severity"] != 0 or m["state"] != "FUNCTION" for m in system):
        return blocked("system", "Robot must be active in FUNCTION, outside low power mode, with severity zero.")
    if any(m["posture"] != 1 or m["motion"] != 0 or m["action"] != "RL_TROT" for m in body):
        return blocked("posture", "Robot must be standing idle. Inspect it onsite, stand it using the app, then rearm.")
    if any(m["fault"] for m in head):
        return blocked("head_fault", "Head reports a fault. Inspect the robot before rearming.")
    if any(m["pending"] for m in head):
        return blocked("head_pending", "Head still has a pending action.")
    if any(m["state"] != 0 for m in head):
        return blocked("head_busy", "Head is still busy.")
    return {"ready": True, "code": "ready", "reason": None}


def readiness_problem(samples):
    return readiness_details(samples)["reason"]


def settle_postflight(read_check, *, timeout=12, clock=time.monotonic, wait=time.sleep):
    """Observe settling after known completion; never submit or retry a goal.

    Only head busy/pending can be observed again. A fault or any other failed
    gate stops immediately. Every attempt rechecks ALL fresh safety telemetry.
    """
    started = clock()
    deadline = started + timeout
    attempts = 0
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        result = read_check(min(8, remaining))
        attempts += 1
        if result["ready"] or result.get("code") not in {"head_busy", "head_pending"}:
            return {**result, "attempts": attempts, "waitedSeconds": round(clock() - started, 2)}
        remaining = deadline - clock()
        if remaining <= 0:
            break
        wait(min(.25, remaining))
    return {"ready": False, "code": "settling_timeout",
            "reason": "Head did not settle within the post-action observation window. Inspect it before rearming.",
            "attempts": attempts, "waitedSeconds": round(clock() - started, 2)}


def check_readiness(node, sdk, *, timeout=8, detailed=False):
    """Fresh bounded subscriptions only; never change posture, mode, or services."""
    from bms.BmsState import BmsState
    from sm.SmStatus import SmStatus
    from locomotion.LocomotionStatus import LocomotionStatus
    from locomotion.HeadStatus import HeadStatus
    deadline = time.monotonic() + timeout
    def observe(route, cls, extract, count, predicate=lambda m: True):
        inbox = queue.Queue(maxsize=16)
        def receive(payload, context):
            try: inbox.put_nowait(bytes(payload))
            except queue.Full: pass
        samples = []
        with node.create_subscriber(route, receive, options=sdk.SubscriberOptions(receive_depth=16)):
            while len(samples) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError("Fresh telemetry deadline")
                message = cls.GetRootAs(inbox.get(timeout=remaining), 0)
                if predicate(message): samples.append(extract(message))
        return samples
    try:
        samples = {
            "battery": observe("/bms_state", BmsState, lambda m: dict(soc=m.SocPercent(), charger=m.IsChargerConnected(), alarm=m.Alarm()), 2),
            "system": observe("/system/sm_status", SmStatus, lambda m: dict(heartbeat=m.HeartbeatSeq(), state=text(m.StateName()), powerSaving=m.InPowerSaving(), severity=m.Severity(), active=m.IsActive()), 2, lambda m: m.Category() == 0),
            "body": observe("/locomotion/status", LocomotionStatus, lambda m: dict(heartbeat=m.HeartbeatSeq(), posture=m.Posture(), motion=m.Motion(), action=text(m.CurrentAction())), 3),
            "head": observe("/locomotion/head_status", HeadStatus, lambda m: dict(state=m.State(), pending=text(m.PendingAction()), fault=text(m.FaultReason())), 2),
        }
        result = readiness_details(samples)
    except Exception:
        result = {"ready": False, "code": "telemetry", "reason": "Fresh readiness telemetry could not be verified. Inspect the robot and connection before rearming."}
    return result if detailed else result["reason"]


def emit(**fields):
    print(json.dumps(fields), flush=True)


def make_goal(preset):
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.services.rcp.DagInput import DagInput
    from aorta.services.rcp.DagPresetRef import DagPresetRefT
    return ExecuteTaskGoalT(source="chess-coach-demo", inputType=DagInput.DagPresetRef,
                            input=DagPresetRefT(relativePath=preset, templateArgs=[]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-motion", action="store_true")
    parser.add_argument("--check-ready", action="store_true", help="Read-only live telemetry/provider check; never submits a goal")
    parser.add_argument("--preset", choices=PRESETS, default=PRESETS[0])
    parser.add_argument("--request-id", default=uuid.uuid4().hex)
    args = parser.parse_args(argv)
    try:
        if uuid.UUID(args.request_id).hex != args.request_id:
            raise ValueError()
    except (ValueError, AttributeError):
        parser.error("request-id must be a lowercase 32-character UUID hex string")
    if not args.execute and not args.check_ready:
        emit(event="preview", execute=False, requestId=args.request_id,
             route="/rcp/execute_task", input_type="DagPresetRef",
             input={"relative_path": args.preset}, expected_application="V1.6.0")
        return 0
    if args.execute and not args.confirm_motion:
        parser.error("--execute also requires --confirm-motion after onsite checks")
    if pwd.getpwuid(os.geteuid()).pw_name != "vbot" or platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        raise RuntimeError("Execute only on the ARM64 robot as vbot. Use the default offline preview on a Mac.")
    if not os.access(SESSION, os.R_OK):
        raise RuntimeError("The documented EDU session file is unavailable.")
    for name, version in VERSIONS.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"Install the documented SDK pairing: {name}=={version}")
    # Process-local native SDK environment; never source or modify shell configuration.
    os.environ["ZENOH_SESSION_CONFIG_URI"] = SESSION
    import aorta as sdk
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.action.rcp.ExecuteTaskResult import ExecuteTaskResultT
    from aorta.action.rcp.ExecuteTaskFeedbackData import ExecuteTaskFeedbackDataT
    directory = Path(__file__).resolve().parent
    requests = directory / "requests"
    unresolved = directory / "unresolved-action.json"
    if unresolved.exists():
        raise FileExistsError("An unresolved request requires inspection before another submission.")
    goal_id = args.request_id
    handle = None
    terminal_observed = False
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    with sdk.Node("edu_sdk") as node:
        codec = sdk.FlatbuffersActionCodec(goal=ExecuteTaskGoalT, result=ExecuteTaskResultT,
                                           feedback=ExecuteTaskFeedbackDataT)
        with node.create_action_client("/rcp/execute_task", codec,
                options=sdk.ActionClientOptions(control_timeout_ms=3000, info_timeout_ms=3000)) as client:
            info = client.info()
            if info is None or not info.supports_cancel or info.schema_hash_hex != SCHEMA_HASH:
                raise RuntimeError("A cancellable RCP provider with the exact client schema is required.")
            readiness = check_readiness(node, sdk, detailed=True)
            if args.check_ready:
                emit(event="readiness", requestId=args.request_id, **readiness)
                return 0 if readiness["ready"] else 1
            if not readiness["ready"]:
                emit(event="not_ready", requestId=args.request_id, **readiness)
                return 1
            requests.mkdir(mode=0o700, exist_ok=True)
            record = {"requestId": args.request_id, "preset": args.preset, "goalId": goal_id}
            # Keep handled IDs across reconnects; no goal is sent before both exclusive records exist.
            with (requests / (args.request_id + ".json")).open("x") as file:
                json.dump(record, file)
            with unresolved.open("x") as file:
                json.dump({"requestId": args.request_id, "goalId": goal_id, "preset": args.preset}, file)
            emit(event="submitting", requestId=args.request_id, goalId=goal_id, preset=args.preset)
            try:
                handle = client.send_goal_with_id(goal_id, codec.serialize(make_goal(args.preset)))
                deadline = time.monotonic() + 90
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Dance deadline expired")
                    try:
                        result = handle.wait_result(timeout=min(0.25, remaining))
                        break
                    except sdk.TimeoutError:
                        continue
                terminal_observed = result.status in {
                    sdk.ActionStatus.SUCCEEDED, sdk.ActionStatus.CANCELED, sdk.ActionStatus.ABORTED}
                if not terminal_observed:
                    raise RuntimeError("Action result did not contain a terminal lifecycle state")
                data = ExecuteTaskResultT.InitFromPackedBuf(result.result, 0) if result.result else None
                postflight = (settle_postflight(lambda timeout: check_readiness(node, sdk, timeout=timeout, detailed=True))
                              if result.status == sdk.ActionStatus.SUCCEEDED else
                              {"ready": False, "code": "action_failed", "reason": "Inspect the failed/canceled task before rearming."})
                summary = dict(event="terminal", requestId=args.request_id, goalId=goal_id,
                               status=result.status.name, code=result.code.name, message=diagnostic(result.message),
                               durationMs=data.durationMs if data else None,
                               errorCategory=data.errorCategory if data else None,
                               readyForNext=postflight["ready"], postflightReason=postflight["reason"],
                               postflightReadiness=postflight)
                emit(**summary)
                record["terminal"] = summary
                temporary = requests / (args.request_id + ".terminal.tmp")
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as file:
                    json.dump(record, file)
                os.replace(temporary, requests / (args.request_id + ".json"))
                return 0 if result.status == sdk.ActionStatus.SUCCEEDED and data and data.errorCategory == 0 else 1
            finally:
                if not terminal_observed and handle is not None:
                    try:
                        handle.cancel()
                        terminal = handle.wait_result(timeout=5)
                        terminal_observed = terminal.status in {
                            sdk.ActionStatus.SUCCEEDED, sdk.ActionStatus.CANCELED, sdk.ActionStatus.ABORTED}
                        emit(event="cleanup", requestId=args.request_id, status=terminal.status.name)
                    except Exception:
                        emit(event="unknown", requestId=args.request_id, goalId=goal_id,
                             message="Cancellation not confirmed. Use the onsite stop and inspect the task.")
                if terminal_observed:
                    unresolved.unlink()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        emit(event="interrupted", outcome="Inspect terminal/cancellation status; do not retry automatically.")
        raise SystemExit(130)
    except Exception as error:
        # Do not expose SDK configuration, credentials or arbitrary provider messages.
        emit(event="error", error=type(error).__name__,
             message="Action failed or outcome unknown. Check SDK setup, pending task and handset before retrying.")
        raise SystemExit(1)
