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
        "title": {"type": "string"},
        "feedback": {"type": "string"},
        "lesson": {"type": "string"},
        "question": {"type": "string"},
    },
    "required": [
        "title",
        "feedback",
        "lesson",
        "question",
    ],
    "additionalProperties": False,
}



CRITICAL_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
        },
        "question": {
            "type": "string",
        },
    },
    "required": [
        "title",
        "question",
    ],
    "additionalProperties": False,
}


COACH_DETAIL_CONFIG = {
    "quick": {
        "target": "15-25 words",
        "max_output_tokens": 220,
        "instruction": """
COACH DETAIL LEVEL: QUICK

Use 1-2 short sentences, roughly 15-25 words total.

Give the concrete chess reason, not merely a verdict.
If there is a forcing reply, name the important reply or consequence.
Do not add a generic lesson just to fill space.
""".strip(),
    },

    "balanced": {
        "target": "35-55 words",
        "max_output_tokens": 360,
        "instruction": """
COACH DETAIL LEVEL: BALANCED

Use 2-3 natural sentences, roughly 35-55 words total.

Explain:
1. what specifically changed or became vulnerable after the student's move,
2. how the opponent can exploit it or what opportunity was missed,
3. why the recommended move handles the position better.

Include a reusable thinking habit only when it is specific to this position.
""".strip(),
    },

    "deep": {
        "target": "60-90 words",
        "max_output_tokens": 520,
        "instruction": """
COACH DETAIL LEVEL: DEEP

Use 3-5 concise sentences, roughly 60-90 words total.

Explain the causal chess story:
- what the student's move changed,
- the concrete tactical or positional consequence,
- the important engine continuation when it genuinely teaches the idea,
- why the recommended move works,
- one reusable lesson.

Deep means more chess insight, not filler.
""".strip(),
    },
}


LANGUAGE_INSTRUCTIONS = {
    "en": (
        "COACH LANGUAGE: English. "
        "Use natural, conversational English that sounds good aloud. "
        "Prefer spoken chess language such as 'knight takes g3' rather than "
        "only 'Nxg3', 'knight to f3' rather than only 'Nf3', "
        "'queen takes d5, check' rather than only 'Qxd5+', and "
        "'castles kingside' rather than only 'O-O'. "
        "Standard notation may appear in parentheses when it genuinely helps."
    ),

    "zh-CN": (
        "COACH LANGUAGE: Simplified Chinese (简体中文). "
        "Use natural, conversational Mandarin that sounds good aloud. "
        "Prefer spoken chess language such as '马吃 g3' rather than only "
        "'Nxg3', '马走到 f3' rather than only 'Nf3', "
        "'后吃 d5，将军' rather than only 'Qxd5+', and "
        "'王翼易位' rather than only 'O-O'. "
        "Standard notation may appear in parentheses when useful. "
        "Do not mix unnecessary English explanations into Chinese."
    ),
}


