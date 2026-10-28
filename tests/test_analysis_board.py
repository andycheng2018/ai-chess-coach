from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import chess
import chess.engine
import chess.pgn

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))
import app
from coach.stockfish_analyzer import StockfishAnalyzer


class AnalysisBoardTests(unittest.TestCase):
    def test_multipv_scores_white_even_when_black_is_to_move(self):
        analyzer = StockfishAnalyzer.__new__(StockfishAnalyzer)
        analyzer.engine = Mock()
        board = chess.Board()
        board.push_uci("e2e4")
        analyzer.engine.analyse.return_value = [{
            "score": chess.engine.PovScore(chess.engine.Cp(-70), chess.BLACK),
            "pv": [chess.Move.from_uci("e7e5"), chess.Move.from_uci("g1f3")], "depth": 12,
        }]
        result = analyzer.analyze_position(board)
        self.assertEqual(result["score"], {"cp": 70, "mate": None})
        self.assertEqual(result["lines"][0]["moves"], ["e5", "Nf3"])
        self.assertEqual(analyzer.engine.analyse.call_args.kwargs["multipv"], 3)

    def test_mate_and_draw_positions_do_not_search(self):
        analyzer = StockfishAnalyzer.__new__(StockfishAnalyzer)
        analyzer.engine = Mock()
        board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
        board.push_uci("g6g7")
        result = analyzer.analyze_position(board)
        self.assertTrue(result["terminal"])
        self.assertEqual(result["winner"], "white")
        draw = analyzer.analyze_position(chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1"))
        self.assertEqual(draw["score"]["cp"], 0)
        analyzer.engine.analyse.assert_not_called()

    def test_position_endpoint_replays_history_without_coaching_or_live_bot(self):
        fake = Mock()
        with patch("app.get_analyzer", return_value=fake), patch("app.get_llm_coach") as llm, patch("app.runtime") as bot:
            app.analyze_position({"rootFen": chess.STARTING_FEN, "moves": ["e2e4", "e7e5"], "detail": "quick"})
        board = fake.analyze_position.call_args.args[0]
        self.assertEqual(len(board.move_stack), 2)
        self.assertEqual(fake.analyze_position.call_args.kwargs["time_ms"], app.COACH_ANALYSIS_PROFILES["quick"]["time_ms"])
        llm.assert_not_called()
        self.assertEqual(bot.mock_calls, [])

    def test_invalid_positions_and_moves_never_start_the_engine(self):
        for payload in [{"rootFen": "bad"}, {"rootFen": "8/8/8/8/8/8/8/8 w - - 0 1"},
                        {"rootFen": chess.STARTING_FEN, "moves": ["e2e5"]},
                        {"rootFen": chess.STARTING_FEN, "moves": [None]},
                        {"rootFen": chess.STARTING_FEN, "moves": ["0000"]},
                        {"rootFen": chess.STARTING_FEN, "moves": ["e2e4"] * 513}]:
            with patch("app.get_analyzer") as engine, self.assertRaises(ValueError):
                app.analyze_position(payload)
            engine.assert_not_called()

    def test_busy_engine_is_rejected_instead_of_queueing(self):
        with patch("app._analyzer_lock") as lock, patch("app.get_analyzer") as engine:
            lock.acquire.return_value = False
            with self.assertRaisesRegex(RuntimeError, "engine is busy"):
                app.analyze_position({"rootFen": chess.STARTING_FEN})
            engine.assert_not_called()

    def test_variation_export_syntax_preserves_both_lines_in_standard_pgn(self):
        game = chess.pgn.read_game(io.StringIO('[Result "*"]\n\n1. e4 (1. d4 1... d5) 1... e5 *'))
        self.assertEqual(game.errors, [])
        self.assertEqual([child.move.uci() for child in game.variations], ["e2e4", "d2d4"])
        self.assertEqual(game.variations[1].variations[0].move.uci(), "d7d5")
