#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path.cwd()

TARGETS = [
    ROOT / "server" / "coach" / "stockfish_analyzer.py",
    ROOT / "server" / "bot_runtime.py",
    ROOT / "server" / "app.py",
    ROOT / "src" / "coach.ts",
    ROOT / "src" / "App.tsx",
]

NEW_STOCKFISH = 'from __future__ import annotations\n\nimport os\nimport shutil\nfrom dataclasses import asdict, dataclass\nfrom pathlib import Path\nfrom typing import Any\n\nimport chess\nimport chess.engine\n\n\n@dataclass\nclass MoveAnalysis:\n    move_number: int\n    ply: int\n    color: str\n    played_move: str\n    played_move_uci: str\n    best_move: str\n    best_move_uci: str\n    opponent_reply: str\n    opponent_reply_uci: str\n    evaluation_before: int\n    evaluation_after: int\n    centipawn_loss: int\n    classification: str\n    best_line: list[str]\n    refutation_line: list[str]\n    fen_before: str\n    fen_after: str\n    theme_hint: str\n    engine_diagnostics: dict[str, Any]\n\n    def to_dict(self) -> dict[str, Any]:\n        return asdict(self)\n\n\nMANAGED_ENGINE_OPTIONS = {"Ponder", "MultiPV", "UCI_Chess960", "UCI_Variant"}\n\n\ndef configure_supported_options(\n    engine: chess.engine.SimpleEngine,\n    requested: dict[str, Any],\n) -> dict[str, Any]:\n    """Configure ordinary UCI options that python-chess does not manage."""\n    safe: dict[str, Any] = {}\n\n    for name, value in requested.items():\n        option = engine.options.get(name)\n        if option is None:\n            continue\n\n        managed = name in MANAGED_ENGINE_OPTIONS\n        is_managed = getattr(option, "is_managed", None)\n\n        if callable(is_managed):\n            try:\n                managed = managed or bool(is_managed())\n            except Exception:\n                pass\n\n        if not managed:\n            safe[name] = value\n\n    if safe:\n        engine.configure(safe)\n\n    return safe\n\n\ndef find_stockfish() -> str:\n    candidates: list[str] = []\n\n    env_path = os.getenv("STOCKFISH_PATH", "").strip()\n    if env_path:\n        candidates.append(env_path)\n\n    which = shutil.which("stockfish")\n    if which:\n        candidates.append(which)\n\n    candidates.extend(\n        [\n            "/opt/homebrew/bin/stockfish",\n            "/usr/local/bin/stockfish",\n            "/usr/bin/stockfish",\n        ]\n    )\n\n    for candidate in candidates:\n        if candidate and Path(candidate).is_file():\n            return str(Path(candidate).resolve())\n\n    raise FileNotFoundError(\n        "Stockfish was not found. On macOS run: brew install stockfish. "\n        "Or set STOCKFISH_PATH=/full/path/to/stockfish."\n    )\n\n\ndef score_cp(score: chess.engine.PovScore, perspective: chess.Color) -> int:\n    value = score.pov(perspective).score(mate_score=20_000)\n    return int(value if value is not None else 0)\n\n\ndef classify_move(cp_loss: int) -> str:\n    if cp_loss < 35:\n        return "good"\n    if cp_loss < 90:\n        return "inaccuracy"\n    if cp_loss < 200:\n        return "mistake"\n    return "blunder"\n\n\ndef pv_to_san(\n    board: chess.Board,\n    moves: list[chess.Move],\n    max_plies: int = 6,\n) -> list[str]:\n    temp = board.copy()\n    result: list[str] = []\n\n    for move in moves[:max_plies]:\n        if move not in temp.legal_moves:\n            break\n\n        result.append(temp.san(move))\n        temp.push(move)\n\n    return result\n\n\ndef infer_theme(\n    board_before: chess.Board,\n    board_after: chess.Board,\n    opponent_reply_san: str,\n) -> str:\n    if opponent_reply_san:\n        if "#" in opponent_reply_san:\n            return "king safety and mating threats"\n        if "+" in opponent_reply_san:\n            return "forcing checks and king safety"\n        if "x" in opponent_reply_san:\n            return "captures, loose pieces, and tactical safety"\n\n    if board_before.fullmove_number <= 10:\n        return "development and king safety"\n\n    if board_after.is_check():\n        return "forcing moves and king safety"\n\n    return "checks, captures, threats, and piece safety"\n\n\ndef info_diagnostics(info: dict[str, Any]) -> dict[str, Any]:\n    elapsed = info.get("time")\n\n    return {\n        "depth": int(info.get("depth") or 0),\n        "seldepth": int(info.get("seldepth") or 0),\n        "nodes": int(info.get("nodes") or 0),\n        "nps": int(info.get("nps") or 0),\n        "timeMs": (\n            int(float(elapsed) * 1000)\n            if isinstance(elapsed, (int, float))\n            else 0\n        ),\n        "hashfull": int(info.get("hashfull") or 0),\n    }\n\n\nclass StockfishAnalyzer:\n    """Reliable live move analysis using same-position comparisons."""\n\n    def __init__(self, time_ms: int = 250) -> None:\n        self.stockfish_path = find_stockfish()\n        self.time_ms = max(200, int(time_ms))\n        self.debug = (\n            os.getenv("COACH_ENGINE_DEBUG", "").strip().lower()\n            in {"1", "true", "yes", "on"}\n        )\n\n        self.engine = chess.engine.SimpleEngine.popen_uci(\n            self.stockfish_path\n        )\n\n        configure_supported_options(\n            self.engine,\n            {"Threads": 1, "Hash": 64},\n        )\n\n    def close(self) -> None:\n        try:\n            self.engine.quit()\n        except Exception:\n            try:\n                self.engine.close()\n            except Exception:\n                pass\n\n    def analyze_move(\n        self,\n        board_before: chess.Board,\n        played_move: chess.Move,\n    ) -> MoveAnalysis:\n        if played_move not in board_before.legal_moves:\n            raise ValueError(f"Illegal move: {played_move.uci()}")\n\n        player = board_before.turn\n        fen_before = board_before.fen()\n        played_san = board_before.san(played_move)\n\n        limit = chess.engine.Limit(\n            time=self.time_ms / 1000.0\n        )\n\n        # Search the original position for Stockfish\'s actual top choice.\n        before_info = self.engine.analyse(\n            board_before,\n            limit,\n        )\n\n        before_score = before_info.get("score")\n        before_pv = list(before_info.get("pv") or [])\n\n        if before_score is None or not before_pv:\n            raise RuntimeError(\n                "Stockfish returned no usable best-move analysis."\n            )\n\n        best_move = before_pv[0]\n\n        if best_move not in board_before.legal_moves:\n            raise RuntimeError(\n                "Stockfish returned an illegal best move."\n            )\n\n        best_san = board_before.san(best_move)\n        eval_before = score_cp(before_score, player)\n        best_line = pv_to_san(board_before, before_pv, 6)\n\n        board_after = board_before.copy()\n        board_after.push(played_move)\n\n        if played_move == best_move:\n            # Reuse the best search instead of running Stockfish again.\n            played_info = before_info\n            played_pv = before_pv\n            eval_played = eval_before\n            cp_loss = 0\n        else:\n            # Compare the student\'s move from the SAME original position.\n            # root_moves forces Stockfish to evaluate that exact move.\n            played_info = self.engine.analyse(\n                board_before,\n                limit,\n                root_moves=[played_move],\n            )\n\n            played_score = played_info.get("score")\n            played_pv = list(played_info.get("pv") or [])\n\n            if (\n                played_score is None\n                or not played_pv\n                or played_pv[0] != played_move\n            ):\n                raise RuntimeError(\n                    "Stockfish returned no usable forced-move analysis."\n                )\n\n            eval_played = score_cp(played_score, player)\n            cp_loss = min(\n                5000,\n                max(0, eval_before - eval_played),\n            )\n\n        continuation = (\n            played_pv[1:]\n            if played_pv and played_pv[0] == played_move\n            else []\n        )\n\n        reply_san = ""\n        reply_uci = ""\n\n        if continuation:\n            reply = continuation[0]\n\n            if reply in board_after.legal_moves:\n                reply_san = board_after.san(reply)\n                reply_uci = reply.uci()\n\n        refutation = pv_to_san(\n            board_after,\n            continuation,\n            6,\n        )\n\n        diagnostics = {\n            "budgetMs": self.time_ms,\n            "bestSearch": info_diagnostics(before_info),\n            "playedSearch": {\n                **info_diagnostics(played_info),\n                "reusedBestSearch": played_move == best_move,\n            },\n        }\n\n        if self.debug:\n            print(\n                "[COACH STOCKFISH]",\n                f"fen={fen_before}",\n                f"played={played_move.uci()}",\n                f"best={best_move.uci()}",\n                f"loss={cp_loss}",\n                f"bestDepth={diagnostics[\'bestSearch\'][\'depth\']}",\n                f"bestNodes={diagnostics[\'bestSearch\'][\'nodes\']}",\n                f"playedDepth={diagnostics[\'playedSearch\'][\'depth\']}",\n                f"playedNodes={diagnostics[\'playedSearch\'][\'nodes\']}",\n                flush=True,\n            )\n\n        return MoveAnalysis(\n            move_number=board_before.fullmove_number,\n            ply=board_before.ply() + 1,\n            color="white" if player == chess.WHITE else "black",\n            played_move=played_san,\n            played_move_uci=played_move.uci(),\n            best_move=best_san,\n            best_move_uci=best_move.uci(),\n            opponent_reply=reply_san,\n            opponent_reply_uci=reply_uci,\n            evaluation_before=eval_before,\n            evaluation_after=eval_played,\n            centipawn_loss=cp_loss,\n            classification=classify_move(cp_loss),\n            best_line=best_line,\n            refutation_line=refutation,\n            fen_before=fen_before,\n            fen_after=board_after.fen(),\n            theme_hint=infer_theme(\n                board_before,\n                board_after,\n                reply_san,\n            ),\n            engine_diagnostics=diagnostics,\n        )\n'
NEW_CHOOSE_MOVE = '    def choose_move(\n        self,\n        board: chess.Board,\n        level: BotLevel,\n    ) -> tuple[chess.Move, int]:\n        legal = list(board.legal_moves)\n\n        if not legal:\n            raise RuntimeError("No legal bot move is available.")\n\n        started = time.perf_counter()\n\n        def pick_with_engine(\n            engine: chess.engine.SimpleEngine,\n        ) -> chess.Move:\n            raw = engine.analyse(\n                board,\n                chess.engine.Limit(\n                    time=max(\n                        0.02,\n                        level.think_ms / 1000.0,\n                    )\n                ),\n                multipv=min(\n                    level.multipv,\n                    len(legal),\n                ),\n            )\n\n            infos = raw if isinstance(raw, list) else [raw]\n            candidates: list[tuple[chess.Move, int]] = []\n\n            for info in infos:\n                pv = info.get("pv") or []\n\n                if not pv:\n                    continue\n\n                candidate = pv[0]\n\n                if candidate in board.legal_moves:\n                    candidates.append(\n                        (\n                            candidate,\n                            self._score(\n                                info,\n                                board.turn,\n                            ),\n                        )\n                    )\n\n            if not candidates:\n                raise RuntimeError(\n                    "Stockfish returned no legal candidate moves."\n                )\n\n            best_score = max(\n                score for _, score in candidates\n            )\n\n            weights: list[float] = []\n\n            for _, score in candidates:\n                loss = min(\n                    1500,\n                    max(0, best_score - score),\n                )\n\n                weights.append(\n                    math.exp(\n                        -loss\n                        / max(\n                            1.0,\n                            level.temperature_cp,\n                        )\n                    )\n                )\n\n            return self._rng.choices(\n                [move for move, _ in candidates],\n                weights=weights,\n                k=1,\n            )[0]\n\n        with self._lock:\n            try:\n                move = pick_with_engine(\n                    self._ensure_engine()\n                )\n            except Exception as first_error:\n                self._reset_after_failure()\n\n                print(\n                    "[BOT STOCKFISH] first search failed; retrying:",\n                    first_error,\n                    flush=True,\n                )\n\n                try:\n                    move = pick_with_engine(\n                        self._ensure_engine()\n                    )\n                except Exception as second_error:\n                    self._reset_after_failure()\n\n                    # Do not teach with a completely random fallback move.\n                    # The game stream will retry after the engine failure.\n                    raise RuntimeError(\n                        "Stockfish bot move failed twice; "\n                        "refusing to submit a random fallback move."\n                    ) from second_error\n\n        elapsed_ms = int(\n            (time.perf_counter() - started) * 1000\n        )\n\n        return move, elapsed_ms\n\n'
NEW_ANALYZE_BLOCK = 'def analyze_move(\n    payload: dict[str, Any],\n) -> dict[str, Any]:\n    fen = str(payload.get("fen", "")).strip()\n    move_uci = str(payload.get("move", "")).strip().lower()\n\n    language = normalize_language(\n        payload.get("language", "en")\n    )\n\n    detail = str(\n        payload.get("detail", "balanced")\n    ).strip().lower()\n\n    if detail not in {"quick", "balanced", "deep"}:\n        detail = "balanced"\n\n    if not fen or not move_uci:\n        raise ValueError("fen and move are required")\n\n    try:\n        board = chess.Board(fen)\n    except ValueError as exc:\n        raise ValueError("Invalid FEN.") from exc\n\n    try:\n        move = chess.Move.from_uci(move_uci)\n    except ValueError as exc:\n        raise ValueError("Invalid UCI move.") from exc\n\n    if move not in board.legal_moves:\n        raise ValueError(\n            "Move is not legal in the supplied position."\n        )\n\n    with _analyzer_lock:\n        try:\n            analysis = (\n                get_analyzer()\n                .analyze_move(board, move)\n                .to_dict()\n            )\n        except (\n            chess.engine.EngineError,\n            chess.engine.EngineTerminatedError,\n            BrokenPipeError,\n        ):\n            reset_analyzer()\n\n            analysis = (\n                get_analyzer()\n                .analyze_move(board, move)\n                .to_dict()\n            )\n\n    should_coach = (\n        int(analysis["centipawn_loss"])\n        >= MISTAKE_THRESHOLD_CP\n    )\n\n    result: dict[str, Any] = {\n        "shouldCoach": should_coach,\n        "moveNumber": analysis["move_number"],\n        "ply": analysis["ply"],\n        "playedMove": analysis["played_move"],\n        "playedMoveUci": analysis["played_move_uci"],\n        "classification": analysis["classification"],\n        "centipawnLoss": analysis["centipawn_loss"],\n        "bestMove": analysis["best_move"],\n        "bestMoveUci": analysis["best_move_uci"],\n        "opponentReply": analysis["opponent_reply"],\n        "opponentReplyUci": analysis["opponent_reply_uci"],\n        "fenBefore": analysis["fen_before"],\n        "fenAfter": analysis["fen_after"],\n        "bestLine": analysis.get("best_line", []),\n        "refutationLine": analysis.get("refutation_line", []),\n        "themeHint": analysis.get("theme_hint", ""),\n        "evaluationBefore": analysis.get("evaluation_before", 0),\n        "evaluationAfter": analysis.get("evaluation_after", 0),\n        "engineDiagnostics": analysis.get("engine_diagnostics", {}),\n        "coachDetail": detail,\n        "language": language,\n    }\n\n    if should_coach:\n        # Return deterministic Stockfish facts immediately.\n        # The frontend requests LLM wording separately.\n        result.update(\n            fallback_coaching(\n                analysis,\n                language=language,\n            )\n        )\n    else:\n        cp_loss = int(analysis["centipawn_loss"])\n\n        if cp_loss < 35:\n            result.update({\n                "title": "稳健" if language == "zh-CN" else "Solid",\n                "feedback": "这步很稳。" if language == "zh-CN" else "Solid choice.",\n                "lesson": "",\n                "question": "",\n                "arrows": [],\n                "highlightsBefore": [],\n                "highlightsAfter": [],\n            })\n        else:\n            result.update({\n                "title": "再看一眼" if language == "zh-CN" else "Worth a look",\n                "feedback": (\n                    "这步可以走，不过还有更干净的选择。"\n                    if language == "zh-CN"\n                    else "Playable, but there was a cleaner choice."\n                ),\n                "lesson": "",\n                "question": "",\n                "arrows": [],\n                "highlightsBefore": [],\n                "highlightsAfter": [],\n            })\n\n    return result\n\n\ndef explain_move(\n    payload: dict[str, Any],\n) -> dict[str, Any]:\n    raw = payload.get("analysis")\n\n    if not isinstance(raw, dict):\n        raise ValueError("analysis must be an object")\n\n    language = normalize_language(\n        payload.get(\n            "language",\n            raw.get("language", "en"),\n        )\n    )\n\n    detail = str(\n        payload.get(\n            "detail",\n            raw.get("coachDetail", "balanced"),\n        )\n    ).strip().lower()\n\n    if detail not in {"quick", "balanced", "deep"}:\n        detail = "balanced"\n\n    analysis = {\n        "move_number": raw.get("moveNumber"),\n        "ply": raw.get("ply"),\n        "played_move": raw.get("playedMove"),\n        "played_move_uci": raw.get("playedMoveUci"),\n        "classification": raw.get("classification"),\n        "centipawn_loss": raw.get("centipawnLoss"),\n        "best_move": raw.get("bestMove"),\n        "best_move_uci": raw.get("bestMoveUci"),\n        "opponent_reply": raw.get("opponentReply", ""),\n        "opponent_reply_uci": raw.get("opponentReplyUci", ""),\n        "fen_before": raw.get("fenBefore"),\n        "fen_after": raw.get("fenAfter"),\n        "best_line": raw.get("bestLine", []),\n        "refutation_line": raw.get("refutationLine", []),\n        "theme_hint": raw.get("themeHint", ""),\n        "evaluation_before": raw.get("evaluationBefore", 0),\n        "evaluation_after": raw.get("evaluationAfter", 0),\n    }\n\n    coaching = fallback_coaching(\n        analysis,\n        language=language,\n    )\n\n    llm_payload = coach_payload(\n        analysis,\n        detail=detail,\n        language=language,\n    )\n\n    for key in (\n        "title",\n        "feedback",\n        "lesson",\n        "question",\n    ):\n        value = llm_payload.get(key)\n\n        if isinstance(value, str) and value.strip():\n            coaching[key] = value.strip()\n\n    return {\n        "title": coaching["title"],\n        "feedback": coaching["feedback"],\n        "lesson": coaching.get("lesson", ""),\n        "question": coaching.get("question", ""),\n    }\n\n\n'
NEW_PUZZLE_SELECTOR = "function isHighValuePuzzleCandidate(\n  note: CoachNote,\n): boolean {\n  if (\n    note.classification !== 'mistake' &&\n    note.classification !== 'blunder'\n  ) {\n    return false;\n  }\n\n  if (note.centipawnLoss < 150) {\n    return false;\n  }\n\n  if (\n    !note.fenBefore ||\n    !note.bestMoveUci ||\n    note.bestMoveUci.length < 4\n  ) {\n    return false;\n  }\n\n  // Puzzle mode does not yet have its own promotion chooser.\n  if (note.bestMoveUci.length > 4) {\n    return false;\n  }\n\n  const engineLine = [\n    note.bestMove,\n    note.opponentReply,\n    ...(note.bestLine || []),\n    ...(note.refutationLine || []),\n  ]\n    .filter(Boolean)\n    .join(' ');\n\n  const teachingText = [\n    note.themeHint,\n    note.title,\n    note.lesson,\n    note.feedback,\n  ]\n    .filter(Boolean)\n    .join(' ')\n    .toLowerCase();\n\n  const hasForcingSignal =\n    /[x+#]/.test(engineLine);\n\n  const hasClearTeachingTheme =\n    [\n      'tactic',\n      'fork',\n      'pin',\n      'skewer',\n      'hanging',\n      'loose piece',\n      'undefended',\n      'king safety',\n      'mating',\n      'endgame',\n      '战术',\n      '双攻',\n      '牵制',\n      '串击',\n      '挂子',\n      '未保护',\n      '王的安全',\n      '将杀',\n      '残局',\n    ].some((keyword) =>\n      teachingText.includes(keyword),\n    );\n\n  if (\n    note.moveNumber <= 8 &&\n    !hasForcingSignal &&\n    !hasClearTeachingTheme\n  ) {\n    return false;\n  }\n\n  return (\n    hasForcingSignal ||\n    hasClearTeachingTheme\n  );\n}\n\n\nfunction puzzleThemeKey(\n  note: CoachNote,\n): string {\n  const text = [\n    note.themeHint,\n    note.title,\n    note.lesson,\n    note.feedback,\n  ]\n    .filter(Boolean)\n    .join(' ')\n    .toLowerCase();\n\n  if (\n    /fork|pin|skewer|tactic|combination|双攻|牵制|串击|战术|组合/.test(\n      text,\n    )\n  ) {\n    return 'tactics';\n  }\n\n  if (\n    /hanging|loose piece|undefended|unprotected|挂子|未保护|没有保护/.test(\n      text,\n    )\n  ) {\n    return 'piece-safety';\n  }\n\n  if (\n    /king|castle|mate|王|易位|将杀/.test(\n      text,\n    )\n  ) {\n    return 'king-safety';\n  }\n\n  if (\n    /endgame|promotion|残局|升变/.test(\n      text,\n    )\n  ) {\n    return 'endgame';\n  }\n\n  return 'forcing';\n}\n\n\nfunction selectPracticePuzzles(\n  notes: CoachNote[],\n  limit = 3,\n): CoachNote[] {\n  const ranked = [...notes]\n    .filter(isHighValuePuzzleCandidate)\n    .sort((a, b) => {\n      const scoreA =\n        classificationWeight(a.classification) +\n        a.centipawnLoss;\n\n      const scoreB =\n        classificationWeight(b.classification) +\n        b.centipawnLoss;\n\n      return scoreB - scoreA;\n    });\n\n  const selected: CoachNote[] = [];\n\n  for (const note of ranked) {\n    const theme = puzzleThemeKey(note);\n\n    const duplicate =\n      selected.some((existing) => {\n        const sameExactPosition =\n          existing.fenBefore === note.fenBefore;\n\n        const nearbySameTheme =\n          Math.abs(existing.ply - note.ply) <= 6 &&\n          puzzleThemeKey(existing) === theme;\n\n        const nearbySameBestMove =\n          Math.abs(existing.ply - note.ply) <= 6 &&\n          existing.bestMoveUci === note.bestMoveUci;\n\n        return (\n          sameExactPosition ||\n          nearbySameTheme ||\n          nearbySameBestMove\n        );\n      });\n\n    if (duplicate) {\n      continue;\n    }\n\n    selected.push(note);\n\n    if (selected.length >= limit) {\n      break;\n    }\n  }\n\n  // Never force three puzzles.\n  // One excellent position is better than three mediocre ones.\n  return selected;\n}\n"
NEW_PROCESS_QUEUE = "  const processCoachQueue = useCallback(async () => {\n    if (coachProcessingRef.current) return;\n\n    coachProcessingRef.current = true;\n\n    try {\n      while (coachQueueRef.current.length > 0) {\n        const job = coachQueueRef.current.shift();\n\n        if (!job) continue;\n\n        const controller = new AbortController();\n        coachAbortRef.current = controller;\n\n        setCoachThinking(true);\n        setCoachError('');\n\n        try {\n          // Stage 1: Stockfish only.\n          const result = await analyzeMove(\n            job.fenBefore,\n            job.uci,\n            coachDetail,\n            controller.signal,\n            coachLanguage,\n          );\n\n          setCoachThinking(false);\n\n          setMoveEvaluations((current) => {\n            const next = [\n              ...current.filter(\n                (item) => item.ply !== result.ply,\n              ),\n              result,\n            ];\n\n            return next.sort(\n              (a, b) => a.ply - b.ply,\n            );\n          });\n\n          if (!result.shouldCoach) {\n            if (result.classification === 'good') {\n              goodMoveStreakRef.current += 1;\n\n              const justRecovered =\n                result.ply - lastMistakePlyRef.current <= 4;\n\n              const enoughGap =\n                result.ply - lastPraisePlyRef.current >= 6;\n\n              const shouldPraise =\n                enoughGap &&\n                (\n                  justRecovered ||\n                  goodMoveStreakRef.current >= 3\n                );\n\n              if (shouldPraise) {\n                const englishPraise = [\n                  'Good rhythm.',\n                  'Clean choice.',\n                  'You’re seeing the board well.',\n                  'Nice process.',\n                ];\n\n                const chinesePraise = [\n                  '节奏不错。',\n                  '这步很干净。',\n                  '你现在看棋盘很清楚。',\n                  '思路不错。',\n                ];\n\n                const pool =\n                  coachLanguage === 'zh-CN'\n                    ? chinesePraise\n                    : englishPraise;\n\n                const feedback =\n                  justRecovered\n                    ? coachLanguage === 'zh-CN'\n                      ? '调整得很好，已经回到正确节奏了。'\n                      : 'Nice recovery. You reset well.'\n                    : pool[\n                        Math.abs(result.ply) %\n                          pool.length\n                      ];\n\n                const praisedResult: CoachResult = {\n                  ...result,\n                  title:\n                    coachLanguage === 'zh-CN'\n                      ? '不错'\n                      : 'Nice',\n                  feedback,\n                };\n\n                setCoachResult(praisedResult);\n                speak(feedback);\n\n                lastPraisePlyRef.current =\n                  result.ply;\n\n                goodMoveStreakRef.current = 0;\n              }\n\n              // Most good moves intentionally stay quiet.\n              continue;\n            }\n\n            goodMoveStreakRef.current = 0;\n\n            // Small inaccuracies may be visible but are not spoken.\n            if (result.centipawnLoss >= 50) {\n              setCoachResult(result);\n            }\n\n            continue;\n          }\n\n          goodMoveStreakRef.current = 0;\n          lastMistakePlyRef.current = result.ply;\n\n          const currentGameId = gameId;\n\n          // Immediate deterministic Stockfish feedback.\n          setCoachNotes((current) => {\n            const note: CoachNote = {\n              ...result,\n              gameId: currentGameId || '',\n              savedAt: Date.now(),\n              playerColor: myColor,\n              language: coachLanguage,\n            };\n\n            return [\n              note,\n              ...current.filter(\n                (item) => item.ply !== note.ply,\n              ),\n            ].slice(0, 16);\n          });\n\n          setCoachResult(result);\n\n          // Stage 2: GPT wording only. Do not await it.\n          void explainMove(\n            result,\n            coachDetail,\n            undefined,\n            coachLanguage,\n          )\n            .then((explanation) => {\n              if (\n                gameIdRef.current !== currentGameId\n              ) {\n                return;\n              }\n\n              const enriched: CoachResult = {\n                ...result,\n                ...explanation,\n              };\n\n              setMoveEvaluations((current) => {\n                const next = [\n                  ...current.filter(\n                    (item) =>\n                      item.ply !== enriched.ply,\n                  ),\n                  enriched,\n                ];\n\n                return next.sort(\n                  (a, b) => a.ply - b.ply,\n                );\n              });\n\n              setCoachNotes((current) => {\n                const existing =\n                  current.find(\n                    (item) =>\n                      item.ply === enriched.ply,\n                  );\n\n                const note: CoachNote = {\n                  ...enriched,\n                  gameId:\n                    existing?.gameId ||\n                    currentGameId ||\n                    '',\n                  savedAt:\n                    existing?.savedAt ||\n                    Date.now(),\n                  playerColor:\n                    existing?.playerColor ||\n                    myColor,\n                  language: coachLanguage,\n                };\n\n                return [\n                  note,\n                  ...current.filter(\n                    (item) =>\n                      item.ply !== note.ply,\n                  ),\n                ].slice(0, 16);\n              });\n\n              setCoachResult((current) =>\n                current?.ply === enriched.ply\n                  ? enriched\n                  : current,\n              );\n\n              speak(explanation.feedback);\n            })\n            .catch((error) => {\n              console.warn(\n                'Coach explanation unavailable:',\n                error,\n              );\n\n              if (\n                gameIdRef.current === currentGameId\n              ) {\n                speak(result.feedback);\n              }\n            });\n\n        } catch (error) {\n          setCoachThinking(false);\n\n          if (!isAbortError(error)) {\n            setCoachError(\n              `Coach analysis unavailable: ${String(error)}`,\n            );\n          }\n        }\n      }\n\n    } finally {\n      coachProcessingRef.current = false;\n      coachAbortRef.current = null;\n      setCoachThinking(false);\n    }\n  }, [\n    coachDetail,\n    coachLanguage,\n    gameId,\n    myColor,\n    voiceEnabled,\n  ]);\n"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def backup(path: Path) -> None:
    backup_path = path.with_name(
        path.name + ".before-reliability-fix"
    )

    if not backup_path.exists():
        shutil.copy2(path, backup_path)


