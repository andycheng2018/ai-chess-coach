from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine


@dataclass
class MoveAnalysis:
    move_number: int
    ply: int
    color: str
    played_move: str
    played_move_uci: str
    best_move: str
    best_move_uci: str
    opponent_reply: str
    opponent_reply_uci: str
    evaluation_before: int
    evaluation_after: int
    centipawn_loss: int
    classification: str
    best_line: list[str]
    refutation_line: list[str]
    fen_before: str
    fen_after: str
    theme_hint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MANAGED_ENGINE_OPTIONS = {"Ponder", "MultiPV", "UCI_Chess960", "UCI_Variant"}


def configure_supported_options(engine: chess.engine.SimpleEngine, requested: dict[str, Any]) -> dict[str, Any]:
    """Configure only ordinary UCI options that python-chess does not manage.

    python-chess owns options such as Ponder and MultiPV and raises an
    EngineError if callers try to set them through ``engine.configure()``.
    Filtering here keeps bot and coach startup compatible across Stockfish and
    python-chess versions while still applying useful options like Threads and
    Hash when they are available.
    """
    safe: dict[str, Any] = {}
    for name, value in requested.items():
        option = engine.options.get(name)
        if option is None:
            continue
        managed = name in MANAGED_ENGINE_OPTIONS
        is_managed = getattr(option, "is_managed", None)
        if callable(is_managed):
            try:
                managed = managed or bool(is_managed())
            except Exception:
                pass
        if not managed:
            safe[name] = value
    if safe:
        engine.configure(safe)
    return safe


def find_stockfish() -> str:
    candidates: list[str] = []
    env_path = os.getenv("STOCKFISH_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    which = shutil.which("stockfish")
    if which:
        candidates.append(which)
    candidates.extend([
        "/opt/homebrew/bin/stockfish",
        "/usr/local/bin/stockfish",
        "/usr/bin/stockfish",
    ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError(
        "Stockfish was not found. On macOS run: brew install stockfish. "
        "Or set STOCKFISH_PATH=/full/path/to/stockfish."
    )


def score_cp(score: chess.engine.PovScore, perspective: chess.Color) -> int:
    value = score.pov(perspective).score(mate_score=20_000)
    return int(value if value is not None else 0)


def classify_move(cp_loss: int) -> str:
    if cp_loss < 35:
        return "good"
    if cp_loss < 90:
        return "inaccuracy"
    if cp_loss < 200:
        return "mistake"
    return "blunder"


def pv_to_san(board: chess.Board, moves: list[chess.Move], max_plies: int = 6) -> list[str]:
    temp = board.copy()
    result: list[str] = []
    for move in moves[:max_plies]:
        if move not in temp.legal_moves:
            break
        result.append(temp.san(move))
        temp.push(move)
    return result


def infer_theme(board_before: chess.Board, board_after: chess.Board, opponent_reply_san: str) -> str:
    if opponent_reply_san:
        if "#" in opponent_reply_san:
            return "king safety and mating threats"
        if "+" in opponent_reply_san:
            return "forcing checks and king safety"
        if "x" in opponent_reply_san:
            return "captures, loose pieces, and tactical safety"
    if board_before.fullmove_number <= 10:
        undeveloped = sum(
            1
            for sq in (chess.B1, chess.G1) if board_before.piece_at(sq) and board_before.piece_at(sq).piece_type == chess.KNIGHT
        ) + sum(
            1
            for sq in (chess.B8, chess.G8) if board_before.piece_at(sq) and board_before.piece_at(sq).piece_type == chess.KNIGHT
        )
        if undeveloped:
            return "development, center control, and king safety"
    if board_after.is_check():
        return "forcing moves and king safety"
    return "checks, captures, threats, and piece activity"


class StockfishAnalyzer:
    def __init__(self, time_ms: int = 180) -> None:
        self.stockfish_path = find_stockfish()
        self.time_ms = max(50, time_ms)
        self.engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
        configure_supported_options(self.engine, {"Threads": 1, "Hash": 16})

    def close(self) -> None:
        try:
            self.engine.quit()
        except Exception:
            try:
                self.engine.close()
            except Exception:
                pass

    def analyze_move(self, board_before: chess.Board, played_move: chess.Move) -> MoveAnalysis:
        if played_move not in board_before.legal_moves:
            raise ValueError(f"Illegal move: {played_move.uci()}")

        player = board_before.turn
        fen_before = board_before.fen()
        played_san = board_before.san(played_move)
        limit = chess.engine.Limit(time=self.time_ms / 1000.0)

        before_info = self.engine.analyse(board_before, limit)
        before_pv = list(before_info.get("pv") or [])
        if not before_pv:
            raise RuntimeError("Stockfish returned no best line.")
        best_move = before_pv[0]
        best_san = board_before.san(best_move)
        eval_before = score_cp(before_info["score"], player)
        best_line = pv_to_san(board_before, before_pv, 6)

        board_after = board_before.copy()
        board_after.push(played_move)
        after_info = self.engine.analyse(board_after, limit)
        after_pv = list(after_info.get("pv") or [])
        eval_after = score_cp(after_info["score"], player)
        cp_loss = min(5000, max(0, eval_before - eval_after))

        reply_san = ""
        reply_uci = ""
        if after_pv:
            reply = after_pv[0]
            if reply in board_after.legal_moves:
                reply_san = board_after.san(reply)
                reply_uci = reply.uci()
        refutation = pv_to_san(board_after, after_pv, 6)

        return MoveAnalysis(
            move_number=board_before.fullmove_number,
            ply=board_before.ply() + 1,
            color="white" if player == chess.WHITE else "black",
            played_move=played_san,
            played_move_uci=played_move.uci(),
            best_move=best_san,
            best_move_uci=best_move.uci(),
            opponent_reply=reply_san,
            opponent_reply_uci=reply_uci,
            evaluation_before=eval_before,
            evaluation_after=eval_after,
            centipawn_loss=cp_loss,
            classification=classify_move(cp_loss),
            best_line=best_line,
            refutation_line=refutation,
            fen_before=fen_before,
            fen_after=board_after.fen(),
            theme_hint=infer_theme(board_before, board_after, reply_san),
        )