class LLMCoach:
    """
    Converts deterministic Stockfish facts into useful coaching language.

    Stockfish remains the authority for chess facts.
    The LLM explains those facts and adds conversational teaching style.
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
        recent_feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_detail = str(
            detail
        ).strip().lower()

        if normalized_detail not in COACH_DETAIL_CONFIG:
            normalized_detail = "balanced"

        detail_config = COACH_DETAIL_CONFIG[
            normalized_detail
        ]

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

        recent = [
            str(item).strip()
            for item in (recent_feedback or [])
            if str(item).strip()
        ][-4:]

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
            "best_line": analysis.get(
                "best_line",
                [],
            )[:8],
            "refutation_line": analysis.get(
                "refutation_line",
                [],
            )[:8],
            "theme_hint": analysis.get(
                "theme_hint"
            ),
            "opening_eco": analysis.get(
                "opening_eco",
                "",
            ),
            "opening_name": analysis.get(
                "opening_name",
                "",
            ),
            "opening_variation": analysis.get(
                "opening_variation",
                "",
            ),
            "opening_in_book": analysis.get(
                "opening_in_book",
                False,
            ),
            "opening_left_book_at": analysis.get(
                "opening_left_book_at",
            ),
            "opening_book_move": analysis.get(
                "opening_book_move_san",
                "",
            ),
            "opening_book_move_uci": analysis.get(
                "opening_book_move_uci",
                "",
            ),
            "opening_transposed": analysis.get(
                "opening_transposed",
                False,
            ),
            "opening_depth_matched": analysis.get(
                "opening_depth_matched",
                0,
            ),
            "coach_detail": normalized_detail,
            "feedback_target": detail_config[
                "target"
            ],
            "language": normalized_language,

            # Short-term memory is used only to avoid sounding repetitive.
            "recent_feedback": recent,
        }

        if recent:
            recent_instruction = (
                "RECENT COACHING FROM THIS SAME GAME:\n"
                + "\n".join(
                    f"- {item}"
                    for item in recent
                )
                + "\n\n"
                "Do not reuse the same opener, catchphrase, lesson wording, "
                "or sentence structure unless repetition is genuinely needed. "
                "Continue the conversation naturally. If the same weakness "
                "is recurring, you may briefly connect it to the earlier "
                "pattern instead of repeating the old explanation."
            )
        else:
            recent_instruction = (
                "There is no recent coaching context yet. "
                "Use a natural conversational opening."
            )

        combined_instructions = (
            self.instructions
            + "\n\n"
            + LANGUAGE_INSTRUCTIONS[
                normalized_language
            ]
            + "\n\n"
            + str(
                detail_config[
                    "instruction"
                ]
            )
            + "\n\n"
            + recent_instruction
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
                detail_config[
                    "max_output_tokens"
                ]
            ),

            store=False,
        )

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

        return {
            "title": title,
            "feedback": feedback,
            "lesson": lesson,
            "question": question,
        }

    def create_critical_question(
        self,
        position: dict[str, Any],
        language: str = "en",
        recent_questions: list[str] | None = None,
    ) -> dict[str, str]:
        """
        Turn a Stockfish-confirmed critical position into one short
        Socratic question WITHOUT revealing the answer.
        """
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

        recent = [
            str(item).strip()
            for item in (
                recent_questions or []
            )
            if str(item).strip()
        ][-4:]

        payload = {
            "fen": position.get(
                "fen"
            ),
            "kind": position.get(
                "kind"
            ),
            "side_to_move": position.get(
                "side_to_move"
            ),
            "last_opponent_move": position.get(
                "last_opponent_move"
            ),
            "last_opponent_move_uci": position.get(
                "last_opponent_move_uci"
            ),
            "opponent_moved_piece": position.get(
                "opponent_moved_piece"
            ),
            "newly_pinned_squares": position.get(
                "newly_pinned_squares",
                [],
            ),
            "attacked_targets": position.get(
                "attacked_targets",
                [],
            ),

            # These are private chess facts used to formulate a good
            # question. The answer must NOT reveal them.
            "best_move": position.get(
                "best_move"
            ),
            "best_move_uci": position.get(
                "best_move_uci"
            ),
            "best_line": position.get(
                "best_line",
                [],
            )[:6],
            "best_gap_cp": position.get(
                "best_gap_cp"
            ),
            "in_check": position.get(
                "in_check"
            ),
            "threat_move": position.get(
                "threat_move"
            ),
            "threat_move_uci": position.get(
                "threat_move_uci"
            ),
            "threat_line": position.get(
                "threat_line",
                [],
            )[:5],
            "recent_questions": recent,
            "language": normalized_language,
        }

        instructions = """
You are Chess Buddy during a live chess game.

The opponent JUST moved and it is now the student's turn.

Ask ONE short Socratic question about what the OPPONENT is trying
to accomplish with their last move.

ABSOLUTE RULES:
- Ask about the opponent's intention, target, threat, line, pin, or setup.
- Do NOT ask what move the student should play.
- Do NOT ask the student to find the best move.
- Do NOT ask for a forcing move.
- Do NOT hint at Stockfish's recommended response.
- Do NOT reveal best_move or best_line.
- Do NOT ask a vague "What changed?" by itself.
- Keep the question roughly 7-20 words.
- Sound like a human coach.
- Use recent_questions to avoid repetitive wording.

Good examples:
- "What do you think their rook is trying to accomplish on that file?"
- "Which piece did that bishop just pin, and why does that matter?"
- "What target did their queen just create pressure against?"
- "If you ignore that move, what is your opponent preparing next?"

Use ONLY supplied facts:
- last_opponent_move
- opponent_moved_piece
- newly_pinned_squares
- attacked_targets
- threat_move / threat_line
- in_check
- FEN

Never invent a pin, target, threat, or plan.

If newly_pinned_squares is non-empty, prefer asking about the new pin.
If the opponent just gave check, ask what their checking move is trying
to gain or force.
Otherwise ask about the concrete opponent threat or target.

Return JSON only:
{
  "title": "short opponent-focused title",
  "question": "one opponent-intention question"
}
""".strip()

        response = self.client.responses.create(
            model=self.model,
            instructions=(
                instructions
                + "\n\n"
                + LANGUAGE_INSTRUCTIONS[
                    normalized_language
                ]
            ),
            input=json.dumps(
                payload,
                ensure_ascii=False,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "critical_chess_question",
                    "strict": True,
                    "schema": CRITICAL_QUESTION_SCHEMA,
                },
            },
            max_output_tokens=160,
            store=False,
        )

        text = response.output_text.strip()

        if not text:
            raise ValueError(
                "Critical-question coach returned an empty response."
            )

        data = json.loads(
            text
        )

        title = str(
            data.get(
                "title",
                "",
            )
        ).strip()

        question = str(
            data.get(
                "question",
                "",
            )
        ).strip()

        if not question:
            raise ValueError(
                "Critical-question coach returned an empty question."
            )

        return {
            "title": title,
            "question": question,
        }
