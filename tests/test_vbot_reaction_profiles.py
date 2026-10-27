"""Offline session-profile behavior; never contacts a device."""
import sys
from pathlib import Path
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
