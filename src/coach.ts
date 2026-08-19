export type CoachArrow = {
  from: string;
  to: string;
  kind?: 'best' | 'danger' | 'idea';
};

export type CoachResult = {
  shouldCoach: boolean;
  moveNumber: number;
  ply: number;
  playedMove: string;
  playedMoveUci: string;
  classification: 'good' | 'inaccuracy' | 'mistake' | 'blunder';
  centipawnLoss: number;
  bestMove: string;
  bestMoveUci: string;
  opponentReply?: string;
  opponentReplyUci?: string;
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
  fenAfter: string;

  feedback: string;
  title: string;
  lesson?: string;
  question?: string;

  arrows?: CoachArrow[];
  highlightsBefore?: string[];
  highlightsAfter?: string[];

  themeHint?: string;
  bestLine?: string[];
  refutationLine?: string[];

  // Two-phase coaching:
  // Stockfish returns immediately, then the LLM wording arrives separately.
  analysisId?: string;
  explanationPending?: boolean;
};

export type CoachDetail =
  | 'quick'
  | 'balanced'
  | 'deep';

export type CoachLanguage =
  | 'en'
  | 'zh-CN';

export type CoachWording = {
  title: string;
  feedback: string;
  lesson: string;
  question: string;
};

const CONTROL_URL =
  import.meta.env.VITE_BOT_CONTROL_URL ||
  'http://127.0.0.1:8765';


export async function analyzeMove(
  fen: string,
  move: string,
  detailOrSignal: CoachDetail | AbortSignal = 'balanced',
  maybeSignal?: AbortSignal,
  language: CoachLanguage = 'en',
): Promise<CoachResult> {
  const detail: CoachDetail =
    typeof detailOrSignal === 'string'
      ? detailOrSignal
      : 'balanced';

  const signal =
    typeof detailOrSignal === 'string'
      ? maybeSignal
      : detailOrSignal;

  const response = await fetch(
    `${CONTROL_URL}/api/coach/analyze`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        fen,
        move,
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

  return data as CoachResult;
}


/**
 * Fetch conversational wording for a Stockfish analysis already cached
 * by the backend. This request does not run Stockfish again.
 */
export async function explainMove(
  analysisId: string,
  detail: CoachDetail = 'balanced',
  language: CoachLanguage = 'en',
  recentFeedback: string[] = [],
  signal?: AbortSignal,
): Promise<CoachWording> {
  const response = await fetch(
    `${CONTROL_URL}/api/coach/explain`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        analysisId,
        detail,
        language,
        recentFeedback,
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

  return data as CoachWording;
}


export type CriticalPositionPrompt = {
  isCritical: boolean;
  kind?: 'threat' | 'opportunity' | 'decision' | 'check';
  title?: string;
  question?: string;
};

export async function checkCriticalPosition(
  fen: string,
  lastOpponentMove: string,
  lastOpponentMoveUci: string,
  language: CoachLanguage = 'en',
  recentQuestions: string[] = [],
  signal?: AbortSignal,
): Promise<CriticalPositionPrompt> {
  const response = await fetch(
    `${CONTROL_URL}/api/coach/critical-question`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        fen,
        lastOpponentMove,
        lastOpponentMoveUci,
        language,
        recentQuestions,
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

  return data as CriticalPositionPrompt;
}
