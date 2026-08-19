import { scanSenseRoom } from './senseScanner';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Chess, type Move, type Square } from 'chess.js';
import { ChessBoard, type Arrow } from './components/ChessBoard';
import { finishOAuthCallback, getToken, loginWithLichess, logout, listenForNativeOAuth } from './auth';
import { acceptBotChallenge, getBotStatus, getCachedGameState, setBotLevel, startBot, type BotRuntimeStatus } from './botControl';
import {
  analyzeMove,
  checkCriticalPosition,
  explainMove,
  type CoachLanguage,
  type CoachResult,
} from './coach';
import {
  speakCoach,
  stopCoachSpeech,
  unlockCoachAudio,
} from './tts';
import {
  abortGame,
  challengeBot,
  getAccount,
  getPlayingGames,
  handleTakeback,
  LichessHttpError,
  makeMove,
  resignGame,
  retryingStream,
  streamEvents,
  streamGame,
  type Account,
  type StreamEvent,
} from './lichess';

const BOT_USERNAME = import.meta.env.VITE_COACH_BOT_USERNAME || 'bot_2435';
const ACTIVE_GAME_STORAGE_KEY = 'ai-chess-coach.active-game.v1';
const LEARNING_LOG_STORAGE_KEY = 'ai-chess-coach.learning-log.v2';
const TIME_CONTROL_STORAGE_KEY = 'ai-chess-coach.time-control.v1';

type StoredGame = { gameId: string; username?: string; savedAt: number };
type Player = { name: string; rating?: number; title?: string };
type ClockState = { enabled: boolean; white: number; black: number; increment: number; updatedAt: number };
type PromotionChoice = 'q' | 'r' | 'b' | 'n';
type CoachReviewMode = 'better' | 'threat';
type PendingPromotion = { from: string; to: string; fenBefore: string; basePly: number; choices: PromotionChoice[] };
type PendingMove = { uci: string; basePly: number };
type Winner = 'white' | 'black' | null;
type CoachNote =
  CoachResult & {
    gameId: string;
    savedAt: number;
    playerColor:
      | 'white'
      | 'black';
    language?: CoachLanguage;
  };
type ReviewTarget = CoachResult & { playerColor?: 'white' | 'black' };
type StoredLearningSession = { gameId: string; username?: string; updatedAt: number; notes: CoachNote[] };

type StoredEvaluationSession = {
  gameId: string;
  username?: string;
  updatedAt: number;
  evaluations: CoachResult[];
};

type GameReport = {
  strengths: string[];
  improvements: string[];
  takeaway: string;
};

type PuzzleState =
  | 'solving'
  | 'incorrect'
  | 'correct'
  | 'revealed';

type CriticalPrompt = {
  kind:
    | 'threat'
    | 'opportunity'
    | 'decision'
    | 'check';
  title: string;
  question: string;
  ply: number;
};

const GAME_EVALUATION_STORAGE_KEY =
  'ai-chess-coach.game-evaluations.v1';

function readEvaluationSessions(): StoredEvaluationSession[] {
  try {
    const raw = window.localStorage.getItem(
      GAME_EVALUATION_STORAGE_KEY,
    );

    if (!raw) return [];

    const parsed = JSON.parse(raw);

    if (!Array.isArray(parsed)) return [];

    return parsed.filter(
      (session): session is StoredEvaluationSession =>
        Boolean(
          session &&
          typeof session.gameId === 'string' &&
          Array.isArray(session.evaluations),
        ),
    );
  } catch {
    return [];
  }
}

function readGameEvaluations(
  gameId: string,
): CoachResult[] {
  return (
    readEvaluationSessions().find(
      (session) => session.gameId === gameId,
    )?.evaluations || []
  );
}

function storeGameEvaluations(
  gameId: string,
  username: string | undefined,
  evaluations: CoachResult[],
) {
  try {
    const existing = readEvaluationSessions().filter(
      (session) => session.gameId !== gameId,
    );

    const next: StoredEvaluationSession[] = [
      {
        gameId,
        username,
        updatedAt: Date.now(),
        evaluations,
      },
      ...existing,
    ].slice(0, 8);

    window.localStorage.setItem(
      GAME_EVALUATION_STORAGE_KEY,
      JSON.stringify(next),
    );
  } catch {
    // localStorage may be unavailable.
  }
}

function classificationWeight(
  classification: CoachResult['classification'],
): number {
  switch (classification) {
    case 'blunder':
      return 300;
    case 'mistake':
      return 200;
    case 'inaccuracy':
      return 100;
    default:
      return 0;
  }
}

