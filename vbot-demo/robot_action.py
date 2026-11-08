#!/usr/bin/env python3
"""One bounded, identified VBOT RCP preset. Default invocation is an offline preview."""
from __future__ import annotations
import argparse
from collections import deque
from contextlib import ExitStack
import select
import sys
import threading
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

PRESETS = ('actions/ROCKYOU.json', 'actions/CHEER_R.json', 'actions/WAVE.json', 'atom/look_left.json', 'atom/look_right.json', 'atom/look_forward.json', 'atom/look_up.json', 'atom/look_down.json', 'actions/SHAKEHAND.json', 'actions/SHAKEHAND_L.json', 'actions/HIGH_FIVE_R.json', 'actions/HIGH_FIVE_L.json', 'actions/SAYYES.json', 'actions/GRIEVANCE.json', 'actions/HAPPY_LITTLE_JUMP.json', 'actions/HAPPY_JUMP.json', 'actions/JUMP_IN_PLACE.json', 'actions/RHYTHM.json', 'actions/RHYTHMIC_SWING.json', 'actions/RELAXED_SWING.json', 'actions/TWIST_BUTT.json')
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
    if any(m["soc"] < 10 or m["charger"] or m["alarm"] != 0 for m in battery):
        return blocked("battery", "Battery must be at least 10%, unplugged, and reporting no BMS alarm.")
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


def readiness_topics():
    from bms.BmsState import BmsState
    from sm.SmStatus import SmStatus
    from locomotion.LocomotionStatus import LocomotionStatus
    from locomotion.HeadStatus import HeadStatus
    return [
        ('battery', '/bms_state', BmsState, lambda m: dict(soc=m.SocPercent(), charger=m.IsChargerConnected(), alarm=m.Alarm()), 2, lambda m: True),
        ('system', '/system/sm_status', SmStatus, lambda m: dict(heartbeat=m.HeartbeatSeq(), state=text(m.StateName()), powerSaving=m.InPowerSaving(), severity=m.Severity(), active=m.IsActive()), 2, lambda m: m.Category() == 0),
        ('body', '/locomotion/status', LocomotionStatus, lambda m: dict(heartbeat=m.HeartbeatSeq(), posture=m.Posture(), motion=m.Motion(), action=text(m.CurrentAction())), 3, lambda m: True),
        ('head', '/locomotion/head_status', HeadStatus, lambda m: dict(state=m.State(), pending=text(m.PendingAction()), fault=text(m.FaultReason())), 2, lambda m: True),
    ]


class LiveReadiness:
    """Fresh rolling telemetry for one bounded session. No readiness-result cache.

    Retains the original sample counts and predicates. The newest sample on every
    topic must be <=1.5s old and the entire window <=3.5s. Postflight body/head
    samples must all arrive AFTER observing the terminal action result.
    """
    def __init__(self, node, sdk, topics, clock=time.monotonic):
        self.node, self.sdk, self.topics, self.clock = node, sdk, topics, clock
        self.condition = threading.Condition()
        self.samples = {name: deque(maxlen=count) for name, _, _, _, count, _ in topics}
        self.error = False
        self.closed = False
        self.resources = ExitStack()

    def __enter__(self):
        try:
            for name, route, cls, extract, count, predicate in self.topics:
                def receive(payload, context, name=name, cls=cls, extract=extract, predicate=predicate):
                    try:
                        message = cls.GetRootAs(bytes(payload), 0)
                        if not predicate(message): return
                        sample = extract(message)
                        with self.condition:
                            self.samples[name].append((self.clock(), sample))
                            self.condition.notify_all()
                    except Exception:
                        with self.condition:
                            self.error = True
                            self.condition.notify_all()
                self.resources.enter_context(self.node.create_subscriber(route, receive,
                    options=self.sdk.SubscriberOptions(receive_depth=16)))
            return self
        except BaseException:
            self.resources.close()
            raise

    def __exit__(self, *exc):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        return self.resources.__exit__(*exc)

    def check(self, timeout=8, detailed=False, after=None):
        deadline = self.clock() + timeout
        with self.condition:
            while True:
                now = self.clock()
                if self.closed or self.error:
                    result = {'ready': False, 'code': 'telemetry', 'reason': 'The live telemetry session failed or closed.'}
                    break
                complete = all(len(self.samples[name]) == count for name, _, _, _, count, _ in self.topics)
                if complete:
                    stale = any(now - values[-1][0] > 1.5 or now - values[0][0] > 3.5 for values in self.samples.values())
                    if stale:
                        result = {'ready': False, 'code': 'stale', 'reason': 'Live robot telemetry is stale. No next cue submitted.'}
                        break
                    settled_samples = after is None or all(self.samples[name][0][0] > after for name in ('body', 'head'))
                    if settled_samples:
                        result = readiness_details({name: [sample for _, sample in values] for name, values in self.samples.items()})
                        break
                remaining = deadline - now
                if remaining <= 0:
                    result = {'ready': False, 'code': 'telemetry', 'reason': 'Fresh live telemetry did not arrive before the deadline.'}
                    break
                self.condition.wait(min(.05, remaining))
        return result if detailed else result['reason']


