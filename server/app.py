#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import chess
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from bot_runtime import BOT_LEVELS, runtime
from coach.stockfish_analyzer import StockfishAnalyzer, find_stockfish

HOST = "127.0.0.1"
PORT = int(os.environ.get("CHESS_SERVER_PORT", "8765"))
COACH_TIME_MS = int(os.environ.get("COACH_TIME_MS", "180"))
MISTAKE_THRESHOLD_CP = int(os.environ.get("COACH_MISTAKE_THRESHOLD_CP", "80"))
MAX_BODY_BYTES = 64 * 1024

_analyzer: StockfishAnalyzer | None = None
_analyzer_lock = threading.Lock()
_llm_coach: Any = None
_llm_lock = threading.Lock()


def get_analyzer() -> StockfishAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = StockfishAnalyzer(time_ms=COACH_TIME_MS)
    return _analyzer


def reset_analyzer() -> None:
    global _analyzer
    if _analyzer is not None:
        _analyzer.close()
    _analyzer = None


def get_llm_coach() -> Any:
    global _llm_coach
    if _llm_coach is None:
        from coach.llm_coach import LLMCoach
        _llm_coach = LLMCoach()
    return _llm_coach


def fallback_coaching(analysis: dict[str, Any]) -> dict[str, Any]:
    played = str(analysis["played_move"])
    best = str(analysis["best_move"])
    reply = str(analysis.get("opponent_reply", ""))
    classification = str(analysis["classification"])
    theme = str(analysis.get("theme_hint", "checks, captures, and threats"))
    best_uci = str(analysis.get("best_move_uci", ""))
    reply_uci = str(analysis.get("opponent_reply_uci", ""))

    if reply:
        feedback = (
            f"{played} lets your opponent answer with {reply}, which makes the position harder to handle. "
            f"{best} was stronger because it deals with the position more actively. "
            f"Before committing, scan the opponent's forcing replies first."
        )
    else:
        feedback = (
            f"{played} was a {classification}. {best} kept the position healthier. "
            f"Use a quick forcing-move scan before you settle on your move."
        )

    arrows: list[dict[str, str]] = []
    if len(best_uci) >= 4:
        arrows.append({"from": best_uci[:2], "to": best_uci[2:4], "kind": "best"})
    if len(reply_uci) >= 4:
        arrows.append({"from": reply_uci[:2], "to": reply_uci[2:4], "kind": "danger"})
    highlights_before = [best_uci[:2], best_uci[2:4]] if len(best_uci) >= 4 else []
    highlights_after = [reply_uci[:2], reply_uci[2:4]] if len(reply_uci) >= 4 else []

    return {
        "title": classification.capitalize(),
        "feedback": feedback,
        "lesson": theme.capitalize(),
        "question": "What checks, captures, or threats does my opponent have after this move?",
        "arrows": arrows,
        "highlightsBefore": highlights_before,
        "highlightsAfter": highlights_after,
    }


def coach_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return fallback_coaching(analysis)
    try:
        with _llm_lock:
            return get_llm_coach().create_feedback(analysis)
    except Exception as exc:
        print(f"LLM coach unavailable; using deterministic fallback: {exc}")
        return fallback_coaching(analysis)


