"""Offline session-profile behavior; never contacts a device."""
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from vbot_demo import VbotDemo
from vbot_policy import HEAD_PRESETS

class ReactionProfiles(unittest.TestCase):
    def make(self, profile):
        self.now=1000
        d=VbotDemo(clock=lambda:self.now, verification={},sender=Mock(),chooser=lambda pool:pool[0])
        d.arm({'gameId':'AbCd1234','reactionProfile':profile})
        return d
    def record(self):
        return dict(gameId='AbCd1234',playerColor='white',ply=1,classification='good')
    def test_unknown_profile_does_not_arm(self):
        d=VbotDemo(verification={})
        with self.assertRaises(ValueError): d.arm({'gameId':'AbCd1234','reactionProfile':'unsafe'})
        self.assertFalse(d.armed)
    def test_quiet_major_becomes_head_gesture_without_robot_contact(self):
        d=self.make('quiet')
        e=d._submit(self.record(),{'tier':'major','reason':'Material gain','briefOnly':False})
        self.assertEqual(e['tier'],'small');self.assertIn(e['preset'],HEAD_PRESETS)
        d.sender.assert_not_called()
    def test_quiet_blunder_has_no_body_performance(self):
        d=self.make('quiet')
        e=d._submit({**self.record(),'classification':'blunder'})
        self.assertEqual(e['status'],'skipped');d.sender.assert_not_called()
    def test_showmanship_changes_only_small_rest(self):
        d=self.make('showmanship');d._submit(self.record())
        self.assertEqual(d.cooldown,3)
        self.now+=4
        e=d._submit({**self.record(),'ply':3},{'tier':'major','reason':'Gain','briefOnly':False})
        self.assertEqual(e['tier'],'major');self.assertEqual(d.cooldown,20)
        d.sender.assert_not_called()
    def test_default_profile_remains_balanced(self):
        d=VbotDemo(verification={});d.arm({'gameId':'AbCd1234'})
        self.assertEqual(d.status()['reactionProfile'],'balanced')
    def test_named_demo_profile_is_accepted(self):
        d=self.make('demo')
        self.assertEqual(d.status()['reactionProfile'],'demo')


LINE = 'e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 d2d3 f8c5 c2c3 d7d6'.split()


class DemoRhythm(unittest.TestCase):
    """Demo mode: Rock You on every second human move, whatever the coach says."""
    def setUp(self):
        self.now=1000.0
        self.sender=Mock(return_value={'status':'completed','readyForNext':True})
        self.d=VbotDemo(clock=lambda:self.now, verification={}, sender=self.sender)

    def arm(self, mode='rehearsal', **extra):
        return self.d.arm({'gameId':'AbCd1234','mode':mode,'reactionProfile':'demo','target':'vbot@robot.example',
                           'applicationVersion':'V1.6.0','confirmSafeWorkspace':True,'confirmHandsetStop':True,
                           'playerColor':'white', **extra})

    def play(self, ply, classification='inaccuracy'):
        """White's move at 1-based ply `ply`, confirmed by the stream."""
        import chess
        board=chess.Board()
        for uci in LINE[:ply-1]: board.push_uci(uci)
        record=dict(recordId=f'r{ply}', gameId='AbCd1234', ply=ply, playerColor='white',
                    playedMoveUci=LINE[ply-1], playedMove=LINE[ply-1], classification=classification,
                    fenBefore=board.fen())
        self.d.remember(record)
        game=dict(gameId='AbCd1234', botColor='black', initialFen='startpos', updatedAt=int(time.time()*1000),
                  timeControlKnown=True, clock=None, state=dict(status='started', moves=' '.join(LINE[:ply+1])))
        self.now+=10
        return self.d.celebrate({'recordId':f'r{ply}','gameId':'AbCd1234','playerColor':'white'}, game)

    def test_every_second_move_dances_rock_you_regardless_of_verdict(self):
        self.arm()
        results=[self.play(p, c) for p,c in ((1,'blunder'),(3,'mistake'),(5,'good'),(7,'inaccuracy'),(9,'best'))]
        self.assertEqual([r['status'] for r in results],['skipped','rehearsed','skipped','rehearsed','skipped'])
        self.assertTrue(all(r['preset']=='actions/ROCKYOU.json' and r['tier']=='demo' for r in results if r['status']=='rehearsed'))
        self.sender.assert_not_called()

    def test_busy_dog_dances_on_the_next_move_instead(self):
        self.arm()
        self.play(1)
        self.d.busy=True
        self.assertEqual(self.play(3)['status'],'skipped')
        self.d.busy=False
        r=self.play(5)
        self.assertEqual((r['status'],r['preset']),('rehearsed','actions/ROCKYOU.json'))
        self.assertEqual(self.play(7)['status'],'skipped')
        self.assertEqual(self.play(9)['status'],'rehearsed')

    def test_live_demo_sends_rock_you(self):
        self.arm('live')
        self.play(1)
        r=self.play(3)
        self.assertEqual((r['status'],r['preset'],r['tier']),('requested','actions/ROCKYOU.json','demo'))
        deadline=time.time()+5
        while self.d.busy and time.time()<deadline: time.sleep(.01)
        self.assertEqual(self.sender.call_args[0][1],'actions/ROCKYOU.json')
        self.assertTrue(self.d.armed)

    def test_capture_practice_keeps_its_own_rewards(self):
        from vbot_demo import PRACTICE_ID
        self.d.arm({'gameId':PRACTICE_ID,'mode':'rehearsal','reactionProfile':'demo','practice':True})
        self.assertEqual(self.d.status()['reactionProfile'],'balanced')
