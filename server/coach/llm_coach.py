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


COACH_DETAIL_CONFIG = {
    "quick": {
        "target": "8-15 words",
        "max_output_tokens": 160,
        "instruction": """
COACH DETAIL LEVEL: QUICK

Give ONE short coaching sentence.

Only say the most important thing the student should notice.

Do not explain variations unless absolutely necessary.

Keep it fast and memorable.
""".strip(),
    },

    "balanced": {
        "target": "18-30 words",
        "max_output_tokens": 220,
        "instruction": """
COACH DETAIL LEVEL: BALANCED

Use at most TWO short sentences.

Explain:
- what mattered
- why it mattered

Give the student enough information to understand the idea
without turning the response into a lecture.

End with a useful thinking idea only when it adds value.
""".strip(),
    },

    "deep": {
        "target": "30-50 words",
        "max_output_tokens": 300,
        "instruction": """
COACH DETAIL LEVEL: DEEP

Use at most THREE concise sentences.

Explain:
- the key mistake or idea
- the concrete tactical or positional reason
- the reusable lesson

A short concrete variation is allowed only when it genuinely
helps the student understand the position.

Deep means more insight, NOT more words.

Never pad the explanation.
""".strip(),
    },
}


LANGUAGE_INSTRUCTIONS = {
    "en": (
        "COACH LANGUAGE: English. "
        "Use natural, encouraging language suitable for a child or student. "
        "When explaining chess moves, prefer clear spoken chess language. "
        "For example, say 'knight takes g3' instead of only 'Nxg3', "
        "'knight to f3' instead of only 'Nf3', "
        "'queen takes d5, check' instead of only 'Qxd5+', "
        "and 'castles kingside' instead of only 'O-O'. "
        "You may include standard chess notation in parentheses when it helps "
        "teach notation, for example 'knight takes g3 (Nxg3)'. "
        "Make move explanations easy for a young chess student to understand "
        "when spoken aloud."
    ),

    "zh-CN": (
        "COACH LANGUAGE: Simplified Chinese (简体中文). "
        "Write every user-facing field in natural, friendly Mandarin "
        "suitable for a child or student. "
        "When explaining chess moves, prefer clear spoken Chinese. "
        "For example, say '马吃 g3' instead of only 'Nxg3', "
        "'马走到 f3' instead of only 'Nf3', "
        "'后吃 d5，将军' instead of only 'Qxd5+', "
        "and '王翼易位' instead of only 'O-O'. "
        "You may include standard chess notation in parentheses when useful, "
        "for example '马吃 g3（Nxg3）'. "
        "Use short sentences that sound natural when spoken aloud. "
        "Do not mix unnecessary English explanations into the Chinese response."
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

        # ------------------------------
        # Normalize coach detail
        # ------------------------------

        normalized_detail = str(
            detail
        ).strip().lower()

        if normalized_detail not in COACH_DETAIL_CONFIG:
            normalized_detail = "balanced"

        detail_config = COACH_DETAIL_CONFIG[
            normalized_detail
        ]

        # ------------------------------
        # Normalize coach language
        # ------------------------------

        normalized_language = (
            "zh-CN"
            if str(language).strip().lower()
            in {
                "zh",
                "zh-cn",
                "zh_cn",
                "chinese",
                "mandarin",
                "simplified chinese",
            }
            else "en"
        )

        # ------------------------------
        # Give the LLM only facts that
        # came from deterministic analysis
        # ------------------------------

        payload = {
            "fen_before": analysis.get(
                "fen_before"
            ),
            "fen_after": analysis.get(
                "fen_after"
            ),

            "move_number": analysis.get(
                "move_number"
            ),
            "color": analysis.get(
                "color"
            ),

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

            # Keep engine lines short.
            # The coach only needs enough context
            # to explain the main idea.
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

            "coach_detail": normalized_detail,
            "feedback_target": detail_config[
                "target"
            ],

            "language": normalized_language,
        }

        # ------------------------------
        # Combine:
        #
        # 1. main Chess Buddy personality
        # 2. language / spoken chess style
        # 3. selected explanation depth
        # ------------------------------

        language_instruction = (
            LANGUAGE_INSTRUCTIONS[
                normalized_language
            ]
        )

        combined_instructions = (
            self.instructions
            + "\n\n"
            + language_instruction
            + "\n\n"
            + str(
                detail_config[
                    "instruction"
                ]
            )
        )

        # ------------------------------
        # Generate structured coaching
        # ------------------------------

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

            # This is intentionally larger
            # than the requested feedback length.
            #
            # The model still follows the short
            # word targets above, but needs room
            # for title + feedback + lesson +
            # question + JSON formatting.
            max_output_tokens=int(
                detail_config[
                    "max_output_tokens"
                ]
            ),

            store=False,
        )

        # ------------------------------
        # Parse response
        # ------------------------------

        text = response.output_text.strip()

        if not text:
            raise ValueError(
                "Coach returned an empty response."
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                "Coach returned invalid JSON."
            ) from error

        title = str(
            data.get(
                "title",
                "",
            )
        ).strip()

        feedback = str(
            data.get(
                "feedback",
                "",
            )
        ).strip()

        lesson = str(
            data.get(
                "lesson",
                "",
            )
        ).strip()

        question = str(
            data.get(
                "question",
                "",
            )
        ).strip()

        if not feedback:
            raise ValueError(
                "Coach returned empty feedback."
            )

        # Do not hard-cut responses here.
        #
        # Character slicing can cut English
        # sentences or Chinese text in awkward
        # places.
        #
        # The prompt controls the desired length,
        # while the frontend can visually clamp
        # text if necessary.
        return {
            "title": title,
            "feedback": feedback,
            "lesson": lesson,
            "question": question,
        }