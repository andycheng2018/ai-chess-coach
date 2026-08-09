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
};

const CONTROL_URL = import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';

export async function analyzeMove(fen: string, move: string, signal?: AbortSignal): Promise<CoachResult> {
  const response = await fetch(`${CONTROL_URL}/api/coach/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen, move }),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `${response.status} ${response.statusText}`);
  return data as CoachResult;
}
