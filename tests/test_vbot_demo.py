from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from vbot_demo import VbotDemo, RobotNotReady, RobotRejected, load_verification, send_dance, ssh_command
import app


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.sender = Mock(return_value={"status": "completed", "goalId": "goal"})
        self.demo = VbotDemo(sender=self.sender, clock=lambda: self.now, verification={"target":"vbot@robot.example", "presets":[{"preset":"actions/WAVE.json","status":"SUCCEEDED","errorCategory":0,"movementConfirmed":True}]})
        self.arm()

    def arm(self, mode="rehearsal"):
        return self.demo.arm({"mode": mode, "gameId": "AbCd1234", "target": "vbot@robot.example",
                              "applicationVersion": "V1.6.0", "confirmSafeWorkspace": True, "confirmHandsetStop": True})

    def record(self, **updates):
        import chess
        return {"recordId": "record-1", "gameId": "AbCd1234", "ply": 1, "playerColor": "white",
                "playedMoveUci": "e2e4", "playedMove": "e4", "classification": "good",
                "fenBefore": chess.STARTING_FEN, **updates}

    def game(self, **updates):
        return {"gameId": "AbCd1234", "botColor": "black", "initialFen": "startpos",
                "updatedAt": int(time.time() * 1000), "timeControlKnown":True, "clock":None, "state": {"status": "started", "moves": "e2e4 e7e5"}, **updates}

    def event(self, record=None, game=None, **payload):
        record = record or self.record()
        self.demo.remember(record)
        return self.demo.celebrate({"recordId": record["recordId"], "gameId": record["gameId"],
                                    "playerColor": "white", **payload}, self.game() if game is None else game)

    def wait_idle(self):
        deadline = time.monotonic() + 2
        while self.demo.status()["busy"] and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.demo.status()["busy"])

    def test_startup_disarmed_and_no_connections(self):
        d = VbotDemo(sender=self.sender, verification={})
        self.assertFalse(d.status()["armed"])
        self.sender.assert_not_called()

    def test_real_good_move_rehearses_without_robot(self):
        self.assertEqual(self.event()["status"], "rehearsed")
        self.sender.assert_not_called()

    def test_other_engine_classifications_never_dance(self):
        for label in ["inaccuracy", "mistake"]:
            with self.subTest(label=label):
                self.assertEqual(self.event(self.record(classification=label))["status"], "skipped")
        self.sender.assert_not_called()

    def test_canonical_blunder_previews_sad_and_cannot_be_upgraded_by_client(self):
        result = self.event(self.record(classification="blunder"), classification="good", tier="major")
        self.assertEqual(result["status"], "rehearsed")
        self.assertEqual(result["tier"], "sad")
        self.assertEqual(result["preset"], "actions/GRIEVANCE.json")
        self.sender.assert_not_called()
        self.now += 181
        self.assertIn("already handled", self.event(self.record(recordId="duplicate", classification="blunder"))["reason"])

    def test_synthetic_blunder_preview_never_becomes_major(self):
        result = self.demo.rehearse("blunder", "major")
        self.assertEqual(result["tier"], "sad")
        self.assertTrue(result["synthetic"])
        self.sender.assert_not_called()

    def test_client_cannot_upgrade_engine_mistake_to_good(self):
        result = self.event(self.record(classification="mistake"), classification="good")
        self.assertEqual(result["status"], "skipped")

    def test_unknown_record_and_invalid_id_never_dispatch(self):
        self.assertEqual(self.demo.celebrate({"recordId": "forged"}, self.game())["status"], "skipped")
        with self.assertRaises(ValueError): self.demo.celebrate({"recordId": []}, self.game())

    def test_duplicate_ply_even_with_new_record_id_is_suppressed(self):
        self.assertEqual(self.event()["status"], "rehearsed")
        self.now += 21
        self.assertIn("already handled", self.event(self.record(recordId="record-2"))["reason"])

    def test_stale_and_prearm_results_are_rejected(self):
        record = self.record()
        self.demo.remember(record)
        self.now += 31
        self.assertIn("stale", self.demo.celebrate({"recordId": "record-1"}, self.game())["reason"])
        self.demo.remember(record)
        self.now += 1
        self.arm()
        self.assertIn("predates", self.demo.celebrate({"recordId": "record-1"}, self.game())["reason"])

    def test_selected_game_and_player_must_match(self):
        self.assertEqual(self.event(gameId="other123")["status"], "skipped")
        self.assertEqual(self.event(playerColor="black")["status"], "skipped")
        self.demo.arm({"gameId": "Other123", "mode": "rehearsal"})
        self.assertEqual(self.event()["status"], "skipped")

    def test_opponent_moves_missing_and_terminal_streams_rejected(self):
        for game in [self.game(botColor="white"), self.game(botColor=None), {},
                     self.game(state={"status": "mate", "moves": "e2e4"}), self.game(updatedAt=0),
                     self.game(state={"status": "started", "moves": "d2d4"}),
                     self.game(state={"status": "started", "moves": ""})]:
            with self.subTest(game=game): self.assertEqual(self.event(game=game)["status"], "skipped")

    def test_same_uci_in_different_position_is_rejected(self):
        import chess
        other = chess.Board(); other.push_uci("d2d4"); other.push_uci("d7d5")
        self.assertEqual(self.event(self.record(fenBefore=other.fen()))["status"], "skipped")

    def test_takeback_branch_change_clears_baseline_without_replaying_duplicate(self):
        self.event()
        self.demo.policy.points.append({"cp":-200,"ply":1})
        changed=self.game(state={"status":"started","moves":"e2e4 c7c5"})
        self.now+=21
        self.assertEqual(self.event(self.record(recordId="new-record"),game=changed)["status"],"skipped")
        self.assertEqual(len(self.demo.policy.points),0)
        self.sender.assert_not_called()

    def test_black_human_and_bot_reply_are_supported(self):
        import chess
        board = chess.Board(); board.push_uci("e2e4")
        record = self.record(ply=2, playerColor="black", playedMoveUci="e7e5", playedMove="e5", fenBefore=board.fen())
        result = self.event(record, self.game(botColor="white"), playerColor="black")
        self.assertEqual(result["status"], "rehearsed")

    def test_cooldown_skips_instead_of_queuing_or_replaying(self):
        self.assertEqual(self.event()["status"], "rehearsed")
        self.assertEqual(self.demo.rehearse("good")["status"], "skipped")
        self.now += 21
        self.assertEqual(self.demo.rehearse("good")["status"], "rehearsed")
        self.sender.assert_not_called()

    def test_disarm_stops_future_dispatch_and_rearm_does_not_replay(self):
        self.event(); self.demo.disarm(); self.now += 21
        self.assertEqual(self.event()["status"], "skipped")
        self.arm()
        self.assertEqual(self.event()["status"], "skipped")

    def test_live_arm_requires_target_version_and_onsite_checks(self):
        for field,value in [("target", ""), ("target", "-oProxyCommand=bad"), ("applicationVersion", "V1.5.0"),
                            ("confirmSafeWorkspace", False), ("confirmHandsetStop", False)]:
            payload = {"mode":"live", "gameId":"AbCd1234", "target":"vbot@robot.example",
                       "applicationVersion":"V1.6.0", "confirmSafeWorkspace":True, "confirmHandsetStop":True, field:value}
            with self.subTest(field=field), self.assertRaises(ValueError): self.demo.arm(payload)
        self.sender.assert_not_called()

    def test_live_success_requires_worker_terminal_result(self):
        self.arm("live")
        self.assertEqual(self.event()["status"], "requested")
        self.wait_idle()
        self.sender.assert_called_once()
        self.assertEqual(self.demo.status()["events"][0]["status"], "completed")

    def test_lost_connection_disarms_and_never_retries(self):
        self.sender.side_effect = TimeoutError()
        self.arm("live"); self.event(); self.wait_idle()
        self.assertFalse(self.demo.status()["armed"])
        self.assertEqual(self.demo.status()["events"][0]["status"], "unknown")
        self.now += 21
        self.event(); self.sender.assert_called_once()

    def test_busy_skips_and_manual_samples_cannot_trigger_live_motion(self):
        finish = threading.Event()
        self.sender.side_effect = lambda *a: (finish.wait(2), {"status":"completed"})[1]
        self.arm("live"); self.event()
        try:
            with self.assertRaises(ValueError): self.demo.rehearse("good")
            with self.assertRaises(ValueError): self.arm()
            self.assertTrue(self.demo.status()["busy"])
        finally: finish.set(); self.wait_idle()
        self.sender.assert_called_once()


