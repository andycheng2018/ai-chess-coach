from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from coach.opening_recognizer import recognize_opening  # noqa: E402


class OpeningRecognizerTests(unittest.TestCase):
    def test_recognizes_ryu_lopez_line(self) -> None:
        state = recognize_opening(
            [
                "e2e4",
                "e7e5",
                "g1f3",
                "b8c6",
                "f1b5",
            ]
        )

        self.assertTrue(state.in_book)
        self.assertEqual(state.depth_matched, 5)
        self.assertTrue(state.name)
        self.assertTrue(state.eco.startswith("C"))

    def test_recognizes_transposed_ryu_lopez(self) -> None:
        state = recognize_opening(
            [
                "e2e4",
                "e7e5",
                "f1b5",
                "b8c6",
                "g1f3",
            ]
        )

        self.assertTrue(state.in_book)
        self.assertTrue(state.transposed)
        self.assertEqual(state.depth_matched, 5)
        self.assertTrue(state.name)
        self.assertTrue(state.eco.startswith("C"))

    def test_detects_left_book_move(self) -> None:
        state = recognize_opening(
            [
                "e2e4",
                "e7e5",
                "g1f3",
                "b8c6",
                "h2h3",
            ]
        )

        self.assertFalse(state.in_book)
        self.assertEqual(state.left_book_at, 5)
        self.assertEqual(state.depth_matched, 4)
        self.assertTrue(state.book_move_uci)

    def test_empty_moves_return_neutral_state(self) -> None:
        state = recognize_opening([])

        self.assertFalse(state.in_book)
        self.assertEqual(state.depth_matched, 0)
        self.assertEqual(state.name, "")


if __name__ == "__main__":
    unittest.main()
