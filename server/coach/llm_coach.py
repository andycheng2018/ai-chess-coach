from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "kid_coach_prompt.txt"
SQUARE_RE = re.compile(r"^[a-h][1-8]$")
MOVE_RE = re.compile(r"([a-h][1-8])")


def _uci_squares(value: Any) -> set[str]:
    uci = str(value or "")
    if len(uci) < 4:
        return set()
    return {uci[:2], uci[2:4]}


def _line_squares(line: Any) -> set[str]:
    result: set[str] = set()
    for san in line or []:
        result.update(MOVE_RE.findall(str(san)))
    return result


def allowed_squares_by_context(analysis: dict[str, Any]) -> tuple[set[str], set[str]]:
    # BEFORE contains alternatives available before the student's move. AFTER
    # contains the position created by the student's move and the opponent's
    # refutation. Keeping these sets separate prevents a valid square from a
    # different snapshot being painted on the wrong board.
    before = (
        _uci_squares(analysis.get("played_move_uci"))
        | _uci_squares(analysis.get("best_move_uci"))
        | _line_squares(analysis.get("best_line"))
    )
    after = (
        _uci_squares(analysis.get("played_move_uci"))
        | _uci_squares(analysis.get("opponent_reply_uci"))
        | _line_squares(analysis.get("refutation_line"))
    )
    return (
        {sq for sq in before if SQUARE_RE.fullmatch(sq)},
        {sq for sq in after if SQUARE_RE.fullmatch(sq)},
    )



class LLMCoach:
    """Turns deterministic Stockfish data into student-friendly coaching.

    The model chooses what is worth explaining and which grounded hints to show,
    while the server validates all board annotations before the frontend sees them.
    """

    def __init__(self, model: str | None = None) -> None:
        if not PROMPT_PATH.is_file():
            raise FileNotFoundError(f"Coach prompt not found: {PROMPT_PATH}")
        self.client = OpenAI()
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        self.instructions = PROMPT_PATH.read_text(encoding="utf-8").strip()

    def create_feedback(self, analysis: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "fen_before": analysis.get("fen_before"),
            "fen_after": analysis.get("fen_after"),
            "move_number": analysis.get("move_number"),
            "color": analysis.get("color"),
            "played_move": analysis.get("played_move"),
            "played_move_uci": analysis.get("played_move_uci"),
            "best_move": analysis.get("best_move"),
            "best_move_uci": analysis.get("best_move_uci"),
            "opponent_reply": analysis.get("opponent_reply"),
            "opponent_reply_uci": analysis.get("opponent_reply_uci"),
            "classification": analysis.get("classification"),
            "centipawn_loss": analysis.get("centipawn_loss"),
            "best_line": analysis.get("best_line", [])[:6],
            "refutation_line": analysis.get("refutation_line", [])[:6],
            "theme_hint": analysis.get("theme_hint"),
        }
        response = self.client.responses.create(
            model=self.model,
            instructions=self.instructions,
            input=json.dumps(payload, ensure_ascii=False),
            max_output_tokens=320,
            store=False,
        )
        text = response.output_text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)

        feedback = str(data.get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Coach returned empty feedback.")

        valid_before, valid_after = allowed_squares_by_context(analysis)

        def validated_highlights(key: str, allowed: set[str]) -> list[str]:
            result: list[str] = []
            for raw in data.get(key, []) or []:
                sq = str(raw).lower().strip()
                if sq in allowed and sq not in result:
                    result.append(sq)
                if len(result) >= 3:
                    break
            return result

        highlights_before = validated_highlights("highlights_before", valid_before)
        highlights_after = validated_highlights("highlights_after", valid_after)

        best_uci = str(analysis.get("best_move_uci", ""))
        reply_uci = str(analysis.get("opponent_reply_uci", ""))
        arrows: list[dict[str, str]] = []
        if bool(data.get("show_best", True)) and len(best_uci) >= 4:
            arrows.append({"from": best_uci[:2], "to": best_uci[2:4], "kind": "best"})
        if bool(data.get("show_threat", False)) and len(reply_uci) >= 4:
            arrows.append({"from": reply_uci[:2], "to": reply_uci[2:4], "kind": "danger"})

        return {
            "title": str(data.get("title", analysis.get("classification", "Coach note"))).strip()[:48],
            "feedback": feedback[:700],
            "lesson": str(data.get("lesson", "")).strip()[:140],
            "question": str(data.get("question", "")).strip()[:160],
            "arrows": arrows[:2],
            "highlightsBefore": highlights_before,
            "highlightsAfter": highlights_after,
        }
