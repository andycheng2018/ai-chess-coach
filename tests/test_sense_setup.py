from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from app import Handler
from bot_runtime import LichessBotRuntime


class SenseSetupTests(unittest.TestCase):
    def test_open_room_catches_game_start_during_slow_accept_response(self) -> None:
        bot = LichessBotRuntime()
        bot.status = Mock(return_value={"running": True, "connected": True})
        bot._ensure_game_thread = Mock()

        def accept(*args, **kwargs):
            # A gameStart arrives while the HTTP request is still in flight;
            # a later game for another player must not be mistaken for ours.
            bot._recent_game_starts = [
                (100.1, "AbCd1234", "alice"),
                (100.2, "XyZa5678", "bob"),
            ]
            return SimpleNamespace(status_code=200)

        bot._request = Mock(side_effect=accept)
        with patch("bot_runtime.time.monotonic", side_effect=[100.0, 102.0]):
            result = bot.accept_challenge("AbCd1234", opponent="Alice", color="black")
        self.assertEqual(result["gameId"], "AbCd1234")
        bot._ensure_game_thread.assert_called_once_with("AbCd1234")
        self.assertEqual(bot._request.call_args.args[1], "/api/challenge/AbCd1234/accept?color=black")

    def test_setup_health_exposes_configuration_status_without_api_key(self) -> None:
        handler = Handler.__new__(Handler)
        handler.path = "/api/health"
        handler._send = Mock()
        with patch("app.os.environ", {"OPENAI_API_KEY": "private-test-key"}), \
             patch("app.find_stockfish", return_value="/test/stockfish"), \
             patch("app.runtime.status", return_value={"connected": False}):
            handler.do_GET()
        payload = handler._send.call_args.args[1]
        self.assertTrue(payload["coach"]["configured"])
        self.assertNotIn("private-test-key", str(payload))

    def test_missing_engine_and_key_are_visible_as_incomplete_setup(self) -> None:
        handler = Handler.__new__(Handler)
        handler.path = "/api/health"
        handler._send = Mock()
        with patch("app.os.environ", {}), \
             patch("app.find_stockfish", side_effect=RuntimeError("Stockfish missing")), \
             patch("app.runtime.status", return_value={"connected": False}):
            handler.do_GET()
        payload = handler._send.call_args.args[1]
        self.assertFalse(payload["coach"]["configured"])
        self.assertIsNone(payload["stockfish"])
        self.assertEqual(payload["warning"], "Stockfish missing")
