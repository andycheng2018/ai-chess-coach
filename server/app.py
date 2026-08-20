#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import chess
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from bot_runtime import BOT_LEVELS, runtime
from coach.stockfish_analyzer import StockfishAnalyzer, find_stockfish

HOST = os.environ.get("HOST", "0.0.0.0")

EXTRA_CORS_ORIGINS = {
    item.strip()
    for item in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "",
    ).split(",")
    if item.strip()
}

PORT = int(
    os.environ.get(
        "PORT",
        os.environ.get("CHESS_SERVER_PORT", "8765")
    )
)
COACH_TIME_MS = max(200, int(os.environ.get("COACH_TIME_MS", "250")))

COACH_ANALYSIS_PROFILES = {
    "quick": {
        "time_ms": max(
            200,
            int(
                os.environ.get(
                    "COACH_TIME_MS_QUICK",
                    str(COACH_TIME_MS),
                )
            ),
        ),
        "pv_plies": 6,
    },
    "balanced": {
        "time_ms": max(
            200,
            int(
                os.environ.get(
                    "COACH_TIME_MS_BALANCED",
                    "800",
                )
            ),
        ),
        "pv_plies": 10,
    },
    "deep": {
        "time_ms": max(
            200,
            int(
                os.environ.get(
                    "COACH_TIME_MS_DEEP",
                    "2000",
                )
            ),
        ),
        "pv_plies": 14,
    },
}

# Keep the modes ordered even if only one environment variable is changed.
COACH_ANALYSIS_PROFILES["balanced"]["time_ms"] = max(
    COACH_ANALYSIS_PROFILES["quick"]["time_ms"] + 100,
    COACH_ANALYSIS_PROFILES["balanced"]["time_ms"],
)
COACH_ANALYSIS_PROFILES["deep"]["time_ms"] = max(
    COACH_ANALYSIS_PROFILES["balanced"]["time_ms"] + 100,
    COACH_ANALYSIS_PROFILES["deep"]["time_ms"],
)
MISTAKE_THRESHOLD_CP = int(os.environ.get("COACH_MISTAKE_THRESHOLD_CP", "80"))
MAX_BODY_BYTES = 64 * 1024

ELEVENLABS_API_KEY = os.environ.get(
    "ELEVENLABS_API_KEY",
    "",
).strip()

ELEVENLABS_VOICE_ID = os.environ.get(
    "ELEVENLABS_VOICE_ID",
    "",
).strip()

ELEVENLABS_VOICE_ID_ZH = os.environ.get(
    "ELEVENLABS_VOICE_ID_ZH",
    "",
).strip()

ELEVENLABS_MODEL_ID = os.environ.get(
    "ELEVENLABS_MODEL_ID",
    "eleven_flash_v2_5",
).strip()

_analyzer: StockfishAnalyzer | None = None
_analyzer_lock = threading.Lock()
_llm_coach: Any = None
_llm_lock = threading.Lock()

_tts_session = requests.Session()
_tts_lock = threading.Lock()

_analysis_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_analysis_cache_lock = threading.Lock()
_ANALYSIS_CACHE_LIMIT = 128


def cache_analysis(analysis: dict[str, Any]) -> str:
    analysis_id = uuid.uuid4().hex

    with _analysis_cache_lock:
        _analysis_cache[analysis_id] = analysis
        _analysis_cache.move_to_end(analysis_id)

        while len(_analysis_cache) > _ANALYSIS_CACHE_LIMIT:
            _analysis_cache.popitem(last=False)

    return analysis_id


def get_cached_analysis(analysis_id: str) -> dict[str, Any] | None:
    with _analysis_cache_lock:
        analysis = _analysis_cache.get(analysis_id)

        if analysis is not None:
            _analysis_cache.move_to_end(analysis_id)

        return analysis


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


def normalize_language(value: Any) -> str:
    raw = str(value or "").strip().lower()

    if raw in {
        "zh",
        "zh-cn",
        "chinese",
        "mandarin",
    }:
        return "zh-CN"

    return "en"


