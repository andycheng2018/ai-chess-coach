"""Session safety witnesses with fake telemetry and streams; no robot I/O."""
from contextlib import contextmanager
import json
import time
import unittest
from unittest.mock import Mock
from test_vbot_companion import helper
from vbot_session import CueSession


class LiveTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.callbacks = {}
        self.closed = []
        @contextmanager
        def subscribe(route, callback, options):
            self.callbacks[route] = callback
            try: yield
            finally: self.closed.append(route)
        self.topics = [(name, name, Mock(GetRootAs=lambda b, _: json.loads(b)), lambda m: m, count, lambda m: True)
                       for name, count in [('battery', 2), ('system', 2), ('body', 3), ('head', 2)]]
        self.live = helper.LiveReadiness(Mock(create_subscriber=subscribe), Mock(), self.topics, clock=lambda: self.now)
        self.live.__enter__()
        self.addCleanup(self.live.__exit__, None, None, None)
        self.feed()

    def feed(self, only=None, fault=''):
        values = {'battery': [dict(soc=80,charger=False,alarm=0)]*2,
                  'system': [dict(heartbeat=i,state='FUNCTION',powerSaving=False,severity=0,active=True) for i in [1,2]],
                  'body': [dict(heartbeat=i,posture=1,motion=0,action='RL_TROT') for i in [1,2,3]],
                  'head': [dict(state=0,pending='',fault=fault)]*2}
        for name, samples in values.items():
            if only and name not in only: continue
            for sample in samples: self.callbacks[name](json.dumps(sample).encode(), None)

    def test_ready_snapshot_does_not_cache_a_later_fault(self):
        self.assertTrue(self.live.check(detailed=True)['ready'])
        self.feed(only=['head'], fault='fault')
        self.assertEqual(self.live.check(detailed=True)['code'], 'head_fault')

    def test_stale_topics_refuse_another_cue(self):
        self.now += 1.6
        self.feed(only=['body','head'])
        self.assertEqual(self.live.check(detailed=True)['code'], 'stale')

    def test_postflight_cannot_reuse_preterminal_body_or_head_samples(self):
        # timeout=0 refuses immediately rather than waiting in this offline witness.
        self.assertFalse(self.live.check(timeout=0, detailed=True, after=10.)['ready'])
        self.now = 10.1
        self.feed(only=['body'])
        self.assertFalse(self.live.check(timeout=0, detailed=True, after=10.)['ready'])
        self.feed(only=['head'])
        self.assertTrue(self.live.check(timeout=0, detailed=True, after=10.)['ready'])

    def test_nonadvancing_heartbeats_and_decode_failure_refuse(self):
        self.live.samples['body'][-1] = self.live.samples['body'][0]
        self.assertEqual(self.live.check(detailed=True)['code'], 'stale')
        self.callbacks['head'](b'bad json',None)
        self.assertEqual(self.live.check(detailed=True)['code'], 'telemetry')

    def test_closing_session_never_leaves_ready_true(self):
        self.live.__exit__(None,None,None)
        self.assertFalse(self.live.check(detailed=True)['ready'])
        self.assertEqual(set(self.closed), set(self.callbacks))


class CueTransportTests(unittest.TestCase):
    def setUp(self):
        self.run_id = 'a'*32
        self.cue_id = 'b'*32
        self.stream = Mock()
        self.stream.readLine.side_effect = [json.dumps(dict(event='session_ready',requestId=self.run_id,protocol=1,rescanProtocol=1,ready=True))]
        self.factory = Mock(return_value=self.stream)
        self.session = CueSession('vbot@robot.example',self.run_id,'robot.example',stream_factory=self.factory)
        self.addCleanup(self.session.close)

    def terminal(self, **extra):
        return json.dumps(dict(event='terminal',requestId=self.cue_id,status='SUCCEEDED',errorCategory=0,
                               readyForNext=True, **extra))

    def test_one_connection_and_no_duplicate_identity_replay(self):
        self.stream.readLine.side_effect = [self.terminal()]
        self.assertTrue(self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)['readyForNext'])
        with self.assertRaises(ValueError): self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)
        self.assertEqual(self.stream.writeLine.call_count,1)
        self.factory.assert_called_once()

    def test_lost_reply_never_reconnects_or_rewrites_a_cue(self):
        self.stream.readLine.side_effect = EOFError()
        with self.assertRaises(EOFError): self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)
        with self.assertRaises(ValueError): self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)
        self.assertEqual(self.stream.writeLine.call_count,1)
        self.factory.assert_called_once()

    def test_nonmatching_result_cannot_complete_the_active_cue(self):
        self.stream.readLine.side_effect = [json.dumps(dict(event='terminal',requestId='c'*32,status='SUCCEEDED',errorCategory=0)), self.terminal()]
        self.assertEqual(self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)['status'],'completed')
        self.assertEqual(self.stream.readLine.call_count,3)  # handshake and two result frames

    def test_failed_postflight_is_not_converted_into_readiness(self):
        result=json.loads(self.terminal()); result['readyForNext']=False
        self.stream.readLine.side_effect = [json.dumps(result)]
        self.assertFalse(self.session.send('vbot@robot.example','actions/WAVE.json',self.cue_id)['readyForNext'])

