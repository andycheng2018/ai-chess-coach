from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
from coach.history import CoachHistory
from coach.llm_coach import LLMCoach


def record(**updates):
    return {
        "recordId": "analysis-1", "analysisId": "analysis-1", "ply": 1,
        "gameId": "game-a", "fenBefore": "initial position", "fenAfter": "next position",
        "playedMoveUci": "e2e4", "playedMove": "e4", "moveNumber": 1,
        "shouldCoach": True, "feedback": "Accepted lesson", "savedAt": 100,
        "explanationPending": False, "wordingSource": "llm", **updates,
    }


class HistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = CoachHistory(Path(directory.name) / "history.jsonl")
        for target in ("coach.history.history", "app.history"):
            patcher = patch(target, self.journal)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_session_and_audit_share_one_record_across_restart(self):
        self.journal.append([{
            "timestamp": "2026-10-01T00:00:00+00:00", "type": "feedback",
            "record_id": "analysis-1", "game_id": "game-a", "raw_output": '{"feedback":"Draft"}',
        }])
        self.journal.save_records("game-a", [record()])
        restarted = CoachHistory(self.journal.path)
        self.assertEqual(restarted.session("game-a"), [record()])
        self.assertEqual(restarted.audit_entries()[0]["learning_record"], record())
        self.assertEqual(restarted.audit_entries()[0]["raw_output"], '{"feedback":"Draft"}')

    def test_pending_and_stale_uploads_do_not_replace_completed_wording(self):
        self.journal.save_records("game-a", [record()])
        self.journal.save_records("game-a", [record(feedback="Checking…", savedAt=200, explanationPending=True)])
        self.journal.save_records("game-a", [record(feedback="Older lesson", savedAt=50)])
        self.assertEqual(self.journal.session("game-a")[0]["feedback"], "Accepted lesson")
        self.assertEqual(len(self.journal.entries()), 1)

    def test_fallback_and_takeback_replace_review_but_preserve_audit(self):
        self.journal.save_records("game-a", [record(explanationPending=True, wordingSource="pending")])
        fallback = record(feedback="Engine fallback", wordingSource="fallback", savedAt=200)
        self.journal.save_records("game-a", [fallback])
        self.assertEqual(self.journal.session("game-a"), [fallback])
        replacement = record(recordId="analysis-2", playedMoveUci="d2d4", playedMove="d4", savedAt=300)
        self.journal.save_records("game-a", [replacement])
        self.assertEqual(self.journal.session("game-a"), [replacement])
        self.assertEqual(len(self.journal.entries()), 3)
        self.journal.save_records("game-b", [record(savedAt=400)])
        self.assertEqual(self.journal.session("game-a"), [replacement])

    def test_clear_removes_attempts_and_keeps_learning_records(self):
        self.journal.save_records("game-a", [record()])
        self.journal.append([{"event": "model_attempt", "game_id": "game-a", "record_id": "analysis-1"}])
        self.journal.clear_attempts()
        self.assertEqual(self.journal.session("game-a"), [record()])
        self.assertEqual(len(self.journal.audit_entries()), 1)
        self.assertNotIn("raw_output", self.journal.audit_entries()[0])

    def test_old_logs_and_truncated_tail_survive_new_appends(self):
        self.journal.path.write_text('{"type":"feedback","raw_output":"old"}\n{"truncated":', encoding="utf-8")
        self.journal.save_records("game-a", [record()])
        self.assertEqual(self.journal.audit_entries()[0]["raw_output"], "old")
        self.assertEqual(self.journal.session("game-a"), [record()])

    def test_legacy_attempt_links_only_with_an_exact_unambiguous_game_position_move(self):
        self.journal.save_records("game-a", [record()])
        self.journal.append([
            {"timestamp": "2026-10-01", "type": "feedback", "game_id": game,
             "played_move_uci": "e2e4", "payload": {"fen_before": "initial position"}}
            for game in ("game-a", "game-b", "")
        ])
        attempts = [entry for entry in self.journal.audit_entries() if "payload" in entry and "record" not in entry]
        linked = [entry for entry in attempts if "learning_record" in entry]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["link_source"], "legacy_position")
        self.assertEqual(linked[0]["learning_record"], record())

    def test_parallel_writers_preserve_every_complete_event(self):
        def write(index):
            self.journal.append([{"event": "model_attempt", "index": index}])
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(write, range(32)))
        self.assertEqual({entry["index"] for entry in self.journal.entries()}, set(range(32)))

    def coach(self, outputs):
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            output = outputs.pop(0)
            if isinstance(output, Exception):
                raise output
            return SimpleNamespace(output_text=json.dumps(output))
        coach = LLMCoach.__new__(LLMCoach)
        coach.client = SimpleNamespace(responses=SimpleNamespace(create=create))
        coach.model = "test-model"
        coach.instructions = "Use verified facts."
        return coach, calls

    def test_correction_attempts_link_to_one_accepted_learning_record(self):
        coach, calls = self.coach([
            {"feedback": "This forks the queen and pawn.", "themes": ["Fork / Double Attack"]},
            {"feedback": "Attack the loose pawn.", "themes": []},
        ])
        wording = coach.create_feedback({"played_move": "e4"}, game_id="game-a", record_id="analysis-1")
        self.journal.save_records("game-a", [record(**wording)])
        attempts = self.journal.audit_entries()
        self.assertEqual(len(attempts), 2)
        self.assertEqual([entry["outcome"] for entry in attempts], ["rejected", "accepted"])
        self.assertNotEqual(attempts[0]["attempt_id"], attempts[1]["attempt_id"])
        self.assertEqual(attempts[1]["final_output"]["feedback"], wording["feedback"])
        self.assertEqual(attempts[0]["learning_record"], attempts[1]["learning_record"])
        self.assertIn("CORRECTION REQUIRED", attempts[1]["instructions"])
        self.assertTrue(all(call["store"] is False for call in calls))

    def test_validation_failure_is_not_marked_as_accepted(self):
        coach, _ = self.coach([{"feedback": ""}])
        with self.assertRaisesRegex(ValueError, "empty feedback"):
            coach.create_feedback({}, game_id="game-a", record_id="analysis-1")
        attempt = self.journal.audit_entries()[0]
        self.assertEqual(attempt["outcome"], "rejected")
        self.assertIn("empty feedback", attempt["validation_error"])
        self.assertNotIn("final_output", attempt)

    def test_api_failure_keeps_inputs_and_error(self):
        coach, _ = self.coach([RuntimeError("provider unavailable")])
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            coach.create_feedback({}, game_id="game-a", record_id="analysis-1")
        attempt = self.journal.audit_entries()[0]
        self.assertEqual(attempt["status"], "error")
        self.assertIn("instructions", attempt)
        self.assertIn("payload", attempt)

    def test_explanation_persists_final_record_before_client_receives_it(self):
        coach, _ = self.coach([{"feedback": "Attack the loose pawn.", "themes": []}])
        base = record(recordId="placeholder", explanationPending=True, wordingSource="pending")
        analysis = {"played_move": "e4", "_history_record": base}
        analysis_id = app.cache_analysis(analysis)
        base["recordId"] = analysis_id
        self.journal.save_records("game-a", [base])
        with patch("app.get_llm_coach", return_value=coach), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            wording = app.explain_analysis({"analysisId": analysis_id, "gameId": "game-a"})
        saved = self.journal.session("game-a")[0]
        self.assertEqual(saved["feedback"], wording["feedback"])
        self.assertEqual(saved["recordId"], analysis_id)
        self.assertEqual(self.journal.audit_entries()[0]["learning_record"], saved)
        with self.assertRaisesRegex(ValueError, "does not match"):
            app.explain_analysis({"analysisId": analysis_id, "gameId": "game-b"})

    def request(self, method, path, payload=None):
        handler = app.Handler.__new__(app.Handler)
        handler.path = path
        handler._json_body = lambda: payload
        replies = []
        handler._send = lambda status, body: replies.append((status, body))
        getattr(handler, f"do_{method}")()
        return replies[0]

    def test_history_and_audit_routes_use_the_same_store(self):
        status, body = self.request("POST", "/api/coach/history", {"gameId": "game-a", "records": [record()]})
        self.assertEqual(status, 200)
        self.assertEqual(body["records"], [record()])
        self.assertEqual(self.request("GET", "/api/coach/history?gameId=game-a")[1]["records"], [record()])
        self.assertEqual(self.request("GET", "/api/logs")[1]["logs"][0]["learning_record"], record())
        self.assertEqual(self.request("GET", "/api/coach/history")[0], 400)
        self.assertEqual(self.request("POST", "/api/coach/history", {"gameId": "game-a", "records": [{}]})[0], 400)
        self.request("POST", "/api/logs/clear")
        self.assertEqual(self.journal.session("game-a"), [record()])


if __name__ == "__main__":
    unittest.main()
