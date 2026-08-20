from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from bot_runtime import BOT_LEVELS, LichessBotRuntime  # noqa: E402
from coach.llm_coach import LLMCoach, ensure_primary_theme_named, normalize_chess_themes, supported_chess_themes, unverified_tactical_claims  # noqa: E402
from coach.stockfish_analyzer import capture_context, classify_move, configure_supported_options, pv_to_san, verified_move_themes  # noqa: E402
from coach.tactic_verifier import verified_move_facts, verify_tactical_line  # noqa: E402
from app import COACH_ANALYSIS_PROFILES, Handler, analyze_move, critical_position_question, fallback_coaching  # noqa: E402


class CoreTests(unittest.TestCase):
    def test_puzzle_labels_are_verified_from_the_answer_move(self) -> None:
        fork_board = chess.Board(
            "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
        )
        self.assertIn(
            "Fork / Double Attack",
            verified_move_themes(
                fork_board,
                chess.Move.from_uci("b5c7"),
            ),
        )

        pin_board = chess.Board(
            "4k3/8/2n5/8/2B5/8/8/4K3 w - - 0 1"
        )
        self.assertIn(
            "Pin",
            verified_move_themes(
                pin_board,
                chess.Move.from_uci("c4b5"),
            ),
        )

        hanging_board = chess.Board(
            "r3k3/8/8/8/8/8/8/Q3K3 w - - 0 1"
        )
        self.assertIn(
            "Hanging Piece",
            verified_move_themes(
                hanging_board,
                chess.Move.from_uci("a1a8"),
            ),
        )

        one_target_board = chess.Board(
            "4k3/8/8/2p5/8/8/3N4/4K3 w - - 0 1"
        )
        self.assertNotIn(
            "Fork / Double Attack",
            verified_move_themes(
                one_target_board,
                chess.Move.from_uci("d2e4"),
            ),
        )
        self.assertEqual(
            verified_move_facts(
                one_target_board,
                chess.Move.from_uci("d2e4"),
            )["attacked_enemy_pieces"],
            ["pawn on c5"],
        )

        queen_and_pawn_board = chess.Board(
            "4k3/8/5q2/2p5/8/8/3N4/4K3 w - - 0 1"
        )
        self.assertIn(
            "Fork / Double Attack",
            verified_move_themes(
                queen_and_pawn_board,
                chess.Move.from_uci("d2e4"),
            ),
        )

    def test_unverified_fork_is_rejected_from_labels_and_prose(self) -> None:
        analysis = {
            "best_move_verified_themes": [],
            "opponent_reply_verified_themes": [],
        }

        self.assertEqual(
            supported_chess_themes(
                analysis,
                ["Fork / Double Attack", "Skewer"],
            ),
            [],
        )
        self.assertEqual(
            unverified_tactical_claims(
                "Knight e4 forks the queen and pawn.",
                analysis,
            ),
            ["Fork / Double Attack"],
        )
        self.assertEqual(
            unverified_tactical_claims(
                "This skewer wins the rook.",
                analysis,
            ),
            ["Skewer"],
        )

    def test_coach_retries_an_unverified_spoken_fork(self) -> None:
        class FakeResponse:
            def __init__(self, data):
                self.output_text = __import__("json").dumps(data)

        class FakeResponses:
            def __init__(self):
                self.calls = []
                self.outputs = [
                    {
                        "title": "Missed tactic",
                        "feedback": "Knight e4 forks the queen and pawn.",
                        "lesson": "Look for forks.",
                        "question": "",
                        "themes": ["Fork / Double Attack"],
                    },
                    {
                        "title": "Pawn pressure",
                        "feedback": "Knight e4 attacks the pawn on c5.",
                        "lesson": "Check every attacked square.",
                        "question": "",
                        "themes": [],
                    },
                ]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse(self.outputs.pop(0))

        class FakeClient:
            def __init__(self):
                self.responses = FakeResponses()

        coach = LLMCoach.__new__(LLMCoach)
        coach.client = FakeClient()
        coach.model = "test-model"
        coach.instructions = "Use Stockfish facts only."

        result = coach.create_feedback({
            "played_move": "Qc4",
            "best_move": "Ne4",
            "best_move_verified_themes": [],
            "opponent_reply_verified_themes": [],
        })

        self.assertEqual(
            result["feedback"],
            "Knight e4 attacks the pawn on c5.",
        )
        self.assertEqual(result["themes"], [])
        self.assertEqual(
            len(coach.client.responses.calls),
            2,
        )

    def test_line_verifier_names_slider_tactics_with_evidence(self) -> None:
        cases = [
            (
                "r3k3/q7/8/8/8/8/R7/4K3 w - - 0 1",
                "a2a6",
                "Skewer",
                "queen on a7",
            ),
            (
                "q3k3/p7/8/8/8/8/R7/4K3 w - - 0 1",
                "a2a6",
                "X-Ray Attack",
                "queen on a8",
            ),
            (
                "4k3/8/8/8/4r3/3N4/8/KB6 w - - 0 1",
                "d3f4",
                "Discovered Attack",
                "bishop on b1",
            ),
        ]

        for fen, uci, expected_theme, reason_text in cases:
            with self.subTest(theme=expected_theme):
                board = chess.Board(fen)
                evidence = verify_tactical_line(
                    board,
                    [chess.Move.from_uci(uci)],
                )
                match = next(
                    item
                    for item in evidence
                    if item.theme == expected_theme
                )
                self.assertIn(reason_text, match.reason)

    def test_line_verifier_names_specific_mating_pattern(self) -> None:
        back_rank = chess.Board(
            "6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1"
        )
        themes = {
            item.theme
            for item in verify_tactical_line(
                back_rank,
                [chess.Move.from_uci("e1e8")],
            )
        }
        self.assertIn("Mate in One", themes)
        self.assertIn("Back-Rank Mate", themes)

        smothered = chess.Board(
            "6rk/6pp/7N/8/2B5/8/8/4K3 w - - 0 1"
        )
        themes = {
            item.theme
            for item in verify_tactical_line(
                smothered,
                [chess.Move.from_uci("h6f7")],
            )
        }
        self.assertIn("Mate in One", themes)
        self.assertIn("Smothered Mate", themes)

    def test_confirmed_tactic_is_always_named_in_spoken_feedback(self) -> None:
        feedback = "The knight attacks the queen and rook at the same time."
        named = ensure_primary_theme_named(
            feedback,
            ["Fork / Double Attack"],
            "en",
        )
        self.assertIn("fork / double attack", named.lower())

        already_named = "This fork wins the exchange."
        self.assertEqual(
            ensure_primary_theme_named(
                already_named,
                ["Fork / Double Attack"],
                "en",
            ),
            already_named,
        )

    def test_capture_context_reports_legal_recapture(self) -> None:
        board = chess.Board(
            "4k3/8/8/q7/8/8/2N5/R3K3 b - - 0 1"
        )
        context = capture_context(
            board,
            chess.Move.from_uci("a5a1"),
        )
        self.assertTrue(context["is_capture"])
        self.assertTrue(context["legally_recapturable"])
        self.assertIn("Nxa1", context["legal_recaptures"])
        self.assertNotIn(
            "Hanging Piece",
            verified_move_themes(
                board,
                chess.Move.from_uci("a5a1"),
            ),
        )

    def test_critical_question_uses_selected_analysis_profile(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeAnalyzer:
            def analyze_critical_position(self, board, **kwargs):
                calls.append(kwargs)
                return {"is_critical": False}

        with patch("app.get_analyzer", return_value=FakeAnalyzer()):
            result = critical_position_question({
                "fen": chess.STARTING_FEN,
                "detail": "deep",
            })

        self.assertFalse(result["isCritical"])
        self.assertEqual(calls, [{
            "time_ms": COACH_ANALYSIS_PROFILES["deep"]["time_ms"],
            "profile": "deep",
        }])

    def test_critical_question_marks_attacked_rook_as_recapturable(self) -> None:
        before = chess.Board(
            "3qk3/8/8/8/8/8/2N4K/R7 b - - 0 1"
        )
        after = before.copy()
        after.push_uci("d8a5")
        captured: dict[str, object] = {}

        class FakeAnalyzer:
            def analyze_critical_position(self, board, **kwargs):
                return {
                    "is_critical": True,
                    "in_check": False,
                    "threat_is_capture": True,
                    "threat_is_mate": False,
                    "threat_gives_check": False,
                }

        class FakeCoach:
            def create_critical_question(self, position, **kwargs):
                captured.update(position)
                return {
                    "title": "Opponent idea",
                    "question": "What pressure did the queen add?",
                }

        with (
            patch("app.get_analyzer", return_value=FakeAnalyzer()),
            patch("app.get_llm_coach", return_value=FakeCoach()),
        ):
            result = critical_position_question({
                "fen": after.fen(),
                "fenBeforeOpponent": before.fen(),
                "lastOpponentMove": "Qa5",
                "lastOpponentMoveUci": "d8a5",
                "detail": "quick",
            })

        self.assertTrue(result["isCritical"])
        details = captured["attacked_target_details"]
        self.assertIsInstance(details, list)
        rook = next(
            item
            for item in details
            if item["target"] == "rook on a1"
        )
        self.assertTrue(rook["defended"])
        self.assertIn("Nxa1", rook["legal_recaptures"])

    def test_disconnected_client_does_not_raise_a_second_response_error(self) -> None:
        handler = Handler.__new__(Handler)
        handler.close_connection = False

        def disconnected(_status):
            raise BrokenPipeError("client canceled stale request")

        handler.send_response = disconnected
        handler._send(200, {"ok": True})
        self.assertTrue(handler.close_connection)

        handler.close_connection = False
        handler._send_bytes(200, b"audio", "audio/mpeg")
        self.assertTrue(handler.close_connection)

    def test_chess_themes_are_validated_deduplicated_and_limited(self) -> None:
        self.assertEqual(
            normalize_chess_themes([
                "Fork / Double Attack",
                "Made Up Tactic",
                "Pin",
                "Pin",
                "Skewer",
                "X-Ray Attack",
            ]),
            ["Fork / Double Attack", "Pin", "Skewer"],
        )
        self.assertEqual(normalize_chess_themes("Pin"), [])

    def test_coach_detail_profiles_increase_engine_strength(self) -> None:
        quick = COACH_ANALYSIS_PROFILES["quick"]
        balanced = COACH_ANALYSIS_PROFILES["balanced"]
        deep = COACH_ANALYSIS_PROFILES["deep"]

        self.assertLess(quick["time_ms"], balanced["time_ms"])
        self.assertLess(balanced["time_ms"], deep["time_ms"])
        self.assertLess(quick["pv_plies"], balanced["pv_plies"])
        self.assertLess(balanced["pv_plies"], deep["pv_plies"])
        self.assertGreaterEqual(quick["time_ms"], 400)
        self.assertGreaterEqual(balanced["time_ms"], 900)
        self.assertGreaterEqual(deep["time_ms"], 2200)

    def test_selected_detail_is_forwarded_to_stockfish(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeResult:
            def to_dict(self):
                return {
                    "move_number": 1,
                    "ply": 1,
                    "played_move": "e4",
                    "played_move_uci": "e2e4",
                    "classification": "good",
                    "centipawn_loss": 0,
                    "best_move": "e4",
                    "best_move_uci": "e2e4",
                    "opponent_reply": "c5",
                    "opponent_reply_uci": "c7c5",
                    "fen_before": chess.STARTING_FEN,
                    "fen_after": chess.Board().fen(),
                    "best_line": ["e4", "c5"],
                    "refutation_line": ["c5"],
                    "theme_hint": "development",
                    "evaluation_before": 20,
                    "evaluation_after": 20,
                    "engine_diagnostics": {},
                }

        class FakeAnalyzer:
            def analyze_move(self, board, move, **kwargs):
                calls.append(kwargs)
                return FakeResult()

        fake = FakeAnalyzer()

        with patch("app.get_analyzer", return_value=fake):
            for detail in ("quick", "balanced", "deep"):
                analyze_move({
                    "fen": chess.STARTING_FEN,
                    "move": "e2e4",
                    "detail": detail,
                })

        for detail, call in zip(
            ("quick", "balanced", "deep"),
            calls,
            strict=True,
        ):
            profile = COACH_ANALYSIS_PROFILES[detail]
            self.assertEqual(call["profile"], detail)
            self.assertEqual(call["time_ms"], profile["time_ms"])
            self.assertEqual(call["max_plies"], profile["pv_plies"])

    def test_classification_boundaries(self) -> None:
        self.assertEqual(classify_move(0), "good")
        self.assertEqual(classify_move(34), "good")
        self.assertEqual(classify_move(35), "inaccuracy")
        self.assertEqual(classify_move(89), "inaccuracy")
        self.assertEqual(classify_move(90), "mistake")
        self.assertEqual(classify_move(199), "mistake")
        self.assertEqual(classify_move(200), "blunder")

    def test_levels_progress_without_slow_fake_thinking(self) -> None:
        levels = list(BOT_LEVELS.values())
        self.assertEqual([level.display_elo for level in levels], sorted(level.display_elo for level in levels))
        self.assertEqual([level.think_ms for level in levels], sorted(level.think_ms for level in levels))
        self.assertLessEqual(max(level.think_ms for level in levels), 250)
        self.assertGreater(levels[0].temperature_cp, levels[-1].temperature_cp)

    def test_managed_engine_options_are_never_configured(self) -> None:
        class FakeOption:
            def __init__(self, managed: bool) -> None:
                self.managed = managed

            def is_managed(self) -> bool:
                return self.managed

        class FakeEngine:
            def __init__(self) -> None:
                self.options = {
                    "Threads": FakeOption(False),
                    "Hash": FakeOption(False),
                    "Ponder": FakeOption(True),
                    "MultiPV": FakeOption(True),
                }
                self.configured = None

            def configure(self, values):
                self.configured = values

        engine = FakeEngine()
        applied = configure_supported_options(
            engine,
            {"Threads": 1, "Hash": 64, "Ponder": False, "MultiPV": 3, "Missing": 1},
        )
        self.assertEqual(applied, {"Threads": 1, "Hash": 64})
        self.assertEqual(engine.configured, {"Threads": 1, "Hash": 64})

    def test_reconstructs_lichess_move_state(self) -> None:
        board = LichessBotRuntime._board_from_state("startpos", "e2e4 e7e5 g1f3")
        expected = chess.Board()
        for uci in ("e2e4", "e7e5", "g1f3"):
            expected.push_uci(uci)
        self.assertEqual(board.fen(), expected.fen())

    def test_invalid_stream_move_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            LichessBotRuntime._board_from_state("startpos", "e2e5")

    def test_duplicate_bot_move_is_not_submitted_twice(self) -> None:
        runtime = LichessBotRuntime()
        calls: list[str] = []

        class FakeEngine:
            def choose_move(self, board: chess.Board, level):
                return chess.Move.from_uci("e2e4"), 12

            def close(self):
                return None

        runtime._engine = FakeEngine()  # type: ignore[assignment]
        runtime._request = lambda method, path, **kwargs: calls.append(path)  # type: ignore[method-assign]
        state = {"status": "started", "moves": ""}
        runtime._maybe_move("game1", "startpos", state, chess.WHITE)
        runtime._maybe_move("game1", "startpos", state, chess.WHITE)
        self.assertEqual(calls, ["/api/bot/game/game1/move/e2e4"])

    def test_takeback_only_accepts_opponents_request(self) -> None:
        runtime = LichessBotRuntime()
        calls: list[str] = []
        runtime._request = lambda method, path, **kwargs: calls.append(path)  # type: ignore[method-assign]
        runtime._maybe_accept_takeback("g", {"moves": "e2e4", "btakeback": True}, chess.WHITE)
        runtime._maybe_accept_takeback("g2", {"moves": "e2e4", "wtakeback": True}, chess.WHITE)
        self.assertEqual(calls, ["/api/bot/game/g/takeback/yes"])

    def test_pv_to_san_stops_at_illegal_move(self) -> None:
        board = chess.Board()
        line = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5"), chess.Move.from_uci("g1f3")]
        self.assertEqual(pv_to_san(board, line), ["e4", "e5", "Nf3"])

    def test_invalid_coach_input_fails_before_engine_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid FEN"):
            analyze_move({"fen": "not-a-fen", "move": "e2e4"})

    def test_fallback_annotations_keep_before_after_contexts_separate(self) -> None:
        feedback = fallback_coaching({
            "played_move": "f3",
            "best_move": "Nf3",
            "opponent_reply": "Qh4+",
            "classification": "mistake",
            "theme_hint": "king safety",
            "best_move_uci": "g1f3",
            "opponent_reply_uci": "d8h4",
        })
        self.assertEqual(feedback["highlightsBefore"], ["g1", "f3"])
        self.assertEqual(feedback["highlightsAfter"], ["d8", "h4"])
        self.assertEqual([arrow["kind"] for arrow in feedback["arrows"]], ["best", "danger"])

    def test_game_start_event_is_recorded_for_challenge_handshake(self) -> None:
        runtime = LichessBotRuntime()
        runtime._ensure_game_thread = lambda game_id: None  # type: ignore[method-assign]
        before = __import__("time").monotonic()
        runtime._handle_event({
            "type": "gameStart",
            "game": {"id": "game123", "opponent": {"username": "Andy2435"}},
        })
        self.assertEqual(
            runtime._wait_for_game_start(opponent="andy2435", since=before, timeout=0.01),
            "game123",
        )

    def test_game_start_waiter_does_not_match_wrong_opponent(self) -> None:
        runtime = LichessBotRuntime()
        runtime._ensure_game_thread = lambda game_id: None  # type: ignore[method-assign]
        before = __import__("time").monotonic()
        runtime._handle_event({
            "type": "gameStart",
            "game": {"id": "game123", "opponent": {"username": "someone_else"}},
        })
        self.assertIsNone(runtime._wait_for_game_start(opponent="andy2435", since=before, timeout=0.01))


if __name__ == "__main__":
    unittest.main()
