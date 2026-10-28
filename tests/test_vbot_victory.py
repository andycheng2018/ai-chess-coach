"""Result celebrations over the existing bot stream. All robot sends are mocks."""
import copy,json,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from vbot_demo import VbotDemo,RobotNotReady
from bot_runtime import LichessBotRuntime

class VictoryTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.
        self.wait_hook=None
        def wait(seconds):
            self.now+=seconds
            if self.wait_hook:self.wait_hook()
        self.sender=Mock(return_value={'status':'completed','readyForNext':True})
        profile={'target':'vbot@robot.example','hostKeyFingerprint':'SHA256:'+'a'*43,
                 'presets':[{'preset':'actions/ROCKYOU.json','status':'SUCCEEDED','errorCategory':0,'movementConfirmed':True}]}
        self.demo=VbotDemo(clock=lambda:self.now,verification=profile,sender=self.sender,
            fingerprint_reader=lambda _:{profile['hostKeyFingerprint']},victory_wait=wait)
        self.game={'gameId':'AbCd1234','botColor':'black','updatedAt':int(time.time()*1000),
                   'timeControlKnown':True,'clock':{'initial':60000,'increment':0},
                   'state':{'status':'mate','winner':'white','moves':'e2e4','wtime':1}}
        self.payload={'gameId':'AbCd1234','playerColor':'white','mode':'live','target':'vbot@robot.example',
                      'applicationVersion':'unknown','confirmSafeWorkspace':True,'confirmHandsetStop':True}
    def arm(self,**updates):
        self.demo.arm({**self.payload,**updates})
        return {'gameId':self.demo.game_id,'generation':self.demo.generation}
    def wait_idle(self):
        deadline=time.monotonic()+2
        while (self.demo.status()['finishPending'] or self.demo.status()['busy']) and time.monotonic()<deadline:time.sleep(.001)
        self.assertFalse(self.demo.status()['finishPending']);self.assertFalse(self.demo.status()['busy'])
    def finish(self,**payload):
        self.demo.finish_game({'gameId':self.demo.game_id,'generation':self.demo.generation,**payload},lambda _:self.game)
        self.wait_idle()
    def test_human_win_both_colors_triggers_exact_rockyou_once_even_after_blitz(self):
        for color in ['white','black']:
            with self.subTest(color=color):
                self.setUp()
                self.game['botColor']='black' if color=='white' else 'white'
                self.game['state']['winner']=color
                session=self.arm(playerColor=color)
                self.demo.last_dance_finished=self.now-1  # victory ignores major interval
                self.finish(winner='black' if color=='white' else 'white')  # client winner ignored
                self.sender.assert_called_once()
                self.assertEqual(self.sender.call_args.args[1],'actions/ROCKYOU.json')
                self.assertFalse(self.demo.status()['armed'])
                self.demo.finish_game(session,lambda _:self.game)
                self.demo.observe_game_end(self.game,lambda _:self.game)
                self.sender.assert_called_once()
    def test_loss_draw_abort_stalemate_and_unconfirmed_winner_do_not_dance(self):
        for status,winner in [('mate','black'),('resign','black'),('draw',None),('stalemate',None),
                              ('aborted','white'),('noStart','white'),('unknownFinish','white'),('resign',None)]:
            with self.subTest(status=status,winner=winner):
                self.setUp();self.arm();self.game['state'].update(status=status,winner=winner)
                self.finish(winner='white');self.sender.assert_not_called();self.assertFalse(self.demo.armed)
    def test_resignation_and_timeout_wins_are_celebrated(self):
        for status in ['resign','outoftime','timeout','variantEnd','cheat']:
            self.setUp();self.arm();self.game['state']['status']=status;self.finish();self.sender.assert_called_once()
    def test_off_wrong_session_and_practice_cannot_receive_a_victory(self):
        self.demo.finish_game({'gameId':'AbCd1234','generation':0},lambda _:self.game)
        self.sender.assert_not_called()
        session=self.arm()
        for wrong in [{'gameId':'Other123'},{'generation':session['generation']-1}]:
            self.demo.finish_game({**session,**wrong},lambda _:self.game)
            self.assertFalse(self.demo.finish_pending)
        self.demo.arm({**self.payload,'gameId':'CAPTURE1','practice':True})
        self.finish();self.sender.assert_not_called()
    def test_stale_wrong_game_bot_identity_and_color_cannot_claim_win(self):
        for changed in [{'updatedAt':int(time.time()*1000)-31000},{'gameId':'Other123'},
                        {'botColor':'white'},{'botColor':None}]:
            self.setUp();self.arm();self.game.update(changed);self.finish();self.sender.assert_not_called()
    def test_browser_end_can_arrive_before_canonical_terminal_result(self):
        self.arm();self.game['state']['status']='started'
        def complete():self.game['state']['status']='mate'
        self.wait_hook=complete
        self.finish();self.sender.assert_called_once()
    def test_missing_canonical_result_times_out_disarmed_without_motion(self):
        self.arm();self.game['state']['status']='started'
        self.finish();self.sender.assert_not_called();self.assertFalse(self.demo.armed)
        self.assertTrue(any('15 seconds' in e.get('reason','') for e in self.demo.events))
    def test_victory_waits_for_inflight_reaction_and_full_rest(self):
        self.arm();self.demo.busy=True;finished=[]
        def complete():
            if not finished:
                self.demo.busy=False;self.demo.last_finished=self.now;self.demo.cooldown=20;finished.append(self.now)
        self.wait_hook=complete
        dispatched=[]
        self.sender.side_effect=lambda *args:(dispatched.append(self.now) or {'status':'completed','readyForNext':True})
        self.finish();self.sender.assert_called_once()
        self.assertGreaterEqual(dispatched[0]-finished[0],20)
    def test_operator_off_cancels_wait_without_replay(self):
        self.arm();self.demo.last_finished=self.now;self.demo.cooldown=20
        self.wait_hook=lambda:self.demo.disarm({'gameId':self.demo.game_id,'generation':self.demo.generation,'reason':'operator_off'})
        self.finish();self.sender.assert_not_called();self.assertFalse(self.demo.armed)
    def test_new_session_cancels_old_wait_and_old_worker_cannot_disarm_it(self):
        self.arm();self.demo.last_finished=self.now;self.demo.cooldown=20
        changed=[]
        def switch():
            if not changed:
                self.demo.arm({**self.payload,'gameId':'Other123'});changed.append(True)
        self.wait_hook=switch
        self.finish();self.sender.assert_not_called()
        self.assertTrue(self.demo.armed);self.assertEqual(self.demo.game_id,'Other123')
    def test_preview_win_and_device_refusal_never_retry_or_auto_rearm(self):
        self.arm(mode='rehearsal');self.finish();self.sender.assert_not_called()
        self.assertTrue(any(e['status']=='rehearsed' and e.get('tier')=='victory' for e in self.demo.events))
        self.setUp();self.arm();self.sender.side_effect=RobotNotReady('Battery below ten percent')
        self.finish();self.sender.assert_called_once();self.assertFalse(self.demo.armed)
    def test_move_reactions_close_as_soon_as_end_notification_is_pending(self):
        self.arm();self.demo.finish_pending=True
        result=self.demo._submit({'gameId':'AbCd1234','playerColor':'white','ply':3,'classification':'good','playedMove':'e4'})
        self.assertEqual(result['status'],'skipped');self.sender.assert_not_called()
    def test_canonical_stream_calls_observer_after_caching_terminal_state(self):
        runtime=LichessBotRuntime();runtime._username='coachbot'
        runtime._credentials=Mock(return_value=('test-token','coachbot'))
        runtime._wait_for_api_cooldown=Mock();runtime._maybe_move=Mock();runtime._maybe_accept_takeback=Mock()
        seen=[]
        runtime.game_observer=lambda game:seen.append((game,runtime.game_state(game['gameId'])))
        events=[{'type':'gameFull','rated':False,'white':{'id':'human'},'black':{'id':'coachbot'},
                 'state':{'status':'started','moves':''}},
                {'type':'gameState','status':'resign','winner':'white','moves':'e2e4'}]
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_lines(self):return iter(json.dumps(event).encode() for event in events)
        with patch('bot_runtime.requests.get',return_value=Response()):runtime._game_loop('AbCd1234')
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0][0],seen[0][1]);self.assertEqual(seen[0][0]['state']['winner'],'white')

if __name__=='__main__':unittest.main()
