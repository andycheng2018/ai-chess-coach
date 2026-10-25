"""Native companion controls and postflight checks. No device connections."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from vbot_demo import VbotDemo, check_robot
spec = importlib.util.spec_from_file_location('robot_action_offline', ROOT / 'vbot-demo/robot_action.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class NativeCompanionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.checker = Mock(return_value={'ready': True, 'code': 'ready', 'reason': None})
        self.demo = VbotDemo(clock=lambda: self.now, checker=self.checker, verification={}, sender=Mock())
        self.payload = dict(mode='live', gameId='AbCd1234', playerColor='white', target='vbot@robot.example',
                            applicationVersion='V1.6.0', confirmSafeWorkspace=True, confirmHandsetStop=True)
        self.game = dict(gameId='AbCd1234', botColor='black', state={'status': 'started'})
    def test_rendering_status_never_contacts_robot(self):
        self.demo.status(); self.demo.status()
        self.checker.assert_not_called()
        self.demo.sender.assert_not_called()
    def test_live_connection_requires_fresh_readiness_for_the_same_target(self):
        for update in [{}, {'target': 'vbot@other.example'}]:
            with self.assertRaises(ValueError): self.demo.connect_game({**self.payload, **update}, lambda _: self.game)
        self.demo.check_device({'target': self.payload['target']})
        self.assertTrue(self.demo.connect_game(self.payload, lambda _: self.game)['armed'])
        self.demo.disarm(); self.now += 31
        with self.assertRaises(ValueError): self.demo.connect_game(self.payload, lambda _: self.game)
        self.demo.sender.assert_not_called()
    def test_expired_connection_probe_does_not_disarm_a_live_game_or_reprobe(self):
        self.demo.check_device({'target':self.payload['target']})
        self.demo.connect_game(self.payload,lambda _:self.game)
        self.now += 3600
        for _ in range(5):
            status = self.demo.status()
            self.assertTrue(status['armed'])
            self.assertFalse(status['readinessFresh'])
        self.checker.assert_called_once()
        self.demo.sender.assert_not_called()

    def test_scoped_disarm_records_specific_lifecycle_reason(self):
        status=self.demo.arm({'gameId':'AbCd1234'})
        self.demo.disarm({'gameId':status['gameId'],'generation':status['generation'],'reason':'match_changed'})
        event=self.demo.status()['events'][0]
        self.assertEqual(event['reasonCode'],'match_changed')
        self.assertIn('Selected match changed',event['reason'])

    def test_failed_probe_and_invalid_targets_cannot_enable_motion(self):
        with self.assertRaises(ValueError): self.demo.check_device({'target': '-oProxyCommand=bad'})
        self.checker.assert_not_called()
        self.checker.return_value={'ready':False, 'reason':'Robot must stand'}
        self.demo.check_device({'target': self.payload['target']})
        with self.assertRaises(ValueError): self.demo.connect_game(self.payload, lambda _: self.game)
    def test_terminal_wrong_game_and_bot_side_cannot_connect(self):
        payload={**self.payload, 'mode':'rehearsal'}
        for game in [None, {**self.game, 'gameId':'Other123'}, {**self.game, 'state':{'status':'mate'}}, {**self.game, 'botColor':'white'}]:
            with self.subTest(game=game), self.assertRaises(ValueError): self.demo.connect_game(payload, lambda _:game)
        self.demo.sender.assert_not_called()
    def test_preview_needs_no_robot_probe(self):
        s=self.demo.connect_game({**self.payload,'mode':'rehearsal'},lambda _:self.game)
        self.assertEqual(s['mode'],'rehearsal'); self.assertTrue(s['armed'])
        self.checker.assert_not_called(); self.demo.sender.assert_not_called()
    def test_stale_tab_cannot_disarm_a_new_session(self):
        old=self.demo.arm({'gameId':'AbCd1234'})
        current=self.demo.arm({'gameId':'Other123'})
        self.demo.disarm({'gameId':old['gameId'],'generation':old['generation']})
        self.assertTrue(self.demo.status()['armed'])
        self.demo.disarm({'gameId':current['gameId'],'generation':current['generation']})
        self.assertFalse(self.demo.status()['armed'])
    def test_slow_probe_cannot_replace_a_changed_session(self):
        def probe(_):
            self.demo.disarm()
            return {'ready':True}
        self.demo.checker=probe
        with self.assertRaises(ValueError): self.demo.check_device({'target':self.payload['target']})
        self.assertIsNone(self.demo.status()['readiness'])
    def test_postflight_failure_invalidates_the_pre_arm_readiness_probe(self):
        self.demo.check_device({'target':self.payload['target']})
        self.demo.arm(self.payload)
        self.demo.sender=Mock(return_value={'status':'completed','readyForNext':False,'postflightReason':'Head fault'})
        self.demo._run(self.payload['target'],'actions/ROCKYOU.json','a'*32,self.demo.generation)
        self.assertFalse(self.demo.status()['armed'])
        self.assertIsNone(self.demo.status()['readiness'])
        with self.assertRaises(ValueError): self.demo.connect_game(self.payload,lambda _:self.game)
        self.demo.sender.assert_called_once()
    def test_unknown_outcome_invalidates_readiness_without_retry(self):
        self.demo.check_device({'target':self.payload['target']})
        self.demo.arm(self.payload)
        self.demo.sender=Mock(side_effect=TimeoutError())
        self.demo._run(self.payload['target'],'actions/ROCKYOU.json','a'*32,self.demo.generation)
        self.assertIsNone(self.demo.status()['readiness'])
        self.assertEqual(self.demo.status()['events'][0]['status'],'unknown')
        self.demo.sender.assert_called_once()
    def test_result_events_keep_their_game_identity(self):
        self.demo.arm({'gameId':'AbCd1234'})
        self.assertEqual(self.demo._event('completed',requestId='r')['gameId'],'AbCd1234')

class ReadOnlyProbeTests(unittest.TestCase):
    def test_probe_uses_strict_ssh_and_never_execution_flags(self):
        def run(command, **kwargs):
            self.assertIn('StrictHostKeyChecking=yes',command)
            self.assertIn('--check-ready',command[-1]); self.assertNotIn('--execute',command[-1])
            request_id=command[-1].split('--request-id ')[1]
            import json
            return Mock(returncode=0,stderr='',stdout=json.dumps({'event':'readiness','requestId':request_id,'ready':True,'reason':None}))
        with patch('vbot_demo.subprocess.run',side_effect=run): self.assertTrue(check_robot('robot.example')['ready'])
    def test_mismatched_probe_output_is_not_ready(self):
        with patch('vbot_demo.subprocess.run',return_value=Mock(returncode=0,stdout='{"ready":true}',stderr='')):
            self.assertFalse(check_robot('robot.example')['ready'])

class SettlingTests(unittest.TestCase):
    def setUp(self): self.now=0.0
    def wait(self,t): self.now+=t
    def settle(self,check,timeout=2):
        return helper.settle_postflight(check,timeout=timeout,clock=lambda:self.now,wait=self.wait)
    def test_transient_head_activity_can_settle_without_any_motion_retry(self):
        check=Mock(side_effect=[{'ready':False,'code':'head_busy'}, {'ready':False,'code':'head_pending'}, {'ready':True,'code':'ready','reason':None}])
        result=self.settle(check)
        self.assertTrue(result['ready']); self.assertEqual(result['attempts'],3)
    def test_fault_or_any_other_failed_gate_stops_immediately(self):
        for code in ['head_fault','battery','system','posture','telemetry','stale','incomplete']:
            check=Mock(return_value={'ready':False,'code':code,'reason':'Blocked'})
            self.assertFalse(self.settle(check)['ready']); check.assert_called_once()
    def test_busy_head_has_a_bounded_deadline(self):
        check=Mock(return_value={'ready':False,'code':'head_busy'})
        result=self.settle(check)
        self.assertFalse(result['ready']); self.assertEqual(result['code'],'settling_timeout')
        self.assertLessEqual(self.now,2); self.assertLessEqual(check.call_count,8)
    def test_hard_fault_after_transient_state_is_not_retried_away(self):
        check=Mock(side_effect=[{'ready':False,'code':'head_pending'}, {'ready':False,'code':'head_fault','reason':'Fault'}, {'ready':True}])
        self.assertEqual(self.settle(check)['code'],'head_fault'); self.assertEqual(check.call_count,2)
    def test_ten_percent_demo_cutoff_preserves_other_battery_and_system_gates(self):
        def samples(soc=10, charger=False, alarm=0, power_saving=False):
            return {'battery':[dict(soc=soc,charger=charger,alarm=alarm)]*2,
                    'system':[dict(heartbeat=i,state='FUNCTION',powerSaving=power_saving,severity=0,active=True) for i in [1,2]],
                    'body':[dict(heartbeat=i,posture=1,motion=0,action='RL_TROT') for i in [1,2,3]],
                    'head':[dict(state=0,pending='',fault='')]*2}
        for soc in [10,11,19,20,49,50,100]:
            self.assertTrue(helper.readiness_details(samples(soc=soc))['ready'])
        for changes in [dict(soc=9),dict(soc=0),dict(charger=True),dict(alarm=1),dict(power_saving=True)]:
            self.assertFalse(helper.readiness_details(samples(**changes))['ready'])
        mixed=samples(soc=10)
        mixed['battery']=[dict(soc=10,charger=False,alarm=0),dict(soc=9,charger=False,alarm=0)]
        result=helper.readiness_details(mixed)
        self.assertFalse(result['ready']); self.assertEqual(result['code'],'battery')
        self.assertIn('at least 10%',result['reason'])

    def test_readiness_distinguishes_busy_pending_and_fault(self):
        samples={'battery':[dict(soc=80,charger=False,alarm=0)]*2,
                 'system':[dict(heartbeat=i,state='FUNCTION',powerSaving=False,severity=0,active=True) for i in [1,2]],
                 'body':[dict(heartbeat=i,posture=1,motion=0,action='RL_TROT') for i in [1,2,3]],
                 'head':[dict(state=0,pending='',fault='')]*2}
        self.assertTrue(helper.readiness_details(samples)['ready'])
        for field,value,code in [('state',1,'head_busy'),('pending','ACTION','head_pending'),('fault','FAULT','head_fault')]:
            changed={**samples,'head':[dict(state=0,pending='',fault='',**{}) for _ in range(2)]}
            changed['head'][0][field]=value
            self.assertEqual(helper.readiness_details(changed)['code'],code)

if __name__=='__main__': unittest.main()
