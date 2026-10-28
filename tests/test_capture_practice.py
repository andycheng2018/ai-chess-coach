from pathlib import Path
import sys,time,unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import chess
from capture_practice import EXERCISES,PRACTICE_ID,assess_capture
from vbot_demo import VbotDemo

class CapturePracticeTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.
        self.sender=Mock(return_value={'status':'completed','readyForNext':True})
        profile={'target':'vbot@robot.example','hostKeyFingerprint':'SHA256:'+'a'*43,
                 'presets':[{'preset':'actions/ROCKYOU.json','status':'SUCCEEDED','errorCategory':0,'movementConfirmed':True}]}
        self.demo=VbotDemo(sender=self.sender,clock=lambda:self.now,verification=profile,
                          fingerprint_reader=lambda _:{profile['hostKeyFingerprint']})
    def arm(self,mode='live'):
        self.demo.arm({'mode':mode,'gameId':PRACTICE_ID,'playerColor':'white','practice':True,
            'target':'vbot@robot.example','applicationVersion':'unknown',
            'confirmSafeWorkspace':True,'confirmHandsetStop':True})
    def start(self,lesson='pawn-queen'):
        return self.demo.start_capture({'exerciseId':lesson})['attemptId']
    def submit(self,attempt,move='e4d5'):
        result=self.demo.capture_reward({'attemptId':attempt,'moveUci':move})
        deadline=time.monotonic()+2
        while self.demo.status()['busy'] and time.monotonic()<deadline:time.sleep(.005)
        return result
    def test_every_authored_position_and_capture_is_legal(self):
        for lesson in EXERCISES.values():
            self.assertTrue(chess.Board(lesson['fen']).is_valid())
            result=assess_capture(lesson['id'],lesson['move'])
            self.assertTrue(result['correct']);self.assertIn(result['captured'],['queen','rook'])
            self.assertIn(result['points'],[5,9])
    def test_wrong_or_malformed_move_never_rewards_and_can_be_retried(self):
        self.arm();attempt=self.start()
        for move in ['e4e5','nonsense','h8h7']:
            self.assertFalse(self.submit(attempt,move)['correct'])
        self.sender.assert_not_called()
        self.assertTrue(self.submit(attempt)['correct']);self.sender.assert_called_once()
    def test_correct_live_capture_uses_full_rockyou_and_duplicate_is_idempotent(self):
        self.arm();attempt=self.start();first=self.submit(attempt)
        self.assertEqual(first['reward']['status'],'requested')
        self.assertEqual(first['reward']['preset'],'actions/ROCKYOU.json')
        self.assertEqual(self.submit(attempt),first);self.sender.assert_called_once()
    def test_offline_practice_needs_no_robot_and_cannot_replay_after_arming(self):
        attempt=self.start();first=self.submit(attempt)
        self.assertTrue(first['correct']);self.assertEqual(first['reward']['status'],'skipped')
        self.arm();self.assertEqual(self.submit(attempt),first);self.sender.assert_not_called()
    def test_practice_cannot_hijack_an_armed_lichess_game(self):
        self.demo.arm({'gameId':'AbCd1234','mode':'rehearsal'})
        result=self.submit(self.start())
        self.assertEqual(result['reward']['status'],'skipped')
        self.assertEqual(self.demo.game_id,'AbCd1234');self.sender.assert_not_called()
    def test_practice_repeats_full_reward_after_rest_without_small_gesture_downgrade(self):
        self.arm();self.submit(self.start());self.now+=21
        second=self.submit(self.start('rook-queen'),'d2d5')
        self.assertEqual(second['reward']['preset'],'actions/ROCKYOU.json')
        self.assertEqual(self.sender.call_count,2)
    def test_correct_capture_during_rest_is_skipped_permanently_not_queued(self):
        self.arm();self.submit(self.start());attempt=self.start('rook-queen')
        skipped=self.submit(attempt,'d2d5');self.assertEqual(skipped['reward']['status'],'skipped')
        self.now+=100;self.assertEqual(self.submit(attempt,'d2d5'),skipped);self.sender.assert_called_once()
    def test_expired_unknown_or_fake_attempts_cannot_trigger_motion(self):
        self.arm();attempt=self.start();self.now+=1801
        for token in [attempt,'forged']:
            with self.assertRaises(ValueError):self.submit(token)
        with self.assertRaises(ValueError):self.demo.start_capture({'exerciseId':'forged'})
        self.sender.assert_not_called()
    def test_practice_arming_still_requires_readiness_and_exact_practice_identity(self):
        payload={'gameId':PRACTICE_ID,'playerColor':'white','mode':'live','target':'vbot@robot.example',
                 'applicationVersion':'unknown','confirmSafeWorkspace':True,'confirmHandsetStop':True}
        with self.assertRaises(ValueError):self.demo.connect_practice(payload)
        with self.assertRaises(ValueError):self.demo.connect_practice({**payload,'gameId':'AbCd1234'})
        self.sender.assert_not_called()

if __name__=='__main__':unittest.main()
