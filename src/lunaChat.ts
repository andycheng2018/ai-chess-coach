import { CONTROL_URL, type CoachDetail, type CoachLanguage } from './coach';

export type ChatPosition = { fen: string; rootFen: string; moves: string[] };
export type ChatRequest = ChatPosition & {
  sessionId: string; requestId: string; message: string; language: CoachLanguage; detail: CoachDetail;
};
export type ChatTurn = {
  requestId: string; recordId: string; sessionId: string; fen: string;
  message: string; reply: string; savedAt: number; language: CoachLanguage;
};
export type ChatCache = { turns: ChatTurn[]; draft: string; attempt?: ChatRequest };
const key = (sessionId: string) => `ai-chess-coach.chat.v1:${sessionId}`;

export function mergeChatTurns(current: ChatTurn[], incoming: ChatTurn[]): ChatTurn[] {
  const turns = new Map(current.map(turn => [turn.requestId, turn]));
  incoming.forEach(turn => turns.set(turn.requestId, turn));
  return [...turns.values()].sort((a, b) => a.savedAt - b.savedAt);
}

export function readChatCache(sessionId: string): ChatCache {
  try {
    const data = JSON.parse(window.localStorage.getItem(key(sessionId)) || '{}') as ChatCache;
    return { turns: Array.isArray(data.turns) ? data.turns.filter(turn => turn.sessionId === sessionId
      && typeof turn.message === 'string' && typeof turn.reply === 'string' && typeof turn.fen === 'string') : [],
      draft: typeof data.draft === 'string' ? data.draft : '',
      attempt: data.attempt?.sessionId === sessionId ? data.attempt : undefined };
  } catch { return { turns: [], draft: '' }; }
}

export function writeChatCache(sessionId: string, cache: ChatCache): boolean {
  try { window.localStorage.setItem(key(sessionId), JSON.stringify(cache)); return true; }
  catch { return false; }
}

async function chatFetch(path: string, options?: RequestInit) {
  const response = await fetch(`${CONTROL_URL}${path}`, { ...options, signal: AbortSignal.timeout(65000) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `Luna is unavailable (${response.status}).`);
  return data;
}

export async function loadChat(sessionId: string): Promise<ChatTurn[]> {
  const data = await chatFetch(`/api/coach/chat?sessionId=${encodeURIComponent(sessionId)}`);
  return data.turns || [];
}

export async function sendChat(request: ChatRequest): Promise<ChatTurn> {
  return chatFetch('/api/coach/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request) });
}

export function positionLabel(fen: string, chinese = false): string {
  const parts = fen.split(' ');
  return chinese ? `第 ${parts[5]} 回合 · ${parts[1] === 'w' ? '白方' : '黑方'}走棋`
    : `Move ${parts[5]} · ${parts[1] === 'w' ? 'White' : 'Black'} to move`;
}
