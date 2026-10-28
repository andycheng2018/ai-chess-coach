"""Offline reconciliation checks; only fake game snapshots and robot sender."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from vbot_demo import VbotDemo


class StreamWaitTests(unittest.TestCase):
    def setUp(self):
        import chess
        self.now = 100.0
        self.sender = Mock()
        self.demo = VbotDemo(sender=self.sender, clock=lambda: self.now, verification={})
        self.demo.arm({'mode':'rehearsal', 'gameId':'AbCd1234'})
        self.record = dict(recordId='engine-1', gameId='AbCd1234', ply=1,
            playerColor='white', playedMoveUci='e2e4', playedMove='e4',
            classification='good', fenBefore=chess.STARTING_FEN)
        self.demo.remember(self.record)
        self.payload = {key:self.record[key] for key in ('recordId','gameId','playerColor')}

    def snapshot(self, moves='', status='started'):
        return dict(gameId='AbCd1234', botColor='black', initialFen='startpos',
            updatedAt=int(time.time()*1000), timeControlKnown=True, clock=None,
            state=dict(status=status, moves=moves))

    def advance(self, seconds):
        self.now += seconds

    def test_move_arriving_just_after_analysis_is_reconciled_once(self):
        reader=Mock(side_effect=[self.snapshot(), self.snapshot('e2e4 e7e5')])
        result=self.demo.reconcile(self.payload, reader, wait=self.advance)
        self.assertEqual(result['status'],'rehearsed')
        self.assertEqual(reader.call_count,2)
        self.sender.assert_not_called()
        self.assertEqual(len([e for e in self.demo.events if e['status']=='rehearsed']),1)
        again=self.demo.reconcile(self.payload,lambda _:self.snapshot('e2e4'),wait=self.advance)
        self.assertEqual(again['status'],'skipped')

    def test_missing_snapshot_can_arrive_within_the_window(self):
        reader=Mock(side_effect=[None,self.snapshot('e2e4')])
        self.assertEqual(self.demo.reconcile(self.payload,reader,wait=self.advance)['status'],'rehearsed')
        self.sender.assert_not_called()

    def test_deadline_skips_without_submitting_or_queuing(self):
        result=self.demo.reconcile(self.payload,lambda _:self.snapshot(),timeout=.1,wait=self.advance)
        self.assertEqual(result['status'],'skipped')
        self.assertIn('sync window',result['reason'])
        self.assertLessEqual(self.now,100.100001)
        self.sender.assert_not_called()
        self.assertFalse(self.demo.busy)
        self.assertEqual(len(self.demo.seen),0)

    def test_disarm_while_waiting_ends_observation(self):
        def wait(seconds):
            self.advance(seconds)
            self.demo.disarm()
        result=self.demo.reconcile(self.payload,lambda _:self.snapshot(),wait=wait)
        self.assertEqual(result['status'],'skipped')
        self.assertIn('Demo changed',result['reason'])
        self.sender.assert_not_called()

    def test_rearm_cannot_adopt_an_old_pending_observation(self):
        def wait(seconds):
            self.advance(seconds)
            self.demo.arm({'mode':'rehearsal','gameId':'AbCd1234'})
        reader=Mock(side_effect=[self.snapshot(),self.snapshot('e2e4')])
        result=self.demo.reconcile(self.payload,reader,wait=wait)
        self.assertIn('Demo changed',result['reason'])
        self.sender.assert_not_called()

    def test_branch_mismatch_and_terminal_game_never_wait(self):
        for snapshot in (self.snapshot('d2d4'), self.snapshot('e2e4','mate')):
            wait=Mock()
            result=self.demo.reconcile(self.payload,lambda _:snapshot,wait=wait)
            self.assertEqual(result['status'],'skipped')
            wait.assert_not_called()
        self.sender.assert_not_called()

    def test_busy_or_cooling_action_never_waits_to_become_available(self):
        for busy in (True,False):
            self.demo.busy=busy
            self.demo.last_finished=self.now
            wait=Mock()
            result=self.demo.reconcile(self.payload,lambda _:self.snapshot(),wait=wait)
            self.assertEqual(result['status'],'skipped')
            wait.assert_not_called()
        self.sender.assert_not_called()

    def test_slow_snapshot_cannot_dispatch_after_the_deadline(self):
        def reader(_):
            self.advance(.2)
            return self.snapshot('e2e4')
        result=self.demo.reconcile(self.payload,reader,timeout=.1,wait=self.advance)
        self.assertIn('sync window',result['reason'])
        self.assertFalse(self.demo.seen)
        self.sender.assert_not_called()

    def test_oversleep_cannot_adopt_a_late_confirming_snapshot(self):
        reader=Mock(side_effect=[self.snapshot(),self.snapshot('e2e4')])
        result=self.demo.reconcile(self.payload,reader,timeout=.1,wait=lambda _:self.advance(.2))
        self.assertIn('sync window',result['reason'])
        self.assertEqual(reader.call_count,1)
        self.sender.assert_not_called()

    def test_terminal_state_arriving_while_waiting_ends_observation(self):
        reader=Mock(side_effect=[self.snapshot(),self.snapshot('e2e4','mate')])
        result=self.demo.reconcile(self.payload,reader,wait=self.advance)
        self.assertEqual(result['status'],'skipped')
        self.assertIn('No active game',result['reason'])
        self.sender.assert_not_called()

    def test_busy_action_during_stream_wait_skips_instead_of_queuing(self):
        reader=Mock(side_effect=[self.snapshot(),self.snapshot('e2e4')])
        def wait(seconds):
            self.advance(seconds)
            self.demo.busy=True
        result=self.demo.reconcile(self.payload,reader,wait=wait)
        self.assertEqual(result['status'],'skipped')
        self.assertIn('not queued',result['reason'])
        self.sender.assert_not_called()

    def test_invalid_record_never_uses_the_wait_window(self):
        wait=Mock()
        result=self.demo.reconcile({**self.payload,'recordId':'forged'},lambda _:None,wait=wait)
        self.assertEqual(result['status'],'skipped')
        wait.assert_not_called()
        self.sender.assert_not_called()


if __name__=='__main__':unittest.main()