STATIC_TASKS = {'actions/ROCKYOU.json': 'rockyou_30s'}
TRANSIENT_GATES = {'head_busy', 'head_pending', 'posture', 'not_static'}


def precondition_refusal(result, task_name):
    """Narrow root refusal, never a generic ABORTED/timeout/partial DAG failure."""
    if not result or result.get('status') != 'ABORTED' or result.get('code') != 'HANDLER_ERROR' or result.get('durationMs') is not None:
        return False
    try:
        detail = json.loads(result.get('message', ''))
    except (ValueError, TypeError):
        return False
    if not isinstance(detail, dict) or not isinstance(detail.get('taskError'), dict):
        return False
    message = detail['taskError'].get('message', '')
    return (detail.get('schemaVersion') == 1 and detail.get('task_name') == task_name
            and detail.get('error_category') == 7 and detail.get('error_category_str') == 'PRECONDITION_FAILED'
            and detail['taskError'].get('code') == 'rcp.execution.precondition_failed'
            and isinstance(message, str) and message.startswith('Precondition check failed:')
            and "Precondition 'is_robot_static' failed" in message
            and 'false == true evaluated to false' in message
            and not any(key in detail or key in detail['taskError'] for key in ('failed_at', 'failedAt', 'completed_nodes')))


def make_static_probe(request_id):
    """Only a 1 ms Sleep with a root predicate; no static setup or motion node."""
    from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
    from aorta.services.rcp.DagInput import DagInput
    from aorta.services.rcp.DagSpec import DagSpecT
    from aorta.services.rcp.DagNode import DagNodeT
    from aorta.services.rcp.NodeCommand import NodeCommand
    from aorta.services.rcp.SleepCommand import SleepCommandT
    from aorta.services.rcp.PreconditionExpr import PreconditionExprT
    from aorta.services.rcp.ConditionValue import ConditionValueT
    return ExecuteTaskGoalT(source='chess-coach-static-probe', inputType=DagInput.DagSpec,
        input=DagSpecT(taskId='chess-static-probe-'+request_id, skipBatchPreCheck=False, requiresStatic=False,
            requiredResources=[], optionalResources=[],
            preconditions=PreconditionExprT(key='is_robot_static', value=ConditionValueT(kind=1, boolValue=True)),
            nodes=[DagNodeT(id='observe-only', dependencies=[], executionTimeoutMs=1000, lifecycle=1,
                commandType=NodeCommand.SleepCommand, command=SleepCommandT(durationMs=1))]))


def rescan_cue(preset, read_check, static_check, perform, canceled, announce,
               *, clock=time.monotonic, wait=time.sleep, timeout=30, max_attempts=3):
    """One logical cue. Repeat observations, only retry a verified root refusal.

    perform raises on unknown outcomes; those exceptions are never caught here.
    Static-check goals contain no motion. The original show confirmations remain
    required, and operator cancellation is polled before EVERY movement attempt.
    """
    deadline = clock() + timeout
    attempts, scans, after = 0, 0, None
    reason = 'Waiting for fresh safety conditions.'
    def blocked(code, message):
        return {'event': 'not_ready', 'ready': False, 'code': code, 'reason': message,
                'attemptCount': attempts, 'rescanCount': scans}
    while clock() < deadline:
        if canceled(): return blocked('operator_stop', 'Stopped before the next movement attempt.')
        scans += 1
        ready = read_check(timeout=min(1, max(.01, deadline-clock())), detailed=True, after=after)
        if ready['ready'] and preset in STATIC_TASKS:
            ready = static_check()
        if not ready['ready']:
            reason = ready.get('reason') or 'Waiting for the robot to settle.'
            if ready.get('code') not in TRANSIENT_GATES:
                return blocked(ready.get('code', 'not_ready'), reason)
            announce({'phase': 'rescanning', 'reason': reason, 'attemptCount': attempts, 'rescanCount': scans})
            after = clock()
            if canceled(): return blocked('operator_stop', 'Stopped during safety rescans.')
            wait(min(.25, max(0, deadline-clock())))
            continue
        if canceled(): return blocked('operator_stop', 'Stopped before the movement command.')
        if clock() >= deadline: break
        announce({'phase': 'acting', 'reason': None, 'attemptCount': attempts+1, 'rescanCount': scans})
        result = perform()
        if result is None:  # execute_preset positively refused BEFORE submitting a goal.
            after = clock()
            wait(min(.25, max(0, deadline-clock())))
            continue
        attempts += 1
        if canceled():
            return {**result, 'stopRequested': True, 'attemptCount': attempts, 'rescanCount': scans}
        if (preset in STATIC_TASKS and precondition_refusal(result, STATIC_TASKS[preset])
                and attempts < max_attempts):
            reason = 'Dance refused before execution: waiting for the provider’s static condition.'
            announce({'phase': 'rescanning', 'reason': reason, 'attemptCount': attempts, 'rescanCount': scans})
            after = clock()
            wait(min(.25, max(0, deadline-clock())))
            continue
        return {**result, 'attemptCount': attempts, 'rescanCount': scans}
    return blocked('rescan_timeout', 'Safety rescan window expired. No further movement attempts. ' + reason)


