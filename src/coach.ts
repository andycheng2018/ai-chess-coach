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
  bestMoveVerifiedThemes?: ChessTheme[];
  opponentReplyVerifiedThemes?: ChessTheme[];
  bestMoveVerifiedThemeEvidence?: ThemeEvidence[];
  opponentReplyVerifiedThemeEvidence?: ThemeEvidence[];
  bestMoveFacts?: VerifiedMoveFacts;
  opponentReplyFacts?: VerifiedMoveFacts;
  evaluationBefore?: number;
  evaluationAfter?: number;

  engineDiagnostics?: {
    profile?: 'quick' | 'balanced' | 'deep';
    budgetMs?: number;
    pvPlies?: number;
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
  themes?: ChessTheme[];
  bestLine?: string[];
  refutationLine?: string[];

  // Two-phase coaching:
  // Stockfish returns immediately, then the LLM wording arrives separately.
  analysisId?: string;
  explanationPending?: boolean;

  openingEco?: string;
  openingName?: string;
  openingVariation?: string;
  openingDepthMatched?: number;
  openingInBook?: boolean;
  openingLeftBookAt?: number | null;
  openingBookMove?: string | null;
  openingBookMoveUci?: string | null;
  openingTransposed?: boolean;
};

export type OpeningState = {
  eco: string;
  name: string;
  variation: string;
  depthMatched: number;
  inBook: boolean;
  leftBookAt: number | null;
  bookMove?: string | null;
  bookMoveUci?: string | null;
  transposed?: boolean;
};

export type ThemeEvidence = {
  theme: ChessTheme;
  reason: string;
};

export type VerifiedMoveFacts = {
  move: string;
  move_uci: string;
  moved_piece: string;
  from: string;
  to: string;
  is_capture: boolean;
  captured_piece: string;
  gives_check: boolean;
  is_checkmate: boolean;
  attacked_enemy_pieces: string[];
};

export type CoachDetail =
  | 'quick'
  | 'balanced'
  | 'deep';

export type ChessTheme =
  | 'Fork / Double Attack'
  | 'Pin'
  | 'Skewer'
  | 'Discovered Attack'
  | 'Discovered Check'
  | 'Double Check'
  | 'X-Ray Attack'
  | 'Defense'
  | 'Back-Rank Weakness'
  | 'Back-Rank Mate'
  | 'Deflection'
  | 'Decoy'
  | 'Removal of the Defender'
  | 'Overloading'
  | 'Interference'
  | 'Clearance'
  | 'Clearance Sacrifice'
  | 'Sacrifice'
  | 'Exchange Sacrifice'
  | 'Queen Sacrifice'
  | 'Zwischenzug'
  | 'Desperado'
  | 'Hanging Piece'
  | 'Trapped Piece'
  | 'Mating Net'
  | 'Smothered Mate'
  | 'Support Mate'
  | 'Checkmate Pattern'
  | 'Mate in One'
  | 'Mate in Two'
  | 'Mate in Three or More'
  | 'Forced Mate'
  | 'Perpetual Check'
  | 'Windmill'
  | 'Attack on f7 / f2'
  | 'Attacking the Castled King'
  | 'Vulnerable King'
  | 'King Safety'
  | 'Simplification'
  | 'Promotion'
  | 'Underpromotion'
  | 'En Passant'
  | 'Stalemate'
  | 'Zugzwang'
  | 'Endgame Tactic'
  | 'Passed Pawn'
  | 'Opposition'
  | 'Open File'
  | 'Weak Square';

export type CoachLanguage =
  | 'en'
  | 'zh-CN';

export type CoachWording = {
  title: string;
  feedback: string;
  lesson: string;
  question: string;
  themes: ChessTheme[];
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
  moves: string[] = [],
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
        moves,
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


export async function fetchOpeningStatus(
  moves: string[],
  signal?: AbortSignal,
): Promise<OpeningState> {
  const response = await fetch(
    `${CONTROL_URL}/api/coach/opening`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ moves }),
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

  return data as OpeningState;
}


export type CriticalPositionPrompt = {
  isCritical: boolean;
  mateThreat?: boolean;
  kind?: 'threat' | 'opportunity' | 'decision' | 'check';
  title?: string;
  question?: string;
};

export async function checkCriticalPosition(
  fen: string,
  fenBeforeOpponent: string,
  lastOpponentMove: string,
  lastOpponentMoveUci: string,
  language: CoachLanguage = 'en',
  detail: CoachDetail = 'balanced',
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
        fenBeforeOpponent,
        lastOpponentMove,
        lastOpponentMoveUci,
        language,
        detail,
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
