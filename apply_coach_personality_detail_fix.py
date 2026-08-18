#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path.cwd()

APP = ROOT / "server" / "app.py"
LLM = ROOT / "server" / "coach" / "llm_coach.py"
PROMPT = ROOT / "server" / "coach" / "prompts" / "kid_coach_prompt.txt"
COACH_TS = ROOT / "src" / "coach.ts"
APP_TSX = ROOT / "src" / "App.tsx"

FILES = [APP, LLM, PROMPT, COACH_TS, APP_TSX]

LLM_CONTENT = 'from __future__ import annotations\n\nimport json\nimport os\nfrom pathlib import Path\nfrom typing import Any\n\nfrom openai import OpenAI\n\n\nPROMPT_PATH = (\n    Path(__file__).resolve().parent\n    / "prompts"\n    / "kid_coach_prompt.txt"\n)\n\n\nCOACH_RESPONSE_SCHEMA = {\n    "type": "object",\n    "properties": {\n        "title": {"type": "string"},\n        "feedback": {"type": "string"},\n        "lesson": {"type": "string"},\n        "question": {"type": "string"},\n    },\n    "required": [\n        "title",\n        "feedback",\n        "lesson",\n        "question",\n    ],\n    "additionalProperties": False,\n}\n\n\nCOACH_DETAIL_CONFIG = {\n    "quick": {\n        "target": "15-25 words",\n        "max_output_tokens": 220,\n        "instruction": """\nCOACH DETAIL LEVEL: QUICK\n\nUse 1-2 short sentences, roughly 15-25 words total.\n\nGive the concrete chess reason, not merely a verdict.\nIf there is a forcing reply, name the important reply or consequence.\nDo not add a generic lesson just to fill space.\n""".strip(),\n    },\n\n    "balanced": {\n        "target": "35-55 words",\n        "max_output_tokens": 360,\n        "instruction": """\nCOACH DETAIL LEVEL: BALANCED\n\nUse 2-3 natural sentences, roughly 35-55 words total.\n\nExplain:\n1. what specifically changed or became vulnerable after the student\'s move,\n2. how the opponent can exploit it or what opportunity was missed,\n3. why the recommended move handles the position better.\n\nInclude a reusable thinking habit only when it is specific to this position.\n""".strip(),\n    },\n\n    "deep": {\n        "target": "60-90 words",\n        "max_output_tokens": 520,\n        "instruction": """\nCOACH DETAIL LEVEL: DEEP\n\nUse 3-5 concise sentences, roughly 60-90 words total.\n\nExplain the causal chess story:\n- what the student\'s move changed,\n- the concrete tactical or positional consequence,\n- the important engine continuation when it genuinely teaches the idea,\n- why the recommended move works,\n- one reusable lesson.\n\nDeep means more chess insight, not filler.\n""".strip(),\n    },\n}\n\n\nLANGUAGE_INSTRUCTIONS = {\n    "en": (\n        "COACH LANGUAGE: English. "\n        "Use natural, conversational English that sounds good aloud. "\n        "Prefer spoken chess language such as \'knight takes g3\' rather than "\n        "only \'Nxg3\', \'knight to f3\' rather than only \'Nf3\', "\n        "\'queen takes d5, check\' rather than only \'Qxd5+\', and "\n        "\'castles kingside\' rather than only \'O-O\'. "\n        "Standard notation may appear in parentheses when it genuinely helps."\n    ),\n\n    "zh-CN": (\n        "COACH LANGUAGE: Simplified Chinese (简体中文). "\n        "Use natural, conversational Mandarin that sounds good aloud. "\n        "Prefer spoken chess language such as \'马吃 g3\' rather than only "\n        "\'Nxg3\', \'马走到 f3\' rather than only \'Nf3\', "\n        "\'后吃 d5，将军\' rather than only \'Qxd5+\', and "\n        "\'王翼易位\' rather than only \'O-O\'. "\n        "Standard notation may appear in parentheses when useful. "\n        "Do not mix unnecessary English explanations into Chinese."\n    ),\n}\n\n\nclass LLMCoach:\n    """\n    Converts deterministic Stockfish facts into useful coaching language.\n\n    Stockfish remains the authority for chess facts.\n    The LLM explains those facts and adds conversational teaching style.\n    """\n\n    def __init__(\n        self,\n        model: str | None = None,\n    ) -> None:\n        if not PROMPT_PATH.is_file():\n            raise FileNotFoundError(\n                f"Coach prompt not found: {PROMPT_PATH}"\n            )\n\n        self.client = OpenAI()\n\n        self.model = model or os.getenv(\n            "OPENAI_MODEL",\n            "gpt-4.1-mini",\n        )\n\n        self.instructions = PROMPT_PATH.read_text(\n            encoding="utf-8"\n        ).strip()\n\n    def create_feedback(\n        self,\n        analysis: dict[str, Any],\n        detail: str = "balanced",\n        language: str = "en",\n        recent_feedback: list[str] | None = None,\n    ) -> dict[str, Any]:\n        normalized_detail = str(\n            detail\n        ).strip().lower()\n\n        if normalized_detail not in COACH_DETAIL_CONFIG:\n            normalized_detail = "balanced"\n\n        detail_config = COACH_DETAIL_CONFIG[\n            normalized_detail\n        ]\n\n        normalized_language = (\n            "zh-CN"\n            if str(language).strip().lower()\n            in {\n                "zh",\n                "zh-cn",\n                "zh_cn",\n                "chinese",\n                "mandarin",\n                "simplified chinese",\n            }\n            else "en"\n        )\n\n        recent = [\n            str(item).strip()\n            for item in (recent_feedback or [])\n            if str(item).strip()\n        ][-4:]\n\n        payload = {\n            "fen_before": analysis.get(\n                "fen_before"\n            ),\n            "fen_after": analysis.get(\n                "fen_after"\n            ),\n            "move_number": analysis.get(\n                "move_number"\n            ),\n            "color": analysis.get(\n                "color"\n            ),\n            "played_move": analysis.get(\n                "played_move"\n            ),\n            "played_move_uci": analysis.get(\n                "played_move_uci"\n            ),\n            "best_move": analysis.get(\n                "best_move"\n            ),\n            "best_move_uci": analysis.get(\n                "best_move_uci"\n            ),\n            "opponent_reply": analysis.get(\n                "opponent_reply"\n            ),\n            "opponent_reply_uci": analysis.get(\n                "opponent_reply_uci"\n            ),\n            "classification": analysis.get(\n                "classification"\n            ),\n            "centipawn_loss": analysis.get(\n                "centipawn_loss"\n            ),\n            "best_line": analysis.get(\n                "best_line",\n                [],\n            )[:8],\n            "refutation_line": analysis.get(\n                "refutation_line",\n                [],\n            )[:8],\n            "theme_hint": analysis.get(\n                "theme_hint"\n            ),\n            "coach_detail": normalized_detail,\n            "feedback_target": detail_config[\n                "target"\n            ],\n            "language": normalized_language,\n\n            # Short-term memory is used only to avoid sounding repetitive.\n            "recent_feedback": recent,\n        }\n\n        if recent:\n            recent_instruction = (\n                "RECENT COACHING FROM THIS SAME GAME:\\n"\n                + "\\n".join(\n                    f"- {item}"\n                    for item in recent\n                )\n                + "\\n\\n"\n                "Do not reuse the same opener, catchphrase, lesson wording, "\n                "or sentence structure unless repetition is genuinely needed. "\n                "Continue the conversation naturally. If the same weakness "\n                "is recurring, you may briefly connect it to the earlier "\n                "pattern instead of repeating the old explanation."\n            )\n        else:\n            recent_instruction = (\n                "There is no recent coaching context yet. "\n                "Use a natural conversational opening."\n            )\n\n        combined_instructions = (\n            self.instructions\n            + "\\n\\n"\n            + LANGUAGE_INSTRUCTIONS[\n                normalized_language\n            ]\n            + "\\n\\n"\n            + str(\n                detail_config[\n                    "instruction"\n                ]\n            )\n            + "\\n\\n"\n            + recent_instruction\n        )\n\n        response = self.client.responses.create(\n            model=self.model,\n\n            instructions=combined_instructions,\n\n            input=json.dumps(\n                payload,\n                ensure_ascii=False,\n            ),\n\n            text={\n                "format": {\n                    "type": "json_schema",\n                    "name": "chess_coach_feedback",\n                    "strict": True,\n                    "schema": COACH_RESPONSE_SCHEMA,\n                },\n            },\n\n            max_output_tokens=int(\n                detail_config[\n                    "max_output_tokens"\n                ]\n            ),\n\n            store=False,\n        )\n\n        text = response.output_text.strip()\n\n        if not text:\n            raise ValueError(\n                "Coach returned an empty response."\n            )\n\n        try:\n            data = json.loads(text)\n        except json.JSONDecodeError as error:\n            raise ValueError(\n                "Coach returned invalid JSON."\n            ) from error\n\n        title = str(\n            data.get("title", "")\n        ).strip()\n\n        feedback = str(\n            data.get("feedback", "")\n        ).strip()\n\n        lesson = str(\n            data.get("lesson", "")\n        ).strip()\n\n        question = str(\n            data.get("question", "")\n        ).strip()\n\n        if not feedback:\n            raise ValueError(\n                "Coach returned empty feedback."\n            )\n\n        return {\n            "title": title,\n            "feedback": feedback,\n            "lesson": lesson,\n            "question": question,\n        }\n'
PROMPT_CONTENT = 'You are Chess Buddy, a calm, sharp, curious chess coach helping a student think better during a real game.\n\nStockfish is the ONLY authority for chess facts.\n\nUse only the supplied:\n- played_move\n- best_move\n- opponent_reply\n- centipawn_loss\n- classification\n- best_line\n- refutation_line\n- theme_hint\n- FEN positions\n- recent_feedback\n\nNever invent a tactic, threat, check, capture, material gain, mate, fork, pin, skewer, positional claim, or continuation that is not supported by the supplied facts, FEN, or engine lines.\n\nCORE RULE: CONCRETE BEFORE CONCISE\n\nNever shorten the explanation so much that the actual chess reason disappears.\n\nFor a mistake or blunder, try to answer the causal chess story:\n1. What specifically changed or became wrong after the student\'s move?\n2. What concrete opponent reply, threat, weakness, or missed opportunity makes that matter?\n3. Why does the recommended move solve the problem or create a better idea?\n\nWhen the engine line clearly demonstrates the point, use a short part of that line naturally.\n\nDo NOT merely say:\n- "more precise"\n- "more active"\n- "better"\n- "keeps the position healthier"\n- "look for forcing moves"\n- "scan checks, captures, and threats"\n\nunless you immediately explain exactly what that means in THIS position.\n\nIf the engine data does not support a precise tactical or positional explanation, make a narrower claim rather than guessing.\n\nPERSONALITY\n\nSound like a real coach sitting beside the student:\n- calm\n- observant\n- curious\n- encouraging\n- occasionally playful, but never goofy\n- never robotic\n- never lecture-y\n\nTalk about the position, not the engine score.\n\nDo not begin every response with the move classification.\nDo not repeatedly use "Great move", "Nice move", "Worth a look", "Remember", or any other stock opener.\nVary sentence rhythm and wording naturally.\n\nPraise thinking habits and recovery, not raw engine agreement.\n\nA serious mistake should sound calm and useful, not dramatic or shaming.\n\nRECENT CONVERSATION\n\nrecent_feedback contains up to four recent coaching messages from this same game.\n\nUse it as short-term conversational memory.\n\nAvoid repeating:\n- the same opening phrase\n- the same generic lesson\n- the same sentence structure\n- the same catchphrase\n\nIf the current mistake repeats an earlier weakness, you may connect the moments naturally, for example by saying that the same piece-safety issue is showing up again. Do this only when the supplied facts support the connection.\n\nTEACHING\n\nPrefer one strong lesson over a list of weak observations.\n\nFor tactical mistakes, explain the concrete tactic or forcing continuation if supported.\n\nFor positional mistakes, explain the specific piece, square, weakness, king-safety issue, or plan involved. Do not hide behind vague words like "positionally better."\n\nIf the recommended move is strong because it prevents something, say what it prevents when the engine data supports that.\n\nIf the recommended move creates a threat or improves a piece, explain the concrete purpose.\n\nQUESTIONS\n\nThe "question" field is optional teaching support.\n\nUse it only when asking a specific question would improve the learning moment.\n\nGood questions refer to this exact position, such as:\n- what became undefended?\n- what forcing reply does the opponent have?\n- which piece was doing an important defensive job?\n- what changed after the move?\n\nDo not automatically ask "checks, captures, and threats?" after every mistake.\n\nLANGUAGE\n\nRespond entirely in the requested language.\n\nFor zh-CN:\n- use natural conversational Simplified Chinese\n- keep the chess idea clear when spoken aloud\n- avoid unnecessary English except standard notation when useful\n\nFor en:\n- use natural conversational English\n\nOUTPUT\n\nReturn valid JSON only:\n\n{\n  "title": "short natural headline",\n  "feedback": "the main coaching explanation",\n  "lesson": "one specific reusable habit, or empty string",\n  "question": "one useful position-specific question, or empty string"\n}\n\nDo not repeat the same idea across feedback, lesson, and question.\nDo not mention centipawns or engine evaluation numbers in user-facing fields.\n'
COACH_TS_CONTENT = "export type CoachArrow = {\n  from: string;\n  to: string;\n  kind?: 'best' | 'danger' | 'idea';\n};\n\nexport type CoachResult = {\n  shouldCoach: boolean;\n  moveNumber: number;\n  ply: number;\n  playedMove: string;\n  playedMoveUci: string;\n  classification: 'good' | 'inaccuracy' | 'mistake' | 'blunder';\n  centipawnLoss: number;\n  bestMove: string;\n  bestMoveUci: string;\n  opponentReply?: string;\n  opponentReplyUci?: string;\n  evaluationBefore?: number;\n  evaluationAfter?: number;\n\n  engineDiagnostics?: {\n    budgetMs?: number;\n    bestSearch?: {\n      depth?: number;\n      seldepth?: number;\n      nodes?: number;\n      nps?: number;\n      timeMs?: number;\n      hashfull?: number;\n    };\n    playedSearch?: {\n      depth?: number;\n      seldepth?: number;\n      nodes?: number;\n      nps?: number;\n      timeMs?: number;\n      hashfull?: number;\n      reusedBestSearch?: boolean;\n    };\n  };\n\n  fenBefore: string;\n  fenAfter: string;\n\n  feedback: string;\n  title: string;\n  lesson?: string;\n  question?: string;\n\n  arrows?: CoachArrow[];\n  highlightsBefore?: string[];\n  highlightsAfter?: string[];\n\n  themeHint?: string;\n  bestLine?: string[];\n  refutationLine?: string[];\n\n  // Two-phase coaching:\n  // Stockfish returns immediately, then the LLM wording arrives separately.\n  analysisId?: string;\n  explanationPending?: boolean;\n};\n\nexport type CoachDetail =\n  | 'quick'\n  | 'balanced'\n  | 'deep';\n\nexport type CoachLanguage =\n  | 'en'\n  | 'zh-CN';\n\nexport type CoachWording = {\n  title: string;\n  feedback: string;\n  lesson: string;\n  question: string;\n};\n\nconst CONTROL_URL =\n  import.meta.env.VITE_BOT_CONTROL_URL ||\n  'http://127.0.0.1:8765';\n\n\nexport async function analyzeMove(\n  fen: string,\n  move: string,\n  detailOrSignal: CoachDetail | AbortSignal = 'balanced',\n  maybeSignal?: AbortSignal,\n  language: CoachLanguage = 'en',\n): Promise<CoachResult> {\n  const detail: CoachDetail =\n    typeof detailOrSignal === 'string'\n      ? detailOrSignal\n      : 'balanced';\n\n  const signal =\n    typeof detailOrSignal === 'string'\n      ? maybeSignal\n      : detailOrSignal;\n\n  const response = await fetch(\n    `${CONTROL_URL}/api/coach/analyze`,\n    {\n      method: 'POST',\n      headers: {\n        'Content-Type': 'application/json',\n      },\n      body: JSON.stringify({\n        fen,\n        move,\n        detail,\n        language,\n      }),\n      signal,\n    },\n  );\n\n  const data = await response\n    .json()\n    .catch(() => ({}));\n\n  if (!response.ok) {\n    throw new Error(\n      data.message ||\n      `${response.status} ${response.statusText}`,\n    );\n  }\n\n  return data as CoachResult;\n}\n\n\n/**\n * Fetch conversational wording for a Stockfish analysis already cached\n * by the backend. This request does not run Stockfish again.\n */\nexport async function explainMove(\n  analysisId: string,\n  detail: CoachDetail = 'balanced',\n  language: CoachLanguage = 'en',\n  recentFeedback: string[] = [],\n  signal?: AbortSignal,\n): Promise<CoachWording> {\n  const response = await fetch(\n    `${CONTROL_URL}/api/coach/explain`,\n    {\n      method: 'POST',\n      headers: {\n        'Content-Type': 'application/json',\n      },\n      body: JSON.stringify({\n        analysisId,\n        detail,\n        language,\n        recentFeedback,\n      }),\n      signal,\n    },\n  );\n\n  const data = await response\n    .json()\n    .catch(() => ({}));\n\n  if (!response.ok) {\n    throw new Error(\n      data.message ||\n      `${response.status} ${response.statusText}`,\n    );\n  }\n\n  return data as CoachWording;\n}\n"
STRICT_LLM_FUNCTION = 'def generate_llm_coaching(\n    analysis: dict[str, Any],\n    detail: str = "balanced",\n    language: str = "en",\n    recent_feedback: list[str] | None = None,\n) -> dict[str, Any]:\n    """\n    Generate real LLM wording.\n\n    Important: this function never silently substitutes canned coaching.\n    If the LLM is unavailable, the caller receives an error and the\n    frontend can honestly show that the explanation did not load.\n    """\n\n    if not os.environ.get(\n        "OPENAI_API_KEY",\n        "",\n    ).strip():\n        raise RuntimeError(\n            "OPENAI_API_KEY is not configured."\n        )\n\n    try:\n        with _llm_lock:\n            result = get_llm_coach().create_feedback(\n                analysis,\n                detail=detail,\n                language=language,\n                recent_feedback=recent_feedback or [],\n            )\n\n        print(\n            "[COACH LLM] success "\n            f"move={analysis.get(\'played_move_uci\', \'\')} "\n            f"detail={detail} "\n            f"language={normalize_language(language)}",\n            flush=True,\n        )\n\n        return result\n\n    except Exception as exc:\n        print(\n            "[COACH LLM] failed "\n            f"move={analysis.get(\'played_move_uci\', \'\')}: "\n            f"{exc}",\n            flush=True,\n        )\n\n        raise RuntimeError(\n            f"AI coach explanation failed: {exc}"\n        ) from exc\n\n\n'
NEW_ANALYSIS_BLOCK = 'def analyze_move(\n    payload: dict[str, Any],\n) -> dict[str, Any]:\n    fen = str(\n        payload.get(\n            "fen",\n            "",\n        )\n    ).strip()\n\n    move_uci = str(\n        payload.get(\n            "move",\n            "",\n        )\n    ).strip().lower()\n\n    language = normalize_language(\n        payload.get(\n            "language",\n            "en",\n        )\n    )\n\n    detail = str(\n        payload.get(\n            "detail",\n            "balanced",\n        )\n    ).strip().lower()\n\n    if detail not in {\n        "quick",\n        "balanced",\n        "deep",\n    }:\n        detail = "balanced"\n\n    if not fen or not move_uci:\n        raise ValueError(\n            "fen and move are required"\n        )\n\n    try:\n        board = chess.Board(fen)\n    except ValueError as exc:\n        raise ValueError(\n            "Invalid FEN."\n        ) from exc\n\n    try:\n        move = chess.Move.from_uci(\n            move_uci\n        )\n    except ValueError as exc:\n        raise ValueError(\n            "Invalid UCI move."\n        ) from exc\n\n    if move not in board.legal_moves:\n        raise ValueError(\n            "Move is not legal in the supplied position."\n        )\n\n    with _analyzer_lock:\n        try:\n            analysis = (\n                get_analyzer()\n                .analyze_move(\n                    board,\n                    move,\n                )\n                .to_dict()\n            )\n\n        except (\n            chess.engine.EngineError,\n            chess.engine.EngineTerminatedError,\n            BrokenPipeError,\n        ):\n            reset_analyzer()\n\n            analysis = (\n                get_analyzer()\n                .analyze_move(\n                    board,\n                    move,\n                )\n                .to_dict()\n            )\n\n    should_coach = (\n        int(\n            analysis[\n                "centipawn_loss"\n            ]\n        )\n        >= MISTAKE_THRESHOLD_CP\n    )\n\n    result: dict[str, Any] = {\n        "shouldCoach": should_coach,\n        "moveNumber": analysis[\n            "move_number"\n        ],\n        "ply": analysis[\n            "ply"\n        ],\n        "playedMove": analysis[\n            "played_move"\n        ],\n        "playedMoveUci": analysis[\n            "played_move_uci"\n        ],\n        "classification": analysis[\n            "classification"\n        ],\n        "centipawnLoss": analysis[\n            "centipawn_loss"\n        ],\n        "bestMove": analysis[\n            "best_move"\n        ],\n        "bestMoveUci": analysis[\n            "best_move_uci"\n        ],\n        "opponentReply": analysis[\n            "opponent_reply"\n        ],\n        "opponentReplyUci": analysis[\n            "opponent_reply_uci"\n        ],\n        "fenBefore": analysis[\n            "fen_before"\n        ],\n        "fenAfter": analysis[\n            "fen_after"\n        ],\n        "bestLine": analysis.get(\n            "best_line",\n            [],\n        ),\n        "refutationLine": analysis.get(\n            "refutation_line",\n            [],\n        ),\n        "themeHint": analysis.get(\n            "theme_hint",\n            "",\n        ),\n        "evaluationBefore": analysis.get(\n            "evaluation_before",\n            0,\n        ),\n        "evaluationAfter": analysis.get(\n            "evaluation_after",\n            0,\n        ),\n        "engineDiagnostics": analysis.get(\n            "engine_diagnostics",\n            {},\n        ),\n    }\n\n    if should_coach:\n        # Cache the deterministic analysis on the server. The second,\n        # asynchronous request uses this ID to generate conversational wording.\n        analysis_id = cache_analysis(\n            analysis\n        )\n\n        # Reuse fallback_coaching ONLY for deterministic visual arrows.\n        # Its canned text is deliberately not returned as the AI explanation.\n        visual = fallback_coaching(\n            analysis,\n            language=language,\n        )\n\n        result.update({\n            "analysisId": analysis_id,\n            "explanationPending": True,\n            "title": (\n                "关键失误"\n                if (\n                    language == "zh-CN"\n                    and analysis["classification"] == "blunder"\n                )\n                else "值得看一看"\n                if language == "zh-CN"\n                else "Critical miss"\n                if analysis["classification"] == "blunder"\n                else "Worth a look"\n            ),\n            "feedback": "",\n            "lesson": "",\n            "question": "",\n            "arrows": visual.get(\n                "arrows",\n                [],\n            ),\n            "highlightsBefore": visual.get(\n                "highlightsBefore",\n                [],\n            ),\n            "highlightsAfter": visual.get(\n                "highlightsAfter",\n                [],\n            ),\n        })\n\n    else:\n        cp_loss = int(\n            analysis[\n                "centipawn_loss"\n            ]\n        )\n\n        if cp_loss < 35:\n            result.update({\n                "title": (\n                    "稳健"\n                    if language == "zh-CN"\n                    else "Solid"\n                ),\n                "feedback": "",\n                "lesson": "",\n                "question": "",\n                "arrows": [],\n                "highlightsBefore": [],\n                "highlightsAfter": [],\n                "explanationPending": False,\n            })\n\n        else:\n            result.update({\n                "title": (\n                    "再看一眼"\n                    if language == "zh-CN"\n                    else "Worth a look"\n                ),\n                "feedback": "",\n                "lesson": "",\n                "question": "",\n                "arrows": [],\n                "highlightsBefore": [],\n                "highlightsAfter": [],\n                "explanationPending": False,\n            })\n\n    return result\n\n\ndef explain_analysis(\n    payload: dict[str, Any],\n) -> dict[str, Any]:\n    analysis_id = str(\n        payload.get(\n            "analysisId",\n            "",\n        )\n    ).strip()\n\n    if not analysis_id:\n        raise ValueError(\n            "analysisId is required"\n        )\n\n    analysis = get_cached_analysis(\n        analysis_id\n    )\n\n    if analysis is None:\n        raise ValueError(\n            "The cached coach analysis expired. "\n            "Please analyze the move again."\n        )\n\n    detail = str(\n        payload.get(\n            "detail",\n            "balanced",\n        )\n    ).strip().lower()\n\n    if detail not in {\n        "quick",\n        "balanced",\n        "deep",\n    }:\n        detail = "balanced"\n\n    language = normalize_language(\n        payload.get(\n            "language",\n            "en",\n        )\n    )\n\n    raw_recent = payload.get(\n        "recentFeedback",\n        [],\n    )\n\n    recent_feedback: list[str] = []\n\n    if isinstance(\n        raw_recent,\n        list,\n    ):\n        for item in raw_recent[-4:]:\n            value = str(\n                item\n            ).strip()\n\n            if value:\n                recent_feedback.append(\n                    value[:600]\n                )\n\n    return generate_llm_coaching(\n        analysis,\n        detail=detail,\n        language=language,\n        recent_feedback=recent_feedback,\n    )\n\n\n'
ROUTE_BLOCK = '            elif self.path == "/api/coach/analyze":\n                self._send(\n                    200,\n                    analyze_move(\n                        self._json_body()\n                    ),\n                )\n            elif self.path == "/api/coach/explain":\n                self._send(\n                    200,\n                    explain_analysis(\n                        self._json_body()\n                    ),\n                )\n            else:\n                self._send(404, {"message": "Not found"})\n'


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def backup(path: Path) -> None:
    backup_path = path.with_name(
        path.name + ".before-personality-fix"
    )

    if not backup_path.exists():
        shutil.copy2(
            path,
            backup_path,
        )


