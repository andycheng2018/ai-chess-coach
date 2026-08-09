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


class LLMCoach:
    """
    Turns deterministic Stockfish analysis into concise,
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
    ) -> dict[str, Any]:
        """
        Generate wording for an already-computed Stockfish analysis.

        The model does NOT choose:
        - classification
        - centipawn loss
        - best move
        - opponent reply
        - arrows
        - board highlights
        - FENs

        Those remain controlled by deterministic engine analysis.
        """

        payload = {
            "fen_before": analysis.get("fen_before"),
            "fen_after": analysis.get("fen_after"),

            "move_number": analysis.get("move_number"),
            "color": analysis.get("color"),

            "played_move": analysis.get(
                "played_move"
            ),
            "played_move_uci": analysis.get(
                "played_move_uci"
            ),

            "best_move": analysis.get(
                "best_move"
            ),
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

            # Limit engine lines so the prompt stays compact
            # and the live coach remains responsive.
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
        }

        response = self.client.responses.create(
            model=self.model,

            instructions=self.instructions,

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

            max_output_tokens=320,

            # Live coaching does not need server-side
            # conversation persistence.
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

        # Defensive size limits.
        # These are intentionally larger than the prompt's
        # requested lengths so normal responses are not cut off.
        return {
            "title": title[:80],
            "feedback": feedback[:500],
            "lesson": lesson[:160],
            "question": question[:180],
        }