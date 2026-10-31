"""Bounded wait/retry policy: all SDK, actuator, and clock inputs are test doubles."""
import json
from types import SimpleNamespace, ModuleType
import sys
import unittest
from unittest.mock import Mock, patch
from test_vbot_companion import helper

DANCE='actions/ROCKYOU.json'
GOOD={'event':'terminal','status':'SUCCEEDED','errorCategory':0,'readyForNext':True}
READY={'ready':True,'code':'ready','reason':None}
BLOCKED={'ready':False,'code':'not_static','reason':'Not static yet.'}

def refusal():
    return {'event':'terminal','status':'ABORTED','code':'HANDLER_ERROR','durationMs':None,
            'message':json.dumps({'schemaVersion':1,'task_name':'rockyou_30s','error_category':7,
                'error_category_str':'PRECONDITION_FAILED','taskError':{'code':'rcp.execution.precondition_failed',
                    'message':"Precondition check failed: Precondition 'is_robot_static' failed: false == true evaluated to false"}})}

class RescanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=0.
        self.stopped=False
        self.read=Mock(return_value=READY)
        self.probe=Mock(return_value=READY)
        self.perform=Mock(return_value=GOOD)
        self.announce=Mock()
    def wait(self, seconds): self.now += seconds
    def run_cue(self, **kw):
        return helper.rescan_cue(DANCE,self.read,self.probe,self.perform,lambda:self.stopped,self.announce,
                                 clock=lambda:self.now,wait=self.wait,**kw)
    def test_no_movement_until_repeated_scans_and_static_probe_pass(self):
        self.read.side_effect=[{'ready':False,'code':'head_busy'},READY,READY,READY]
        self.probe.side_effect=[BLOCKED,BLOCKED,READY]
        result=self.run_cue()
        self.assertEqual(result['status'],'SUCCEEDED')
        self.perform.assert_called_once()
        self.assertEqual(self.read.call_count,4)
        self.assertEqual(self.probe.call_count,3)
        self.assertGreater(self.now,0)
    def test_confirmed_root_refusal_gets_rescanned_before_a_new_attempt(self):
        self.perform.side_effect=[refusal(),GOOD]
        self.probe.side_effect=[READY,BLOCKED,READY]
        result=self.run_cue()
        self.assertEqual(result['attemptCount'],2)
        self.assertEqual(self.perform.call_count,2)
        self.assertEqual(self.probe.call_count,3)
    def test_refusal_retry_is_limited_to_three_movement_attempts(self):
        self.perform.return_value=refusal()
        result=self.run_cue()
        self.assertEqual(result['status'],'ABORTED')
        self.assertEqual(self.perform.call_count,3)
    def test_static_never_passes_expires_without_any_movement(self):
        self.probe.return_value=BLOCKED
        result=self.run_cue(timeout=1)
        self.assertEqual(result['code'],'rescan_timeout')
        self.perform.assert_not_called()
        self.assertLessEqual(self.now,1)
    def test_hard_gates_stop_instead_of_being_retried_away(self):
        for code in ['battery','system','head_fault','stale','telemetry','incomplete']:
            self.setUp();self.read.return_value={'ready':False,'code':code}
            self.assertEqual(self.run_cue()['code'],code)
            self.perform.assert_not_called();self.probe.assert_not_called()
            self.assertEqual(self.read.call_count,1)
    def test_unknown_or_lost_motion_reply_is_not_retried(self):
        self.perform.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError): self.run_cue()
        self.perform.assert_called_once()
    def test_nonprecondition_abort_and_cancellation_are_not_retried(self):
        for status in ['CANCELED','ABORTED']:
            self.setUp();self.perform.return_value={'status':status,'code':'INTERNAL','message':'failed'}
            self.assertEqual(self.run_cue()['status'],status)
            self.perform.assert_called_once()
    def test_cancel_during_scans_prevents_movement(self):
        self.probe.return_value=BLOCKED
        def announce(_): self.stopped=True
        self.announce.side_effect=announce
        self.assertEqual(self.run_cue()['code'],'operator_stop')
        self.perform.assert_not_called()
    def test_cancel_after_probe_before_movement_still_prevents_movement(self):
        def probe(): self.stopped=True; return READY
        self.probe.side_effect=probe
        self.assertEqual(self.run_cue()['code'],'operator_stop')
        self.perform.assert_not_called()
    def test_duplicate_or_unclear_failure_is_not_classified_as_root_refusal(self):
        self.assertTrue(helper.precondition_refusal(refusal(),'rockyou_30s'))
        for change in [{'status':'CANCELED'},{'durationMs':10},{'message':'not static'}, {'code':'TIMEOUT'}]:
            self.assertFalse(helper.precondition_refusal({**refusal(),**change},'rockyou_30s'))
        for path,value in [('task_name','nested_task'),('failed_at','motion_node'),('error_category',6)]:
            result=refusal();detail=json.loads(result['message']);detail[path]=value;result['message']=json.dumps(detail)
            self.assertFalse(helper.precondition_refusal(result,'rockyou_30s'))
    def test_non_static_cues_keep_fast_path_and_never_run_static_probe(self):
        result=helper.rescan_cue('atom/look_left.json',self.read,self.probe,self.perform,lambda:False,self.announce)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.probe.assert_not_called()
        self.perform.assert_called_once()

    def test_hard_fault_after_root_refusal_prevents_second_attempt(self):
        self.perform.return_value=refusal()
        self.read.side_effect=[READY,{'ready':False,'code':'battery','reason':'Alarm'}]
        self.assertEqual(self.run_cue()['code'],'battery')
        self.perform.assert_called_once()
    def test_failed_probe_never_authorizes_movement(self):
        self.probe.return_value={'ready':False,'code':'probe_failed'}
        self.assertEqual(self.run_cue()['code'],'probe_failed')
        self.perform.assert_not_called()
    def test_failed_postflight_is_not_retried(self):
        self.perform.return_value={**GOOD,'readyForNext':False}
        self.assertFalse(self.run_cue()['readyForNext'])
        self.perform.assert_called_once()
    def test_cancel_after_refusal_prevents_another_attempt(self):
        def perform(): self.stopped=True; return refusal()
        self.perform.side_effect=perform
        self.assertTrue(self.run_cue()['stopRequested'])
        self.perform.assert_called_once()