def replace_once(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = text.count(old)

    if count != 1:
        fail(
            f"{label}: expected one exact match, found {count}."
        )

    return text.replace(old, new, 1)


def regex_replace_once(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    next_text, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=re.S,
    )

    if count != 1:
        fail(
            f"{label}: expected one regex match, found {count}."
        )

    return next_text


for target in TARGETS:
    if not target.is_file():
        fail(
            "Run this script from the ai-chess-coach repo root. "
            f"Missing: {target}"
        )

for target in TARGETS:
    backup(target)


# 1) Reliable Stockfish move evaluation.
stockfish_path = TARGETS[0]
stockfish_path.write_text(
    NEW_STOCKFISH,
    encoding="utf-8",
)


# 2) Never immediately substitute a random bot move after an engine crash.
bot_path = TARGETS[1]
bot_text = bot_path.read_text(encoding="utf-8")

bot_text = regex_replace_once(
    bot_text,
    r"    def choose_move\(self, board: chess\.Board, level: BotLevel\) -> tuple\[chess\.Move, int\]:.*?(?=class LichessBotRuntime:)",
    NEW_CHOOSE_MOVE,
    "bot_runtime.py choose_move",
)

bot_path.write_text(
    bot_text,
    encoding="utf-8",
)


# 3) Backend: sensible Stockfish floor + split GPT wording from engine analysis.
app_path = TARGETS[2]
app_text = app_path.read_text(encoding="utf-8")

app_text, count = re.subn(
    r'COACH_TIME_MS = int\(os\.environ\.get\("COACH_TIME_MS", "\d+"\)\)',
    'COACH_TIME_MS = max(200, int(os.environ.get("COACH_TIME_MS", "250")))',
    app_text,
    count=1,
)

if count != 1:
    fail("Could not update COACH_TIME_MS.")

app_text = regex_replace_once(
    app_text,
    r"def analyze_move\(payload: dict\[str, Any\]\) -> dict\[str, Any\]:.*?(?=class Handler\(BaseHTTPRequestHandler\):)",
    NEW_ANALYZE_BLOCK,
    "server/app.py analyze/explain",
)

app_text = replace_once(
    app_text,
    """            elif self.path == "/api/coach/analyze":
                self._send(
                    200,
                    analyze_move(
                        self._json_body()
                    ),
                )
""",
    """            elif self.path == "/api/coach/analyze":
                self._send(
                    200,
                    analyze_move(
                        self._json_body()
                    ),
                )
            elif self.path == "/api/coach/explain":
                self._send(
                    200,
                    explain_move(
                        self._json_body()
                    ),
                )
""",
    "server/app.py explain route",
)

app_path.write_text(
    app_text,
    encoding="utf-8",
)


# 4) Frontend API for asynchronous explanation.
coach_path = TARGETS[3]
coach_text = coach_path.read_text(encoding="utf-8")

coach_text = replace_once(
    coach_text,
    """  opponentReply?: string;
  opponentReplyUci?: string;
  fenBefore: string;
""",
    """  opponentReply?: string;
  opponentReplyUci?: string;
  bestLine?: string[];
  refutationLine?: string[];
  themeHint?: string;
  evaluationBefore?: number;
  evaluationAfter?: number;
  engineDiagnostics?: {
    budgetMs?: number;
    bestSearch?: {
      depth?: number;
      seldepth?: number;
      nodes?: number;
      nps?: number;
      timeMs?: number;
      hashfull?: number;
    };
    playedSearch?: {
      depth?: number;
      seldepth?: number;
      nodes?: number;
      nps?: number;
      timeMs?: number;
      hashfull?: number;
      reusedBestSearch?: boolean;
    };
  };
  fenBefore: string;
""",
    "src/coach.ts engine metadata",
)

if "export async function explainMove(" not in coach_text:
    coach_text += """

export type CoachExplanation = {
  title: string;
  feedback: string;
  lesson?: string;
  question?: string;
};

export async function explainMove(
  analysis: CoachResult,
  detail: CoachDetail = 'balanced',
  signal?: AbortSignal,
  language: CoachLanguage = 'en',
): Promise<CoachExplanation> {
  const response = await fetch(
    `${CONTROL_URL}/api/coach/explain`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        analysis,
        detail,
        language,
      }),
      signal,
    },
  );

  const data = await response
    .json()
    .catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.message ||
      `${response.status} ${response.statusText}`,
    );
  }

  return data as CoachExplanation;
}
"""

coach_path.write_text(
    coach_text,
    encoding="utf-8",
)


# 5) App: strict puzzles + restrained praise + async GPT wording.
tsx_path = TARGETS[4]
tsx = tsx_path.read_text(encoding="utf-8")

tsx = replace_once(
    tsx,
    """import {
  analyzeMove,
  type CoachLanguage,
  type CoachResult,
} from './coach';
""",
    """import {
  analyzeMove,
  explainMove,
  type CoachLanguage,
  type CoachResult,
} from './coach';
""",
    "src/App.tsx explainMove import",
)

tsx = regex_replace_once(
    tsx,
    r"function selectPracticePuzzles\(\s*notes: CoachNote\[],\s*limit = 3,\s*\): CoachNote\[] \{.*?\n\}\n\n(?=type ReportTheme)",
    NEW_PUZZLE_SELECTOR + "\n\n",
    "src/App.tsx puzzle selector",
)

tsx = replace_once(
    tsx,
    """  const coachAbortRef = useRef<AbortController | null>(null);
  const coachQueueRef = useRef<CoachJob[]>([]);
  const coachProcessingRef = useRef(false);
  const observedCoachPlyRef = useRef<number | null>(null);
""",
    """  const coachAbortRef = useRef<AbortController | null>(null);
  const coachQueueRef = useRef<CoachJob[]>([]);
  const coachProcessingRef = useRef(false);
  const observedCoachPlyRef = useRef<number | null>(null);

  const goodMoveStreakRef = useRef(0);
  const lastPraisePlyRef = useRef(-999);
  const lastMistakePlyRef = useRef(-999);
""",
    "src/App.tsx praise refs",
)

tsx = replace_once(
    tsx,
    """    coachProcessingRef.current = false;
    observedCoachPlyRef.current = null;
    setCoachResult(null);
""",
    """    coachProcessingRef.current = false;
    observedCoachPlyRef.current = null;
    goodMoveStreakRef.current = 0;
    lastPraisePlyRef.current = -999;
    lastMistakePlyRef.current = -999;
    setCoachResult(null);
""",
    "src/App.tsx praise reset",
)

tsx = regex_replace_once(
    tsx,
    r"  const processCoachQueue = useCallback\(async \(\) => \{.*?\n  \}, \[\n    coachDetail,\n    coachLanguage,\n    gameId,\n    myColor,\n    voiceEnabled,\n  \]\);",
    NEW_PROCESS_QUEUE,
    "src/App.tsx processCoachQueue",
)

tsx_path.write_text(
    tsx,
    encoding="utf-8",
)


print("Applied all reliability fixes.")
print("")
print("Next commands:")
print(
    "python -m py_compile "
    "server/app.py server/bot_runtime.py "
    "server/coach/stockfish_analyzer.py"
)
print("npm run build")
