from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chess

DATA_DIR = Path(__file__).resolve().parent / "data"
OPENINGS_JSON = DATA_DIR / "openings.json"
OPENING_PHASE_MAX_MOVE = 15


@dataclass(frozen=True)
class _OpeningLine:
    eco: str
    name: str
    variation: str
    uci: tuple[str, ...]
    ply_at_fen: int


@dataclass
class OpeningState:
    eco: str = ""
    name: str = ""
    variation: str = ""
    depth_matched: int = 0
    in_book: bool = False
    left_book_at: int | None = None
    book_move_uci: str | None = None
    book_move_san: str | None = None
    transposed: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        payload = {
            "eco": self.eco,
            "name": self.name,
            "variation": self.variation,
            "depthMatched": self.depth_matched,
            "inBook": self.in_book,
            "leftBookAt": self.left_book_at,
            "bookMoveUci": self.book_move_uci,
            "transposed": self.transposed,
        }

        if self.book_move_san:
            payload["bookMove"] = self.book_move_san

        return payload

    def to_analysis_dict(self) -> dict[str, Any]:
        return {
            "opening_eco": self.eco,
            "opening_name": self.name,
            "opening_variation": self.variation,
            "opening_depth_matched": self.depth_matched,
            "opening_in_book": self.in_book,
            "opening_left_book_at": self.left_book_at,
            "opening_book_move_uci": self.book_move_uci,
            "opening_book_move_san": self.book_move_san,
            "opening_transposed": self.transposed,
        }


@dataclass
class _TrieNode:
    children: dict[str, _TrieNode] = field(default_factory=dict)
    eco: str = ""
    name: str = ""
    variation: str = ""


