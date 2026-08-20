from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from coach.tactic_verifier import THEME_PRIORITY


PROMPT_PATH = (
    Path(__file__).resolve().parent
    / "prompts"
    / "kid_coach_prompt.txt"
)


CHESS_THEME_TERMS = (
    "Fork / Double Attack",
    "Pin",
    "Skewer",
    "Discovered Attack",
    "Discovered Check",
    "Double Check",
    "X-Ray Attack",
    "Defense",
    "Back-Rank Weakness",
    "Back-Rank Mate",
    "Deflection",
    "Decoy",
    "Removal of the Defender",
    "Overloading",
    "Interference",
    "Clearance",
    "Clearance Sacrifice",
    "Sacrifice",
    "Exchange Sacrifice",
    "Queen Sacrifice",
    "Zwischenzug",
    "Desperado",
    "Hanging Piece",
    "Trapped Piece",
    "Mating Net",
    "Smothered Mate",
    "Support Mate",
    "Checkmate Pattern",
    "Mate in One",
    "Mate in Two",
    "Mate in Three or More",
    "Forced Mate",
    "Perpetual Check",
    "Windmill",
    "Attack on f7 / f2",
    "Attacking the Castled King",
    "Vulnerable King",
    "King Safety",
    "Simplification",
    "Promotion",
    "Underpromotion",
    "En Passant",
    "Stalemate",
    "Zugzwang",
    "Endgame Tactic",
    "Passed Pawn",
    "Opposition",
    "Open File",
    "Weak Square",
)


CHINESE_THEME_LABELS = {
    "Fork / Double Attack": "叉攻 / 双攻",
    "Pin": "牵制",
    "Skewer": "串击",
    "Discovered Attack": "闪击",
    "Discovered Check": "闪将",
    "Double Check": "双将",
    "X-Ray Attack": "X 射线攻击",
    "Defense": "防守",
    "Back-Rank Weakness": "后排弱点",
    "Back-Rank Mate": "后排将杀",
    "Deflection": "引离",
    "Decoy": "诱离",
    "Removal of the Defender": "消除防守子",
    "Overloading": "过载",
    "Interference": "干扰",
    "Clearance": "腾挪",
    "Clearance Sacrifice": "腾挪弃子",
    "Sacrifice": "弃子",
    "Exchange Sacrifice": "弃质量",
    "Queen Sacrifice": "弃后",
    "Zwischenzug": "中间着",
    "Desperado": "亡命攻击",
    "Hanging Piece": "悬子",
    "Trapped Piece": "困子",
    "Mating Net": "将杀网",
    "Smothered Mate": "闷杀",
    "Support Mate": "保护式将杀",
    "Checkmate Pattern": "基本将杀型",
    "Mate in One": "一步将杀",
    "Mate in Two": "两步将杀",
    "Mate in Three or More": "三步以上将杀",
    "Forced Mate": "强制将杀",
    "Perpetual Check": "长将",
    "Windmill": "风车战术",
    "Attack on f7 / f2": "攻击 f7 / f2",
    "Attacking the Castled King": "进攻易位后的王",
    "Vulnerable King": "王位脆弱",
    "King Safety": "王的安全",
    "Simplification": "简化局面",
    "Promotion": "升变",
    "Underpromotion": "低级升变",
    "En Passant": "吃过路兵",
    "Stalemate": "逼和",
    "Zugzwang": "无着可动",
    "Endgame Tactic": "残局战术",
    "Passed Pawn": "通路兵",
    "Opposition": "对王",
    "Open File": "开放线",
    "Weak Square": "弱格",
}


# Every structured label is now owned by the deterministic verifier. The
# language model explains verified evidence; it never creates taxonomy data.
VERIFIER_CONTROLLED_THEMES = frozenset(
    CHESS_THEME_TERMS
)


