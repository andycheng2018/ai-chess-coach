export type BotRuntimeStatus = {
  running: boolean;
  connected?: boolean;
  username?: string;
  level?: string;
  displayElo?: number;
  lastMoveMs?: number | null;
  activeGames?: number;
  lastGameId?: string | null;
  gameId?: string | null;
  error?: string | null;
  message?: string;
};

const CONTROL_URL = import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';

async function jsonRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${CONTROL_URL}${path}`, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `${response.status} ${response.statusText}`);
  return data as T;
}

export function getBotStatus(): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/status');
}

export function startBot(): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/start', { method: 'POST' });
}

export function acceptBotChallenge(challengeId: string, opponent: string): Promise<BotRuntimeStatus> {
  return jsonRequest(`/api/bot/challenge/${encodeURIComponent(challengeId)}/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ opponent }),
  });
}

export function setBotLevel(level: string): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/level', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
}
