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
    engine_diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MANAGED_ENGINE_OPTIONS = {"Ponder", "MultiPV", "UCI_Chess960", "UCI_Variant"}


def configure_supported_options(
    engine: chess.engine.SimpleEngine,
    requested: dict[str, Any],
) -> dict[str, Any]:
    """Configure ordinary UCI options that python-chess does not manage."""
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

    candidates.extend(
        [
            "/opt/homebrew/bin/stockfish",
            "/usr/local/bin/stockfish",
            "/usr/bin/stockfish",
        ]
    )

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


def pv_to_san(
    board: chess.Board,
    moves: list[chess.Move],
    max_plies: int = 6,
) -> list[str]:
    temp = board.copy()
    result: list[str] = []

    for move in moves[:max_plies]:
        if move not in temp.legal_moves:
            break

        result.append(temp.san(move))
        temp.push(move)

    return result


def infer_theme(
    board_before: chess.Board,
    board_after: chess.Board,
    opponent_reply_san: str,
) -> str:
    if opponent_reply_san:
        if "#" in opponent_reply_san:
            return "king safety and mating threats"
        if "+" in opponent_reply_san:
            return "forcing checks and king safety"
        if "x" in opponent_reply_san:
            return "captures, loose pieces, and tactical safety"

    if board_before.fullmove_number <= 10:
        return "development and king safety"

    if board_after.is_check():
        return "forcing moves and king safety"

    return "checks, captures, threats, and piece safety"


def info_diagnostics(info: dict[str, Any]) -> dict[str, Any]:
    elapsed = info.get("time")

    return {
        "depth": int(info.get("depth") or 0),
        "seldepth": int(info.get("seldepth") or 0),
        "nodes": int(info.get("nodes") or 0),
        "nps": int(info.get("nps") or 0),
        "timeMs": (
            int(float(elapsed) * 1000)
            if isinstance(elapsed, (int, float))
            else 0
        ),
        "hashfull": int(info.get("hashfull") or 0),
    }


class StockfishAnalyzer:
    """Reliable live move analysis using same-position comparisons."""

    def __init__(self, time_ms: int = 250) -> None:
        self.stockfish_path = find_stockfish()
        self.time_ms = max(200, int(time_ms))
        self.debug = (
            os.getenv("COACH_ENGINE_DEBUG", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        self.engine = chess.engine.SimpleEngine.popen_uci(
            self.stockfish_path
        )

        configure_supported_options(
            self.engine,
            {"Threads": 1, "Hash": 64},
        )

    def close(self) -> None:
        try:
            self.engine.quit()
        except Exception:
            try:
                self.engine.close()
            except Exception:
                pass

    def analyze_move(
        self,
        board_before: chess.Board,
        played_move: chess.Move,
    ) -> MoveAnalysis:
        if played_move not in board_before.legal_moves:
            raise ValueError(f"Illegal move: {played_move.uci()}")

        player = board_before.turn
        fen_before = board_before.fen()
        played_san = board_before.san(played_move)

        limit = chess.engine.Limit(
            time=self.time_ms / 1000.0
        )

        # Search the original position for Stockfish's actual top choice.
        before_info = self.engine.analyse(
            board_before,
            limit,
        )

        before_score = before_info.get("score")
        before_pv = list(before_info.get("pv") or [])

        if before_score is None or not before_pv:
            raise RuntimeError(
                "Stockfish returned no usable best-move analysis."
            )

        best_move = before_pv[0]

        if best_move not in board_before.legal_moves:
            raise RuntimeError(
                "Stockfish returned an illegal best move."
            )

        best_san = board_before.san(best_move)
        eval_before = score_cp(before_score, player)
        best_line = pv_to_san(board_before, before_pv, 6)

        board_after = board_before.copy()
        board_after.push(played_move)

        if played_move == best_move:
            # Reuse the best search instead of running Stockfish again.
            played_info = before_info
            played_pv = before_pv
            eval_played = eval_before
            cp_loss = 0
        else:
            # Compare the student's move from the SAME original position.
            # root_moves forces Stockfish to evaluate that exact move.
            played_info = self.engine.analyse(
                board_before,
                limit,
                root_moves=[played_move],
            )

            played_score = played_info.get("score")
            played_pv = list(played_info.get("pv") or [])

            if (
                played_score is None
                or not played_pv
                or played_pv[0] != played_move
            ):
                raise RuntimeError(
                    "Stockfish returned no usable forced-move analysis."
                )

            eval_played = score_cp(played_score, player)
            cp_loss = min(
                5000,
                max(0, eval_before - eval_played),
            )

        continuation = (
            played_pv[1:]
            if played_pv and played_pv[0] == played_move
            else []
        )

        reply_san = ""
        reply_uci = ""

        if continuation:
            reply = continuation[0]

            if reply in board_after.legal_moves:
                reply_san = board_after.san(reply)
                reply_uci = reply.uci()

        refutation = pv_to_san(
            board_after,
            continuation,
            6,
        )

        diagnostics = {
            "budgetMs": self.time_ms,
            "bestSearch": info_diagnostics(before_info),
            "playedSearch": {
                **info_diagnostics(played_info),
                "reusedBestSearch": played_move == best_move,
            },
        }

        if self.debug:
            print(
                "[COACH STOCKFISH]",
                f"fen={fen_before}",
                f"played={played_move.uci()}",
                f"best={best_move.uci()}",
                f"loss={cp_loss}",
                f"bestDepth={diagnostics['bestSearch']['depth']}",
                f"bestNodes={diagnostics['bestSearch']['nodes']}",
                f"playedDepth={diagnostics['playedSearch']['depth']}",
                f"playedNodes={diagnostics['playedSearch']['nodes']}",
                flush=True,
            )

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
            evaluation_after=eval_played,
            centipawn_loss=cp_loss,
            classification=classify_move(cp_loss),
            best_line=best_line,
            refutation_line=refutation,
            fen_before=fen_before,
            fen_after=board_after.fen(),
            theme_hint=infer_theme(
                board_before,
                board_after,
                reply_san,
            ),
            engine_diagnostics=diagnostics,
        )
