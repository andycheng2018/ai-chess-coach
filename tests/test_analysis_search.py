from __future__ import annotations
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock
import chess
import chess.engine
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from coach.analysis_search import AnalysisSearches

class Stream:
    def __init__(self, limit):
        self.limit=limit
        self.stopped=threading.Event()
        self.multipv=[{'depth':limit.depth or 9,'score':chess.engine.PovScore(chess.engine.Cp(20),chess.WHITE),'pv':[chess.Move.from_uci('e2e4')]}]
    def __enter__(self): return self
    def __exit__(self,*args): self.stop()
    def stop(self): self.stopped.set()
    def __iter__(self):
        yield self.multipv[0]
        if self.limit.depth is None: self.stopped.wait(3)

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.streams=[]
        def analysis(board, limit, multipv):
            self.assertEqual(multipv,3)
            stream=Stream(limit);self.streams.append(stream);return stream
        self.adapter=Mock();self.adapter.engine.analysis.side_effect=analysis
        self.factory=Mock(return_value=self.adapter)
        self.manager=AnalysisSearches(self.factory,lease_seconds=0.2)
        self.owner=str(uuid.uuid4())
    def tearDown(self): self.manager.close()
    def payload(self, mode='depth', depth=7): return {'id':str(uuid.uuid4()),'owner':self.owner,'mode':mode,'depth':depth}
    def wait(self, condition):
        until=time.monotonic()+2
        while not condition() and time.monotonic()<until: time.sleep(.01)
        self.assertTrue(condition())
    def test_exact_depth_has_no_time_limit_and_returns_live_format(self):
        payload=self.payload();self.manager.start(payload,chess.Board());self.wait(lambda:self.manager.jobs[payload['id']].done)
        self.assertEqual(self.streams[0].limit.depth,7);self.assertIsNone(self.streams[0].limit.time)
        result=self.manager.status(payload);self.assertFalse(result['running']);self.assertEqual(result['result']['lines'][0]['depth'],7);self.assertEqual(result['result']['score']['cp'],20)
        self.adapter.close.assert_called_once()
    def test_unlimited_can_be_stopped_and_keeps_last_result(self):
        payload=self.payload('unlimited');self.manager.start(payload,chess.Board());self.wait(lambda:self.manager.status(payload)['result'] is not None)
        self.assertIsNone(self.streams[0].limit.depth);self.assertIsNone(self.streams[0].limit.time)
        self.manager.stop(payload);self.wait(lambda:self.manager.jobs[payload['id']].done)
        self.assertIsNotNone(self.manager.status(payload)['result']);self.assertTrue(self.streams[0].stopped.is_set())
    def test_session_ownership_and_replacement(self):
        first=self.payload('unlimited');self.manager.start(first,chess.Board());self.wait(lambda:len(self.streams)==1)
        foreign={**self.payload(), 'owner':str(uuid.uuid4())}
        with self.assertRaisesRegex(RuntimeError,'another session'): self.manager.start(foreign,chess.Board())
        with self.assertRaises(ValueError): self.manager.stop({**first,'owner':foreign['owner']})
        next_job=self.payload();self.manager.start(next_job,chess.Board());self.wait(lambda:self.manager.jobs[next_job['id']].done)
        self.assertTrue(self.streams[0].stopped.is_set());self.assertTrue(self.manager.jobs[first['id']].done)
    def test_abandoned_search_expires(self):
        payload=self.payload('unlimited');self.manager.start(payload,chess.Board());self.wait(lambda:len(self.streams)==1)
        self.manager.jobs[payload['id']].last_seen=time.monotonic()-1
        self.manager.expire();self.wait(lambda:self.manager.jobs[payload['id']].done);self.assertTrue(self.streams[0].stopped.is_set())
    def test_terminal_position_needs_no_engine(self):
        payload=self.payload('unlimited');self.manager.start(payload,chess.Board('7k/8/8/8/8/8/8/K7 w - - 0 1'))
        self.wait(lambda:self.manager.jobs[payload['id']].done);self.factory.assert_not_called();self.assertTrue(self.manager.status(payload)['result']['terminal'])
    def test_invalid_depth_never_starts_worker(self):
        for value in [0,129,True,1.5,'12']:
            with self.assertRaises(ValueError):self.manager.start(self.payload(depth=value),chess.Board())
        self.factory.assert_not_called()