VERIFIED_THEME_CLAIM_PATTERNS: dict[str, tuple[str, ...]] = {
    "Fork / Double Attack": (
        r"\bfork(?:s|ed|ing)?\b",
        r"\bdouble attack\b",
        r"叉攻|双攻",
    ),
    "Pin": (
        r"\bpin(?:s|ned|ning)?\b",
        r"牵制",
    ),
    "Discovered Check": (
        r"\bdiscovered check\b",
        r"闪将",
    ),
    "Double Check": (
        r"\bdouble check\b",
        r"双将",
    ),
    "Hanging Piece": (
        r"\bhanging piece\b",
        r"\bundefended piece\b",
        r"\bloose piece\b",
        r"悬子|挂子",
    ),
    "Mate in One": (
        r"\bmate in (?:one|1)\b",
        r"\bone[ -]move (?:mate|checkmate)\b",
        r"一步将杀",
    ),
    "Underpromotion": (
        r"\bunderpromot(?:e|es|ed|ing|ion)\b",
        r"低级升变",
    ),
    "Promotion": (
        r"\bpromot(?:e|es|ed|ing|ion)\b",
        r"升变",
    ),
    "En Passant": (
        r"\ben passant\b",
        r"吃过路兵",
    ),
    "Mate in Two": (
        r"\bmate in (?:two|2)\b",
        r"两步将杀",
    ),
    "Mate in Three or More": (
        r"\bmate in (?:three|3)(?:\s+or\s+more)?\b",
        r"三步以上将杀",
    ),
    "Attack on f7 / f2": (
        r"\battack(?:s|ed|ing)?\s+(?:on\s+)?f[27]\b",
        r"攻击\s*f[27]",
    ),
}


# Exact canonical tactic phrases are also protected in prose. Keep generic
# teaching language such as "defend your king" available, while blocking a
# named motif such as "skewer" unless the verifier supplied it.
PROSE_GATED_THEMES = frozenset({
    "Skewer",
    "Discovered Attack",
    "X-Ray Attack",
    "Back-Rank Weakness",
    "Back-Rank Mate",
    "Deflection",
    "Decoy",
    "Removal of the Defender",
    "Overloading",
    "Interference",
    "Clearance",
    "Clearance Sacrifice",
    "Sacrifice",
    "Exchange Sacrifice",
    "Queen Sacrifice",
    "Zwischenzug",
    "Desperado",
    "Trapped Piece",
    "Mating Net",
    "Smothered Mate",
    "Support Mate",
    "Checkmate Pattern",
    "Mate in Two",
    "Mate in Three or More",
    "Forced Mate",
    "Perpetual Check",
    "Windmill",
    "Attack on f7 / f2",
    "Attacking the Castled King",
    "Simplification",
    "Stalemate",
    "Zugzwang",
    "Endgame Tactic",
    "Passed Pawn",
    "Opposition",
    "Open File",
    "Weak Square",
})


for _theme in PROSE_GATED_THEMES:
    if _theme in VERIFIED_THEME_CLAIM_PATTERNS:
        continue

    english = re.escape(_theme.lower()).replace(
        r"\ ",
        r"\s+",
    ).replace(
        r"\-",
        r"[-\s]?",
    )
    chinese = re.escape(
        CHINESE_THEME_LABELS.get(
            _theme,
            "",
        )
    )
    patterns = [rf"\b{english}\b"]
    if chinese:
        patterns.append(chinese)
    VERIFIED_THEME_CLAIM_PATTERNS[_theme] = tuple(
        patterns
    )


