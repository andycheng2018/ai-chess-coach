from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

PROMPT_PATH = (
    Path(__file__).resolve().parent
    / "prompts"
    / "kid_coach_prompt.txt"
)

COACH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
        },
        "feedback": {
            "type": "string",
        },
        "lesson": {
            "type": "string",
        },
        "question": {
            "type": "string",
        },
    },
    "required": [
        "title",
        "feedback",
        "lesson",
        "question",
    ],
    "additionalProperties": False,
}


COACH_DETAIL_CONFIG: dict[str, dict[str, Any]] = {
    "quick": {
        "target": "35-50 words",
        "max_output_tokens": 220,
        "instruction": """
COACH DETAIL LEVEL: QUICK

Keep the feedback approximately 35-50 words.

Focus on:
- the main problem with the student's move
- the strongest relevant opponent idea, if supported
- why the Stockfish best move is better

Be concrete and concise. Do not add extra background or repeat yourself.
""".strip(),
    },
    "balanced": {
        "target": "60-90 words",
        "max_output_tokens": 320,
        "instruction": """
COACH DETAIL LEVEL: BALANCED

Keep the feedback approximately 60-90 words.

Explain:
- what went wrong
- why it matters in this exact position
- the opponent's strongest relevant idea, if supported
- why the Stockfish best move is better
- one reusable thinking habit

Prefer concrete chess language over generic advice.
""".strip(),
    },
    "deep": {
        "target": "100-140 words",
        "max_output_tokens": 520,
        "instruction": """
COACH DETAIL LEVEL: DEEP

Keep the feedback approximately 100-140 words.

Explain:
- what went wrong
- the tactical or positional reason
- the opponent's strongest relevant reply, if supported
- the important engine continuation when useful
- why the Stockfish best move improves the position
- one reusable lesson the student can apply later

Be detailed but focused. Do not pad the answer or repeat the same point.
""".strip(),
    },
}

LANGUAGE_INSTRUCTIONS = {
    "en": (
        "COACH LANGUAGE: English. "
        "Use natural, encouraging language suitable for a child or student. "
        "Keep standard chess notation such as Nf3, Qxd5+, and O-O unchanged."
    ),

    "zh-CN": (
        "COACH LANGUAGE: Simplified Chinese (简体中文). "
        "Write every user-facing field in natural, friendly Mandarin "
        "suitable for a child or student. "
        "Keep standard chess notation such as Nf3, Qxd5+, and O-O unchanged. "
        "Use short sentences that sound natural when spoken aloud. "
        "Do not mix English explanations into the Chinese response. "
        "Treat English word-count targets only as a general brevity guideline."
    ),
}

class LLMCoach:
    """
    Turns deterministic Stockfish analysis into
    student-friendly coaching.

    Stockfish remains the source of truth for chess facts.
    The LLM is used only to explain those facts clearly.
    """

    def __init__(
        self,
        model: str | None = None,
    ) -> None:
        if not PROMPT_PATH.is_file():
            raise FileNotFoundError(
                f"Coach prompt not found: {PROMPT_PATH}"
            )

        self.client = OpenAI()

        self.model = model or os.getenv(
            "OPENAI_MODEL",
            "gpt-4.1-mini",
        )

        self.instructions = PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()

    def create_feedback(
        self,
        analysis: dict[str, Any],
        detail: str = "balanced",
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Generate wording for an already-computed
        Stockfish analysis.

        The detail setting changes explanation depth only.
        It never changes Stockfish's chess conclusions.
        """

        normalized_detail = str(detail).strip().lower()

        detail_config = COACH_DETAIL_CONFIG.get(
            normalized_detail,
            COACH_DETAIL_CONFIG["balanced"],
        )

        normalized_language = (
            "zh-CN"
            if str(language).strip().lower()
            in {
                "zh",
                "zh-cn",
                "chinese",
                "mandarin",
            }
            else "en"
        )

        payload = {
            "fen_before": analysis.get("fen_before"),
            "fen_after": analysis.get("fen_after"),

            "move_number": analysis.get("move_number"),
            "color": analysis.get("color"),

            "played_move": analysis.get("played_move"),
            "played_move_uci": analysis.get(
                "played_move_uci"
            ),

            "best_move": analysis.get("best_move"),
            "best_move_uci": analysis.get(
                "best_move_uci"
            ),

            "opponent_reply": analysis.get(
                "opponent_reply"
            ),
            "opponent_reply_uci": analysis.get(
                "opponent_reply_uci"
            ),

            "classification": analysis.get(
                "classification"
            ),
            "centipawn_loss": analysis.get(
                "centipawn_loss"
            ),

            "best_line": analysis.get(
                "best_line",
                [],
            )[:6],

            "refutation_line": analysis.get(
                "refutation_line",
                [],
            )[:6],

            "theme_hint": analysis.get(
                "theme_hint"
            ),

            "coach_detail": normalized_detail
            if normalized_detail in COACH_DETAIL_CONFIG
            else "balanced",

            "feedback_target": detail_config["target"],
            "language": normalized_language,
        }

        combined_instructions = (
            self.instructions
            + "\n\n"
            + str(detail_config["instruction"])
            + "\n\n"
            + LANGUAGE_INSTRUCTIONS[normalized_language]
        )

        response = self.client.responses.create(
            model=self.model,

            instructions=combined_instructions,

            input=json.dumps(
                payload,
                ensure_ascii=False,
            ),

            text={
                "format": {
                    "type": "json_schema",
                    "name": "chess_coach_feedback",
                    "strict": True,
                    "schema": COACH_RESPONSE_SCHEMA,
                },
            },

            max_output_tokens=int(
                detail_config["max_output_tokens"]
            ),

            store=False,
        )

        text = response.output_text.strip()

        if not text:
            raise ValueError(
                "Coach returned an empty response."
            )

        data = json.loads(text)

        title = str(
            data.get("title", "")
        ).strip()

        feedback = str(
            data.get("feedback", "")
        ).strip()

        lesson = str(
            data.get("lesson", "")
        ).strip()

        question = str(
            data.get("question", "")
        ).strip()

        if not feedback:
            raise ValueError(
                "Coach returned empty feedback."
            )

        # Do not hard-cut feedback. The model already has
        # a detail-specific word target and token budget.
        # Character slicing can cut a sentence in half.
        return {
            "title": title[:80],
            "feedback": feedback,
            "lesson": lesson[:200],
            "question": question[:220],
        }