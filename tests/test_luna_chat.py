from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
from coach.history import CoachHistory
from coach.llm_coach import LLMCoach


class LunaChatTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = CoachHistory(Path(directory.name) / "history.jsonl")
        self.coach = LLMCoach.__new__(LLMCoach)
        self.coach.model = "configured-model"
        self.coach.client = Mock()
        self.coach.client.with_options.return_value = self.coach.client
        self.coach.client.responses.create.return_value = SimpleNamespace(output_text="Develop your pieces, then compare their activity.", status="completed")
        def engine_result(payload):
            board = app.analysis_board(payload)
            replay = board.copy()
            moves = []; san = []
            for _ in range(2):
                move = next((chess.Move.from_uci(uci) for uci in ("e2e4", "e7e5")
                             if chess.Move.from_uci(uci) in replay.legal_moves), next(iter(replay.legal_moves)))
                san.append(replay.san(move)); moves.append(move.uci()); replay.push(move)
            return {"fen": board.fen(), "lines": [{"uci": moves, "moves": san, "score": {"cp": 22, "mate": None}, "depth": 12}], "score": {"cp": 22, "mate": None}}
        self.engine = Mock(side_effect=engine_result)
        for target, value in [("app.history", self.journal), ("coach.history.history", self.journal),
                              ("app.get_llm_coach", Mock(return_value=self.coach)), ("app.analyze_position", self.engine)]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self, **updates):
        return {"sessionId": "analysis:save-a", "requestId": str(uuid.uuid4()),
                "fen": chess.STARTING_FEN, "rootFen": chess.STARTING_FEN, "moves": [],
                "message": "What should I notice?", "language": "en", "detail": "balanced", **updates}

    def test_exchange_and_model_audit_share_the_journal_and_survive_restart(self):
        payload = self.payload()
        turn = app.chat_reply(payload)
        restarted = CoachHistory(self.journal.path)
        self.assertEqual(restarted.chat_session(payload["sessionId"]), [turn])
        audit = restarted.audit_entries()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["chat_turn"], turn)
        self.assertEqual(audit[0]["record_id"], turn["recordId"])
        self.assertEqual(audit[0]["raw_output"], turn["reply"])
        arguments = self.coach.client.responses.create.call_args.kwargs
        self.assertFalse(arguments["store"])
        self.assertEqual(arguments["model"], "configured-model")
        self.assertEqual(audit[0]["input"], arguments["input"])
        self.assertTrue(audit[0]["payload"]["legal_moves"])
        self.assertEqual(audit[0]["payload"]["engine"]["lines"][0]["move_facts"][0]["san"], "e4")

    def test_followup_uses_only_its_session_with_each_turns_position(self):
        first = app.chat_reply(self.payload(message="Why develop first?"))
        app.chat_reply(self.payload(sessionId="analysis:other", message="Other board"))
        board = chess.Board(); board.push_uci("e2e4")
        app.chat_reply(self.payload(fen=board.fen(), moves=["e2e4"], message="And now?"))
        inputs = self.coach.client.responses.create.call_args.kwargs["input"]
        self.assertEqual(len(inputs), 3)
        self.assertIn(first["message"], inputs[0]["content"])
        self.assertIn(first["fen"], inputs[0]["content"])
        self.assertEqual(inputs[1]["content"], first["reply"])
        self.assertNotIn("Other board", str(inputs))
        self.assertIn(board.fen(), inputs[-1]["content"])

    def test_retry_is_idempotent_even_after_restart_and_rejects_changed_question(self):
        payload = self.payload()
        turn = app.chat_reply(payload)
        self.journal = CoachHistory(self.journal.path)
        with patch("app.history", self.journal):
            self.assertEqual(app.chat_reply(payload), turn)
            with self.assertRaisesRegex(ValueError, "different question"):
                app.chat_reply({**payload, "message": "New question"})
        self.coach.client.responses.create.assert_called_once()
        self.engine.assert_called_once()

    def test_invalid_message_session_and_snapshot_never_call_engine_or_model(self):
        for updates in [{"sessionId": "<script>"}, {"message": " "}, {"message": "x" * 2001},
                        {"requestId": "not-a-uuid"}, {"fen": "bad fen"}, {"moves": ["e2e5"]},
                        {"moves": ["e2e4"]}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                app.chat_reply(self.payload(**updates))
        self.engine.assert_not_called()
        self.coach.client.responses.create.assert_not_called()

    def test_missing_key_and_busy_model_keep_request_retryable(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            app.chat_reply(self.payload())
        app._llm_lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "another coaching question"):
                app.chat_reply(self.payload())
        finally:
            app._llm_lock.release()
        self.assertEqual(self.journal.entries(), [])
        self.engine.assert_not_called()

    def test_failed_model_attempt_is_auditable_but_is_not_a_saved_reply(self):
        self.coach.client.responses.create.side_effect = RuntimeError("provider failed")
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            app.chat_reply(self.payload())
        self.assertEqual(self.journal.chat_session("analysis:save-a"), [])
        self.assertEqual(self.journal.audit_entries()[0]["status"], "error")
        self.assertEqual(self.journal.audit_entries()[0]["outcome"], "rejected")
        self.assertFalse(app._llm_lock.locked())

    def test_clear_attempts_preserves_the_player_conversation(self):
        turn = app.chat_reply(self.payload())
        self.journal.clear_attempts()
        self.assertEqual(self.journal.chat_session("analysis:save-a"), [turn])
        audit = self.journal.audit_entries()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["chat_turn"], turn)
        self.assertNotIn("raw_output", audit[0])

    def test_history_context_is_bounded_but_saved_transcript_is_retained(self):
        for number in range(11):
            app.chat_reply(self.payload(message=f"Question {number}"))
        inputs = self.coach.client.responses.create.call_args.kwargs["input"]
        self.assertEqual(len(inputs), 17)
        self.assertNotIn('"question": "Question 0"', str(inputs))
        self.assertEqual(len(self.journal.chat_session("analysis:save-a")), 11)

    def test_live_chat_gets_coaching_for_this_position_only(self):
        self.journal.save_records("g", [{"ply": 1, "fenBefore": "before", "fenAfter": chess.STARTING_FEN,
                                         "playedMoveUci": "e2e4", "feedback": "Current lesson", "question": "Why?"},
                                        {"ply": 2, "fenBefore": "before", "fenAfter": "other position",
                                         "playedMoveUci": "e7e5", "feedback": "Different lesson"}])
        app.chat_reply(self.payload(sessionId="game:g"))
        context = self.journal.audit_entries()[-1]["payload"]
        self.assertEqual(context["coaching"][0]["feedback"], "Current lesson")
        self.assertEqual(len(context["coaching"]), 1)
        self.assertEqual(self.journal.audit_entries()[-1]["game_id"], "g")

    def test_incomplete_reply_is_logged_but_not_presented_as_success(self):
        self.coach.client.responses.create.return_value.status = "incomplete"
        with self.assertRaisesRegex(ValueError, "finish her reply"):
            app.chat_reply(self.payload())
        self.assertEqual(self.journal.chat_session("analysis:save-a"), [])
        self.assertEqual(self.journal.audit_entries()[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