def normalize_chess_themes(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []

    allowed = set(CHESS_THEME_TERMS)
    result: list[str] = []

    for item in raw:
        value = str(item).strip()

        if value in allowed and value not in result:
            result.append(value)

        if len(result) >= 3:
            break

    return result


def verified_chess_themes(
    analysis: dict[str, Any],
) -> list[str]:
    """Return only tactic labels calculated from legal engine moves."""
    merged = [
        *normalize_chess_themes(
            analysis.get(
                "opponent_reply_verified_themes"
            )
        ),
        *normalize_chess_themes(
            analysis.get(
                "best_move_verified_themes"
            )
        ),
    ]
    merged_set = set(merged)

    # Rank the two engine-verified sources together. Otherwise a secondary
    # opponent-reply label can bury a more important missed material win.
    return normalize_chess_themes([
        theme
        for theme in THEME_PRIORITY
        if theme in merged_set
    ])


def supported_chess_themes(
    analysis: dict[str, Any],
    model_themes: Any,
) -> list[str]:
    """Reject model-created versions of mechanically verifiable labels."""
    verified = verified_chess_themes(
        analysis
    )
    verified_set = set(verified)
    model_supported = [
        theme
        for theme in normalize_chess_themes(
            model_themes
        )
        if (
            theme not in VERIFIER_CONTROLLED_THEMES
            or theme in verified_set
        )
    ]

    return normalize_chess_themes([
        *verified,
        *model_supported,
    ])


def unverified_tactical_claims(
    text: str,
    analysis: dict[str, Any],
) -> list[str]:
    """Find concrete tactic names contradicted by the move verifier."""
    if not text:
        return []

    verified = set(
        verified_chess_themes(
            analysis
        )
    )
    claims: list[str] = []

    for theme, patterns in VERIFIED_THEME_CLAIM_PATTERNS.items():
        accepted = {theme}

        # Underpromotion is also a promotion, so the general word is valid
        # whenever the more specific verified label is present.
        if theme == "Promotion":
            accepted.add("Underpromotion")

        if verified.intersection(accepted):
            continue

        if any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        ):
            claims.append(theme)

    return claims


def ensure_primary_theme_named(
    feedback: str,
    themes: list[str],
    language: str,
) -> str:
    """Guarantee that a confirmed structured theme is also spoken aloud."""
    if not feedback or not themes:
        return feedback

    primary = themes[0]
    normalized_feedback = feedback.lower().replace(
        "-",
        " ",
    )

    if language == "zh-CN":
        label = CHINESE_THEME_LABELS.get(
            primary,
            primary,
        )
        if (
            label in feedback
            or primary.lower() in normalized_feedback
        ):
            return feedback

        return f"这里的关键主题是{label}。{feedback}"

    aliases = {
        primary.lower().replace("-", " "),
    }

    if "/" in primary:
        aliases.update(
            part.strip().lower()
            for part in primary.split("/")
        )

    if any(
        alias and alias in normalized_feedback
        for alias in aliases
    ):
        return feedback

    return (
        f"The key pattern here is {primary.lower()}. "
        f"{feedback}"
    )


