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
        *,
        time_ms: int | None = None,
        max_plies: int = 6,
        profile: str = "balanced",
    ) -> MoveAnalysis:
        if played_move not in board_before.legal_moves:
            raise ValueError(f"Illegal move: {played_move.uci()}")

        player = board_before.turn
        fen_before = board_before.fen()
        played_san = board_before.san(played_move)

        search_time_ms = max(
            200,
            int(
                self.time_ms
                if time_ms is None
                else time_ms
            ),
        )
        line_plies = max(
            4,
            min(20, int(max_plies)),
        )

        limit = chess.engine.Limit(
            time=search_time_ms / 1000.0
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
        best_line = pv_to_san(
            board_before,
            before_pv,
            line_plies,
        )

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
            line_plies,
        )

        diagnostics = {
            "profile": profile,
            "budgetMs": search_time_ms,
            "pvPlies": line_plies,
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

    def analyze_critical_position(
        self,
        board: chess.Board,
    ) -> dict[str, Any]:
        """
        Decide whether the side to move is facing a genuinely useful
        "stop and think" moment.

        This is intentionally lighter than the full post-move analysis.
        It is used only to decide whether Chess Buddy should ask a question
        BEFORE the student moves.
        """
        legal = list(board.legal_moves)

        if len(legal) < 2:
            return {
                "is_critical": False,
            }

        player = board.turn

        # This feature must never slow the main coaching pipeline very much.
        critical_ms = max(
            120,
            min(
                180,
                self.time_ms,
            ),
        )

        limit = chess.engine.Limit(
            time=critical_ms / 1000.0
        )

        raw = self.engine.analyse(
            board,
            limit,
            multipv=min(
                2,
                len(legal),
            ),
        )

        infos = (
            raw
            if isinstance(raw, list)
            else [raw]
        )

        usable: list[
            tuple[
                dict[str, Any],
                chess.Move,
                int,
                list[chess.Move],
            ]
        ] = []

        for info in infos:
            score = info.get("score")
            pv = list(
                info.get("pv") or []
            )

            if score is None or not pv:
                continue

            move = pv[0]

            if move not in board.legal_moves:
                continue

            usable.append(
                (
                    info,
                    move,
                    score_cp(
                        score,
                        player,
                    ),
                    pv,
                )
            )

        if not usable:
            return {
                "is_critical": False,
            }

        best_info, best_move, best_score, best_pv = (
            usable[0]
        )

        second_score = (
            usable[1][2]
            if len(usable) > 1
            else best_score
        )

        best_gap = max(
            0,
            best_score - second_score,
        )

        best_san = board.san(
            best_move
        )

        best_is_capture = board.is_capture(
            best_move
        )

        best_gives_check = board.gives_check(
            best_move
        )

        best_is_promotion = (
            best_move.promotion is not None
        )

        best_mate = None

        best_score_object = best_info.get(
            "score"
        )

        if best_score_object is not None:
            try:
                best_mate = (
                    best_score_object
                    .pov(player)
                    .mate()
                )
            except Exception:
                best_mate = None

        # Estimate what the opponent would do if the student could
        # "pass". This gives us a concrete opponent-intention signal.
        #
        # Skip this in check and when en-passant rights are active,
        # because a null move would distort those special positions.
        threat_move_uci = ""
        threat_move_san = ""
        threat_line: list[str] = []
        threat_is_capture = False
        threat_gives_check = False
        threat_is_mate = False

        if (
            not board.is_check()
            and board.ep_square is None
        ):
            null_board = board.copy(
                stack=False
            )

            null_board.push(
                chess.Move.null()
            )

            threat_limit = chess.engine.Limit(
                time=max(
                    90,
                    min(
                        120,
                        critical_ms,
                    ),
                )
                / 1000.0
            )

            try:
                threat_info = self.engine.analyse(
                    null_board,
                    threat_limit,
                )

                threat_pv = list(
                    threat_info.get(
                        "pv"
                    )
                    or []
                )

                if threat_pv:
                    threat_move = threat_pv[0]

                    if (
                        threat_move
                        in null_board.legal_moves
                    ):
                        threat_move_uci = (
                            threat_move.uci()
                        )

                        threat_move_san = (
                            null_board.san(
                                threat_move
                            )
                        )

                        threat_line = pv_to_san(
                            null_board,
                            threat_pv,
                            5,
                        )

                        threat_is_capture = (
                            null_board.is_capture(
                                threat_move
                            )
                        )

                        threat_gives_check = (
                            null_board.gives_check(
                                threat_move
                            )
                        )

                        threat_is_mate = (
                            "#" in threat_move_san
                        )

            except (
                chess.engine.EngineError,
                chess.engine.EngineTerminatedError,
                BrokenPipeError,
            ):
                # The threat probe is optional. Never fail the whole
                # coaching request because this extra probe failed.
                pass

        in_check = board.is_check()

        has_forcing_opportunity = (
            best_is_capture
            or best_gives_check
            or best_is_promotion
            or best_mate is not None
        ) and (
            best_gap >= 50
            or best_mate is not None
        )

        has_forcing_threat = (
            threat_is_capture
            or threat_gives_check
            or threat_is_mate
        ) and best_gap >= 50

        has_clear_only_move_feel = (
            best_gap >= 100
        )

        is_critical = (
            in_check
            or has_forcing_opportunity
            or has_forcing_threat
            or has_clear_only_move_feel
        )

        if not is_critical:
            return {
                "is_critical": False,
            }

        if in_check:
            kind = "check"
        elif has_forcing_opportunity:
            kind = "opportunity"
        elif has_forcing_threat:
            kind = "threat"
        else:
            kind = "decision"

        result = {
            "is_critical": True,
            "kind": kind,
            "fen": board.fen(),
            "side_to_move": (
                "white"
                if player == chess.WHITE
                else "black"
            ),
            "in_check": in_check,
            "best_move": best_san,
            "best_move_uci": best_move.uci(),
            "best_line": pv_to_san(
                board,
                best_pv,
                6,
            ),
            "best_gap_cp": best_gap,
            "best_is_capture": best_is_capture,
            "best_gives_check": best_gives_check,
            "best_is_promotion": best_is_promotion,
            "best_mate": best_mate,
            "threat_move": threat_move_san,
            "threat_move_uci": threat_move_uci,
            "threat_line": threat_line,
            "threat_is_capture": threat_is_capture,
            "threat_gives_check": threat_gives_check,
            "threat_is_mate": threat_is_mate,
            "diagnostics": {
                "budgetMs": critical_ms,
                "bestGapCp": best_gap,
                "search": info_diagnostics(
                    best_info
                ),
            },
        }

        if self.debug:
            print(
                "[COACH CRITICAL]",
                f"kind={kind}",
                f"best={best_move.uci()}",
                f"gap={best_gap}",
                f"threat={threat_move_uci or '-'}",
                flush=True,
            )

        return result