def execute_preset(args, node, sdk, client, codec, result_type, read_check, *, goal_factory=None, publish=True, action_timeout=90):
    """Shared one-shot execution; a session never bypasses this guarded path."""
    directory = Path(__file__).resolve().parent
    requests = directory / "requests"
    unresolved = directory / "unresolved-action.json"
    if unresolved.exists():
        raise FileExistsError("An unresolved request requires inspection before another submission.")
    goal_id, handle, terminal_observed = args.request_id, None, False
    ExecuteTaskResultT = result_type
    readiness = read_check(timeout=8, detailed=True)
    if not readiness["ready"]:
        emit(event="not_ready", requestId=args.request_id, **readiness)
        return None
    requests.mkdir(mode=0o700, exist_ok=True)
    record = {"requestId": args.request_id, "preset": args.preset, "goalId": goal_id, "logicalRequestId": getattr(args, "logical_request_id", None)}
    # Keep handled IDs across reconnects; no goal is sent before both exclusive records exist.
    with (requests / (args.request_id + ".json")).open("x") as file:
        json.dump(record, file)
    with unresolved.open("x") as file:
        json.dump({"requestId": args.request_id, "goalId": goal_id, "preset": args.preset}, file)
    emit(event="submitting", requestId=args.request_id, goalId=goal_id, preset=args.preset)
    try:
        handle = client.send_goal_with_id(goal_id, codec.serialize((goal_factory or make_goal)(args.preset)))
        deadline = time.monotonic() + action_timeout
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
        terminal_at = time.monotonic()
        postflight = (settle_postflight(lambda timeout: read_check(timeout=timeout, detailed=True, after=terminal_at))
                      if result.status == sdk.ActionStatus.SUCCEEDED else
                      {"ready": False, "code": "action_failed", "reason": "Inspect the failed/canceled task before rearming."})
        summary = dict(event="terminal", requestId=args.request_id, goalId=goal_id,
                       status=result.status.name, code=result.code.name, message=diagnostic(result.message),
                       durationMs=data.durationMs if data else None,
                       errorCategory=data.errorCategory if data else None,
                       readyForNext=postflight["ready"], postflightReason=postflight["reason"],
                       postflightReadiness=postflight)
        record["terminal"] = summary
        temporary = requests / (args.request_id + ".terminal.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(record, file)
        os.replace(temporary, requests / (args.request_id + ".json"))
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
    # A session may receive its next cue immediately after this frame. Publish
    # only after the durable result and unresolved-action cleanup are complete.
    if publish:
        emit(**summary)
    return summary

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Bounded identified cue session over stdin; never queues motion")
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
    if args.serve and not (args.execute or args.check_ready):
        parser.error("A session requires explicit execution or read-only checks")
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
    import fcntl
    directory = Path(__file__).resolve().parent
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    with ExitStack() as resources:
        lock = resources.enter_context((directory / "controller.lock").open("a"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / "unresolved-action.json").exists():
            raise FileExistsError("An unresolved action requires onsite inspection")
        node = resources.enter_context(sdk.Node("edu_sdk"))
        codec = sdk.FlatbuffersActionCodec(goal=ExecuteTaskGoalT, result=ExecuteTaskResultT,
                                           feedback=ExecuteTaskFeedbackDataT)
        client = resources.enter_context(node.create_action_client("/rcp/execute_task", codec,
                options=sdk.ActionClientOptions(control_timeout_ms=3000, info_timeout_ms=3000)))
        def provider_ready():
            info = client.info()
            if info is None or not info.supports_cancel or info.schema_hash_hex != SCHEMA_HASH:
                raise RuntimeError("A cancellable RCP provider with the exact client schema is required.")
        provider_ready()
        if args.serve:
            live = resources.enter_context(LiveReadiness(node, sdk, readiness_topics()))
            initial = live.check(detailed=True)
            emit(event="session_ready", requestId=args.request_id, protocol=1, rescanProtocol=1, **initial)
            if not initial["ready"]:
                return 1
            deadline = time.monotonic() + 900
            for _ in range(20):
                if time.monotonic() >= deadline or not select.select([sys.stdin], [], [], min(30, max(0, deadline-time.monotonic())))[0]:
                    return 0
                line = sys.stdin.readline(4097)
                if not line:
                    return 0
                if len(line) > 4096 or not line.endswith("\n"):
                    raise ValueError("Invalid session frame")
                command = json.loads(line)
                if command.get("op") == "close":
                    return 0
                request_id = command.get("requestId")
                if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
                    raise ValueError("Invalid cue identity")
                if command.get("op") == "check":
                    emit(event="readiness", requestId=request_id, **live.check(detailed=True))
                    continue
                if not args.execute or command.get("op") != "cue" or command.get("preset") not in PRESETS:
                    raise ValueError("Invalid session cue")
                # Reserve the logical identity before ANY probe or movement. A lost
                # response cannot cause a new session to replay this logical cue.
                requests = directory / 'requests'
                requests.mkdir(mode=0o700, exist_ok=True)
                logical_path = requests / ('logical-' + request_id + '.json')
                logical = {'requestId': request_id, 'preset': command['preset'], 'attemptIds': [], 'probeIds': []}
                with logical_path.open('x') as record:
                    json.dump(logical, record)
                def canceled():
                    if not select.select([sys.stdin], [], [], 0)[0]: return False
                    frame = sys.stdin.readline(4097)
                    if not frame: return True
                    if len(frame) > 4096 or not frame.endswith('\n'): raise ValueError('Invalid cancellation frame')
                    value = json.loads(frame)
                    if value.get('op') == 'close' or (value.get('op') == 'cancel' and value.get('requestId') == request_id): return True
                    raise ValueError('Only cancellation may interrupt a pending cue; pipelining is forbidden')
                def static_check():
                    provider_ready()
                    probe_id = uuid.uuid4().hex
                    logical['probeIds'].append(probe_id)
                    probe = argparse.Namespace(request_id=probe_id, preset='safety/is_robot_static', logical_request_id=request_id)
                    result = execute_preset(probe, node, sdk, client, codec, ExecuteTaskResultT, live.check,
                        goal_factory=lambda _: make_static_probe(probe_id), publish=False, action_timeout=3)
                    if result and result['status'] == 'SUCCEEDED' and result['errorCategory'] == 0:
                        return {'ready': result['readyForNext'], 'code': 'ready' if result['readyForNext'] else 'probe_postflight',
                                'reason': result.get('postflightReason')}
                    if result is None:
                        current = live.check(timeout=1, detailed=True)
                        return current if not current['ready'] else {'ready': False, 'code': 'not_static', 'reason': 'Static probe was not submitted; rescanning before any movement.'}
                    if precondition_refusal(result, 'chess-static-probe-'+probe_id):
                        return {'ready': False, 'code': 'not_static', 'reason': 'Waiting for the provider to confirm is_robot_static.'}
                    return {'ready': False, 'code': 'probe_failed', 'reason': 'The non-motion static-condition probe failed. Inspect the saved probe result.'}
                def perform():
                    provider_ready()
                    attempt_id = uuid.uuid4().hex
                    logical['attemptIds'].append(attempt_id)
                    cue = argparse.Namespace(request_id=attempt_id, preset=command['preset'], logical_request_id=request_id)
                    return execute_preset(cue, node, sdk, client, codec, ExecuteTaskResultT, live.check, publish=False)
                result = rescan_cue(command['preset'], live.check, static_check, perform, canceled,
                    lambda frame: emit(event='rescan', requestId=request_id, **frame),
                    timeout=min(30, max(0, deadline-time.monotonic())))
                logical['result'] = result
                temporary = logical_path.with_suffix('.complete.tmp')
                with temporary.open('x') as record: json.dump(logical, record)
                os.replace(temporary, logical_path)
                # Keep the logical request identity on the wire, actual attempt
                # goal identity in goalId, and every attempt in the device journal.
                emit(**{**result, 'requestId': request_id})
                if result.get('event') == 'not_ready' or result.get('stopRequested') or result.get('status') != 'SUCCEEDED' or result.get('errorCategory') != 0 or result.get('readyForNext') is not True:
                    return 1
            return 0
        if args.check_ready:
            readiness = check_readiness(node, sdk, detailed=True)
            emit(event="readiness", requestId=args.request_id, **readiness)
            return 0 if readiness["ready"] else 1
        result = execute_preset(args, node, sdk, client, codec, ExecuteTaskResultT,
            lambda timeout=8, detailed=True, after=None: check_readiness(node, sdk, timeout=timeout, detailed=detailed))
        return 0 if result and result['status'] == 'SUCCEEDED' and result['errorCategory'] == 0 else 1


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