class VerifiedPresetTests(unittest.TestCase):
    def setUp(self):
        self.profile={"target":"vbot@robot.example", "hostKeyFingerprint":"SHA256:"+"a"*43,
                      "presets":[{"preset":"actions/ROCKYOU.json", "status":"SUCCEEDED",
                                  "errorCategory":0,"movementConfirmed":True}, {"preset":"actions/WAVE.json", "status":"SUCCEEDED","errorCategory":0,"movementConfirmed":True}]}
        self.sender=Mock(return_value={"status":"completed", "readyForNext":True})
        self.keys=Mock(return_value={self.profile["hostKeyFingerprint"]})
        self.demo=VbotDemo(sender=self.sender, verification=self.profile, fingerprint_reader=self.keys)
        self.payload={"mode":"live", "gameId":"AbCd1234", "target":"vbot@robot.example",
                      "applicationVersion":"unknown", "confirmSafeWorkspace":True,"confirmHandsetStop":True}

    def wait_idle(self):
        deadline=time.monotonic()+2
        while self.demo.status()["busy"] and time.monotonic()<deadline: time.sleep(.005)
        self.assertFalse(self.demo.status()["busy"])

    def submit(self, tier="small"):
        with self.demo.lock:
            return self.demo._submit({"gameId":"AbCd1234", "ply":1,"playerColor":"white",
                                      "playedMove":"e4","classification":"good"}, {"tier":tier,"reason":"test","briefOnly":False})

    def test_unknown_application_requires_tested_preset_target_and_key(self):
        result=self.demo.arm(self.payload)
        self.assertEqual(result["compatibility"]["basis"],"tested-preset")
        self.assertIsNone(result["compatibility"]["applicationVersion"])
        for update in [{"target":"vbot@other.example"},{"preset":"actions/CHEER_R.json"},
                       {"confirmSafeWorkspace":False},{"confirmHandsetStop":False}]:
            with self.subTest(update=update),self.assertRaises(ValueError): self.demo.arm({**self.payload,**update})
        self.keys.return_value=set()
        with self.assertRaises(ValueError): self.demo.arm(self.payload)
        self.sender.assert_not_called()

    def test_key_change_after_arm_disarms_without_dispatch(self):
        self.demo.arm(self.payload); self.keys.return_value=set()
        self.submit(); self.wait_idle()
        self.sender.assert_not_called()
        self.assertFalse(self.demo.status()["armed"])
        self.assertEqual(self.demo.status()["events"][0]["status"],"not_ready")

    def test_readiness_failure_is_known_no_motion_and_disarms(self):
        self.demo.arm(self.payload); self.sender.side_effect=RobotNotReady("Robot is lying down")
        self.submit(); self.wait_idle()
        self.assertFalse(self.demo.status()["armed"])
        self.assertEqual(self.demo.status()["events"][0]["status"],"not_ready")
        self.sender.assert_called_once()

    def test_rest_starts_after_long_dance_finishes(self):
        now=[100.0]; self.demo.clock=lambda:now[0]
        def dance(*args):
            now[0]+=40
            return {"status":"completed","readyForNext":True}
        self.demo.sender=dance
        self.demo.arm(self.payload); self.submit("major"); self.wait_idle()
        self.assertEqual(self.demo.status()["cooldownRemaining"],20.0)
        now[0]+=19
        self.assertEqual(self.demo.status()["cooldownRemaining"],1.0)

    def test_postflight_not_ready_disarms_after_known_completion(self):
        self.sender.return_value={"status":"completed","readyForNext":False,"postflightReason":"Robot rested"}
        self.demo.arm(self.payload); self.submit(); self.wait_idle()
        self.assertFalse(self.demo.status()["armed"])
        self.assertEqual([e["status"] for e in self.demo.status()["events"][:2]],["not_ready","completed"])

    def test_profile_loader_rejects_invalid_schema_or_unobserved_motion(self):
        import tempfile
        from vbot_demo import SCHEMA_HASH
        profile={**self.profile,"schemaVersion":1,"actionSchemaHash":SCHEMA_HASH}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"profile.json"
            path.write_text(json.dumps(profile))
            self.assertIsNotNone(load_verification(path))
            path.write_text(json.dumps({**profile,"actionSchemaHash":"wrong"}))
            self.assertIsNone(load_verification(path))
            for item in profile["presets"]: item["movementConfirmed"]=False
            path.write_text(json.dumps(profile))
            self.assertIsNone(load_verification(path))


class TierDispatchTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.0
        presets=["actions/ROCKYOU.json","actions/WAVE.json","atom/look_left.json","atom/look_right.json"]
        profile={"target":"vbot@robot.example","hostKeyFingerprint":"SHA256:"+"a"*43,
                 "presets":[{"preset":p,"status":"SUCCEEDED","errorCategory":0,"movementConfirmed":True} for p in presets]}
        self.sender=Mock(return_value={"status":"completed","readyForNext":True})
        self.demo=VbotDemo(sender=self.sender,clock=lambda:self.now,verification=profile,
                           fingerprint_reader=lambda target:{profile["hostKeyFingerprint"]},chooser=lambda options:options[0])
        self.demo.arm({"mode":"live","gameId":"AbCd1234","target":"vbot@robot.example", "applicationVersion":"unknown",
                       "confirmSafeWorkspace":True,"confirmHandsetStop":True})

    def submit(self,ply,tier="small",brief=False,classification="good"):
        with self.demo.lock:
            result=self.demo._submit({"gameId":"AbCd1234","ply":ply,"playerColor":"white","playedMove":"e4","classification":classification},
                                     {"tier":tier,"reason":"verified test signal","briefOnly":brief})
        deadline=time.monotonic()+2
        while self.demo.status()["busy"] and time.monotonic()<deadline:time.sleep(.005)
        self.assertFalse(self.demo.status()["busy"])
        return result

    def verify_sad(self):
        self.demo.verification["presets"].append({"preset":"actions/GRIEVANCE.json",
            "status":"SUCCEEDED", "errorCategory":0, "movementConfirmed":True})

    def test_sad_live_requires_exact_rehearsal_even_with_application_version(self):
        self.demo.compatibility = {"basis":"application-version", "applicationVersion":"V1.6.0"}
        result = self.submit(1, classification="blunder")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("supervised", result["reason"])
        self.sender.assert_not_called()

    def test_verified_sad_dispatches_once_and_shares_body_performance_interval(self):
        self.verify_sad()
        result = self.submit(1, classification="blunder")
        self.assertEqual(result["tier"], "sad")
        self.assertEqual(result["preset"], "actions/GRIEVANCE.json")
        self.assertEqual(self.demo.cooldown, 20)
        self.now += 21
        self.assertIn("already handled", self.submit(1, classification="blunder")["reason"])
        self.assertIn("three-minute", self.submit(3, classification="blunder")["reason"])
        self.assertEqual(self.submit(5, "major")["tier"], "small")
        self.assertEqual(self.sender.call_count, 2)

    def test_sad_is_not_sent_for_fast_games_or_when_busy_and_is_not_replayed(self):
        self.verify_sad()
        self.assertEqual(self.submit(1, brief=True, classification="blunder")["status"], "skipped")
        self.assertIn("already handled", self.submit(1, classification="blunder")["reason"])
        self.demo.busy = True
        with self.demo.lock:
            result = self.demo._submit({"gameId":"AbCd1234", "ply":3, "playerColor":"white", "classification":"blunder"})
        self.demo.busy = False
        self.assertIn("busy", result["reason"])
        self.assertIn("already handled", self.submit(3, classification="blunder")["reason"])
        self.sender.assert_not_called()

    def test_sad_rechecks_host_identity_even_with_application_version(self):
        self.verify_sad()
        self.demo.compatibility = {"basis":"application-version"}
        self.demo.fingerprint_reader = lambda _: set()
        self.submit(1, classification="blunder")
        self.assertFalse(self.demo.armed)
        self.sender.assert_not_called()

    def test_ordinary_moves_randomize_verified_brief_presets_and_avoid_repeats(self):
        first=self.submit(1);self.now+=11;second=self.submit(3)
        self.assertEqual(first["tier"],"small")
        self.assertNotEqual(first["preset"],"actions/ROCKYOU.json")
        self.assertNotEqual(first["preset"],second["preset"])
        self.assertEqual(self.sender.call_count,2)

    def test_milestone_uses_rockyou_then_three_minute_interval_downgrades_next(self):
        first=self.submit(1,"major");self.now+=21;second=self.submit(3,"major")
        self.assertEqual(first["preset"],"actions/ROCKYOU.json")
        self.assertEqual(second["tier"],"small")
        self.assertNotEqual(second["preset"],"actions/ROCKYOU.json")
        self.now+=181
        self.assertEqual(self.submit(5,"major")["tier"],"major")

    def test_fast_game_major_and_good_moves_use_only_heads(self):
        for ply,tier in [(1,"major"),(3,"small")]:
            event=self.submit(ply,tier,True)
            self.assertEqual(event["tier"],"small")
            self.assertTrue(event["preset"].startswith("atom/look_"))
            self.now+=11

    def test_unrehearsed_actions_never_enter_random_pool(self):
        self.demo.verification["presets"]=[self.demo.verification["presets"][0]]
        event=self.submit(1)
        self.assertEqual(event["status"],"skipped")
        self.sender.assert_not_called()

    def test_synthetic_major_example_cannot_trigger_live_motion(self):
        with self.assertRaises(ValueError):self.demo.rehearse("good","major")
        self.sender.assert_not_called()

    def test_client_tier_and_fake_evaluation_do_not_upgrade_ordinary_server_record(self):
        import chess
        record={"recordId":"real","gameId":"AbCd1234","playerColor":"white","ply":1,
                "classification":"good","fenBefore":chess.STARTING_FEN,"playedMoveUci":"e2e4","playedMove":"e4"}
        self.demo.remember(record)
        game={"gameId":"AbCd1234","botColor":"black","initialFen":"startpos","updatedAt":int(time.time()*1000),
              "timeControlKnown":True,"clock":None,"state":{"status":"started","moves":"e2e4 e7e5"}}
        event=self.demo.celebrate({"recordId":"real","gameId":"AbCd1234","playerColor":"white", "tier":"major","evaluationAfter":9999},game)
        self.assertEqual(event["tier"],"small")
        deadline=time.monotonic()+2
        while self.demo.status()["busy"] and time.monotonic()<deadline:time.sleep(.005)
        self.assertEqual(self.sender.call_args.args[1],"actions/WAVE.json")


