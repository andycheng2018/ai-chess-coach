#!/usr/bin/env python3
"""Offline generated-code and action-lifecycle witnesses. Never creates a real Node."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import aorta as sdk
import flatbuffers
from aorta.action.rcp.ExecuteTaskGoal import ExecuteTaskGoalT
from aorta.action.rcp.ExecuteTaskResult import ExecuteTaskResultT
from aorta.action.rcp.ExecuteTaskFeedbackData import ExecuteTaskFeedbackDataT
from aorta.services.rcp.DagInput import DagInput

spec = importlib.util.spec_from_file_location("robot_action", Path(__file__).with_name("robot_action.py"))
robot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(robot)


class SDKChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = MagicMock()
        self.client.info.return_value = SimpleNamespace(supports_cancel=True, schema_hash_hex=robot.SCHEMA_HASH)
        self.handle = self.client.send_goal_with_id.return_value
        self.node = MagicMock()
        self.node.create_action_client.return_value.__enter__.return_value = self.client
        self.node_ctor = patch.object(sdk, "Node")
        constructor = self.node_ctor.start()
        constructor.return_value.__enter__.return_value = self.node
        self.addCleanup(self.node_ctor.stop)
        for item in [patch.object(robot, "__file__", str(Path(self.directory.name)/"robot_action.py")),
                     patch.object(robot.pwd, "getpwuid", return_value=SimpleNamespace(pw_name="vbot")),
                     patch.object(robot.platform, "system", return_value="Linux"),
                     patch.object(robot.platform, "machine", return_value="aarch64"),
                     patch.object(robot.os, "access", return_value=True),
                     patch.object(robot, "check_readiness", return_value=None)]:
            item.start(); self.addCleanup(item.stop)
        builder=flatbuffers.Builder(128)
        builder.Finish(ExecuteTaskResultT(durationMs=123,errorCategory=0).Pack(builder))
        self.success=SimpleNamespace(status=sdk.ActionStatus.SUCCEEDED,result=bytes(builder.Output()), code=SimpleNamespace(name="SUCCEEDED"), message="")
        self.handle.wait_result.return_value=self.success

    def run_action(self, request="a"*32):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            result=robot.main(["--execute","--confirm-motion","--request-id",request])
        return result,[json.loads(line) for line in output.getvalue().splitlines()]

    def test_readiness_rejects_resting_busy_fault_stale_or_charging(self):
        from copy import deepcopy
        samples={"battery":[{"soc":80,"charger":False,"alarm":0} for _ in range(2)],
                 "system":[{"heartbeat":i,"state":"FUNCTION","powerSaving":False,"severity":0,"active":True} for i in range(2)],
                 "body":[{"heartbeat":i,"posture":1,"motion":0,"action":"RL_TROT"} for i in range(3)],
                 "head":[{"state":0,"pending":"","fault":""} for _ in range(2)]}
        self.assertIsNone(robot.readiness_problem(samples))
        for family,field,value in [("battery","soc",49),("battery","charger",True),("battery","alarm",1),
                ("system","powerSaving",True),("system","state","EMERGENCY"),("system","severity",1),
                ("body","posture",2),("body","motion",1),("body","heartbeat",1),
                ("head","fault","fault"),("head","pending","busy"),("head","state",1)]:
            changed=deepcopy(samples)
            for sample in changed[family]: sample[field]=value
            with self.subTest(family=family,field=field): self.assertIsNotNone(robot.readiness_problem(changed))
        self.assertIsNotNone(robot.readiness_problem({}))

    def test_every_preset_round_trips_through_real_flatbuffers_codec(self):
        codec=sdk.FlatbuffersActionCodec(goal=ExecuteTaskGoalT,result=ExecuteTaskResultT,feedback=ExecuteTaskFeedbackDataT)
        for preset in robot.PRESETS:
            result=ExecuteTaskGoalT.InitFromPackedBuf(codec.serialize(robot.make_goal(preset)),0)
            self.assertEqual(result.inputType,DagInput.DagPresetRef)
            self.assertEqual(result.input.relativePath.decode(),preset)
        self.client.send_goal_with_id.assert_not_called()

    def test_terminal_success_removes_uncertain_marker_and_retains_request_id(self):
        result,events=self.run_action()
        self.assertEqual(result,0)
        self.assertEqual(events[-1]["status"],"SUCCEEDED")
        self.assertFalse((Path(self.directory.name)/"unresolved-action.json").exists())
        self.assertTrue((Path(self.directory.name)/"requests"/("a"*32+".json")).exists())
        self.client.send_goal_with_id.assert_called_once()

    def test_repeated_id_and_unresolved_admission_never_resubmit(self):
        self.client.send_goal_with_id.side_effect=TimeoutError("uncertain admission")
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(TimeoutError):self.run_action()
        with self.assertRaises(FileExistsError):self.run_action()
        with self.assertRaises(FileExistsError):self.run_action("b"*32)
        self.client.send_goal_with_id.assert_called_once()
        self.assertTrue((Path(self.directory.name)/"unresolved-action.json").exists())

    def test_not_ready_never_creates_goal_or_request_marker(self):
        with patch.object(robot, "check_readiness", return_value="Robot is lying down"):
            result, events = self.run_action()
        self.assertEqual(result, 1)
        self.assertEqual(events[-1]["event"], "not_ready")
        self.client.send_goal_with_id.assert_not_called()
        self.assertFalse((Path(self.directory.name)/"requests").exists())
        self.assertFalse((Path(self.directory.name)/"unresolved-action.json").exists())

    def test_mismatched_schema_never_sends_a_goal(self):
        self.client.info.return_value.schema_hash_hex = "wrong"
        with self.assertRaises(RuntimeError): self.run_action()
        self.client.send_goal_with_id.assert_not_called()

    def test_read_only_readiness_never_sends_a_goal(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(robot.main(["--check-ready"]), 0)
        self.client.send_goal_with_id.assert_not_called()
        self.assertFalse((Path(self.directory.name)/"requests").exists())

    def test_failed_postflight_retains_success_but_blocks_next_action(self):
        with patch.object(robot, "check_readiness", side_effect=[None, "Robot rested"]):
            result, events = self.run_action()
        self.assertEqual(result, 0)
        self.assertEqual(events[-1]["status"], "SUCCEEDED")
        self.assertFalse(events[-1]["readyForNext"])
        saved=json.loads((Path(self.directory.name)/"requests"/("a"*32+".json")).read_text())
        self.assertEqual(saved["terminal"]["postflightReason"], "Robot rested")

    def test_interruption_requests_cancel_and_waits_for_terminal(self):
        self.handle.wait_result.side_effect=[KeyboardInterrupt(),SimpleNamespace(status=sdk.ActionStatus.CANCELED)]
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(KeyboardInterrupt):self.run_action()
        self.handle.cancel.assert_called_once()
        self.assertFalse((Path(self.directory.name)/"unresolved-action.json").exists())

    def test_unconfirmed_cancel_keeps_marker(self):
        self.handle.wait_result.side_effect=[KeyboardInterrupt(),TimeoutError()]
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(KeyboardInterrupt):self.run_action()
        self.assertTrue((Path(self.directory.name)/"unresolved-action.json").exists())


if __name__ == "__main__": unittest.main()