class NonMotionProbeTests(unittest.TestCase):
    def test_probe_contains_only_sleep_and_does_not_request_static_setup(self):
        modules={name:ModuleType(name) for name in ['aorta','aorta.action','aorta.action.rcp','aorta.services','aorta.services.rcp']}
        for name in ['ExecuteTaskGoal','DagInput','DagSpec','DagNode','NodeCommand','SleepCommand','PreconditionExpr','ConditionValue']:
            prefix='aorta.action.rcp' if name=='ExecuteTaskGoal' else 'aorta.services.rcp'
            mod=ModuleType(prefix+'.'+name)
            setattr(mod,name if name in ['DagInput','NodeCommand'] else name+'T',
                    SimpleNamespace(DagSpec='DAG') if name=='DagInput' else
                    SimpleNamespace(SleepCommand='SLEEP') if name=='NodeCommand' else SimpleNamespace)
            modules[mod.__name__]=mod
        with patch.dict(sys.modules,modules): goal=helper.make_static_probe('a'*32)
        spec=goal.input
        self.assertFalse(spec.skipBatchPreCheck);self.assertFalse(spec.requiresStatic)
        self.assertEqual(spec.requiredResources,[]);self.assertEqual(spec.optionalResources,[])
        self.assertEqual(spec.preconditions.key,'is_robot_static');self.assertTrue(spec.preconditions.value.boolValue)
        self.assertEqual(len(spec.nodes),1)
        self.assertEqual(spec.nodes[0].commandType,'SLEEP')
        self.assertEqual(spec.nodes[0].command.durationMs,1)