class OpeningRecognizer:
    """Match openings by board position (FEN) with move-order fallback."""

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._lines: list[_OpeningLine] = []
        self._fen_index: dict[str, list[_OpeningLine]] = {}
        self._load_openings()

    def _load_openings(self) -> None:
        if OPENINGS_JSON.is_file():
            raw = json.loads(
                OPENINGS_JSON.read_text(encoding="utf-8")
            )
        else:
            raw = self._load_from_tsv()

        if not isinstance(raw, list):
            raise ValueError("Opening data must be a JSON array.")

        fen_index: dict[str, list[_OpeningLine]] = {}

        for entry in raw:
            if not isinstance(entry, dict):
                continue

            uci_moves = tuple(
                str(item).strip().lower()
                for item in entry.get("uci", [])
                if str(item).strip()
            )

            if not uci_moves:
                continue

            eco = str(entry.get("eco", "")).strip()
            name = str(entry.get("name", "")).strip()
            variation = str(entry.get("variation", "")).strip()

            self._insert_trie(
                uci_moves,
                eco,
                name,
                variation,
            )

            board = chess.Board()

            for ply, move_uci in enumerate(uci_moves, start=1):
                try:
                    move = chess.Move.from_uci(move_uci)
                except ValueError:
                    board = chess.Board()
                    break

                if move not in board.legal_moves:
                    board = chess.Board()
                    break

                board.push(move)

                line = _OpeningLine(
                    eco=eco,
                    name=name,
                    variation=variation,
                    uci=uci_moves,
                    ply_at_fen=ply,
                )

                fen_key = board.fen()
                fen_index.setdefault(fen_key, []).append(line)

        self._fen_index = fen_index
        self._lines = [
            line
            for entries in fen_index.values()
            for line in entries
        ]

    def _insert_trie(
        self,
        uci_moves: tuple[str, ...],
        eco: str,
        name: str,
        variation: str,
    ) -> None:
        node = self._root

        for move in uci_moves:
            child = node.children.get(move)

            if child is None:
                child = _TrieNode()
                node.children[move] = child

            child.eco = eco
            child.name = name
            child.variation = variation
            node = child

    def _load_from_tsv(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []

        for tsv_path in sorted(DATA_DIR.glob("*.tsv")):
            for line in tsv_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()

                if not line or line.startswith("eco\t"):
                    continue

                parts = line.split("\t", 2)

                if len(parts) < 3:
                    continue

                eco = parts[0].strip()
                name = parts[1].strip()
                pgn = parts[2].strip()
                uci_moves = self._pgn_to_uci(pgn)

                if not uci_moves:
                    continue

                base_name, variation = self._split_name(name)

                entries.append(
                    {
                        "eco": eco,
                        "name": base_name,
                        "variation": variation,
                        "uci": uci_moves,
                    }
                )

        return entries

    @staticmethod
    def _split_name(full_name: str) -> tuple[str, str]:
        if ": " in full_name:
            base, variation = full_name.split(": ", 1)
            return base.strip(), variation.strip()

        return full_name.strip(), ""

    @staticmethod
    def _pgn_to_uci(pgn: str) -> list[str] | None:
        board = chess.Board()
        cleaned = re.sub(r"\d+\.+", " ", pgn)
        tokens = cleaned.split()
        moves: list[str] = []

        for token in tokens:
            if token in {"...", "..."}:
                continue

            try:
                move = board.parse_san(token)
            except ValueError:
                return None

            if move not in board.legal_moves:
                return None

            moves.append(move.uci())
            board.push(move)

        return moves

    @staticmethod
    def normalize_moves(moves: list[str]) -> list[str]:
        return [
            str(item).strip().lower()
            for item in moves
            if str(item).strip()
        ]

    @staticmethod
    def _board_from_moves(moves: list[str]) -> chess.Board | None:
        board = chess.Board()

        for uci in moves:
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                return None

            if move not in board.legal_moves:
                return None

            board.push(move)

        return board

    def _walk_trie(
        self,
        moves: list[str],
    ) -> tuple[_TrieNode, int, int | None]:
        node = self._root
        matched_depth = 0

        for index, move in enumerate(moves, start=1):
            child = node.children.get(move)

            if child is None:
                return node, matched_depth, index

            node = child
            matched_depth = index

        return node, matched_depth, None

    @staticmethod
    def _pick_best_line(
        moves: list[str],
        entries: list[_OpeningLine],
    ) -> _OpeningLine:
        move_tuple = tuple(moves)

        prefix_matches = [
            entry
            for entry in entries
            if entry.uci[: len(move_tuple)] == move_tuple
        ]

        if prefix_matches:
            return max(
                prefix_matches,
                key=lambda entry: len(entry.uci),
            )

        return max(
            entries,
            key=lambda entry: (len(entry.uci), entry.ply_at_fen),
        )

    def _pick_book_move_uci(
        self,
        board: chess.Board,
        entries: list[_OpeningLine],
        moves: list[str],
    ) -> str | None:
        move_counts: Counter[str] = Counter()
        ply = len(moves)

        for entry in entries:
            if entry.ply_at_fen != ply:
                continue

            if entry.ply_at_fen >= len(entry.uci):
                continue

            next_uci = entry.uci[entry.ply_at_fen]

            try:
                move = chess.Move.from_uci(next_uci)
            except ValueError:
                continue

            if move in board.legal_moves:
                move_counts[next_uci] += 1

        if not move_counts:
            return None

        return move_counts.most_common(1)[0][0]

    def recognize(
        self,
        moves: list[str],
    ) -> OpeningState:
        normalized = self.normalize_moves(moves)

        if not normalized:
            return OpeningState()

        board = self._board_from_moves(normalized)

        if board is None:
            return OpeningState()

        current_fen = board.fen()
        fen_entries = self._fen_index.get(current_fen, [])
        trie_node, trie_depth, trie_left_at = self._walk_trie(normalized)

        if fen_entries:
            best = self._pick_best_line(normalized, fen_entries)
            move_tuple = tuple(normalized)
            transposed = not any(
                entry.uci[: len(move_tuple)] == move_tuple
                for entry in fen_entries
            )

            book_move_uci = self._pick_book_move_uci(
                board,
                fen_entries,
                normalized,
            )

            if book_move_uci is None and trie_node.children:
                book_move_uci = sorted(trie_node.children.keys())[0]

            return OpeningState(
                eco=best.eco,
                name=best.name,
                variation=best.variation,
                depth_matched=len(normalized),
                in_book=True,
                book_move_uci=book_move_uci,
                book_move_san=self._uci_to_san(
                    normalized,
                    book_move_uci,
                )
                if book_move_uci
                else None,
                transposed=transposed,
            )

        prev_board = self._board_from_moves(normalized[:-1])
        prev_in_book = (
            prev_board is not None
            and prev_board.fen() in self._fen_index
        )

        state = OpeningState(
            eco=trie_node.eco,
            name=trie_node.name,
            variation=trie_node.variation,
            depth_matched=trie_depth,
            in_book=False,
            left_book_at=trie_left_at,
            transposed=False,
        )

        if prev_in_book and trie_left_at is None:
            state.left_book_at = len(normalized)

        if trie_node.children:
            book_move_uci = sorted(trie_node.children.keys())[0]
            state.book_move_uci = book_move_uci
            state.book_move_san = self._uci_to_san(
                normalized[:trie_depth],
                book_move_uci,
            )

        return state

    @staticmethod
    def _uci_to_san(
        prefix_moves: list[str],
        move_uci: str,
    ) -> str | None:
        board = chess.Board()

        for uci in prefix_moves:
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                return None

            if move not in board.legal_moves:
                return None

            board.push(move)

        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            return None

        if move not in board.legal_moves:
            return None

        return board.san(move)


_recognizer: OpeningRecognizer | None = None


def get_opening_recognizer() -> OpeningRecognizer:
    global _recognizer

    if _recognizer is None:
        _recognizer = OpeningRecognizer()

    return _recognizer


def recognize_opening(moves: list[str]) -> OpeningState:
    return get_opening_recognizer().recognize(moves)


def opening_fields_for_move(
    moves: list[str],
    move_number: int,
) -> dict[str, Any]:
    if move_number > OPENING_PHASE_MAX_MOVE:
        return OpeningState().to_analysis_dict()

    return recognize_opening(moves).to_analysis_dict()