function puzzleThemeKey(note: CoachNote): string | null {
  const text = [
    note.themeHint,
    note.title,
    note.lesson,
    note.feedback,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  const hasAny = (words: string[]) =>
    words.some((word) => text.includes(word));

  if (
    hasAny([
      'fork',
      'pin',
      'skewer',
      'tactic',
      'combination',
      'hanging',
      'loose piece',
      'undefended',
      'unprotected',
      '双攻',
      '牵制',
      '串击',
      '战术',
      '组合',
      '挂子',
      '未保护',
      '没有保护',
    ])
  ) {
    return 'tactics';
  }

  if (
    hasAny([
      'mating threat',
      'checkmate',
      'king safety',
      '王的安全',
      '王安全',
      '将杀',
    ])
  ) {
    return 'king-safety';
  }

  if (
    hasAny([
      'threat',
      'forcing',
      'opponent',
      '威胁',
      '强制',
      '对手',
    ])
  ) {
    return 'opponent-threat';
  }

  if (
    hasAny([
      'endgame',
      'promotion',
      'king and pawn',
      '残局',
      '升变',
      '兵残局',
    ])
  ) {
    return 'endgame';
  }

  return null;
}

function isHighValuePuzzle(note: CoachNote): boolean {
  if (
    note.classification !== 'mistake' &&
    note.classification !== 'blunder'
  ) {
    return false;
  }

  if (
    !note.fenBefore ||
    !note.bestMoveUci ||
    note.bestMoveUci.length < 4
  ) {
    return false;
  }

  // Do not create promotion puzzles until the puzzle board has
  // an explicit promotion-piece picker.
  if (note.bestMoveUci.length > 4) {
    return false;
  }

  // A puzzle needs to be a clearly meaningful miss, not a tiny
  // Stockfish preference.
  if (note.centipawnLoss < 150) {
    return false;
  }

  const theme = puzzleThemeKey(note);
  const reply = note.opponentReply || '';

  // SAN markers give us a deterministic signal that the opponent's
  // best reply is forcing: capture, check, or mate.
  const hasForcingReply = /[x+#]/.test(reply);

  const tacticalOrThreat =
    theme === 'tactics' ||
    theme === 'opponent-threat' ||
    hasForcingReply;

  const clearPositionalLesson =
    (theme === 'king-safety' || theme === 'endgame') &&
    note.centipawnLoss >= 200;

  // Routine early-opening differences are poor personalized puzzles.
  if (
    note.moveNumber <= 8 &&
    !tacticalOrThreat &&
    theme !== 'king-safety'
  ) {
    return false;
  }

  return tacticalOrThreat || clearPositionalLesson;
}

function practicePuzzleScore(note: CoachNote): number {
  const theme = puzzleThemeKey(note);
  const reply = note.opponentReply || '';

  let score =
    classificationWeight(note.classification) +
    note.centipawnLoss;

  if (/[x+#]/.test(reply)) score += 180;
  if (theme === 'tactics') score += 160;
  if (theme === 'opponent-threat') score += 120;
  if (theme === 'king-safety') score += 90;
  if (theme === 'endgame') score += 70;

  return score;
}

function selectPracticePuzzles(
  notes: CoachNote[],
  limit = 3,
): CoachNote[] {
  const ranked = [...notes]
    .filter(isHighValuePuzzle)
    .sort(
      (a, b) =>
        practicePuzzleScore(b) -
        practicePuzzleScore(a),
    );

  const selected: CoachNote[] = [];

  for (const note of ranked) {
    const theme = puzzleThemeKey(note);

    const isDuplicate = selected.some((existing) => {
      const existingTheme = puzzleThemeKey(existing);
      const plyDistance = Math.abs(existing.ply - note.ply);

      // Same teaching idea from the same tactical sequence.
      if (
        theme &&
        existingTheme === theme &&
        plyDistance <= 6
      ) {
        return true;
      }

      // Same best move / refutation appearing again a few moves later.
      if (
        plyDistance <= 10 &&
        (
          existing.bestMoveUci === note.bestMoveUci ||
          (
            existing.opponentReplyUci &&
            existing.opponentReplyUci === note.opponentReplyUci
          )
        )
      ) {
        return true;
      }

      return existing.fenBefore === note.fenBefore;
    });

    if (isDuplicate) continue;

    selected.push(note);

    if (selected.length >= limit) break;
  }

  // Intentionally do NOT fill to three. One excellent puzzle is
  // better than three mediocre ones.
  return selected;
}

type PraiseMoment = 'streak' | 'recovery';

function personalityPraise(
  result: CoachResult,
  language: CoachLanguage,
  moment: PraiseMoment,
): Pick<CoachResult, 'title' | 'feedback'> {
  const index = Math.abs(result.ply) % 4;

  if (language === 'zh-CN') {
    const recovery = [
      ['稳住了', '很好，你马上重新稳住了节奏。'],
      ['调整得不错', '不错，上一处问题之后你很快调整回来了。'],
      ['重新找回节奏', '这步很稳。继续用刚才这种检查方式。'],
      ['处理得很冷静', '很好，没有被前面的失误影响到这一手。'],
    ] as const;

    const streak = [
      ['节奏不错', '你连续几步都处理得很稳，继续保持这个思考节奏。'],
      ['思路很稳', '不错，你现在的落子很有耐心。'],
      ['继续这样想', '这几步的判断都很稳，别急，保持这个过程。'],
      ['状态不错', '你正在连续做出合理的决定。继续专注。'],
    ] as const;

    const [title, feedback] =
      (moment === 'recovery' ? recovery : streak)[index];

    return { title, feedback };
  }

  const recovery = [
    ['Nice recovery', 'You reset quickly after that mistake. Keep that calm process.'],
    ['Back on track', 'Good adjustment. You did not let the last mistake affect this move.'],
    ['Good reset', 'That was a composed response. Keep checking the position this way.'],
    ['Steady again', 'Nice recovery — you got right back to making solid decisions.'],
  ] as const;

  const streak = [
    ['Good rhythm', 'You have put together several steady decisions. Keep that same process.'],
    ['Settling in', 'Your last few moves have been patient and sensible. Keep going.'],
    ['Nice process', 'You are making consistently solid choices right now. Stay focused.'],
    ['Looking steady', 'A good run of decisions. Keep thinking before you commit.'],
  ] as const;

  const [title, feedback] =
    (moment === 'recovery' ? recovery : streak)[index];

  return { title, feedback };
}

type ReportTheme = {
  key: string;
  label: string;
  advice: string;
};

function reportThemeFor(
  note: CoachNote,
  language: CoachLanguage,
): ReportTheme {
  const isChinese = language === 'zh-CN';

  const text = [
    note.title,
    note.lesson,
    note.feedback,
    note.question,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  const includesAny = (words: string[]) =>
    words.some((word) => text.includes(word));

  if (
    includesAny([
      'hanging',
      'loose piece',
      'undefended',
      'unprotected',
      '挂子',
      '没保护',
      '没有保护',
      '未保护',
      '保护不足',
    ])
  ) {
    return {
      key: 'piece-safety',
      label: isChinese
        ? '棋子安全'
        : 'Piece safety',
      advice: isChinese
        ? '落子前检查一下，有没有棋子会变成没有保护、容易被吃掉的目标。'
        : 'Before you move, check whether any piece will be left unprotected or easy to attack.',
    };
  }

  if (
    includesAny([
      'fork',
      'pin',
      'skewer',
      'tactic',
      'combination',
      '双攻',
      '牵制',
      '串击',
      '战术',
      '组合',
    ])
  ) {
    return {
      key: 'tactics',
      label: isChinese
        ? '战术观察'
        : 'Tactical awareness',
      advice: isChinese
        ? '局面复杂时先慢一点，优先检查将军、吃子和直接威胁。'
        : 'In sharp positions, slow down and scan for checks, captures, and direct threats.',
    };
  }

  if (
    includesAny([
      'king',
      'castle',
      'checkmate',
      '王安全',
      '王翼',
      '易位',
      '将杀',
      '将军',
    ])
  ) {
    return {
      key: 'king-safety',
      label: isChinese
        ? '王的安全'
        : 'King safety',
      advice: isChinese
        ? '准备进攻前，先确认自己的王安全，对手没有直接进攻的机会。'
        : 'Before starting an attack, make sure your king is safe and your opponent has no immediate way in.',
    };
  }

  if (
    includesAny([
      'threat',
      'forcing',
      'opponent',
      'check',
      'capture',
      '威胁',
      '对手',
      '强制',
      '吃子',
    ])
  ) {
    return {
      key: 'opponent-threats',
      label: isChinese
        ? '观察对手意图'
        : 'Opponent threats',
      advice: isChinese
        ? '每次落子前先问自己：对手下一步想做什么？有没有将军、吃子或直接威胁？'
        : 'Before every move, ask what your opponent is threatening and whether they have a check or capture you need to answer.',
    };
  }

  if (
    includesAny([
      'opening',
      'develop',
      'development',
      '开局',
      '出子',
      '发展',
    ])
  ) {
    return {
      key: 'opening-habits',
      label: isChinese
        ? '开局习惯'
        : 'Opening habits',
      advice: isChinese
        ? '开局优先把棋子发展出来、保护好王，不要没有明确目的地重复走同一个棋子。'
        : 'In the opening, develop your pieces, get your king safe, and avoid spending extra moves without a clear reason.',
    };
  }

  if (
    includesAny([
      'endgame',
      'promotion',
      'king and pawn',
      '残局',
      '升变',
      '兵残局',
    ])
  ) {
    return {
      key: 'endgame',
      label: isChinese
        ? '残局技巧'
        : 'Endgame technique',
      advice: isChinese
        ? '棋子变少以后更要耐心，先改善棋子位置，再决定最后的行动。'
        : 'In simpler positions, take your time and improve your pieces before rushing into a final sequence.',
    };
  }

  return {
    key: 'move-check',
    label: isChinese
      ? '落子前检查'
      : 'Move-check routine',
    advice: isChinese
      ? '落子前快速检查一次：局面发生了什么变化？哪些棋子能被吃？对手在威胁什么？'
      : 'Before committing to a move, do one quick scan: what changed, what can be taken, and what is your opponent threatening?',
  };
}


function practicePuzzleTitle(
  note: CoachNote,
  language: CoachLanguage,
): string {
  const theme = reportThemeFor(
    note,
    language,
  );

  const isChinese =
    language === 'zh-CN';

  switch (theme.key) {
    case 'piece-safety':
      return isChinese
        ? '保护好你的棋子'
        : 'Keep your pieces safe';

    case 'tactics':
      return isChinese
        ? '找到战术机会'
        : 'Find the tactical idea';

    case 'king-safety':
      return isChinese
        ? '保护你的王'
        : 'Protect your king';

    case 'opponent-threats':
      return isChinese
        ? '发现对手的威胁'
        : 'Spot the threat';

    case 'opening-habits':
      return isChinese
        ? '找到自然的开局走法'
        : 'Find the clean developing move';

    case 'endgame':
      return isChinese
        ? '找到正确的残局计划'
        : 'Find the best endgame plan';

    default:
      return isChinese
        ? '找到更好的走法'
        : 'Find the better move';
  }
}


function buildGameReport(
  evaluations: CoachResult[],
  notes: CoachNote[],
  language: CoachLanguage,
): GameReport {
  const isChinese =
    language === 'zh-CN';

  const ordered = [...evaluations].sort(
    (a, b) => a.ply - b.ply,
  );

  const isStrong = (
    result: CoachResult,
  ) =>
    result.classification === 'good';

  const isMajorMiss = (
    result: CoachResult,
  ) =>
    result.classification === 'mistake' ||
    result.classification === 'blunder';

  const phaseStats = (
    items: CoachResult[],
  ) => ({
    count: items.length,
    strong: items.filter(isStrong).length,
    majorMisses:
      items.filter(isMajorMiss).length,
  });

  const opening = phaseStats(
    ordered.filter(
      (result) =>
        result.moveNumber <= 10,
    ),
  );

  const middlegame = phaseStats(
    ordered.filter(
      (result) =>
        result.moveNumber > 10 &&
        result.moveNumber <= 25,
    ),
  );

  const lateGame = phaseStats(
    ordered.filter(
      (result) =>
        result.moveNumber > 25,
    ),
  );

  const goodMoves =
    ordered.filter(isStrong).length;

  const blunders =
    ordered.filter(
      (result) =>
        result.classification ===
        'blunder',
    ).length;

  const strengths: string[] = [];

  if (
    opening.count >= 4 &&
    opening.majorMisses <= 1 &&
    opening.strong / opening.count >= 0.5
  ) {
    strengths.push(
      isChinese
        ? '你的开局整体很稳，没有很早就给对手明显的机会。'
        : 'You started the game in good shape and avoided giving your opponent easy chances early on.',
    );
  }

  if (
    middlegame.count >= 4 &&
    middlegame.majorMisses <= 1 &&
    middlegame.strong /
      middlegame.count >=
      0.5
  ) {
    strengths.push(
      isChinese
        ? '进入中局以后，你大部分决定都很稳，局面复杂起来时也没有轻易乱掉。'
        : 'You handled the middlegame steadily and made sensible decisions as the position became more complicated.',
    );
  }

  if (
    lateGame.count >= 3 &&
    lateGame.majorMisses <= 1 &&
    lateGame.strong /
      lateGame.count >=
      0.5
  ) {
    strengths.push(
      isChinese
        ? '后半盘你保持了不错的专注，没有因为局面简化就急着走棋。'
        : 'You stayed focused later in the game and kept finding useful moves instead of rushing.',
    );
  }

  if (
    strengths.length < 2 &&
    ordered.length >= 6 &&
    blunders === 0
  ) {
    strengths.push(
      isChinese
        ? '这盘棋你没有出现特别严重的一步失误，所以一直保留着继续战斗的机会。'
        : 'You avoided any major one-move collapse, which kept the game playable throughout.',
    );
  }

  if (
    strengths.length < 2 &&
    goodMoves >=
      Math.max(
        3,
        Math.ceil(
          ordered.length * 0.55,
        ),
      )
  ) {
    strengths.push(
      isChinese
        ? '你有很多决定都很合理。下一步就是让这种稳定的思考方式保持得更久。'
        : 'A lot of your decisions were solid. The next goal is making that good decision-making more consistent.',
    );
  }

  if (
    !strengths.length &&
    goodMoves > 0
  ) {
    strengths.push(
      isChinese
        ? '这盘棋里你找到了不少不错的想法，已经有一个很好的基础可以继续提高。'
        : 'You found several solid ideas during the game. There is a good base here to build on.',
    );
  }

  if (!strengths.length) {
    strengths.push(
      isChinese
        ? '这盘棋留下了几个很值得学习的局面。把关键时刻重新看一遍，会比记住具体走法更有帮助。'
        : 'You created useful positions to learn from. Reviewing the key moments will give you a clear next step.',
    );
  }

  const themes = new Map<
    string,
    ReportTheme & {
      count: number;
      score: number;
    }
  >();

  for (const note of notes) {
    const theme = reportThemeFor(
      note,
      language,
    );

    const severity =
      classificationWeight(
        note.classification,
      ) + note.centipawnLoss;

    const current =
      themes.get(theme.key);

    if (current) {
      current.count += 1;
      current.score += severity;
    } else {
      themes.set(theme.key, {
        ...theme,
        count: 1,
        score: severity,
      });
    }
  }

  const improvementThemes = [
    ...themes.values(),
  ]
    .sort(
      (a, b) =>
        b.count * 1000 +
        b.score -
        (a.count * 1000 +
          a.score),
    )
    .slice(0, 2);

  const improvements =
    improvementThemes.map(
      (theme) =>
        `${theme.label}${isChinese ? '：' : ': '}${theme.advice}`,
    );

  if (!improvements.length) {
    improvements.push(
      isChinese
        ? '继续保持落子前快速检查的习惯：看看局面发生了什么变化，以及对手下一步可能做什么。'
        : 'Keep using a quick move-check routine: look at what changed and what your opponent can do next.',
    );
  }

  const mainTheme =
    improvementThemes[0];

  const takeaway = mainTheme
    ? isChinese
      ? `下一盘棋先专注一个重点：${mainTheme.label}。先把这个习惯练成自然反应，再考虑更多东西。`
      : `Your main focus next game is ${mainTheme.label.toLowerCase()}. Make that one habit automatic before worrying about anything more advanced.`
    : isChinese
      ? '继续保持冷静的思考方式，让好的决定从开局一直延续到最后。'
      : 'Keep the same calm thinking process and make your solid decisions more consistent from move to move.';

  return {
    strengths: strengths.slice(0, 2),
    improvements:
      improvements.slice(0, 2),
    takeaway,
  };
}

const LEVELS = [
  { id: 'newcomer', label: 'Newcomer', elo: 500, hint: 'Just learning patterns' },
  { id: 'beginner', label: 'Beginner', elo: 800, hint: 'Sees basic threats' },
  { id: 'developing', label: 'Developing', elo: 1100, hint: 'Good practice opponent' },
  { id: 'club', label: 'Club', elo: 1400, hint: 'Punishes loose moves' },
  { id: 'strong', label: 'Strong', elo: 1700, hint: 'Tactical and steady' },
  { id: 'expert', label: 'Expert', elo: 2000, hint: 'Serious challenge' },
] as const;

const TIME_CONTROLS = [
  { id: 'unlimited', label: 'Unlimited', detail: 'No clock', timeControl: { type: 'unlimited' as const } },
  { id: '30-0', label: '30 min', detail: 'Relaxed', timeControl: { type: 'clock' as const, limitSeconds: 1800, incrementSeconds: 0 } },
  { id: '15-10', label: '15 + 10', detail: 'Thoughtful', timeControl: { type: 'clock' as const, limitSeconds: 900, incrementSeconds: 10 } },
  { id: '10-5', label: '10 + 5', detail: 'Balanced', timeControl: { type: 'clock' as const, limitSeconds: 600, incrementSeconds: 5 } },
  { id: '10-0', label: '10 min', detail: 'Classic', timeControl: { type: 'clock' as const, limitSeconds: 600, incrementSeconds: 0 } },
  { id: '5-3', label: '5 + 3', detail: 'Quick', timeControl: { type: 'clock' as const, limitSeconds: 300, incrementSeconds: 3 } },
  { id: '3-2', label: '3 + 2', detail: 'Fast', timeControl: { type: 'clock' as const, limitSeconds: 180, incrementSeconds: 2 } },
] as const;

type TimeControlId = (typeof TIME_CONTROLS)[number]['id'];
type CoachDetail = 'quick' | 'balanced' | 'deep';

const COACH_DETAIL_STORAGE_KEY =
  'ai-chess-coach.coach-detail.v1';

const COACH_LANGUAGE_STORAGE_KEY =
  'ai-chess-coach.coach-language.v1';

const VOICE_ENABLED_STORAGE_KEY =
  'ai-chess-coach.voice-enabled.v1';

function readVoiceEnabled(): boolean {
  try {
    return window.localStorage.getItem(
      VOICE_ENABLED_STORAGE_KEY,
    ) === 'true';
  } catch {
    return false;
  }
}

function readStoredGame(): StoredGame | null {
  try {
    const raw = window.localStorage.getItem(ACTIVE_GAME_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredGame>;
    if (!parsed.gameId || typeof parsed.gameId !== 'string') return null;
    return { gameId: parsed.gameId, username: parsed.username, savedAt: Number(parsed.savedAt) || Date.now() };
  } catch {
    return null;
  }
}

function storeActiveGame(gameId: string, username?: string) {
  try {
    window.localStorage.setItem(ACTIVE_GAME_STORAGE_KEY, JSON.stringify({ gameId, username, savedAt: Date.now() } satisfies StoredGame));
  } catch { /* localStorage can be unavailable in private/restricted contexts. */ }
}

function forgetStoredGame() {
  try { window.localStorage.removeItem(ACTIVE_GAME_STORAGE_KEY); } catch { /* no-op */ }
}

function readLearningSessions(): StoredLearningSession[] {
  try {
    const raw = window.localStorage.getItem(LEARNING_LOG_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((session): session is StoredLearningSession => Boolean(
      session && typeof session.gameId === 'string' && Array.isArray(session.notes),
    ));
  } catch {
    return [];
  }
}

function readLearningNotes(gameId: string): CoachNote[] {
  return readLearningSessions().find((session) => session.gameId === gameId)?.notes || [];
}

function storeLearningNotes(gameId: string, username: string | undefined, notes: CoachNote[]) {
  try {
    const existing = readLearningSessions().filter((session) => session.gameId !== gameId);
    const next: StoredLearningSession[] = [
      { gameId, username, updatedAt: Date.now(), notes: notes.slice(0, 16) },
      ...existing,
    ].slice(0, 8);
    window.localStorage.setItem(LEARNING_LOG_STORAGE_KEY, JSON.stringify(next));
  } catch { /* no-op */ }
}

function readPreferredTimeControl(): TimeControlId {
  try {
    const value = window.localStorage.getItem(TIME_CONTROL_STORAGE_KEY) as TimeControlId | null;
    return TIME_CONTROLS.some((item) => item.id === value) ? value! : '10-0';
  } catch {
    return '10-0';
  }
}

function storePreferredTimeControl(value: TimeControlId) {
  try { window.localStorage.setItem(TIME_CONTROL_STORAGE_KEY, value); } catch { /* no-op */ }
}

function readCoachDetail(): CoachDetail {
  try {
    const value = window.localStorage.getItem(COACH_DETAIL_STORAGE_KEY);
    if (value === 'quick' || value === 'balanced' || value === 'deep') {
      return value;
    }
  } catch {
    // no-op
  }
  return 'balanced';
}

function readCoachLanguage(): CoachLanguage {
  try {
    const value = window.localStorage.getItem(
      COACH_LANGUAGE_STORAGE_KEY,
    );

    return value === 'zh-CN'
      ? 'zh-CN'
      : 'en';
  } catch {
    return 'en';
  }
}

function destinations(chess: Chess): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const move of chess.moves({ verbose: true })) {
    const current = result.get(move.from) || [];
    if (!current.includes(move.to)) current.push(move.to);
    result.set(move.from, current);
  }
  return result;
}

function replay(initialFen: string, movesText: string) {
  const chess = initialFen && initialFen !== 'startpos' ? new Chess(initialFen) : new Chess();
  const san: string[] = [];
  const moves = movesText.trim() ? movesText.trim().split(/\s+/) : [];
  for (const uci of moves) {
    const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || 'q' });
    if (move) san.push(move.san);
  }
  const last = moves.at(-1);
  return {
    chess,
    san,
    plyCount: moves.length,
    lastMove: last ? [last.slice(0, 2), last.slice(2, 4)] as [string, string] : undefined,
  };
}

function formatClock(ms: number): string {
  const totalSeconds = Math.ceil(Math.max(0, ms) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function formatTimeControl(clock: any): string {
  if (!clock || typeof clock.initial !== 'number') return 'Unlimited';
  const minutes = Math.round(clock.initial / 60000);
  const increment = Math.round(Number(clock.increment || 0) / 1000);
  return increment ? `${minutes} + ${increment}` : `${minutes} min`;
}

function PlayerBar({ player, clock, active, side }: { player: Player; clock: number | null; active: boolean; side: 'white' | 'black' }) {
  return <div className={`player-bar ${active ? 'active' : ''}`}>
    <div className="player-identity">
      <span className={`color-dot ${side}`} />
      <strong>{player.title ? `${player.title} ` : ''}{player.name}</strong>
      {player.rating ? <span>{player.rating}</span> : null}
    </div>
    <div className={`clock ${clock == null ? 'unlimited' : ''}`} title={clock == null ? 'Unlimited time' : undefined}>
      {clock == null ? <><span className="infinity">∞</span><small>unlimited</small></> : formatClock(clock)}
    </div>
  </div>;
}

function gameEndReason(
  status: string,
  winner: Winner,
  myColor: 'white' | 'black',
  language: CoachLanguage,
): string {
  const isChinese = language === 'zh-CN';

  switch (status) {
    case 'mate':
      return isChinese ? '将杀' : 'Checkmate';

    case 'resign':
      return winner === myColor
        ? isChinese
          ? '对手认输'
          : 'Your opponent resigned'
        : isChinese
          ? '你已认输'
          : 'You resigned';

    case 'timeout':
    case 'outoftime':
      return winner === myColor
        ? isChinese
          ? '对手超时'
          : 'Your opponent ran out of time'
        : isChinese
          ? '你已超时'
          : 'You ran out of time';

    case 'stalemate':
      return isChinese ? '逼和' : 'Stalemate';

    case 'draw':
      return isChinese ? '双方同意和棋' : 'Draw agreed';

    case 'insufficientMaterialClaim':
      return isChinese
        ? '子力不足和棋'
        : 'Draw by insufficient material';

    case 'aborted':
      return isChinese ? '对局已取消' : 'Game aborted';

    case 'noStart':
      return isChinese ? '对局未开始' : 'Game did not start';

    case 'cheat':
      return isChinese
        ? 'Lichess 结束了对局'
        : 'Game ended by Lichess';

    case 'variantEnd':
      return isChinese ? '对局结束' : 'Game ended';

    default:
      return isChinese ? '对局结束' : 'Game finished';
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export default function App() {
  const storedGameAtLoad = useRef<StoredGame | null>(readStoredGame());
  const [token, setToken] = useState<string | null>(getToken());
  const [account, setAccount] = useState<Account | null>(null);
  const [status, setStatus] = useState('Ready');
  const [level, setLevel] = useState<(typeof LEVELS)[number]['id']>('developing');
  const [timeControlId, setTimeControlId] = useState<TimeControlId>(readPreferredTimeControl);
  const [currentTimeControlLabel, setCurrentTimeControlLabel] = useState('10 min');
  const [preferredColor, setPreferredColor] = useState<'random' | 'white' | 'black'>('random');
  const [bot, setBot] = useState<BotRuntimeStatus>({ running: false, connected: false });
  const [startingGame, setStartingGame] = useState(false);
  const [scanningRoom, setScanningRoom] = useState(false);
  const [recoveryChecked, setRecoveryChecked] = useState(false);

  const [gameId, setGameId] = useState<string | null>(storedGameAtLoad.current?.gameId ?? null);
  // SenseRobot mode is intentionally NOT restored from localStorage.
  // A game becomes a SenseRobot game only after this app successfully
  // scans and joins a SenseRobot QR room in the current session.
  const [senseRobotGameId, setSenseRobotGameId] = useState<string | null>(null);
  const gameIdRef = useRef<string | null>(null);
  const [initialFen, setInitialFen] = useState('startpos');
  const [movesText, setMovesText] = useState('');
  const movesTextRef = useRef('');
  const [orientation, setOrientation] = useState<'white' | 'black'>('white');
  const [myColor, setMyColor] = useState<'white' | 'black'>('white');
  const [gameStatus, setGameStatus] = useState(storedGameAtLoad.current?.gameId ? 'recovering' : 'idle');
  const [players, setPlayers] = useState<{ white: Player; black: Player }>({
    white: { name: 'White' }, black: { name: 'Black' },
  });
  const [clock, setClock] = useState<ClockState>({ enabled: true, white: 600000, black: 600000, increment: 0, updatedAt: Date.now() });
  const [now, setNow] = useState(Date.now());
  const [rollbackSignal, setRollbackSignal] = useState(0);
  const [pendingPromotion, setPendingPromotion] = useState<PendingPromotion | null>(null);
  const [moveInFlight, setMoveInFlight] = useState(false);
  const pendingMoveRef = useRef<PendingMove | null>(null);
  const [endGameConfirm, setEndGameConfirm] = useState(false);
  const [winner, setWinner] = useState<Winner>(null);
  const [gameOverOpen, setGameOverOpen] = useState(false);

  const [coachResult, setCoachResult] = useState<CoachResult | null>(null);
  const [criticalPrompt, setCriticalPrompt] = useState<CriticalPrompt | null>(null);
  const [coachThinking, setCoachThinking] = useState(false);
  const [coachError, setCoachError] = useState('');
  const [coachNotes, setCoachNotes] = useState<CoachNote[]>([]);
  const [moveEvaluations, setMoveEvaluations] = useState<CoachResult[]>([]);
  const [puzzleOpen, setPuzzleOpen] = useState(false);
  const [puzzleIndex, setPuzzleIndex] = useState(0);
  const [puzzleFen, setPuzzleFen] = useState('');
  const [puzzleState, setPuzzleState] = useState<PuzzleState>('solving');
  const [puzzleRollbackSignal, setPuzzleRollbackSignal] = useState(0);
  const [voiceEnabled, setVoiceEnabled] = useState(readVoiceEnabled);
  const [hintsEnabled, setHintsEnabled] = useState(true);

  const [coachDetail, setCoachDetail] = useState<CoachDetail>(readCoachDetail);
  const [coachLanguage, setCoachLanguage] = useState<CoachLanguage>(readCoachLanguage);
  const [reviewMode, setReviewMode] = useState<CoachReviewMode | null>(null);
  const [reviewTarget, setReviewTarget] = useState<ReviewTarget | null>(null);
  const [historyPly, setHistoryPly] = useState<number | null>(null);
  type CoachJob = {
    fenBefore: string;
    uci: string;
  };

  const coachAbortRef = useRef<AbortController | null>(null);
  const coachQueueRef = useRef<CoachJob[]>([]);
  const coachProcessingRef = useRef(false);
  const observedCoachPlyRef = useRef<number | null>(null);
  const goodMoveRunRef = useRef(0);
  const lastMistakePlyRef = useRef<number | null>(null);
  const lastPraisePlyRef = useRef<number | null>(null);

  // Last few REAL LLM explanations from this game.
  // Sent back to the next wording request only to reduce repetition.
  const recentCoachFeedbackRef = useRef<string[]>([]);

  // Pre-move Socratic questions are intentionally rare.
  const criticalQuestionAbortRef = useRef<AbortController | null>(null);
  const observedCriticalPlyRef = useRef<number | null>(null);
  const criticalQuestionCountRef = useRef(0);
  const lastCriticalQuestionPlyRef = useRef(-999);
  const recentCriticalQuestionsRef = useRef<string[]>([]);
  const criticalPromptRef = useRef<CriticalPrompt | null>(null);
  const reviewTouchStart = useRef<{ x: number; y: number } | null>(null);
  const [reviewDragX, setReviewDragX] = useState(0);
  const [reviewDragging, setReviewDragging] = useState(false);
  const [reviewNoTransition, setReviewNoTransition] = useState(false);
  const reviewAnimatingRef = useRef(false);

  const position = useMemo(
  () => replay(initialFen, movesText),
  [initialFen, movesText],
);

  const displayPosition = useMemo(() => {
    // null means we are looking at the live/current position.
    if (historyPly == null || historyPly >= position.plyCount) {
      return position;
    }

    const moves = movesText.trim()
      ? movesText.trim().split(/\s+/)
      : [];

    return replay(
      initialFen,
      moves.slice(0, historyPly).join(' '),
    );
  }, [initialFen, movesText, historyPly, position]);

  const turnColor: 'white' | 'black' =
    position.chess.turn() === 'w' ? 'white' : 'black';

  const activeGame =
    gameStatus === 'started' || gameStatus === 'created';

  const isSenseRobotGame =
    Boolean(gameId && senseRobotGameId === gameId);

  const isMyTurn =
    activeGame && myColor === turnColor;

  const canMove =
    !isSenseRobotGame &&
    historyPly == null &&
    isMyTurn &&
    !moveInFlight &&
    !pendingPromotion;
    
  const isCoachGame = players.white.name.toLowerCase() === BOT_USERNAME.toLowerCase()
    || players.black.name.toLowerCase() === BOT_USERNAME.toLowerCase();
  const coachArrows: Arrow[] = useMemo(() => {
    if (!hintsEnabled || !coachResult) return [];
    // A best-move arrow belongs to the position *before* the student's move,
    // while a threat arrow belongs to the position immediately after it. Never
    // draw an arrow on a later live position where it would teach the wrong idea.
    if (position.plyCount === coachResult.ply - 1) {
      return (coachResult.arrows || []).filter((arrow) => arrow.kind === 'best');
    }
    if (position.plyCount === coachResult.ply) {
      return (coachResult.arrows || []).filter((arrow) => arrow.kind === 'danger');
    }
    return [];
  }, [hintsEnabled, coachResult, position.plyCount]);
  const coachHighlights = useMemo(() => {
    if (!hintsEnabled || !coachResult) return [];
    if (position.plyCount === coachResult.ply - 1) return coachResult.highlightsBefore || [];
    if (position.plyCount === coachResult.ply) return coachResult.highlightsAfter || [];
    return [];
  }, [hintsEnabled, coachResult, position.plyCount]);

  const setActiveGameId = useCallback((nextGameId: string) => {
    gameIdRef.current = nextGameId;
    setGameId(nextGameId);
    storeActiveGame(nextGameId, account?.username);
  }, [account?.username]);

  useEffect(() => { gameIdRef.current = gameId; }, [gameId]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    movesTextRef.current = movesText;
  }, [movesText]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        COACH_DETAIL_STORAGE_KEY,
        coachDetail,
      );
    } catch {
      // no-op
    }
  }, [coachDetail]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        COACH_LANGUAGE_STORAGE_KEY,
        coachLanguage,
      );
    } catch {
      // no-op
    }
  }, [coachLanguage]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        VOICE_ENABLED_STORAGE_KEY,
        String(voiceEnabled),
      );
    } catch {
      // no-op
    }
  }, [voiceEnabled]);

  useEffect(() => {
    return () => {
      stopCoachSpeech();
    };
  }, []);

  const displayedClock = useMemo(() => {
    if (!clock.enabled) return { white: null, black: null };
    const elapsed = activeGame ? now - clock.updatedAt : 0;
    return {
      white: turnColor === 'white' && activeGame ? clock.white - elapsed : clock.white,
      black: turnColor === 'black' && activeGame ? clock.black - elapsed : clock.black,
    };
  }, [activeGame, clock, now, turnColor]);

  useEffect(() => {
    storePreferredTimeControl(timeControlId);
  }, [timeControlId]);

  useEffect(() => {
    let disposed = false;
    let removeNativeListener: (() => void) | null = null;

    // Normal browser callback (desktop/web build).
    finishOAuthCallback()
      .then((done) => {
        if (!disposed && done) setToken(getToken());
      })
      .catch((error) => {
        if (!disposed) setStatus(String(error));
      });

    // Native iOS callback delivered through chessbuddy://oauth/callback.
    void listenForNativeOAuth(
      () => {
        if (disposed) return;
        setToken(getToken());
        setStatus('Signed in with Lichess.');
      },
      (error) => {
        if (!disposed) setStatus(error);
      },
    ).then((removeListener) => {
      if (disposed) {
        removeListener();
      } else {
        removeNativeListener = removeListener;
      }
    });

    return () => {
      disposed = true;
      removeNativeListener?.();
    };
  }, []);

  useEffect(() => {
    if (!token) { setAccount(null); return; }
    getAccount(token)
      .then(setAccount)
      .catch((error) => {
        setStatus(`Lichess account error: ${String(error)}`);
        logout();
        setToken(null);
      });
  }, [token]);

  useEffect(() => {
    if (!token || !account) {
      setRecoveryChecked(false);
      return;
    }
    let cancelled = false;
    setRecoveryChecked(false);

    const stored = readStoredGame();
    if (gameIdRef.current) {
      if (stored?.username && stored.username.toLowerCase() !== account.username.toLowerCase()) {
        forgetStoredGame();
        gameIdRef.current = null;
        setGameId(null);
        setGameStatus('idle');
      } else {
        storeActiveGame(gameIdRef.current, account.username);
        setStatus('Reconnecting to your training game…');
        setRecoveryChecked(true);
        return () => { cancelled = true; };
      }
    }

    getPlayingGames(token).then((games) => {
      if (cancelled || gameIdRef.current) return;
      const coachGame = games.find((game) => game.opponent?.username?.toLowerCase() === BOT_USERNAME.toLowerCase());
      if (coachGame?.gameId) {
        setActiveGameId(coachGame.gameId);
        setGameStatus('recovering');
        setStatus('Recovered your active coach game.');
      }
    }).catch((error) => {
      if (!cancelled) setStatus(`Could not check active games yet: ${String(error)}`);
    }).finally(() => {
      if (!cancelled) setRecoveryChecked(true);
    });
    return () => { cancelled = true; };
  }, [token, account, setActiveGameId]);

  useEffect(() => {
    if (!token || !account) return;
    let alive = true;
    const refresh = async () => {
      try {
        const state = await getBotStatus();
        if (alive) setBot(state);
      } catch (error) {
        if (alive) setBot({ running: false, connected: false, error: String(error) });
      }
    };
    void startBot().then((state) => { if (alive) setBot(state); }).catch((error) => {
      if (alive) setBot({ running: false, connected: false, error: String(error) });
    });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [token, account]);

  useEffect(() => {
    if (!token || !account) return;
    const controller = new AbortController();
    void retryingStream(
      (signal) => streamEvents(token, (event: StreamEvent) => {
        if (event.type === 'gameStart' && event.game) {
          const opponent = event.game.opponent?.username?.toLowerCase();
          if (opponent === BOT_USERNAME.toLowerCase()) {
            // A normal Lichess gameStart must stay a normal online game.
            // Preserve SenseRobot mode only when this is the exact game
            // that was activated by a successful QR scan.
            const startedGameId = event.game.id;

            setSenseRobotGameId((current) =>
              current === startedGameId ? current : null
            );
            setActiveGameId(event.game.id);
            setGameStatus('recovering');
            setStatus(`Game started against ${BOT_USERNAME}.`);
          }
        }
        if (event.type === 'gameFinish' && event.game?.id === gameIdRef.current) {
          forgetStoredGame();
          pendingMoveRef.current = null;
          setMoveInFlight(false);
          // The per-game stream carries the authoritative terminal status and
          // winner. Do not overwrite it with a generic "finished" value.
          setStatus('Training game finished. Finalizing your result…');
        }
      }, signal),
      controller.signal,
      () => setStatus('Reconnecting to Lichess…'),
    );
    return () => controller.abort();
  }, [token, account, setActiveGameId]);

  useEffect(() => {
    if (!token || !gameId || !account) return;
    const controller = new AbortController();

    const syncPendingMove = (nextMovesText: string) => {
      const pendingMove = pendingMoveRef.current;
      if (!pendingMove) return;
      const moves = nextMovesText.trim() ? nextMovesText.trim().split(/\s+/) : [];
      if (moves.length <= pendingMove.basePly) return;

      pendingMoveRef.current = null;
      setMoveInFlight(false);
      if (moves[pendingMove.basePly] === pendingMove.uci) {
        setStatus('Move played.');
      } else {
        setRollbackSignal((value) => value + 1);
        setStatus('Board state changed while your move was syncing. Resynced with Lichess.');
      }
    };

    const applyState = (state: any, clockEnabled?: boolean) => {
    const nextMoves = String(state?.moves || '');
    const nextStatus = String(state?.status || 'started');
    const nextWinner: Winner =
      state?.winner === 'white' || state?.winner === 'black'
        ? state.winner
        : null;

    // Keep the synchronous ref in lockstep with the
    // authoritative Lichess stream.
    movesTextRef.current = nextMoves;
    setMovesText(nextMoves);
      setGameStatus(nextStatus);
      if (nextWinner) setWinner(nextWinner);
      syncPendingMove(nextMoves);
      if (nextStatus !== 'started' && nextStatus !== 'created') {
        forgetStoredGame();
        pendingMoveRef.current = null;
        setMoveInFlight(false);
        setEndGameConfirm(false);
        setGameOverOpen(true);
        setStatus(`Training game finished · ${nextStatus}.`);
        controller.abort();
      }
      setClock((previous) => ({
        enabled: clockEnabled ?? previous.enabled,
        white: typeof state?.wtime === 'number' ? state.wtime : previous.white,
        black: typeof state?.btime === 'number' ? state.btime : previous.black,
        increment: typeof state?.winc === 'number' ? state.winc : previous.increment,
        updatedAt: Date.now(),
      }));
    };

    const onGameEvent = (event: any) => {
      if (event.type === 'gameFull') {
        const whiteName = String(event.white?.name || event.white?.id || 'White');
        const blackName = String(event.black?.name || event.black?.id || 'Black');
        const me = account.username.toLowerCase();
        if (whiteName.toLowerCase() !== me && blackName.toLowerCase() !== me) {
          forgetStoredGame();
          gameIdRef.current = null;
          setGameId(null);
          setGameStatus('idle');
          setRecoveryChecked(true);
          setStatus('The saved Lichess game belongs to a different account, so it was not reopened.');
          controller.abort();
          return;
        }
        const color: 'white' | 'black' = whiteName.toLowerCase() === me ? 'white' : 'black';
        setPlayers({
          white: { name: whiteName, rating: event.white?.rating, title: event.white?.title },
          black: { name: blackName, rating: event.black?.rating, title: event.black?.title },
        });
        setMyColor(color);
        setOrientation(color);
        setInitialFen(event.initialFen || 'startpos');
        setCurrentTimeControlLabel(formatTimeControl(event.clock));
        storeActiveGame(gameId, account.username);
        applyState(event.state || {}, Boolean(event.clock));
        setRecoveryChecked(true);
        if ((event.state?.status || 'started') === 'started' || (event.state?.status || 'started') === 'created') {
          setStatus('Training game connected.');
        }
      } else if (event.type === 'gameState') {
        applyState(event);
      }
    };
    void retryingStream(
      (signal) => streamGame(token, gameId, onGameEvent, signal),
      controller.signal,
      () => setStatus('Reconnecting to the game…'),
      (error) => {
        setRecoveryChecked(true);
        if (error instanceof LichessHttpError && error.status === 404) {
          void getPlayingGames(token).then((games) => {
            const found = games.find((game) => game.opponent?.username?.toLowerCase() === BOT_USERNAME.toLowerCase());
            if (found?.gameId && found.gameId !== gameId) {
              setActiveGameId(found.gameId);
              setGameStatus('recovering');
              setStatus('Recovered your current training game.');
              return;
            }
            forgetStoredGame();
            gameIdRef.current = null;
            setGameId(null);
            setGameStatus('idle');
            setStatus('The saved game is no longer active. Ready for a new training game.');
          }).catch((lookupError) => {
            setStatus(`Could not recover the saved game: ${String(lookupError)}`);
          });
          return;
        }
        setStatus(`Game connection stopped: ${String(error)}`);
      },
    );
    return () => controller.abort();
  }, [token, gameId, account, setActiveGameId]);

  useEffect(() => {
    if (!gameId) return;

    let cancelled = false;
    let requestInFlight = false;

    const syncFromBotBackend = async () => {
      if (requestInFlight || cancelled) return;

      requestInFlight = true;

      try {
        const cached = await getCachedGameState(gameId);

        if (!cached || cancelled) {
          return;
        }

        const cachedMoves = String(
          cached.state?.moves || '',
        ).trim();

        const currentMoves =
          movesTextRef.current.trim();

        const cachedMoveList = cachedMoves
          ? cachedMoves.split(/\s+/)
          : [];

        const currentMoveList = currentMoves
          ? currentMoves.split(/\s+/)
          : [];

        // The normal Lichess stream remains the primary source.
        //
        // Only use Render when its cached game has MORE moves
        // than the iPhone currently knows about.
        if (
          cachedMoveList.length >
          currentMoveList.length
        ) {
          movesTextRef.current = cachedMoves;
          setMovesText(cachedMoves);

          if (cached.initialFen) {
            setInitialFen(cached.initialFen);
          }

          const state = cached.state;

          if (
            state.winner === 'white' ||
            state.winner === 'black'
          ) {
            setWinner(state.winner);
          }

          const nextStatus = String(
            state.status || 'started',
          );

          setGameStatus(nextStatus);

          setClock((previous) => ({
            enabled: previous.enabled,
            white:
              typeof state.wtime === 'number'
                ? state.wtime
                : previous.white,
            black:
              typeof state.btime === 'number'
                ? state.btime
                : previous.black,
            increment:
              typeof state.winc === 'number'
                ? state.winc
                : previous.increment,
            updatedAt: Date.now(),
          }));

          // If our own move was waiting for confirmation,
          // the cached state can also confirm it.
          const pendingMove =
            pendingMoveRef.current;

          if (
            pendingMove &&
            cachedMoveList.length >
              pendingMove.basePly
          ) {
            pendingMoveRef.current = null;
            setMoveInFlight(false);
          }

          setStatus(
            'Game resynced automatically.',
          );
        }
      } catch (error) {
        // Do not interrupt the game just because the backup
        // sync temporarily failed. The normal Lichess stream
        // may still be working perfectly.
        console.warn(
          'Backup game sync failed:',
          error,
        );
      } finally {
        requestInFlight = false;
      }
    };

    // Check once immediately.
    void syncFromBotBackend();

    // Then use Render as a lightweight safety net.
    const timer = window.setInterval(
      () => void syncFromBotBackend(),
      1500,
    );

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [gameId]);

  useEffect(() => {
    coachAbortRef.current?.abort();
    coachQueueRef.current = [];
    coachProcessingRef.current = false;
    observedCoachPlyRef.current = null;
    goodMoveRunRef.current = 0;
    lastMistakePlyRef.current = null;
    lastPraisePlyRef.current = null;
    recentCoachFeedbackRef.current = [];
    criticalQuestionAbortRef.current?.abort();
    observedCriticalPlyRef.current = null;
    criticalQuestionCountRef.current = 0;
    lastCriticalQuestionPlyRef.current = -999;
    recentCriticalQuestionsRef.current = [];
    criticalPromptRef.current = null;
    setCriticalPrompt(null);
    setCoachResult(null);
    setCoachError('');
    setCoachThinking(false);
    setPendingPromotion(null);
    pendingMoveRef.current = null;
    setMoveInFlight(false);
    setEndGameConfirm(false);
    setReviewMode(null);
    setReviewTarget(null);
    setWinner(null);
    setGameOverOpen(false);
    if (gameId) {
      setCoachNotes(
        readLearningNotes(gameId),
      );

      setMoveEvaluations(
        readGameEvaluations(gameId),
      );
    } else {
      setCoachNotes([]);
      setMoveEvaluations([]);
    }
    setRollbackSignal((value) => value + 1);
  }, [gameId]);

  useEffect(() => {
    if (!gameId || !coachNotes.length) return;
    storeLearningNotes(gameId, account?.username, coachNotes);
  }, [gameId, account?.username, coachNotes]);

  useEffect(() => {
    if (
      !gameId ||
      !moveEvaluations.length
    ) {
      return;
    }

    storeGameEvaluations(
      gameId,
      account?.username,
      moveEvaluations,
    );
  }, [
    gameId,
    account?.username,
    moveEvaluations,
  ]);

  function speak(text: string) {
    if (!voiceEnabled) return;

    void speakCoach(
      text,
      coachLanguage,
    );
  }

  const processCoachQueue = useCallback(async () => {
    if (coachProcessingRef.current) return;

    coachProcessingRef.current = true;

    try {
      while (coachQueueRef.current.length > 0) {
        const job = coachQueueRef.current.shift();

        if (!job) continue;

        const controller = new AbortController();
        coachAbortRef.current = controller;

        setCoachThinking(true);
        setCoachError('');

        try {
          const result = await analyzeMove(
            job.fenBefore,
            job.uci,
            coachDetail,
            controller.signal,
            coachLanguage,
          );

          const analysisGameId = gameId;

          setMoveEvaluations((current) => {
            const next = [
              ...current.filter(
                (item) => item.ply !== result.ply,
              ),
              result,
            ];

            return next.sort(
              (a, b) => a.ply - b.ply,
            );
          });

          if (!result.shouldCoach) {
            if (result.classification === 'good') {
              goodMoveRunRef.current += 1;
            } else {
              goodMoveRunRef.current = 0;
            }

            const recentMistake =
              lastMistakePlyRef.current != null &&
              result.ply - lastMistakePlyRef.current <= 4;

            const recovery =
              recentMistake &&
              result.classification === 'good' &&
              result.centipawnLoss < 25;

            const streak =
              goodMoveRunRef.current >= 4 &&
              goodMoveRunRef.current % 4 === 0;

            const praiseIsSpacedOut =
              lastPraisePlyRef.current == null ||
              result.ply - lastPraisePlyRef.current >= 8;

            // Routine good moves are intentionally silent. The coach speaks
            // when the praise actually means something: a recovery or a run
            // of consistently strong decisions.
            if ((recovery || streak) && praiseIsSpacedOut) {
              const praise = personalityPraise(
                result,
                coachLanguage,
                recovery ? 'recovery' : 'streak',
              );

              const praisedResult: CoachResult = {
                ...result,
                ...praise,
                lesson: '',
                question: '',
              };

              lastPraisePlyRef.current = result.ply;
              setCoachResult(praisedResult);
              speak(praise.feedback);
            }

            continue;
          }

          goodMoveRunRef.current = 0;
          lastMistakePlyRef.current = result.ply;

          // The fast endpoint returns Stockfish truth immediately. Show the
          // mistake and deterministic arrows now instead of waiting for GPT.
          const fastResult: CoachResult = {
            ...result,
            title:
              coachLanguage === 'zh-CN'
                ? result.classification === 'blunder'
                  ? '关键失误'
                  : '值得看一看'
                : result.classification === 'blunder'
                  ? 'Critical miss'
                  : 'Worth a look',
            feedback:
              coachLanguage === 'zh-CN'
                ? '这里有一个重要的学习点，正在整理最关键的原因…'
                : 'There is an important idea here. I’m checking the clearest reason…',
            lesson: '',
            question: '',
          };

          const saveNote = (value: CoachResult) => {
            setCoachNotes((current) => {
              const note: CoachNote = {
                ...value,
                gameId: analysisGameId || '',
                savedAt: Date.now(),
                playerColor: myColor,
                language: coachLanguage,
              };

              return [
                note,
                ...current.filter(
                  (item) => item.ply !== note.ply,
                ),
              ].slice(0, 16);
            });
          };

          saveNote(fastResult);
          setCoachResult(fastResult);

          // GPT wording happens in a second request and no longer blocks the
          // move-analysis queue. Stockfish feedback/arrows are already on
          // screen while this is running.
          if (result.analysisId) {
            const recentFeedback = [
              ...recentCoachFeedbackRef.current,
            ];

            void explainMove(
              result.analysisId,
              coachDetail,
              coachLanguage,
              recentFeedback,
            )
              .then((wording) => {
                if (
                  analysisGameId &&
                  gameIdRef.current !== analysisGameId
                ) {
                  return;
                }

                const enriched: CoachResult = {
                  ...result,
                  ...wording,
                  explanationPending: false,
                };

                setMoveEvaluations((current) =>
                  current
                    .map((item) =>
                      item.ply === enriched.ply
                        ? enriched
                        : item,
                    )
                    .sort((a, b) => a.ply - b.ply),
                );

                saveNote(enriched);

                setCoachResult((current) => {
                  if (!current || current.ply !== enriched.ply) {
                    return current;
                  }

                  return enriched;
                });

                const memoryEntry = [
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

                // Do not talk over an active pre-move Socratic question.
                if (!criticalPromptRef.current) {
                  speak(enriched.feedback);
                }
              })
              .catch((error) => {
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
        } catch (error) {
          if (!isAbortError(error)) {
            setCoachError(
              `Coach analysis unavailable: ${String(error)}`,
            );
          }
        }
      }
    } finally {
      coachProcessingRef.current = false;
      coachAbortRef.current = null;
      setCoachThinking(false);
    }
  }, [
    coachDetail,
    coachLanguage,
    gameId,
    myColor,
    voiceEnabled,
  ]);



  useEffect(() => {
    // Cancel any old pre-move question request as soon as the position changes.
    criticalQuestionAbortRef.current?.abort();

    if (
      !gameId ||
      !activeGame ||
      !isCoachGame ||
      !isMyTurn
    ) {
      setCriticalPrompt(null);
      return;
    }

    const moves = movesText.trim()
      ? movesText.trim().split(/\s+/)
      : [];

    const currentPly = moves.length;

    // Avoid opening noise. Questions should feel special.
    if (currentPly < 6) {
      return;
    }

    const lastMoveIndex =
      currentPly - 1;

    if (lastMoveIndex < 0) {
      return;
    }

    const lastMover:
      | 'white'
      | 'black' =
      lastMoveIndex % 2 === 0
        ? 'white'
        : 'black';

    // Only ask immediately after the OPPONENT moved.
    if (lastMover === myColor) {
      return;
    }

    // Never analyse the same waiting position twice.
    if (
      observedCriticalPlyRef.current ===
      currentPly
    ) {
      return;
    }

    observedCriticalPlyRef.current =
      currentPly;

    // Cap at three Socratic interruptions per game.
    if (
      criticalQuestionCountRef.current >=
      4
    ) {
      return;
    }

    // At least six plies between questions.
    if (
      currentPly -
        lastCriticalQuestionPlyRef.current <
      4
    ) {
      return;
    }

    const controller =
      new AbortController();

    criticalQuestionAbortRef.current =
      controller;

    const gameSnapshot = gameId;
    const movesSnapshot =
      movesText.trim();

    const lastOpponentMoveUci =
      moves.at(-1) || '';

    const lastOpponentMove =
      position.san.at(-1) || '';

    const recentQuestions = [
      ...recentCriticalQuestionsRef.current,
    ];

    void checkCriticalPosition(
      position.chess.fen(),
      lastOpponentMove,
      lastOpponentMoveUci,
      coachLanguage,
      recentQuestions,
      controller.signal,
    )
      .then((prompt) => {
        if (
          !prompt.isCritical ||
          !prompt.question
        ) {
          return;
        }

        // The student may have already moved while Stockfish/GPT
        // were deciding whether this was worth interrupting.
        if (
          gameIdRef.current !==
            gameSnapshot ||
          movesTextRef.current.trim() !==
            movesSnapshot
        ) {
          return;
        }

        const nextPrompt: CriticalPrompt = {
          kind:
            prompt.kind ||
            'decision',
          title:
            prompt.title ||
            (
              coachLanguage ===
              'zh-CN'
                ? '先想一想'
                : 'Think first'
            ),
          question:
            prompt.question,
          ply: currentPly,
        };

        criticalPromptRef.current =
          nextPrompt;

        setCriticalPrompt(
          nextPrompt
        );

        criticalQuestionCountRef.current +=
          1;

        lastCriticalQuestionPlyRef.current =
          currentPly;

        recentCriticalQuestionsRef.current =
          [
            ...recentCriticalQuestionsRef.current,
            prompt.question,
          ].slice(-4);

        speak(
          prompt.question
        );
      })
      .catch((error) => {
        if (!isAbortError(error)) {
          console.warn(
            'Critical-position question unavailable:',
            error,
          );
        }
      });

    return () => {
      controller.abort();
    };
  }, [
    gameId,
    activeGame,
    isCoachGame,
    isMyTurn,
    movesText,
    myColor,
    position,
    coachLanguage,
    voiceEnabled,
  ]);


const analyzeStudentMove = useCallback(
  (fenBefore: string, uci: string) => {
    if (!isCoachGame) return;

    coachQueueRef.current.push({
      fenBefore,
      uci,
    });

    void processCoachQueue();
  },
  [isCoachGame, processCoachQueue],
);
  useEffect(() => {
    // Normal phone games use the exact local pre-move FEN captured when the
    // player makes the move. Only SenseRobot games need stream-observed
    // coaching because the move is made on the physical board.
    if (!gameId || !isCoachGame || !isSenseRobotGame) {
      observedCoachPlyRef.current = null;
      return;
    }

    const moves = movesText.trim()
      ? movesText.trim().split(/\s+/)
      : [];

    const currentPly = moves.length;

    // First observation after connecting/reconnecting.
    //
    // Don't suddenly analyze every historical move from
    // a game that was already in progress.
    if (observedCoachPlyRef.current == null) {
      observedCoachPlyRef.current = currentPly;
      return;
    }

    const previousPly = observedCoachPlyRef.current;

    if (currentPly <= previousPly) {
      observedCoachPlyRef.current = currentPly;
      return;
    }

    // Mark these moves as observed before starting analysis
    // so React updates/re-renders cannot analyze them twice.
    observedCoachPlyRef.current = currentPly;

    let latestStudentMoveIndex = -1;

    // Look only at NEW moves.
    //
    // Array index 0 = ply 1 = White
    // Array index 1 = ply 2 = Black
    // etc.
    for (
      let moveIndex = previousPly;
      moveIndex < currentPly;
      moveIndex += 1
    ) {
      const moverColor: 'white' | 'black' =
        moveIndex % 2 === 0
          ? 'white'
          : 'black';

      if (moverColor === myColor) {
        latestStudentMoveIndex = moveIndex;
      }
    }

    // The only new move(s) were made by the bot.
    if (latestStudentMoveIndex < 0) {
      return;
    }

    const uci = moves[latestStudentMoveIndex];

    if (!uci) {
      return;
    }

    // Rebuild the exact board immediately BEFORE
    // the student's move.
    const movesBeforeStudentMove = moves
      .slice(0, latestStudentMoveIndex)
      .join(' ');

    const beforePosition = replay(
      initialFen,
      movesBeforeStudentMove,
    );

    analyzeStudentMove(
      beforePosition.chess.fen(),
      uci,
    );
  }, [
    gameId,
    movesText,
    initialFen,
    myColor,
    isCoachGame,
    isSenseRobotGame,
    analyzeStudentMove,
  ]);

    const submitMove = useCallback(async (
      fenBefore: string,
      basePly: number,
      from: string,
      to: string,
      promotion?: PromotionChoice,
    ) => {
    if (!token || !gameId || !activeGame || pendingMoveRef.current) {
      setRollbackSignal((value) => value + 1);
      return;
    }
    const uci = `${from}${to}${promotion || ''}`;

    criticalPromptRef.current = null;
    setCriticalPrompt(null);
    criticalQuestionAbortRef.current?.abort();

    setPendingPromotion(null);
    pendingMoveRef.current = { uci, basePly };
    setMoveInFlight(true);
    setStatus('Sending move…');
    try {
      await makeMove(token, gameId, uci);
      // The game stream is authoritative. Keep the board locked until that
      // stream confirms this exact move, so a fast bot reply cannot leave the
      // frontend one ply behind or allow a second move from a stale position.
      if (pendingMoveRef.current?.uci === uci) {
        setStatus('Move accepted — syncing board…');
      }

      // Restore the earlier, more reliable coaching path for normal games:
      // analyze the exact board position that existed when the move was made.
      analyzeStudentMove(fenBefore, uci);
    } catch (error) {
      if (pendingMoveRef.current?.uci === uci) {
        pendingMoveRef.current = null;
        setMoveInFlight(false);
      }
      setRollbackSignal((value) => value + 1);
      setStatus(`Move failed: ${String(error)}`);
    }
  }, [token, gameId, activeGame, analyzeStudentMove]);

    const handleBoardMove = useCallback((from: string, to: string) => {
      if (
        isSenseRobotGame ||
        !token ||
        !gameId ||
        !canMove ||
        !activeGame
      ) {
        setRollbackSignal((value) => value + 1);
        return;
      }

    const fenBefore = position.chess.fen();
    const basePly = position.plyCount;
    const clone = new Chess(fenBefore);
    const legal = clone.moves({ square: from as Square, verbose: true }).filter((move) => move.to === to) as Move[];
    if (!legal.length) {
      setRollbackSignal((value) => value + 1);
      return;
    }
    const promotions = Array.from(new Set(
      legal.map((move) => move.promotion).filter(Boolean) as PromotionChoice[],
    ));
    if (promotions.length) {
      setPendingPromotion({ from, to, fenBefore, basePly, choices: promotions });
      return;
    }
    void submitMove(fenBefore, basePly, from, to);
  }, [isSenseRobotGame, token, gameId, canMove, activeGame, position.chess, position.plyCount, submitMove]);

  async function waitForBotReady(): Promise<BotRuntimeStatus> {
    const deadline = Date.now() + 8000;
    let last: BotRuntimeStatus = bot;
    while (Date.now() < deadline) {
      last = await getBotStatus();
      setBot(last);
      if (last.running && last.connected) return last;
      await new Promise((resolve) => window.setTimeout(resolve, 180));
    }
    throw new Error(last.error || 'Bot could not connect to Lichess.');
  }

  async function changeLevel(nextLevel: (typeof LEVELS)[number]['id']) {
    setLevel(nextLevel);
    try {
      const state = await setBotLevel(nextLevel);
      setBot(state);
      const selected = LEVELS.find((item) => item.id === nextLevel);
      setStatus(`Difficulty: ${selected?.label} (~${selected?.elo}).`);
    } catch (error) {
      setStatus(`Could not change difficulty: ${String(error)}`);
    }
  }


  function changeTimeControl(nextId: TimeControlId) {
    setTimeControlId(nextId);
    const selected = TIME_CONTROLS.find((item) => item.id === nextId);
    if (selected) setStatus(`Time control: ${selected.label} · ${selected.detail}.`);
  }

  async function startCoachGame() {
    if (!token || !account || startingGame || activeGame || gameId || !recoveryChecked) return;

    setStartingGame(true);
    setStatus('Checking for an existing training game…');

    // Normal Play is always a regular Lichess online game.
    // Only the QR scanner is allowed to enable SenseRobot mode.
    setSenseRobotGameId(null);

    try {
      // Refreshes and slow API propagation must never create a second game.
      const existingGames = await getPlayingGames(token);
      const existing = existingGames.find(
        (game) =>
          game.opponent?.username?.toLowerCase() ===
          BOT_USERNAME.toLowerCase(),
      );

      if (existing?.gameId) {
        setActiveGameId(existing.gameId);
        setGameStatus('recovering');
        setStatus('Rejoined your existing training game.');
        return;
      }

      setStatus('Preparing coach bot…');

      const levelState = await setBotLevel(level);
      setBot(levelState);

      let state = levelState;
      if (!state.running) {
        state = await startBot();
      }

      setBot(state);
      await waitForBotReady();

      const selectedTimeControl =
        TIME_CONTROLS.find((item) => item.id === timeControlId) ||
        TIME_CONTROLS[4];

      setCurrentTimeControlLabel(selectedTimeControl.label);
      setStatus(
        `Challenging ${BOT_USERNAME} · ${selectedTimeControl.label}…`,
      );

      const challenge = await challengeBot(token, BOT_USERNAME, {
        timeControl: selectedTimeControl.timeControl,
        color: preferredColor,
      });

      let acceptedGameId: string | null = null;
      let acceptError: unknown = null;

      try {
        const accepted = await acceptBotChallenge(
          challenge.id,
          account.username,
        );
        setBot(accepted);
        acceptedGameId = accepted.gameId || null;
      } catch (error) {
        // A game can already exist even when the bot's gameStart event
        // arrives late. Recover the real Lichess game before giving up.
        acceptError = error;
      }

      if (!acceptedGameId) {
        setStatus('Challenge accepted · connecting to game…');

        // Poll gently for a short period. This prevents the phone from
        // getting stranded on the setup screen while the real game times out.
        const deadline = Date.now() + 9000;

        while (Date.now() < deadline && !acceptedGameId) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, 750),
          );

          try {
            const games = await getPlayingGames(token);
            const found = games.find(
              (game) =>
                game.opponent?.username?.toLowerCase() ===
                BOT_USERNAME.toLowerCase(),
            );

            if (found?.gameId) {
              acceptedGameId = found.gameId;
            }
          } catch {
            // A transient read failure should not abandon a game that
            // may already be starting.
          }
        }
      }

      if (!acceptedGameId) {
        throw (
          acceptError ||
          new Error(
            'The challenge was accepted, but the game did not become visible in time.',
          )
        );
      }

      setActiveGameId(acceptedGameId);
      setGameStatus('recovering');
      setStatus(`Game started against ${BOT_USERNAME}.`);
    } catch (error) {
      setStatus(
        `Could not start game: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    } finally {
      setStartingGame(false);
    }
  }

  async function scanSenseRobotRoom() {
    if (
      scanningRoom ||
      startingGame ||
      activeGame ||
      gameId ||
      !recoveryChecked
    ) {
      return;
    }

    setScanningRoom(true);

    try {
      setStatus('Preparing coach bot…');

      // Always apply the difficulty currently selected
      // in Chess Buddy before joining the SenseRobot room.
      const levelState = await setBotLevel(level);
      setBot(levelState);

      let state = levelState;

      if (!state.running) {
        state = await startBot();
        setBot(state);
      }

      if (!state.connected) {
        state = await waitForBotReady();
        setBot(state);
      }

      setStatus('Scan the SenseRobot room QR code…');

      const joined = await scanSenseRoom();

      setBot(joined);

      if (!joined.gameId) {
        throw new Error(
          'The room was joined, but Lichess did not report a game.'
        );
      }

      setActiveGameId(joined.gameId);

      // This successful QR scan is the one and only activation path
      // for SenseRobot mode.
      setSenseRobotGameId(joined.gameId);

      setGameStatus('recovering');

      setStatus(
        `SenseRobot room joined as ${BOT_USERNAME}.`
      );
    } catch (error) {
      setStatus(
        `Could not join SenseRobot room: ${
          error instanceof Error
            ? error.message
            : String(error)
        }`
      );
    } finally {
      setScanningRoom(false);
    }
  }

  function requestTakeback() {
    if (!token || !gameId) return;
    handleTakeback(token, gameId, true)
      .then(() => setStatus('Takeback requested. The training bot will accept it.'))
      .catch((error) => setStatus(`Takeback failed: ${String(error)}`));
  }

  async function endCurrentGame() {
    if (!token || !gameId || !activeGame || !endGameConfirm) return;
    try {
      setEndGameConfirm(false);
      if (position.plyCount < 2) {
        await abortGame(token, gameId);
        setStatus('Game aborted.');
      } else {
        await resignGame(token, gameId);
        setStatus('Game resigned.');
      }
      forgetStoredGame();
    } catch (error) {
      setStatus(`Could not end game: ${String(error)}`);
    }
  }

  function resetFinishedGame() {
    coachAbortRef.current?.abort();
    criticalQuestionAbortRef.current?.abort();
    criticalPromptRef.current = null;
    setCriticalPrompt(null);
    coachQueueRef.current = [];
    coachProcessingRef.current = false;

    forgetStoredGame();
    gameIdRef.current = null;
    setGameId(null);

    setSenseRobotGameId(null);

    setMoveEvaluations([]);

    setPuzzleOpen(false);
    setPuzzleIndex(0);
    setPuzzleFen('');
    setPuzzleState('solving');

    setPuzzleRollbackSignal(
      (value) => value + 1,
    );

    movesTextRef.current = '';
    setMovesText('');
    setInitialFen('startpos');
    setGameStatus('idle');
    setPlayers({ white: { name: 'White' }, black: { name: 'Black' } });
    setClock({ enabled: true, white: 600000, black: 600000, increment: 0, updatedAt: Date.now() });
    setCoachResult(null);
    setCoachNotes([]);
    setCoachError('');
    setPendingPromotion(null);
    pendingMoveRef.current = null;
    setMoveInFlight(false);
    setEndGameConfirm(false);
    setWinner(null);
    setGameOverOpen(false);
    setReviewMode(null);
    setReviewTarget(null);
    setRollbackSignal((value) => value + 1);
    setStatus('Ready for another training game.');
  }

  if (!token) {
    return <main className="landing">
      <div className="hero-card">
        <span className="eyebrow">AI CHESS COACH</span>
        <h1>Play a bot.<br />Learn every game.</h1>
        <p>Challenge the training bot on Lichess and get immediate, position-specific coaching when a move needs attention.</p>
        <button className="primary" onClick={() => void loginWithLichess()}>Sign in with Lichess</button>
        <p className="fine-print">AI coaching is enabled only in games against the designated training bot.</p>
      </div>
    </main>;
  }

  const topSide = orientation === 'white' ? 'black' : 'white';
  const bottomSide = orientation === 'white' ? 'white' : 'black';
  const coachingMoments = coachNotes.length;
  const blunders = coachNotes.filter((note) => note.classification === 'blunder').length;
  const mistakes = coachNotes.filter((note) => note.classification === 'mistake').length;
  const goodMoves = moveEvaluations.filter(
    (result) =>
      result.classification === 'good',
  ).length;

const practicePuzzles =
  selectPracticePuzzles(coachNotes);

const gameReport =
  buildGameReport(
    moveEvaluations,
    coachNotes,
    coachLanguage,
  );

const isChinese = coachLanguage === 'zh-CN';

const reportText = isChinese
  ? {
      report: '对局总结',
      closeAria: '关闭对局总结',
      reviewed: '已分析走法',
      strong: '优秀决定',
      moments: '学习时刻',
      puzzles: '练习题',

      whatWorked: '做得好的地方',
      nextFocus: '下一步重点',
      remember: '记住这一点',

      personalized: '个性化练习',
      practiceHeading: '练习这盘棋里的关键局面',
      finishing: '正在完成最后一步分析…',

      practice: '练习 →',
      noPuzzles: '这盘棋没有发现值得专门练习的关键局面。',

      close: '关闭总结',
      review: '复盘失误',
      practiceGame: '开始个性化练习',
      newGame: '开始新对局',
      viewReport: '查看对局总结',

      puzzleEyebrow: '个性化练习',
      puzzleWord: '练习题',
      fromMove: '来自第',
      moveSuffix: '回合',
      tryAgain: '重新挑战这个局面',
      closePuzzle: '关闭',
      puzzlePrompt: '找到最佳走法。',
      puzzlePromptDetail: '这个局面就来自你刚才的对局。',
      yourMove: '轮到你走。',
      incorrect:
        '还差一点。再检查一下将军、吃子、直接威胁和没有保护的棋子。',
      correctTitle: '很好，就是这一步！',
      bestMove: '最佳走法',
      showAnswer: '查看答案',
      nextPuzzle: '下一题',
      backToReport: '返回对局总结',
    }
  : {
      report: 'GAME REPORT',
      closeAria: 'Close game report',
      reviewed: 'moves reviewed',
      strong: 'strong decisions',
      moments: 'learning moments',
      puzzles: 'practice puzzles',

      whatWorked: 'WHAT WORKED',
      nextFocus: 'YOUR NEXT FOCUS',
      remember: 'ONE THING TO REMEMBER',

      personalized: 'PERSONALIZED PRACTICE',
      practiceHeading: 'Practice the key moments from this game',
      finishing: 'Finishing the last move analysis…',

      practice: 'Practice →',
      noPuzzles:
        'No major practice positions were generated from this game.',

      close: 'Close report',
      review: 'Review mistakes',
      practiceGame: 'Practice from this game',
      newGame: 'New training game',
      viewReport: 'View game report',

      puzzleEyebrow: 'PERSONALIZED PUZZLE',
      puzzleWord: 'Puzzle',
      fromMove: 'From move',
      moveSuffix: '',
      tryAgain: 'Try the position again',
      closePuzzle: 'Close',
      puzzlePrompt: 'Find the best move.',
      puzzlePromptDetail: 'This position came directly from your game.',
      yourMove: 'Your move.',
      incorrect:
        'Not quite. Look again for checks, captures, threats, and loose pieces.',
      correctTitle: "Nice — that's the move!",
      bestMove: 'Best move',
      showAnswer: 'Show answer',
      nextPuzzle: 'Next puzzle',
      backToReport: 'Back to game report',
    };

const activePuzzle =
  practicePuzzles[puzzleIndex] || null;

const puzzleChess =
  activePuzzle
    ? new Chess(
        puzzleFen ||
        activePuzzle.fenBefore,
      )
    : null;

const puzzleDestinations =
  puzzleChess
    ? destinations(puzzleChess)
    : new Map<string, string[]>();

const puzzleMovableColor:
  | 'white'
  | 'black'
  | undefined =
  puzzleChess
    ? puzzleChess.turn() === 'w'
      ? 'white'
      : 'black'
    : undefined;

  const focusLessons = Array.from(new Set(coachNotes.map((note) => note.lesson).filter(Boolean))).slice(0, 3);
  const botLabel = bot.connected ? 'Coach bot ready' : bot.running ? 'Coach bot connecting' : 'Coach bot offline';
  const selectedLevel = LEVELS.find((item) => item.id === level) || LEVELS[2];
  const selectedTimeControl = TIME_CONTROLS.find((item) => item.id === timeControlId) || TIME_CONTROLS[4];
  const reviewBestUci = reviewTarget?.bestMoveUci || '';
  const reviewReplyUci = reviewTarget?.opponentReplyUci || '';
  const reviewPlayedUci = reviewTarget?.playedMoveUci || '';
  const reviewOrientation = reviewTarget?.playerColor || myColor;
  const terminalGame = Boolean(gameId && !activeGame && gameStatus !== 'recovering' && gameStatus !== 'idle');
  const drawStatus = ['stalemate', 'draw', 'insufficientMaterialClaim'].includes(gameStatus);
  const gameOutcomeTitle = winner
    ? winner === myColor
      ? isChinese
        ? '你赢了！'
        : 'You won!'
      : isChinese
        ? '本局失利'
        : 'Game lost'
    : drawStatus
      ? isChinese
        ? '和棋'
        : 'Draw'
      : isChinese
        ? '对局结束'
        : 'Game ended';

  const gameOutcomeClass = winner
    ? winner === myColor
      ? 'win'
      : 'loss'
    : drawStatus
      ? 'draw'
      : 'ended';

  const gameScore =
    winner === 'white'
      ? '1–0'
      : winner === 'black'
        ? '0–1'
        : drawStatus
          ? '½–½'
          : '—';

  const gameReason = gameEndReason(
    gameStatus,
    winner,
    myColor,
    coachLanguage,
  );
  const orderedCoachNotes = [...coachNotes].sort((a, b) => a.ply - b.ply);

  const reviewIndex = reviewTarget
    ? orderedCoachNotes.findIndex(
        (note) => note.ply === reviewTarget.ply
      )
    : -1;

  function openPuzzle(index: number) {
  const puzzle =
    practicePuzzles[index];

  if (!puzzle) return;

  setPuzzleIndex(index);
  setPuzzleFen(puzzle.fenBefore);
  setPuzzleState('solving');

  setPuzzleRollbackSignal(
    (value) => value + 1,
  );

  setGameOverOpen(false);
  setPuzzleOpen(true);
}

function handlePuzzleMove(
  from: string,
  to: string,
) {
  if (!activePuzzle) return;

  if (
    puzzleState === 'correct' ||
    puzzleState === 'revealed'
  ) {
    return;
  }

  const playedUci =
    `${from}${to}`.toLowerCase();

  const answerUci =
    activePuzzle.bestMoveUci.toLowerCase();

  // startsWith also handles promotion moves such as e7e8q.
  if (
    answerUci.startsWith(playedUci)
  ) {
    const chess =
      new Chess(activePuzzle.fenBefore);

    chess.move({
        from,
        to,
        promotion:
          answerUci[4] || 'q',
      });

      setPuzzleFen(chess.fen());
      setPuzzleState('correct');
      return;
    }

    setPuzzleState('incorrect');

    // Snap the ChessBoard's optimistic visual
    // move back to the original position.
    setPuzzleRollbackSignal(
      (value) => value + 1,
    );
  }

  function revealPuzzleAnswer() {
    if (!activePuzzle) return;

    setPuzzleFen(
      activePuzzle.fenBefore,
    );

    setPuzzleState('revealed');

    setPuzzleRollbackSignal(
      (value) => value + 1,
    );
  }

  function closePuzzleToReport() {
    setPuzzleOpen(false);
    setGameOverOpen(true);
  }

  function openReviewAt(index: number) {
    if (!orderedCoachNotes.length) return;

    const normalized =
      (index + orderedCoachNotes.length) % orderedCoachNotes.length;

    setReviewTarget(orderedCoachNotes[normalized]);
  }

  function previousReview() {
    if (!orderedCoachNotes.length) return;

    openReviewAt(
      reviewIndex >= 0
        ? reviewIndex - 1
        : orderedCoachNotes.length - 1
    );
  }

  function nextReview() {
    if (!orderedCoachNotes.length) return;

    openReviewAt(
      reviewIndex >= 0
        ? reviewIndex + 1
        : 0
    );
  }

  function animateReviewChange(direction: 'next' | 'previous') {
    if (reviewAnimatingRef.current) return;

    if (orderedCoachNotes.length < 2) {
      setReviewDragging(false);
      setReviewDragX(0);
      return;
    }

    reviewAnimatingRef.current = true;
    setReviewDragging(false);

    const width = Math.max(window.innerWidth, 400);

    // Swipe left -> current review exits left.
    const outgoing =
      direction === 'next'
        ? -width
        : width;

    // New review enters from opposite side.
    const incoming = -outgoing;

    setReviewDragX(outgoing);

    window.setTimeout(() => {
      if (direction === 'next') {
        nextReview();
      } else {
        previousReview();
      }

      // Instantly move the NEW review to the opposite side.
      setReviewNoTransition(true);
      setReviewDragX(incoming);

      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          // Animate new review into the center.
          setReviewNoTransition(false);
          setReviewDragX(0);

          window.setTimeout(() => {
            reviewAnimatingRef.current = false;
          }, 220);
        });
      });
    }, 180);
  }

  return <div className="app-shell">
    <header>
      <div className="brand-row"><span className="eyebrow">AI CHESS COACH</span><strong>{account?.username || 'Connecting…'}</strong></div>
      <div className="header-actions">
        <span className={`status-dot ${bot.connected ? 'online' : 'offline'}`} />
        <span className="header-status">{status}</span>
        {bot.lastMoveMs != null ? <span className="speed-pill">bot {bot.lastMoveMs} ms</span> : null}
        <button className="ghost" onClick={() => { logout(); setToken(null); }}>Log out</button>
      </div>
    </header>

    <main className="game-layout">
      <section className="play-column">
        <PlayerBar player={players[topSide]} clock={displayedClock[topSide]} active={activeGame && turnColor === topSide} side={topSide} />
        <section className="board-panel">
          <ChessBoard
            fen={displayPosition.chess.fen()}
            orientation={orientation}
            movableColor={canMove ? myColor : undefined}
            destinations={canMove ? destinations(position.chess) : new Map()}
            lastMove={displayPosition.lastMove}
            coachArrows={historyPly == null ? coachArrows : []}
            coachHighlights={historyPly == null ? coachHighlights : []}
            rollbackSignal={rollbackSignal}
            onMove={handleBoardMove}
          />
        </section>
        <PlayerBar player={players[bottomSide]} clock={displayedClock[bottomSide]} active={activeGame && turnColor === bottomSide} side={bottomSide} />
        <div className="under-board">
          <span>
            {gameId ? (
              <span className="under-board-meta">
                <span>Training game</span>
                <span className="bot-level-pill">
                  {selectedLevel.label}
                  <small>~{selectedLevel.elo}</small>
                </span>
                <span>{currentTimeControlLabel}</span>
              </span>
            ) : 'No active game'}
          </span>
          <span>
            {gameId
              ? activeGame
                ? moveInFlight
                  ? 'Syncing your move…'
                  : isMyTurn
                    ? isSenseRobotGame
                      ? 'Your turn · move on SenseRobot'
                      : 'Your turn'
                    : `${players[turnColor].name} is thinking`
                : gameStatus === 'recovering'
                  ? 'Reconnecting to game…'
                  : `${gameOutcomeTitle} · ${gameReason}`
              : recoveryChecked
                ? 'Choose a level and start'
                : 'Checking for an active game…'}
          </span>
        </div>
      </section>

      <aside className="side-panel">
        {!gameId && <section className="card setup-card">
          <div className="section-title"><span>1</span> Training opponent</div>
          <p className="section-copy">Estimated practice strength — start low and move up when games feel comfortable.</p>
          <div className="level-grid">
            {LEVELS.map((item) => <button
              key={item.id}
              className={level === item.id ? 'level active' : 'level'}
              onClick={() => void changeLevel(item.id)}
            >
              <strong>{item.label}</strong>
              <small>~{item.elo} · {item.hint}</small>
            </button>)}
          </div>
          <div className="setup-subtitle">Time control</div>
          <div className="time-control-grid" role="group" aria-label="Choose time control">
            {TIME_CONTROLS.map((item) => <button
              key={item.id}
              className={timeControlId === item.id ? 'time-control active' : 'time-control'}
              onClick={() => changeTimeControl(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </button>)}
          </div>
          <div className="setup-subtitle">Your color</div>
          <div className="color-choice" role="group" aria-label="Choose your color">
            {(['random', 'white', 'black'] as const).map((color) => <button
              key={color}
              className={preferredColor === color ? 'active' : ''}
              onClick={() => setPreferredColor(color)}
            >{color === 'random' ? 'Random color' : `Play ${color}`}</button>)}
          </div>
          <div className="bot-runtime-row">
            <span><i className={`runtime-dot ${bot.connected ? 'on' : ''}`} />{botLabel}</span>
            <small>{bot.error ? 'Check backend setup' : selectedTimeControl.label}</small>
          </div>
          {bot.error ? <div className="inline-error">{bot.error}</div> : null}
          <button className="primary wide" disabled={startingGame || !recoveryChecked} onClick={() => void startCoachGame()}>
            {!recoveryChecked ? 'Checking active game…' : startingGame ? 'Starting…' : `Play ${BOT_USERNAME}`}
          </button>

          <button
            className="ghost wide"
            disabled={
              scanningRoom ||
              startingGame ||
              !recoveryChecked
            }
            onClick={() => void scanSenseRobotRoom()}
          >
            {scanningRoom
              ? 'Scanning…'
              : '▣ Scan SenseRobot Room'}
          </button>
        </section>}

        {gameId && <section className="card game-card">
          <div className="active-game-banner">
            <div>
              <span className="active-game-kicker">CURRENT OPPONENT</span>
              <strong>{selectedLevel.label}</strong>
              <small>Estimated strength ~{selectedLevel.elo}</small>
            </div>
            <div className="active-game-chips">
              <span>{currentTimeControlLabel}</span>
              <span>{isSenseRobotGame ? 'SenseRobot' : 'Phone'}</span>
            </div>
          </div>
          <div className="game-toolbar">
            <button className="icon-button" title="Flip board" onClick={() => setOrientation((value) => value === 'white' ? 'black' : 'white')}>⇅</button>
            <button className="icon-button" title="Request takeback" disabled={!activeGame} onClick={requestTakeback}>↶</button>
            <a className="icon-button" title="Open on Lichess" href={`https://lichess.org/${gameId}`} target="_blank" rel="noreferrer">↗</a>
          </div>
          {terminalGame ? <div className={`game-result-strip ${gameOutcomeClass}`}>
            <div><span>{gameOutcomeTitle}</span><strong>{gameReason}</strong></div>
            <b>{gameScore}</b>
          </div> : null}
          <div className="move-list">
              {position.san.length === 0 ? (
                <span className="muted">Moves will appear here.</span>
              ) : (
                Array.from(
                  { length: Math.ceil(position.san.length / 2) },
                  (_, index) => {
                    const whiteMoveIndex = index * 2;
                    const blackMoveIndex = index * 2 + 1;

                    const whitePly = whiteMoveIndex + 1;
                    const blackPly = blackMoveIndex + 1;

                    const whiteCoachNote = coachNotes.find(
                      (note) => note.ply === whitePly
                    );

                    const blackCoachNote = coachNotes.find(
                      (note) => note.ply === blackPly
                    );

                    const whiteMove = position.san[whiteMoveIndex];
                    const blackMove = position.san[blackMoveIndex];

                    return (
                      <div className="move-row" key={index}>
                        <b>{index + 1}.</b>

                        {whiteMove ? (
                          <button
                            type="button"
                            className={`move-cell ${
                              historyPly === whitePly ? 'active' : ''
                            } ${
                              whiteCoachNote?.classification === 'blunder'
                                ? 'move-blunder'
                                : whiteCoachNote?.classification === 'mistake'
                                  ? 'move-mistake'
                                  : ''
                            }`}
                            onClick={() => {
                              setHistoryPly(
                                whitePly >= position.plyCount
                                  ? null
                                  : whitePly
                              );
                            }}
                          >
                            {whiteMove}
                          </button>
                        ) : (
                          <span />
                        )}

                        {blackMove ? (
                          <button
                            type="button"
                            className={`move-cell ${
                              historyPly === blackPly ? 'active' : ''
                            } ${
                              blackCoachNote?.classification === 'blunder'
                                ? 'move-blunder'
                                : blackCoachNote?.classification === 'mistake'
                                  ? 'move-mistake'
                                  : ''
                            }`}
                            onClick={() => {
                              setHistoryPly(
                                blackPly >= position.plyCount
                                  ? null
                                  : blackPly
                              );
                            }}
                          >
                            {blackMove}
                          </button>
                        ) : (
                          <span />
                        )}
                      </div>
                    );
                  }
                )
              )}
            </div>
          <div className="game-actions">
            {activeGame ? (
              <button
                className="ghost"
                onClick={() => setEndGameConfirm(true)}
              >
                End game…
              </button>
            ) : null}

            {terminalGame ? (
              <button
                className="ghost report-reopen-button"
                onClick={() => setGameOverOpen(true)}
              >
                {reportText.viewReport}
              </button>
            ) : null}

            {!activeGame ? (
              <button
                className="primary"
                onClick={resetFinishedGame}
              >
                New training game
              </button>
            ) : null}
          </div>
        </section>}

        <section className="card coach-card">
          <div className="section-title">
            <span>2</span>

            {coachLanguage === 'zh-CN'
              ? 'AI 教练'
              : 'Live coach'}
          </div>
          <div className={`coach-bubble ${coachResult?.classification || ''}`}>
            {criticalPrompt && isMyTurn ? <>
              <div className="coach-heading">
                <strong>{criticalPrompt.title}</strong>
                <span className="quality-badge inaccuracy">
                  {coachLanguage === 'zh-CN'
                    ? '先想一想'
                    : 'Think first'}
                </span>
              </div>

              <div className="coach-question">
                <span>
                  {criticalPrompt.kind === 'opportunity'
                    ? coachLanguage === 'zh-CN'
                      ? '机会'
                      : 'Opportunity'
                    : criticalPrompt.kind === 'threat'
                      ? coachLanguage === 'zh-CN'
                        ? '对手意图'
                        : 'Opponent idea'
                      : coachLanguage === 'zh-CN'
                        ? '关键局面'
                        : 'Critical position'}
                </span>

                {criticalPrompt.question}
              </div>
            </> : coachThinking ? <div className="coach-thinking"><span className="spinner" />Analyzing your move…</div> : coachError ? <div className="inline-error">{coachError}</div> : coachResult ? <>
              <div className="coach-heading">
                <strong>{coachResult.title}</strong>
                {coachResult.shouldCoach ? (
                  <span className={`quality-badge ${coachResult.classification}`}>
                    {coachResult.classification}
                  </span>
                ) : null}
              </div>
              <div>{coachResult.feedback}</div>
              {coachResult.question ? (
                <div className="coach-question">
                  <span>
                    {coachLanguage === 'zh-CN'
                      ? '想一想'
                      : 'Ask yourself'}
                  </span>

                  {coachResult.question}
                </div>
              ) : null}
              {coachResult.lesson ? (
              <div className="coach-lesson">
                {coachLanguage === 'zh-CN'
                  ? '记住：'
                  : 'Remember: '}

                {coachResult.lesson}
              </div>
            ) : null}
              {coachResult.shouldCoach ? <button className="coach-review-button" onClick={() => { setReviewTarget(coachResult); setReviewMode('better'); }}>Review this position</button> : null}
            </> : <>
              <strong>Ready to coach</strong>
              <div>After each move, I’ll quickly check it. Bigger mistakes get a concrete explanation, best-move arrow, and the opponent’s threat when it matters.</div>
            </>}
          </div>
          <div className="coach-detail-setting">
            <span>
              {coachLanguage === 'zh-CN'
                ? '教练语言'
                : 'Coach language'}
            </span>

            <div className="coach-detail-options">
              {(
                [
                  ['en', 'English'],
                  ['zh-CN', '中文'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`coach-detail-button ${
                    coachLanguage === value
                      ? 'active'
                      : ''
                  }`}
                  aria-pressed={
                    coachLanguage === value
                  }
                  onClick={() => {
                    stopCoachSpeech();
                    setCoachLanguage(value);
                  }}
                >
                  <span>{label}</span>

                  {coachLanguage === value ? (
                    <span
                      className="coach-detail-check"
                      aria-hidden="true"
                    >
                      ✓
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
          <div className="coach-detail-setting">
            <span>Coach detail</span>

            <div className="coach-detail-options">
              {(
                [
                  ['quick', 'Quick'],
                  ['balanced', 'Balanced'],
                  ['deep', 'Deep'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`coach-detail-button ${
                    coachDetail === value ? 'active' : ''
                  }`}
                  aria-pressed={coachDetail === value}
                  onClick={() => setCoachDetail(value)}
                >
                  <span>{label}</span>
                  {coachDetail === value ? (
                    <span className="coach-detail-check" aria-hidden="true">✓</span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
          <div className="coach-actions">
            <label>
              <input
                type="checkbox"
                checked={voiceEnabled}
                onChange={(event) => {
                  const enabled =
                    event.target.checked;

                  setVoiceEnabled(enabled);

                  if (enabled) {
                    /*
                    * IMPORTANT:
                    * This happens directly inside a user click,
                    * so iOS can unlock audio playback.
                    */
                    void unlockCoachAudio();
                  } else {
                    stopCoachSpeech();
                  }
                }}
              />

              {coachLanguage === 'zh-CN'
                ? ' 语音'
                : ' Voice'}
            </label>
            <label><input type="checkbox" checked={hintsEnabled} onChange={(event) => setHintsEnabled(event.target.checked)} /> Board hints</label>
          </div>
          <div className="hint-legend"><span><i className="legend-line best" />best</span><span><i className="legend-line danger" />threat</span><span><i className="legend-square" />key square</span></div>
        </section>

        {(gameId || coachNotes.length > 0) && <section className="card learning-card">
          <div className="section-title learning-title"><span>3</span><div>Learning log{!gameId && coachNotes.length ? <small>Saved from your last game</small> : null}</div></div>
          {coachNotes.length === 0 ? <p className="muted">Your important coaching moments will collect here so you can review the exact position later.</p> : <div className="lesson-list">
            {orderedCoachNotes.map((note) => <button
              type="button"
              className="lesson-item"
              key={`${note.gameId}-${note.ply}`}
              onClick={() => { setReviewTarget(note); setReviewMode('better'); }}
            >
              <span className={`lesson-dot ${note.classification}`} />
              <div>
                <strong>Move {note.moveNumber} · {note.playedMove} · {note.title}</strong>
                <small>{note.lesson || 'Review the opponent’s forcing replies.'}</small>
              </div>
              <span className="review-chevron">›</span>
            </button>)}
          </div>}
          {!activeGame && coachNotes.length > 0 ? <div className="session-review">
            <strong>Game review</strong>
            <div className="review-stats"><span><b>{coachingMoments}</b> coach moments</span><span><b>{mistakes}</b> mistakes</span><span><b>{blunders}</b> blunders</span></div>
            {focusLessons.length ? <div className="focus-list"><span>Focus next game</span>{focusLessons.map((lesson) => <small key={lesson}>• {lesson}</small>)}</div> : <small className="muted">No major recurring issue found in this game.</small>}
          </div> : null}
        </section>}
      </aside>
    </main>

    {reviewMode && reviewTarget && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Review coached position" onMouseDown={(event) => { if (event.target === event.currentTarget) setReviewMode(null); }}>
      <div
        className="review-modal"
        style={{
          transform: `translate3d(${reviewDragX}px, 0, 0)`,
          transition:
            reviewNoTransition || reviewDragging
              ? 'none'
              : 'transform 180ms cubic-bezier(0.22, 1, 0.36, 1)',
          willChange: 'transform',
        }}
        onTouchStart={(event) => {
          if (reviewAnimatingRef.current) return;

          const touch = event.changedTouches[0];

          reviewTouchStart.current = {
            x: touch.clientX,
            y: touch.clientY,
          };

          setReviewDragging(true);
        }}
        onTouchMove={(event) => {
          if (
            !reviewTouchStart.current ||
            reviewAnimatingRef.current
          ) {
            return;
          }

          const touch = event.changedTouches[0];

          const dx =
            touch.clientX - reviewTouchStart.current.x;

          const dy =
            touch.clientY - reviewTouchStart.current.y;

          // Don't interfere with vertical scrolling.
          if (Math.abs(dy) > Math.abs(dx)) {
            return;
          }

          // Slight resistance makes it feel less stiff.
          setReviewDragX(dx * 0.9);
        }}
        onTouchEnd={(event) => {
          const start = reviewTouchStart.current;
          reviewTouchStart.current = null;

          if (!start || reviewAnimatingRef.current) {
            return;
          }

          const touch = event.changedTouches[0];

          const dx = touch.clientX - start.x;
          const dy = touch.clientY - start.y;

          // Not enough movement -> snap back.
          if (
            Math.abs(dx) < 65 ||
            Math.abs(dx) < Math.abs(dy)
          ) {
            setReviewDragging(false);
            setReviewDragX(0);
            return;
          }

          if (dx < 0) {
            animateReviewChange('next');
          } else {
            animateReviewChange('previous');
          }
        }}
      >
        <div className="review-modal-head">
          <div>
            <span className="eyebrow">COACH REVIEW</span>
            <strong>Move {reviewTarget.moveNumber} · {reviewTarget.playedMove}</strong>
            <small>{reviewTarget.title}</small>
          </div>
          <div className="review-nav">
            <span>
              {reviewIndex >= 0 ? reviewIndex + 1 : 1}
              {' / '}
              {orderedCoachNotes.length}
            </span>

            <button
              className="ghost"
              onClick={() => setReviewMode(null)}
            >
              Close
            </button>
          </div>
        </div>
        <div className="review-tabs">
          <button className={reviewMode === 'better' ? 'active' : ''} onClick={() => setReviewMode('better')}>Before your move</button>
          <button className={reviewMode === 'threat' ? 'active' : ''} onClick={() => setReviewMode('threat')}>After your move</button>
        </div>
        <div className="review-context">
          {reviewMode === 'better' ? 'This is the exact position where you had to choose your move.' : `This is the position immediately after ${reviewTarget.playedMove}.`}
        </div>
        <div className="review-board-wrap">
          <ChessBoard
            fen={reviewMode === 'better' ? reviewTarget.fenBefore : reviewTarget.fenAfter}
            orientation={reviewOrientation}
            movableColor={undefined}
            destinations={new Map()}
            lastMove={reviewMode === 'threat' && reviewPlayedUci.length >= 4 ? [reviewPlayedUci.slice(0, 2), reviewPlayedUci.slice(2, 4)] as [string, string] : undefined}
            coachArrows={reviewMode === 'better' && reviewBestUci.length >= 4
              ? [{ from: reviewBestUci.slice(0, 2), to: reviewBestUci.slice(2, 4), kind: 'best' }]
              : reviewMode === 'threat' && reviewReplyUci.length >= 4
                ? [{ from: reviewReplyUci.slice(0, 2), to: reviewReplyUci.slice(2, 4), kind: 'danger' }]
                : []}
            coachHighlights={reviewMode === 'better'
              ? (reviewTarget.highlightsBefore || [])
              : (reviewTarget.highlightsAfter || [])}
            rollbackSignal={0}
            onMove={() => undefined}
          />
        </div>
        <div className="review-explanation">
          <strong>
            {reviewMode === 'better'
              ? `Better: ${reviewTarget.bestMove}`
              : reviewTarget.opponentReply
                ? `Threat: ${reviewTarget.opponentReply}`
                : 'What changed?'}
          </strong>
          <p>
            {reviewMode === 'better'
              ? `Trace the green arrow and compare it with ${reviewTarget.playedMove}.`
              : reviewTarget.opponentReply
                ? 'The red arrow shows the strongest reply you needed to notice.'
                : 'Look at what changed immediately after your move.'}
          </p>
        </div>

        <div className="review-analysis">
          <div className="review-analysis-head">
            <span>COACH ANALYSIS</span>
            <span className={`quality-badge ${reviewTarget.classification}`}>
              {reviewTarget.classification}
            </span>
          </div>

          <p>{reviewTarget.feedback}</p>

          <div className="review-analysis-moves">
            <span>
              <small>You played</small>
              <strong>{reviewTarget.playedMove}</strong>
            </span>
            <span>
              <small>Better</small>
              <strong>{reviewTarget.bestMove}</strong>
            </span>
            {reviewTarget.opponentReply ? (
              <span>
                <small>Best reply</small>
                <strong>{reviewTarget.opponentReply}</strong>
              </span>
            ) : null}
          </div>

          {reviewTarget.lesson ? (
            <div className="review-analysis-lesson">
              <span>Remember</span>
              {reviewTarget.lesson}
            </div>
          ) : null}

          {reviewTarget.question ? (
            <div className="review-analysis-question">
              <span>Ask yourself</span>
              {reviewTarget.question}
            </div>
          ) : null}
        </div>
      </div>
    </div>}

    {gameOverOpen && terminalGame && (
      <div
        className="modal-backdrop game-over-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label={reportText.report}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            setGameOverOpen(false);
          }
        }}
      >
        <div
          className={`game-over-modal game-report-modal ${gameOutcomeClass}`}
        >
          <div className="game-report-topbar">
            <span className="eyebrow">
              {reportText.report}
            </span>

            <button
              type="button"
              className="report-close-button"
              aria-label={reportText.closeAria}
              onClick={() => setGameOverOpen(false)}
            >
              ×
            </button>
          </div>

          <div className="game-over-score">
            {gameScore}
          </div>

          <h2>{gameOutcomeTitle}</h2>
          <p>{gameReason}</p>

          <div className="game-report-stats">
            <span>
              <b>{moveEvaluations.length}</b>
              {reportText.reviewed}
            </span>

            <span>
              <b>{goodMoves}</b>
              {reportText.strong}
            </span>

            <span>
              <b>{coachingMoments}</b>
              {reportText.moments}
            </span>

            <span>
              <b>{practicePuzzles.length}</b>
              {reportText.puzzles}
            </span>
          </div>

          {coachThinking ? (
            <div className="report-finishing">
              {reportText.finishing}
            </div>
          ) : null}

          <div className="game-report-grid">
            <section className="report-card positive">
              <span className="report-card-label">
                {reportText.whatWorked}
              </span>

              {gameReport.strengths.map(
                (strength, index) => (
                  <p key={index}>
                    <span className="report-icon">
                      ✓
                    </span>
                    {strength}
                  </p>
                ),
              )}
            </section>

            <section className="report-card improve">
              <span className="report-card-label">
                {reportText.nextFocus}
              </span>

              {gameReport.improvements.map(
                (improvement, index) => (
                  <p key={index}>
                    <span className="report-icon">
                      →
                    </span>
                    {improvement}
                  </p>
                ),
              )}
            </section>
          </div>

          <div className="report-takeaway">
            <span>{reportText.remember}</span>
            <p>{gameReport.takeaway}</p>
          </div>

          <div className="practice-section">
            <div className="practice-heading">
              <div>
                <span className="eyebrow">
                  {reportText.personalized}
                </span>

                <strong>
                  {reportText.practiceHeading}
                </strong>
              </div>

              <b>{practicePuzzles.length}</b>
            </div>

            {practicePuzzles.length ? (
              <div className="practice-list">
                {practicePuzzles.map(
                  (puzzle, index) => (
                    <button
                      key={puzzle.ply}
                      className="practice-card"
                      onClick={() => openPuzzle(index)}
                    >
                      <span className="practice-number">
                        {index + 1}
                      </span>

                      <span className="practice-copy">
                        <strong>
                          {practicePuzzleTitle(
                            puzzle,
                            coachLanguage,
                          )}
                        </strong>

                        <small>
                          {isChinese
                            ? `${reportText.fromMove} ${puzzle.moveNumber} ${reportText.moveSuffix} · ${reportText.tryAgain}`
                            : `${reportText.fromMove} ${puzzle.moveNumber} · ${reportText.tryAgain}`}
                        </small>
                      </span>

                      <span className="practice-play">
                        {reportText.practice}
                      </span>
                    </button>
                  ),
                )}
              </div>
            ) : (
              <p className="practice-empty">
                {reportText.noPuzzles}
              </p>
            )}
          </div>

          <div className="game-over-actions">
            <button
              className="ghost"
              onClick={() => setGameOverOpen(false)}
            >
              {reportText.close}
            </button>

            <button
              className="ghost"
              disabled={!orderedCoachNotes.length}
              onClick={() => {
                const first = orderedCoachNotes[0];

                if (!first) return;

                setGameOverOpen(false);
                setReviewTarget(first);
                setReviewMode('better');
              }}
            >
              {reportText.review}
            </button>

            {practicePuzzles.length ? (
              <button
                className="primary"
                onClick={() => openPuzzle(0)}
              >
                {reportText.practiceGame}
              </button>
            ) : (
              <button
                className="primary"
                onClick={resetFinishedGame}
              >
                {reportText.newGame}
              </button>
            )}

            {practicePuzzles.length ? (
              <button
                className="ghost full-width"
                onClick={resetFinishedGame}
              >
                {reportText.newGame}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    )}

{puzzleOpen && activePuzzle && (
      <div
        className="modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label={reportText.puzzleEyebrow}
      >
        <div className="puzzle-modal">
          <div className="puzzle-head">
            <div>
              <span className="eyebrow">
                {reportText.puzzleEyebrow}
              </span>

              <strong>
                {reportText.puzzleWord} {puzzleIndex + 1}
                {' / '}
                {practicePuzzles.length}
              </strong>

              <small>
                {isChinese
                  ? `${reportText.fromMove} ${activePuzzle.moveNumber} ${reportText.moveSuffix}`
                  : `${reportText.fromMove} ${activePuzzle.moveNumber}`}
              </small>
            </div>

            <button
              className="ghost"
              onClick={closePuzzleToReport}
            >
              {reportText.closePuzzle}
            </button>
          </div>

          <div className="puzzle-prompt">
            <strong>
              {reportText.puzzlePrompt}
            </strong>

            <span>
              {reportText.puzzlePromptDetail}
            </span>
          </div>

          <div className="review-board-wrap">
            <ChessBoard
              fen={
                puzzleFen ||
                activePuzzle.fenBefore
              }
              orientation={
                activePuzzle.playerColor
              }
              movableColor={
                puzzleState === 'correct' ||
                puzzleState === 'revealed'
                  ? undefined
                  : puzzleMovableColor
              }
              destinations={
                puzzleState === 'correct' ||
                puzzleState === 'revealed'
                  ? new Map()
                  : puzzleDestinations
              }
              lastMove={undefined}
              coachArrows={
                puzzleState === 'revealed'
                  ? [
                      {
                        from:
                          activePuzzle.bestMoveUci.slice(
                            0,
                            2,
                          ),
                        to:
                          activePuzzle.bestMoveUci.slice(
                            2,
                            4,
                          ),
                        kind: 'best',
                      },
                    ]
                  : []
              }
              coachHighlights={[]}
              rollbackSignal={
                puzzleRollbackSignal
              }
              onMove={
                handlePuzzleMove
              }
            />
          </div>

          {puzzleState === 'solving' ? (
            <div className="puzzle-feedback neutral">
              {reportText.yourMove}
            </div>
          ) : null}

          {puzzleState === 'incorrect' ? (
            <div className="puzzle-feedback wrong">
              {reportText.incorrect}
            </div>
          ) : null}

          {puzzleState === 'correct' ? (
            <div className="puzzle-feedback correct">
              <strong>
                {reportText.correctTitle}
              </strong>

              <span>
                {activePuzzle.lesson ||
                  activePuzzle.feedback}
              </span>
            </div>
          ) : null}

          {puzzleState === 'revealed' ? (
            <div className="puzzle-feedback revealed">
              <strong>
                {reportText.bestMove}:{' '}
                {activePuzzle.bestMove}
              </strong>

              <span>
                {activePuzzle.lesson ||
                  activePuzzle.feedback}
              </span>
            </div>
          ) : null}

          <div className="puzzle-actions">
            {puzzleState !== 'correct' &&
            puzzleState !== 'revealed' ? (
              <button
                className="ghost"
                onClick={
                  revealPuzzleAnswer
                }
              >
                {reportText.showAnswer}
              </button>
            ) : null}

            {(puzzleState === 'correct' ||
              puzzleState === 'revealed') &&
            puzzleIndex <
              practicePuzzles.length - 1 ? (
              <button
                className="primary"
                onClick={() =>
                  openPuzzle(
                    puzzleIndex + 1,
                  )
                }
              >
                {reportText.nextPuzzle}
              </button>
            ) : null}

            {(puzzleState === 'correct' ||
              puzzleState === 'revealed') &&
            puzzleIndex ===
              practicePuzzles.length - 1 ? (
              <button
                className="primary"
                onClick={
                  closePuzzleToReport
                }
              >
                {reportText.backToReport}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    )}

    {endGameConfirm && gameId && activeGame && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Confirm end game" onMouseDown={(event) => { if (event.target === event.currentTarget) setEndGameConfirm(false); }}>
      <div className="confirm-modal">
        <span className="eyebrow">END TRAINING GAME</span>
        <strong>{position.plyCount < 2 ? 'Abort this game?' : 'Resign this game?'}</strong>
        <p>Refreshing or closing this page will not end the game. Only this confirmation sends an end-game request to Lichess.</p>
        <div className="confirm-actions">
          <button className="ghost" onClick={() => setEndGameConfirm(false)}>Keep playing</button>
          <button className="danger-button" onClick={() => void endCurrentGame()}>{position.plyCount < 2 ? 'Abort game' : 'Resign game'}</button>
        </div>
      </div>
    </div>}

    {pendingPromotion && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Choose promotion piece">
      <div className="promotion-modal">
        <strong>Promote pawn to</strong>
        <div className="promotion-options">
          {pendingPromotion.choices.map((choice) => <button key={choice} onClick={() => void submitMove(pendingPromotion.fenBefore, pendingPromotion.basePly, pendingPromotion.from, pendingPromotion.to, choice)}>
            {{ q: '♕', r: '♖', b: '♗', n: '♘' }[choice]}
          </button>)}
        </div>
        <button className="ghost" onClick={() => { setPendingPromotion(null); setRollbackSignal((value) => value + 1); }}>Cancel</button>
      </div>
    </div>}
  </div>;
}