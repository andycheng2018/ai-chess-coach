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
  fenBefore: string;
  fenAfter: string;
  feedback: string;
  title: string;
  lesson?: string;
  question?: string;
  arrows?: CoachArrow[];
  highlightsBefore?: string[];
  highlightsAfter?: string[];

  // Extra deterministic facts used for better post-game filtering.
  themeHint?: string;
  bestLine?: string[];
  refutationLine?: string[];

  // Two-phase coaching: Stockfish returns immediately, then the LLM
  // wording is fetched separately without blocking the move queue.
  analysisId?: string;
  explanationPending?: boolean;
};

export type CoachDetail = 'quick' | 'balanced' | 'deep';

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
  import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';

/**
 * Fast move analysis.
 *
 * This endpoint returns Stockfish truth immediately. For a mistake/blunder,
 * analysisId is included so the slower LLM wording can be fetched separately.
 */
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

  const response = await fetch(`${CONTROL_URL}/api/coach/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fen,
      move,
      detail,
      language,
    }),
    signal,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.message || `${response.status} ${response.statusText}`,
    );
  }

  return data as CoachResult;
}

/**
 * Fetch the conversational explanation for a move that Stockfish already
 * analyzed. This does not re-run Stockfish; the backend reuses the cached
 * deterministic analysis identified by analysisId.
 */
export async function explainMove(
  analysisId: string,
  detail: CoachDetail = 'balanced',
  language: CoachLanguage = 'en',
  signal?: AbortSignal,
): Promise<CoachWording> {
  const response = await fetch(`${CONTROL_URL}/api/coach/explain`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      analysisId,
      detail,
      language,
    }),
    signal,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.message || `${response.status} ${response.statusText}`,
    );
  }

  return data as CoachWording;
}