def regex_replace_once(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    next_text, count = re.subn(
        pattern,
        lambda _match: replacement,
        text,
        count=1,
        flags=re.S,
    )

    if count != 1:
        fail(
            f"{label}: expected one match, found {count}."
        )

    return next_text


def replace_once(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = text.count(old)

    if count != 1:
        fail(
            f"{label}: expected one match, found {count}."
        )

    return text.replace(
        old,
        new,
        1,
    )


for path in FILES:
    if not path.is_file():
        fail(
            "Run this script from the ai-chess-coach repo root. "
            f"Missing: {path}"
        )

for path in FILES:
    backup(path)


# ---------------------------------------------------------------------
# 1. LLM layer: richer explanations + short-term anti-repetition memory
# ---------------------------------------------------------------------

LLM.write_text(
    LLM_CONTENT,
    encoding="utf-8",
)

PROMPT.write_text(
    PROMPT_CONTENT,
    encoding="utf-8",
)

COACH_TS.write_text(
    COACH_TS_CONTENT,
    encoding="utf-8",
)


# ---------------------------------------------------------------------
# 2. Backend: make analysisId actually work and never disguise an LLM
#    failure as canned AI coaching.
# ---------------------------------------------------------------------

app_text = APP.read_text(
    encoding="utf-8"
)

app_text = regex_replace_once(
    app_text,
    r"def coach_payload\(.*?(?=def synthesize_speech\()",
    STRICT_LLM_FUNCTION,
    "replace coach_payload",
)

app_text = regex_replace_once(
    app_text,
    r"def analyze_move\(.*?(?=class Handler\(BaseHTTPRequestHandler\):)",
    NEW_ANALYSIS_BLOCK,
    "replace analyze/explain block",
)

app_text = regex_replace_once(
    app_text,
    r'            elif self\.path == "/api/coach/analyze":.*?            else:\n                self\._send\(404, \{"message": "Not found"\}\)\n',
    ROUTE_BLOCK,
    "clean coach routes",
)

APP.write_text(
    app_text,
    encoding="utf-8",
)


# ---------------------------------------------------------------------
# 3. Frontend: remember recent real AI coaching so the next explanation
#    can avoid repeating itself.
# ---------------------------------------------------------------------

tsx = APP_TSX.read_text(
    encoding="utf-8"
)

tsx = replace_once(
    tsx,
    """  const lastPraisePlyRef = useRef<number | null>(null);
""",
    """  const lastPraisePlyRef = useRef<number | null>(null);

  // Last few REAL LLM explanations from this game.
  // Sent back to the next wording request only to reduce repetition.
  const recentCoachFeedbackRef = useRef<string[]>([]);
""",
    "add recent coach feedback ref",
)

tsx = replace_once(
    tsx,
    """    lastPraisePlyRef.current = null;
    setCoachResult(null);
""",
    """    lastPraisePlyRef.current = null;
    recentCoachFeedbackRef.current = [];
    setCoachResult(null);
""",
    "reset recent coach feedback",
)

# Praise should be occasional, not every few good moves.
tsx = replace_once(
    tsx,
    """            const streak =
              goodMoveRunRef.current >= 3 &&
              goodMoveRunRef.current % 3 === 0;
""",
    """            const streak =
              goodMoveRunRef.current >= 4 &&
              goodMoveRunRef.current % 4 === 0;
""",
    "reduce praise frequency",
)

tsx = replace_once(
    tsx,
    """            const praiseIsSpacedOut =
              lastPraisePlyRef.current == null ||
              result.ply - lastPraisePlyRef.current >= 4;
""",
    """            const praiseIsSpacedOut =
              lastPraisePlyRef.current == null ||
              result.ply - lastPraisePlyRef.current >= 8;
""",
    "space praise farther apart",
)

tsx = replace_once(
    tsx,
    """            void explainMove(
              result.analysisId,
              coachDetail,
              coachLanguage,
            )
""",
    """            const recentFeedback = [
              ...recentCoachFeedbackRef.current,
            ];

            void explainMove(
              result.analysisId,
              coachDetail,
              coachLanguage,
              recentFeedback,
            )
""",
    "pass recent feedback to LLM",
)

tsx = replace_once(
    tsx,
    """                // Voice waits for the useful explanation instead of reading
                // the temporary "checking" message aloud.
                speak(enriched.feedback);
""",
    """                const memoryEntry = [
                  wording.feedback,
                  wording.lesson,
                ]
                  .filter(Boolean)
                  .join(' ')
                  .trim();

                if (memoryEntry) {
                  recentCoachFeedbackRef.current = [
                    ...recentCoachFeedbackRef.current,
                    memoryEntry,
                  ].slice(-4);
                }

                // Voice waits for the real LLM explanation.
                speak(enriched.feedback);
""",
    "remember successful LLM wording",
)

old_failure = """              .catch((error) => {
                if (!isAbortError(error)) {
                  console.warn(
                    'Coach wording unavailable:',
                    error,
                  );
                }
              });
          } else {
            // Backward compatibility if the backend has not yet been updated
            // to two-phase coaching.
            saveNote(result);
            setCoachResult(result);
            speak(result.feedback);
          }
"""

new_failure = """              .catch((error) => {
                if (isAbortError(error)) {
                  return;
                }

                console.warn(
                  'Coach wording unavailable:',
                  error,
                );

                const unavailable: CoachResult = {
                  ...fastResult,
                  explanationPending: false,
                  title:
                    coachLanguage === 'zh-CN'
                      ? '解释暂时不可用'
                      : 'Explanation unavailable',
                  feedback:
                    coachLanguage === 'zh-CN'
                      ? `棋局分析已经完成，建议走 ${result.bestMove}，但 AI 解释这次没有加载成功。`
                      : `The chess analysis is ready and the suggested move is ${result.bestMove}, but the AI explanation did not load.`,
                  lesson: '',
                  question: '',
                };

                saveNote(unavailable);

                setCoachResult((current) =>
                  current?.ply === unavailable.ply
                    ? unavailable
                    : current,
                );

                // Deliberately do NOT speak a canned replacement.
              });
          } else {
            console.error(
              'Coach backend returned a coaching moment without analysisId. ' +
              'The frontend/backend versions are out of sync.',
            );

            const unavailable: CoachResult = {
              ...fastResult,
              explanationPending: false,
              title:
                coachLanguage === 'zh-CN'
                  ? '解释连接错误'
                  : 'Explanation connection error',
              feedback:
                coachLanguage === 'zh-CN'
                  ? '棋局分析完成了，但 AI 解释接口没有正确连接。'
                  : 'The chess analysis completed, but the AI explanation endpoint is not connected correctly.',
              lesson: '',
              question: '',
            };

            saveNote(unavailable);
            setCoachResult(unavailable);
          }
"""

tsx = replace_once(
    tsx,
    old_failure,
    new_failure,
    "replace fallback-masking behavior",
)

APP_TSX.write_text(
    tsx,
    encoding="utf-8",
)


print("Applied Chess Buddy personality/detail fix.")
print()
print("Changed:")
print("  - server/app.py")
print("  - server/coach/llm_coach.py")
print("  - server/coach/prompts/kid_coach_prompt.txt")
print("  - src/coach.ts")
print("  - src/App.tsx")
print()
print("Backups end in .before-personality-fix")
print()
print("Now run:")
print(
    "python -m py_compile "
    "server/app.py server/coach/llm_coach.py"
)
print("npm run build")