class TransportTests(unittest.TestCase):
    def test_bot_stream_snapshot_preserves_the_bot_side_for_human_filtering(self):
        state = {"gameId":"AbCd1234", "botColor":"black", "initialFen":"startpos",
                 "state":{"status":"started","moves":"e2e4"}, "updatedAt":int(time.time()*1000), "timeControlKnown":True,"clock":{"initial":180000,"increment":2000}}
        with patch.object(app.runtime, "_game_states", {"AbCd1234":state}):
            self.assertEqual(app.runtime.game_state("AbCd1234")["botColor"], "black")
            self.assertTrue(app.runtime.game_state("AbCd1234")["timeControlKnown"])
            self.assertEqual(app.runtime.game_state("AbCd1234")["clock"]["initial"],180000)

    def test_safe_ssh_argv_and_no_shell_interpolation(self):
        cmd = ssh_command("vbot@robot.example", "actions/ROCKYOU.json", "a"*32)
        self.assertIn("StrictHostKeyChecking=yes",cmd)
        self.assertIn("BatchMode=yes",cmd)
        self.assertIn("-I",cmd[-1])
        for target in ["-oProxyCommand=bad", "robot;whoami", "root@robot", "robot\nother"]:
            with self.assertRaises(ValueError): ssh_command(target,"actions/ROCKYOU.json","a"*32)

    def test_ssh_exit_zero_without_matching_terminal_is_not_success(self):
        for stdout in ['{"accepted":true}', '{"event":"terminal","requestId":"other","status":"SUCCEEDED","errorCategory":0}',
                       '{"event":"terminal","requestId":"'+'a'*32+'","status":"ABORTED","errorCategory":1}']:
            with patch('vbot_demo.subprocess.run',return_value=Mock(returncode=0,stdout=stdout)) as run:
                with self.assertRaises(RuntimeError):send_dance("robot.example","actions/ROCKYOU.json","a"*32)
                run.assert_called_once()

    def test_matching_terminal_and_success_are_required(self):
        stdout=json.dumps({"event":"terminal","requestId":"a"*32,"status":"SUCCEEDED","errorCategory":0,"goalId":"goal"})
        with patch('vbot_demo.subprocess.run',return_value=Mock(returncode=0,stdout=stdout)):
            self.assertEqual(send_dance("robot.example","actions/ROCKYOU.json","a"*32)["status"],"completed")

    def test_not_ready_is_trusted_only_before_submission(self):
        event={"event":"not_ready","requestId":"a"*32,"reason":"Robot is lying down"}
        with patch('vbot_demo.subprocess.run',return_value=Mock(returncode=1,stdout=json.dumps(event))):
            with self.assertRaises(RobotNotReady): send_dance("robot.example","actions/ROCKYOU.json","a"*32)
        submitted={"event":"submitting","requestId":"a"*32}
        with patch('vbot_demo.subprocess.run',return_value=Mock(returncode=1,stdout=json.dumps(submitted)+"\n"+json.dumps(event))):
            try: send_dance("robot.example","actions/ROCKYOU.json","a"*32)
            except RobotNotReady: self.fail("Submission cannot become a no-motion claim")
            except RuntimeError: pass
            else: self.fail("Unknown outcome accepted")

    def test_local_origin_and_peer_checks(self):
        request = Mock(client_address=("127.0.0.1",1),server=Mock(server_port=8765))
        for host,origin,peer,expected in [
            ("127.0.0.1:8765","http://localhost:5173","127.0.0.1",True),
            ("127.0.0.1:8765","http://127.0.0.1:8765","127.0.0.1",True),
            ("evil.example:8765","http://evil.example:8765","127.0.0.1",False),
            ("127.0.0.1:8765","https://evil.example","127.0.0.1",False),
            ("127.0.0.1:8765","","192.0.2.20",False)]:
            request.headers={"Host":host,"Origin":origin};request.client_address=(peer,1)
            self.assertEqual(app.Handler._vbot_local_request(request),expected)

    def test_robot_helper_preview_has_no_sdk_import_or_device_side_effects(self):
        result = subprocess.run([sys.executable,str(ROOT/'vbot-demo/robot_action.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)["execute"])
        self.assertFalse((ROOT/'vbot-demo/requests').exists())


if __name__ == '__main__': unittest.main()
