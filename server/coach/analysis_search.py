"""Stoppable long searches using the same Stockfish adapter and score format.

One long-search worker is allowed. Its engine does not monopolize the coaching
engine. A short renewable lease stops abandoned browser searches.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import chess
import chess.engine

from coach.stockfish_analyzer import StockfishAnalyzer, position_analysis_result


@dataclass
class Search:
    id: str
    owner: str
    board: chess.Board
    depth: int | None
    last_seen: float = field(default_factory=time.monotonic)
    cancelled: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str | None = None
    done: bool = False
    stream: Any = None
    thread: Any = None


class AnalysisSearches:
    def __init__(self, factory=StockfishAnalyzer, lease_seconds=12):
        self.factory = factory
        self.lease_seconds = lease_seconds
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()
        self.jobs: dict[str, Search] = {}
        self.active: Search | None = None
        self.closed = threading.Event()
        self.watcher: threading.Thread | None = None

    @staticmethod
    def credentials(payload):
        try:
            return str(uuid.UUID(payload['id'])), str(uuid.UUID(payload['owner']))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Valid search id and owner are required.') from exc

    def start(self, payload, board):
        job_id, owner = self.credentials(payload)
        mode = payload.get('mode')
        depth = payload.get('depth')
        if mode not in {'depth', 'unlimited'}:
            raise ValueError('Search mode must be depth or unlimited.')
        if mode == 'depth' and (type(depth) is not int or not 1 <= depth <= 128):
            raise ValueError('Depth must be a whole number from 1 to 128.')
        depth = depth if mode == 'depth' else None
        with self.start_lock:
            with self.lock:
                if job_id in self.jobs:
                    if self.jobs[job_id].owner != owner:
                        raise ValueError('Search belongs to another session.')
                    return self.snapshot(self.jobs[job_id])
                old = self.active
                if old and not old.done and old.owner != owner:
                    raise RuntimeError('The analysis engine is busy in another session. Try again after that search stops.')
            if old and not old.done:
                self.stop_job(old)
                old.thread.join(timeout=2)
                if old.thread.is_alive():
                    raise RuntimeError('The analysis engine is busy stopping its previous search. Try again.')
            job = Search(job_id, owner, board.copy(), depth)
            with self.lock:
                for key in list(self.jobs):
                    if self.jobs[key].done and time.monotonic() - self.jobs[key].last_seen > 60:
                        del self.jobs[key]
                if len(self.jobs) >= 32:
                    for key in list(self.jobs):
                        if self.jobs[key].done:
                            del self.jobs[key]
                            break
                self.jobs[job_id] = job
                self.active = job
                job.thread = threading.Thread(target=self.run, args=(job,), daemon=True)
                job.thread.start()
                if self.watcher is None:
                    self.watcher = threading.Thread(target=self.watch, daemon=True)
                    self.watcher.start()
                return self.snapshot(job)

    def snapshot(self, job):
        return {'id': job.id, 'running': not job.done and not job.cancelled.is_set(),
                'result': job.result, 'error': job.error, 'depth': job.depth}

    def status(self, payload):
        job_id, owner = self.credentials(payload)
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.owner != owner:
                raise ValueError('Search not found in this session. Start a new search.')
            job.last_seen = time.monotonic()
            return self.snapshot(job)

    def stop(self, payload):
        job_id, owner = self.credentials(payload)
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return {'stopped': True}
            if job.owner != owner:
                raise ValueError('Search belongs to another session.')
        self.stop_job(job)
        with self.lock:
            return self.snapshot(job)

    def stop_job(self, job):
        job.cancelled.set()
        if job.stream is not None:
            try:
                job.stream.stop()
            except chess.engine.EngineError:
                pass

    def run(self, job):
        analyzer = None
        try:
            terminal = position_analysis_result(job.board, [])
            if terminal is not None:
                with self.lock:
                    job.result = terminal
                return
            if job.cancelled.is_set():
                return
            analyzer = self.factory()
            with analyzer.engine.analysis(job.board, chess.engine.Limit(depth=job.depth),
                                          multipv=min(3, job.board.legal_moves.count())) as stream:
                job.stream = stream
                if job.cancelled.is_set():
                    stream.stop()
                last_update = 0.0
                for info in stream:
                    if job.cancelled.is_set():
                        stream.stop()
                        break
                    now = time.monotonic()
                    if now - last_update < 0.15:
                        continue
                    result = position_analysis_result(job.board, stream.multipv)
                    if result is not None:
                        with self.lock:
                            job.result = result
                        last_update = now
                final = position_analysis_result(job.board, stream.multipv)
                if final is not None:
                    with self.lock:
                        job.result = final
        except Exception as exc:
            with self.lock:
                job.error = str(exc)
        finally:
            if analyzer is not None:
                analyzer.close()
            with self.lock:
                job.done = True
                job.stream = None

    def expire(self):
        with self.lock:
            job = self.active
            expired = job and not job.done and time.monotonic() - job.last_seen > self.lease_seconds
        if expired:
            self.stop_job(job)

    def watch(self):
        while not self.closed.wait(1):
            self.expire()

    def close(self):
        self.closed.set()
        with self.lock:
            job = self.active
        if job and not job.done:
            self.stop_job(job)
            job.thread.join(timeout=3)


analysis_searches = AnalysisSearches()