def fallback_coaching(
    analysis: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    played = str(analysis["played_move"])
    best = str(analysis["best_move"])
    reply = str(
        analysis.get(
            "opponent_reply",
            "",
        )
    )

    classification = str(
        analysis["classification"]
    )

    theme = str(
        analysis.get(
            "theme_hint",
            "checks, captures, and threats",
        )
    )

    best_uci = str(
        analysis.get(
            "best_move_uci",
            "",
        )
    )

    reply_uci = str(
        analysis.get(
            "opponent_reply_uci",
            "",
        )
    )

    language = normalize_language(language)

    if language == "zh-CN":
        if reply:
            feedback = (
                f"走 {played} 后，对手可以用 {reply} 反击。"
                f"{best} 会更准确。"
                "落子前先看看对手有没有将军、吃子或直接威胁。"
            )
        else:
            feedback = (
                f"{played} 这步还有改进空间。"
                f"{best} 会更准确。"
                "落子前先快速检查对手的威胁。"
            )

        title_map = {
            "good": "好棋",
            "inaccuracy": "不够准确",
            "mistake": "失误",
            "blunder": "严重失误",
        }

        title = title_map.get(
            classification,
            "教练提示",
        )

        lesson = (
            "落子前检查将军、吃子和直接威胁"
        )

        question = (
            "这步走完以后，对手有没有将军、吃子或直接威胁？"
        )

    else:
        if reply:
            feedback = (
                f"{played} lets your opponent answer with "
                f"{reply}, which makes the position harder "
                f"to handle. {best} was stronger because it "
                "deals with the position more actively. "
                "Before committing, scan the opponent's "
                "forcing replies first."
            )
        else:
            feedback = (
                f"{played} was a {classification}. "
                f"{best} kept the position healthier. "
                "Use a quick forcing-move scan before "
                "you settle on your move."
            )

        title = classification.capitalize()
        lesson = theme.capitalize()

        question = (
            "What checks, captures, or threats does my "
            "opponent have after this move?"
        )

    arrows: list[dict[str, str]] = []

    if len(best_uci) >= 4:
        arrows.append({
            "from": best_uci[:2],
            "to": best_uci[2:4],
            "kind": "best",
        })

    if len(reply_uci) >= 4:
        arrows.append({
            "from": reply_uci[:2],
            "to": reply_uci[2:4],
            "kind": "danger",
        })

    highlights_before = (
        [
            best_uci[:2],
            best_uci[2:4],
        ]
        if len(best_uci) >= 4
        else []
    )

    highlights_after = (
        [
            reply_uci[:2],
            reply_uci[2:4],
        ]
        if len(reply_uci) >= 4
        else []
    )

    return {
        "title": title,
        "feedback": feedback,
        "lesson": lesson,
        "question": question,
        "arrows": arrows,
        "highlightsBefore": highlights_before,
        "highlightsAfter": highlights_after,
    }


def generate_llm_coaching(
    analysis: dict[str, Any],
    detail: str = "balanced",
    language: str = "en",
    recent_feedback: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate real LLM wording.

    Important: this function never silently substitutes canned coaching.
    If the LLM is unavailable, the caller receives an error and the
    frontend can honestly show that the explanation did not load.
    """

    if not os.environ.get(
        "OPENAI_API_KEY",
        "",
    ).strip():
        raise RuntimeError(
            "OPENAI_API_KEY is not configured."
        )

    try:
        with _llm_lock:
            result = get_llm_coach().create_feedback(
                analysis,
                detail=detail,
                language=language,
                recent_feedback=recent_feedback or [],
            )

        print(
            "[COACH LLM] success "
            f"move={analysis.get('played_move_uci', '')} "
            f"detail={detail} "
            f"language={normalize_language(language)}",
            flush=True,
        )

        return result

    except Exception as exc:
        print(
            "[COACH LLM] failed "
            f"move={analysis.get('played_move_uci', '')}: "
            f"{exc}",
            flush=True,
        )

        raise RuntimeError(
            f"AI coach explanation failed: {exc}"
        ) from exc


def synthesize_speech(
    payload: dict[str, Any],
) -> bytes:
    text = str(
        payload.get(
            "text",
            "",
        )
    ).strip()

    language = normalize_language(
        payload.get(
            "language",
            "en",
        )
    )

    if not text:
        raise ValueError(
            "text is required"
        )

    # Live coaching should stay short.
    if len(text) > 1000:
        raise ValueError(
            "text is too long for live coaching"
        )

    if not ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ElevenLabs TTS is not configured"
        )

    if (
        language == "zh-CN"
        and ELEVENLABS_VOICE_ID_ZH
    ):
        voice_id = ELEVENLABS_VOICE_ID_ZH
    else:
        voice_id = ELEVENLABS_VOICE_ID

    if not voice_id:
        raise RuntimeError(
            "ElevenLabs voice ID is not configured"
        )

    with _tts_lock:
        response = _tts_session.post(
            (
                "https://api.elevenlabs.io/"
                f"v1/text-to-speech/{voice_id}"
            ),

            params={
                "output_format": "mp3_44100_128",
            },

            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },

            json={
                "text": text,
                "model_id": ELEVENLABS_MODEL_ID,
            },

            timeout=15,
        )

    try:
        response.raise_for_status()

    except requests.RequestException as exc:
        detail = (
            response.text[:500]
            if response.text
            else "No response body"
        )

        print(
            "[TTS] ElevenLabs error:",
            response.status_code,
            detail,
        )

        raise RuntimeError(
            "ElevenLabs request failed with "
            f"HTTP {response.status_code}: "
            f"{detail}"
        ) from exc

    if not response.content:
        raise RuntimeError(
            "ElevenLabs returned empty audio"
        )

    return response.content
    

def analyze_move(
    payload: dict[str, Any],
) -> dict[str, Any]:
    fen = str(
        payload.get(
            "fen",
            "",
        )
    ).strip()

    move_uci = str(
        payload.get(
            "move",
            "",
        )
    ).strip().lower()

    language = normalize_language(
        payload.get(
            "language",
            "en",
        )
    )

    detail = str(
        payload.get(
            "detail",
            "balanced",
        )
    ).strip().lower()

    if detail not in {
        "quick",
        "balanced",
        "deep",
    }:
        detail = "balanced"

    analysis_profile = COACH_ANALYSIS_PROFILES[
        detail
    ]

    if not fen or not move_uci:
        raise ValueError(
            "fen and move are required"
        )

    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError(
            "Invalid FEN."
        ) from exc

    try:
        move = chess.Move.from_uci(
            move_uci
        )
    except ValueError as exc:
        raise ValueError(
            "Invalid UCI move."
        ) from exc

    if move not in board.legal_moves:
        raise ValueError(
            "Move is not legal in the supplied position."
        )

    with _analyzer_lock:
        try:
            analysis = (
                get_analyzer()
                .analyze_move(
                    board,
                    move,
                    time_ms=analysis_profile[
                        "time_ms"
                    ],
                    max_plies=analysis_profile[
                        "pv_plies"
                    ],
                    profile=detail,
                )
                .to_dict()
            )

        except (
            chess.engine.EngineError,
            chess.engine.EngineTerminatedError,
            BrokenPipeError,
        ):
            reset_analyzer()

            analysis = (
                get_analyzer()
                .analyze_move(
                    board,
                    move,
                    time_ms=analysis_profile[
                        "time_ms"
                    ],
                    max_plies=analysis_profile[
                        "pv_plies"
                    ],
                    profile=detail,
                )
                .to_dict()
            )

    should_coach = (
        int(
            analysis[
                "centipawn_loss"
            ]
        )
        >= MISTAKE_THRESHOLD_CP
    )

    result: dict[str, Any] = {
        "shouldCoach": should_coach,
        "moveNumber": analysis[
            "move_number"
        ],
        "ply": analysis[
            "ply"
        ],
        "playedMove": analysis[
            "played_move"
        ],
        "playedMoveUci": analysis[
            "played_move_uci"
        ],
        "classification": analysis[
            "classification"
        ],
        "centipawnLoss": analysis[
            "centipawn_loss"
        ],
        "bestMove": analysis[
            "best_move"
        ],
        "bestMoveUci": analysis[
            "best_move_uci"
        ],
        "opponentReply": analysis[
            "opponent_reply"
        ],
        "opponentReplyUci": analysis[
            "opponent_reply_uci"
        ],
        "fenBefore": analysis[
            "fen_before"
        ],
        "fenAfter": analysis[
            "fen_after"
        ],
        "bestLine": analysis.get(
            "best_line",
            [],
        ),
        "refutationLine": analysis.get(
            "refutation_line",
            [],
        ),
        "themeHint": analysis.get(
            "theme_hint",
            "",
        ),
        "evaluationBefore": analysis.get(
            "evaluation_before",
            0,
        ),
        "evaluationAfter": analysis.get(
            "evaluation_after",
            0,
        ),
        "engineDiagnostics": analysis.get(
            "engine_diagnostics",
            {},
        ),
    }

    if should_coach:
        # Cache the deterministic analysis on the server. The second,
        # asynchronous request uses this ID to generate conversational wording.
        analysis_id = cache_analysis(
            analysis
        )

        # Reuse fallback_coaching ONLY for deterministic visual arrows.
        # Its canned text is deliberately not returned as the AI explanation.
        visual = fallback_coaching(
            analysis,
            language=language,
        )

        result.update({
            "analysisId": analysis_id,
            "explanationPending": True,
            "title": (
                "关键失误"
                if (
                    language == "zh-CN"
                    and analysis["classification"] == "blunder"
                )
                else "值得看一看"
                if language == "zh-CN"
                else "Critical miss"
                if analysis["classification"] == "blunder"
                else "Worth a look"
            ),
            "feedback": "",
            "lesson": "",
            "question": "",
            "arrows": visual.get(
                "arrows",
                [],
            ),
            "highlightsBefore": visual.get(
                "highlightsBefore",
                [],
            ),
            "highlightsAfter": visual.get(
                "highlightsAfter",
                [],
            ),
        })

    else:
        cp_loss = int(
            analysis[
                "centipawn_loss"
            ]
        )

        if cp_loss < 35:
            result.update({
                "title": (
                    "稳健"
                    if language == "zh-CN"
                    else "Solid"
                ),
                "feedback": "",
                "lesson": "",
                "question": "",
                "arrows": [],
                "highlightsBefore": [],
                "highlightsAfter": [],
                "explanationPending": False,
            })

        else:
            result.update({
                "title": (
                    "再看一眼"
                    if language == "zh-CN"
                    else "Worth a look"
                ),
                "feedback": "",
                "lesson": "",
                "question": "",
                "arrows": [],
                "highlightsBefore": [],
                "highlightsAfter": [],
                "explanationPending": False,
            })

    return result


def explain_analysis(
    payload: dict[str, Any],
) -> dict[str, Any]:
    analysis_id = str(
        payload.get(
            "analysisId",
            "",
        )
    ).strip()

    if not analysis_id:
        raise ValueError(
            "analysisId is required"
        )

    analysis = get_cached_analysis(
        analysis_id
    )

    if analysis is None:
        raise ValueError(
            "The cached coach analysis expired. "
            "Please analyze the move again."
        )

    detail = str(
        payload.get(
            "detail",
            "balanced",
        )
    ).strip().lower()

    if detail not in {
        "quick",
        "balanced",
        "deep",
    }:
        detail = "balanced"

    language = normalize_language(
        payload.get(
            "language",
            "en",
        )
    )

    raw_recent = payload.get(
        "recentFeedback",
        [],
    )

    recent_feedback: list[str] = []

    if isinstance(
        raw_recent,
        list,
    ):
        for item in raw_recent[-4:]:
            value = str(
                item
            ).strip()

            if value:
                recent_feedback.append(
                    value[:600]
                )

    return generate_llm_coaching(
        analysis,
        detail=detail,
        language=language,
        recent_feedback=recent_feedback,
    )



def critical_position_question(
    payload: dict[str, Any],
) -> dict[str, Any]:
    fen = str(
        payload.get(
            "fen",
            "",
        )
    ).strip()

    fen_before_opponent = str(
        payload.get(
            "fenBeforeOpponent",
            "",
        )
    ).strip()

    if not fen:
        raise ValueError(
            "fen is required"
        )

    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise ValueError(
            "Invalid FEN."
        ) from exc

    before_board = None

    if fen_before_opponent:
        try:
            before_board = (
                chess.Board(
                    fen_before_opponent
                )
            )
        except ValueError:
            before_board = None

    last_opponent_move = str(
        payload.get(
            "lastOpponentMove",
            "",
        )
    ).strip()

    last_opponent_move_uci = str(
        payload.get(
            "lastOpponentMoveUci",
            "",
        )
    ).strip().lower()

    language = normalize_language(
        payload.get(
            "language",
            "en",
        )
    )

    recent_questions: list[str] = []

    raw_recent = payload.get(
        "recentQuestions",
        [],
    )

    if isinstance(
        raw_recent,
        list,
    ):
        for item in raw_recent[-4:]:
            value = str(item).strip()

            if value:
                recent_questions.append(
                    value[:300]
                )

    with _analyzer_lock:
        try:
            position = (
                get_analyzer()
                .analyze_critical_position(
                    board
                )
            )
        except (
            chess.engine.EngineError,
            chess.engine.EngineTerminatedError,
            BrokenPipeError,
        ):
            reset_analyzer()

            position = (
                get_analyzer()
                .analyze_critical_position(
                    board
                )
            )

    moved_piece_name = ""
    newly_pinned_squares: list[str] = []
    attacked_targets: list[str] = []

    if (
        before_board is not None
        and last_opponent_move_uci
    ):
        try:
            last_move = (
                chess.Move.from_uci(
                    last_opponent_move_uci
                )
            )

            moved_piece = (
                before_board.piece_at(
                    last_move.from_square
                )
            )

            if moved_piece is not None:
                moved_piece_name = (
                    chess.piece_name(
                        moved_piece.piece_type
                    )
                )

            student_color = board.turn

            for square in chess.SQUARES:
                piece = board.piece_at(
                    square
                )

                if (
                    piece is None
                    or piece.color != student_color
                    or piece.piece_type == chess.KING
                ):
                    continue

                now_pinned = (
                    board.is_pinned(
                        student_color,
                        square,
                    )
                )

                was_pinned = (
                    before_board.is_pinned(
                        student_color,
                        square,
                    )
                    if before_board.piece_at(
                        square
                    )
                    else False
                )

                if (
                    now_pinned
                    and not was_pinned
                ):
                    newly_pinned_squares.append(
                        chess.square_name(
                            square
                        )
                    )

            moved_piece_after = (
                board.piece_at(
                    last_move.to_square
                )
            )

            if (
                moved_piece_after is not None
                and moved_piece_after.color != student_color
            ):
                for target_square in board.attacks(
                    last_move.to_square
                ):
                    target = board.piece_at(
                        target_square
                    )

                    if (
                        target is not None
                        and target.color == student_color
                    ):
                        attacked_targets.append(
                            (
                                f"{chess.piece_name(target.piece_type)} "
                                f"on {chess.square_name(target_square)}"
                            )
                        )

        except ValueError:
            pass

    opponent_intent_evidence = (
        bool(newly_pinned_squares)
        or bool(position.get("in_check"))
        or bool(position.get("threat_is_mate"))
        or bool(position.get("threat_gives_check"))
        or bool(position.get("threat_is_capture"))
    )

    if not opponent_intent_evidence:
        return {
            "isCritical": False,
        }

    position["is_critical"] = True
    position["kind"] = (
        "check"
        if position.get("in_check")
        else "threat"
    )

    position[
        "last_opponent_move"
    ] = last_opponent_move

    position[
        "last_opponent_move_uci"
    ] = last_opponent_move_uci

    position[
        "opponent_moved_piece"
    ] = moved_piece_name

    position[
        "newly_pinned_squares"
    ] = newly_pinned_squares

    position[
        "attacked_targets"
    ] = attacked_targets[:4]

    try:
        with _llm_lock:
            wording = (
                get_llm_coach()
                .create_critical_question(
                    position,
                    language=language,
                    recent_questions=recent_questions,
                )
            )
    except Exception as exc:
        print(
            "[COACH CRITICAL] question generation failed:",
            exc,
            flush=True,
        )

        return {
            "isCritical": False,
        }

    return {
        "isCritical": True,
        "kind": position.get(
            "kind",
            "threat",
        ),
        "title": wording.get(
            "title",
            "",
        ),
        "question": wording.get(
            "question",
            "",
        ),
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "AIChessCoach/1.0"

    def _cors_origin(self) -> str:
        origin = self.headers.get("Origin", "")

        allowed_origins = {
            "capacitor://localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }

        allowed_origins.update(EXTRA_CORS_ORIGINS)

        # Allow Chess Buddy frontend deployed on Render.
        if origin.startswith("https://") and origin.endswith(".onrender.com"):
            return origin

        if origin in allowed_origins:
            return origin


        return "http://localhost:5173"

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
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
        except (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            # Mobile clients intentionally cancel stale coach requests when a
            # newer move arrives. The response is no longer deliverable, so do
            # not turn that normal disconnect into another attempted 503.
            self.close_connection = True

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
    ) -> None:
        try:
            self.send_response(status)

            self.send_header(
                "Access-Control-Allow-Origin",
                self._cors_origin(),
            )

            self.send_header(
                "Vary",
                "Origin",
            )

            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS",
            )

            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type",
            )

            self.send_header(
                "Cache-Control",
                "no-store",
            )

            self.send_header(
                "Content-Type",
                content_type,
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()

            if body:
                self.wfile.write(body)
        except (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            # Audio requests can also be canceled when newer speech takes
            # priority. A closed socket is not a provider or TTS failure.
            self.close_connection = True

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
                "coachAnalysisProfiles": {
                    name: {
                        "timeMs": profile[
                            "time_ms"
                        ],
                        "pvPlies": profile[
                            "pv_plies"
                        ],
                    }
                    for name, profile in COACH_ANALYSIS_PROFILES.items()
                },
                "mistakeThresholdCp": MISTAKE_THRESHOLD_CP,

                "tts": {
                    "provider": "elevenlabs",
                    "configured": bool(
                        ELEVENLABS_API_KEY
                        and ELEVENLABS_VOICE_ID
                    ),
                    "model": ELEVENLABS_MODEL_ID,
                },

                "warning": warning,
            })
        elif self.path == "/api/bot/status":
            self._send(200, runtime.status())
        elif (
            self.path.startswith("/api/bot/game/")
            and self.path.endswith("/state")
        ):
            raw = self.path[
                len("/api/bot/game/"):
                -len("/state")
            ].strip("/")

            game_id = unquote(raw)

            cached = runtime.game_state(game_id)

            if cached is None:
                self._send(
                    404,
                    {"message": "Game state not cached yet."},
                )
            else:
                self._send(200, cached)
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
            elif self.path == "/api/bot/join-room":
                body = self._json_body()

                challenge_id = str(body.get("challengeId", "")).strip()
                color = str(body.get("color", "")).strip().lower()
                opponent = str(body.get("opponent", "")).strip()

                if not challenge_id:
                    raise ValueError("challengeId is required")

                if color and color not in {"white", "black"}:
                    raise ValueError("color must be white or black")

                self._send(
                    200,
                    runtime.accept_challenge(
                        challenge_id,
                        opponent=opponent,
                        color=color,
                    ),
                )
            elif self.path == "/api/tts":
                audio = synthesize_speech(
                    self._json_body()
                )

                self._send_bytes(
                    200,
                    audio,
                    "audio/mpeg",
                )

            elif self.path == "/api/coach/analyze":
                self._send(
                    200,
                    analyze_move(
                        self._json_body()
                    ),
                )
            elif self.path == "/api/coach/explain":
                self._send(
                    200,
                    explain_analysis(
                        self._json_body()
                    ),
                )
            elif self.path == "/api/coach/critical-question":
                self._send(
                    200,
                    critical_position_question(
                        self._json_body()
                    ),
                )
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
    print(
        "Coach analysis profiles: "
        + ", ".join(
            f"{name}={profile['time_ms']} ms"
            for name, profile in COACH_ANALYSIS_PROFILES.items()
        )
        + " per search"
    )
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