def analyze_move(payload: dict[str, Any]) -> dict[str, Any]:
    fen = str(payload.get("fen", "")).strip()
    move_uci = str(payload.get("move", "")).strip().lower()
    if not fen or not move_uci:
        raise ValueError("fen and move are required")

    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError("Invalid FEN.") from exc
    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError as exc:
        raise ValueError("Invalid UCI move.") from exc
    if move not in board.legal_moves:
        raise ValueError("Move is not legal in the supplied position.")

    with _analyzer_lock:
        try:
            analysis = get_analyzer().analyze_move(board, move).to_dict()
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, BrokenPipeError):
            reset_analyzer()
            analysis = get_analyzer().analyze_move(board, move).to_dict()

    should_coach = int(analysis["centipawn_loss"]) >= MISTAKE_THRESHOLD_CP
    result: dict[str, Any] = {
        "shouldCoach": should_coach,
        "moveNumber": analysis["move_number"],
        "ply": analysis["ply"],
        "playedMove": analysis["played_move"],
        "playedMoveUci": analysis["played_move_uci"],
        "classification": analysis["classification"],
        "centipawnLoss": analysis["centipawn_loss"],
        "bestMove": analysis["best_move"],
        "bestMoveUci": analysis["best_move_uci"],
        "opponentReply": analysis["opponent_reply"],
        "opponentReplyUci": analysis["opponent_reply_uci"],
        "fenBefore": analysis["fen_before"],
        "fenAfter": analysis["fen_after"],
    }

    if should_coach:
        result.update(coach_payload(analysis))
    else:
        classification = str(analysis["classification"])
        if classification == "good":
            result.update({
                "title": "Solid move",
                "feedback": f"{analysis['played_move']} has no major problem. Keep looking for your opponent's forcing ideas before the next move.",
                "lesson": "Keep checking threats even after a good move",
                "question": "What changed after my move?",
                "arrows": [],
                "highlightsBefore": [],
                "highlightsAfter": [],
            })
        else:
            result.update({
                "title": "Small inaccuracy",
                "feedback": f"{analysis['played_move']} is playable, but {analysis['best_move']} was a little more precise. No major mistake here.",
                "lesson": "Compare two candidate moves before choosing",
                "question": "Is there a more active version of my idea?",
                "arrows": [],
                "highlightsBefore": [],
                "highlightsAfter": [],
            })
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "AIChessCoach/1.0"

    def _cors_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
            return origin
        return "http://localhost:5173"

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        if status != 204:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            warning = None
            stockfish = None
            try:
                stockfish = find_stockfish()
            except Exception as exc:
                warning = str(exc)
            self._send(200, {
                "ok": True,
                "stockfish": stockfish,
                "bot": runtime.status(),
                "coachTimeMs": COACH_TIME_MS,
                "mistakeThresholdCp": MISTAKE_THRESHOLD_CP,
                "warning": warning,
            })
        elif self.path == "/api/bot/status":
            self._send(200, runtime.status())
        elif self.path == "/api/bot/levels":
            self._send(200, {
                "levels": [
                    {
                        "id": level.id,
                        "label": level.label,
                        "displayElo": level.display_elo,
                        "thinkMs": level.think_ms,
                    }
                    for level in BOT_LEVELS.values()
                ]
            })
        else:
            self._send(404, {"message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/bot/start":
                self._send(200, runtime.start())
            elif self.path == "/api/bot/stop":
                self._send(200, runtime.stop())
            elif self.path == "/api/bot/level":
                level = str(self._json_body().get("level", "")).strip()
                self._send(200, runtime.set_level(level))
            elif self.path.startswith("/api/bot/challenge/") and self.path.endswith("/accept"):
                raw = self.path[len("/api/bot/challenge/"):-len("/accept")].strip("/")
                body = self._json_body()
                opponent = str(body.get("opponent", "")).strip()
                self._send(200, runtime.accept_challenge(unquote(raw), opponent=opponent))
            elif self.path == "/api/coach/analyze":
                self._send(200, analyze_move(self._json_body()))
            else:
                self._send(404, {"message": "Not found"})
        except ValueError as exc:
            self._send(400, {"message": str(exc)})
        except Exception as exc:
            self._send(503, {"message": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def bootstrap_bot() -> None:
    try:
        result = runtime.start()
        print(f"Bot: {result.get('message', 'started')} ({result.get('username')})")
    except Exception as exc:
        print(f"Bot not started yet: {exc}")


if __name__ == "__main__":
    print(f"AI Chess Coach backend: http://{HOST}:{PORT}")
    try:
        print(f"Stockfish: {find_stockfish()}")
    except Exception as exc:
        print(f"Stockfish warning: {exc}")
    print(f"Coach analysis budget: {COACH_TIME_MS} ms per position")
    print(f"Coach trigger: {MISTAKE_THRESHOLD_CP} cp")
    threading.Thread(target=bootstrap_bot, name="bot-bootstrap", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.stop()
        with _analyzer_lock:
            reset_analyzer()