class SharedExecutionTests(unittest.TestCase):
    def execute(self, *, postflight=True, lost=False):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from enum import Enum
        from unittest.mock import patch
        states = Enum('States','SUCCEEDED CANCELED ABORTED')
        sdk=SimpleNamespace(ActionStatus=states,TimeoutError=type('SdkTimeout',(Exception,),{}))
        handle=Mock()
        handle.wait_result.return_value=SimpleNamespace(status=states.SUCCEEDED,code=SimpleNamespace(name='OK'),message='',result=b'data')
        if lost:
            handle.wait_result.side_effect=OSError('lost reply')
        client=Mock(); client.send_goal_with_id.return_value=handle
        read=Mock(side_effect=[{'ready':True,'code':'ready','reason':None},
                              {'ready':postflight,'code':'ready' if postflight else 'battery','reason':None}])
        result_type=Mock(); result_type.InitFromPackedBuf.return_value=SimpleNamespace(durationMs=100,errorCategory=0)
        with tempfile.TemporaryDirectory() as directory, patch.object(helper,'__file__',str(Path(directory)/'robot_action.py')), patch.object(helper,'make_goal'), patch.object(helper,'emit'):
            args=SimpleNamespace(request_id='e'*32,preset='actions/WAVE.json')
            def publication(**frame):
                if frame.get('event') == 'terminal':
                    self.assertFalse((Path(directory)/'unresolved-action.json').exists())
                    saved=json.loads((Path(directory)/'requests'/('e'*32+'.json')).read_text())
                    self.assertEqual(saved['terminal']['requestId'],'e'*32)
            helper.emit.side_effect=publication
            if lost:
                with self.assertRaises(OSError):
                    helper.execute_preset(args,None,sdk,client,Mock(),result_type,read)
                self.assertTrue((Path(directory)/'unresolved-action.json').exists())
                handle.cancel.assert_called_once()
            else:
                result=helper.execute_preset(args,None,sdk,client,Mock(),result_type,read)
                self.assertEqual(result['readyForNext'],postflight)
                self.assertIn('after',read.call_args.kwargs)
                self.assertFalse((Path(directory)/'unresolved-action.json').exists())
                # A repeated identity cannot submit a second goal, even after success.
                read.side_effect=None; read.return_value={'ready':True}
                with self.assertRaises(FileExistsError):
                    helper.execute_preset(args,None,sdk,client,Mock(),result_type,read)
            client.send_goal_with_id.assert_called_once()

    def test_shared_executor_keeps_identity_records_and_postterminal_checks(self):
        self.execute()

    def test_failed_postflight_is_preserved(self):
        self.execute(postflight=False)

    def test_unknown_outcome_keeps_unresolved_guard_and_never_replays(self):
        self.execute(lost=True)

class RescanCancellationTransportTests(unittest.TestCase):
    def test_operator_stop_sends_cancel_without_replaying_the_cue(self):
        import threading
        stream=Mock(); stop=threading.Event(); run='a'*32; cue='b'*32
        stream.readLine.side_effect=[json.dumps(dict(event='session_ready',requestId=run,protocol=1,rescanProtocol=1,ready=True))]
        session=CueSession('vbot@robot.example',run,'robot.example',stream_factory=lambda _:stream)
        session.cancel=stop
        session.on_rescan=lambda _:stop.set()
        stream.readLine.side_effect=[json.dumps(dict(event='rescan',requestId=cue,phase='rescanning')),
                                    json.dumps(dict(event='not_ready',requestId=cue,code='operator_stop'))]
        from vbot_demo import RobotNotReady
        try:
            with self.assertRaises(RobotNotReady):session.send('vbot@robot.example','actions/WAVE.json',cue)
            frames=[json.loads(call.args[0]) for call in stream.writeLine.call_args_list]
            self.assertEqual([frame['op'] for frame in frames],['cue','cancel'])
            self.assertTrue(all(frame['requestId']==cue for frame in frames))
        finally:session.close()