COACH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "feedback": {"type": "string"},
        "lesson": {"type": "string"},
        "question": {"type": "string"},
        "themes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": list(CHESS_THEME_TERMS),
            },
            "maxItems": 3,
        },
    },
    "required": [
        "title",
        "feedback",
        "lesson",
        "question",
        "themes",
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
        "target": "8-15 words",
        "max_output_tokens": 220,
        "line_plies": 6,
        "instruction": """
COACH DETAIL LEVEL: QUICK

Use 1 short sentence, roughly 8-15 words total.

Give the concrete chess reason, not merely a verdict.
Name the key forcing reply or consequence when one exists.
Keep lesson and question empty unless either is essential.
""".strip(),
    },

    "balanced": {
        "target": "18-30 words",
        "max_output_tokens": 360,
        "line_plies": 10,
        "instruction": """
COACH DETAIL LEVEL: BALANCED

Use at most 2 natural sentences, roughly 18-30 words total.

Explain:
1. what specifically changed or became vulnerable after the student's move,
2. the important consequence or why the recommended move works better.

Include a reusable thinking habit only when it is specific to this position.
""".strip(),
    },

    "deep": {
        "target": "30-50 words",
        "max_output_tokens": 520,
        "line_plies": 14,
        "instruction": """
COACH DETAIL LEVEL: DEEP

Use at most 3 concise sentences, roughly 30-50 words total.

Explain the causal chess story:
- what the student's move changed,
- the concrete tactical or positional consequence,
- the important engine continuation when it genuinely teaches the idea,
- why the recommended move works,
- one reusable lesson.

Deep means more chess insight, not a lecture.
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
            "opponent_reply_context": analysis.get(
                "opponent_reply_context",
                {},
            ),
            "best_move_verified_themes": analysis.get(
                "best_move_verified_themes",
                [],
            ),
            "opponent_reply_verified_themes": analysis.get(
                "opponent_reply_verified_themes",
                [],
            ),
            "best_move_verified_theme_evidence": analysis.get(
                "best_move_verified_theme_evidence",
                [],
            ),
            "opponent_reply_verified_theme_evidence": analysis.get(
                "opponent_reply_verified_theme_evidence",
                [],
            ),
            "best_move_facts": analysis.get(
                "best_move_facts",
                {},
            ),
            "opponent_reply_facts": analysis.get(
                "opponent_reply_facts",
                {},
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
            )[: int(detail_config["line_plies"])],
            "refutation_line": analysis.get(
                "refutation_line",
                [],
            )[: int(detail_config["line_plies"])],
            "theme_hint": analysis.get(
                "theme_hint"
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

        def request_data(
            correction: str = "",
        ) -> dict[str, Any]:
            response = self.client.responses.create(
                model=self.model,

                instructions=(
                    combined_instructions
                    + correction
                ),

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
                parsed = json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Coach returned invalid JSON."
                ) from error

            if not isinstance(parsed, dict):
                raise ValueError(
                    "Coach returned an invalid response object."
                )

            return parsed

        data = request_data()

        def claim_text(
            value: dict[str, Any],
        ) -> str:
            return " ".join(
                str(value.get(field, ""))
                for field in (
                    "title",
                    "feedback",
                    "lesson",
                    "question",
                )
            )

        unsupported_claims = (
            unverified_tactical_claims(
                claim_text(data),
                analysis,
            )
        )

        if unsupported_claims:
            labels = ", ".join(
                unsupported_claims
            )
            data = request_data(
                "\n\nCORRECTION REQUIRED: Your previous draft named "
                f"unsupported tactical labels ({labels}). The deterministic "
                "verified-theme lists do not contain those labels. Rewrite "
                "all fields without those claims. Describe only the concrete "
                "engine moves and consequences supplied in the input."
            )

            unsupported_claims = (
                unverified_tactical_claims(
                    claim_text(data),
                    analysis,
                )
            )

        if unsupported_claims:
            raise ValueError(
                "Coach repeated an unverified tactical claim: "
                + ", ".join(
                    unsupported_claims
                )
            )

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

        themes = supported_chess_themes(
            analysis,
            data.get("themes"),
        )

        feedback = ensure_primary_theme_named(
            feedback,
            themes,
            normalized_language,
        )

        if not feedback:
            raise ValueError(
                "Coach returned empty feedback."
            )

        return {
            "title": title,
            "feedback": feedback,
            "lesson": lesson,
            "question": question,
            "themes": themes,
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
            "attacked_target_details": position.get(
                "attacked_target_details",
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
            "threat_is_capture": position.get(
                "threat_is_capture"
            ),
            "threat_gives_check": position.get(
                "threat_gives_check"
            ),
            "threat_is_mate": position.get(
                "threat_is_mate"
            ),
            "threat_mate_in": position.get(
                "threat_mate_in"
            ),
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
- attacked_target_details
- threat_move / threat_line
- in_check
- FEN

Never invent a pin, target, threat, or plan.

If threat_is_mate is true, the forced checkmate threat outranks every other
idea. Ask directly what checkmate the opponent is threatening or how soon it
lands. Do not dilute it with a pin, material target, or general plan, and do
not reveal Stockfish's defensive move.

An attacked target is not automatically hanging. attacked_target_details tells
you whether that piece is defended and lists legal recaptures after a
hypothetical capture. If legal_recaptures is non-empty, do NOT imply that the
opponent can simply win or take that piece. Describe it only as pressure unless
threat_move and threat_line prove a concrete tactic beyond the recapture.

Only ask about a specific capture as an immediate threat when threat_move is
that capture and threat_line supports the consequence. Otherwise ask what the
opponent's move pressures, prepares, pins, or improves.

If threat_is_mate is true, ask about the checkmate threat first.
Otherwise, if newly_pinned_squares is non-empty, prefer asking about the new pin.
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
