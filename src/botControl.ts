export type BotRuntimeStatus = {
  running: boolean;
  connected?: boolean;
  username?: string;
  level?: string;
  displayElo?: number;
  lastMoveMs?: number | null;
  activeGames?: number;
  lastGameId?: string | null;
  demoGames?: string[];
  unratedGames?: string[];
  gameId?: string | null;
  error?: string | null;
  message?: string;
};

export type CachedGameState = {
  gameId: string;
  initialFen: string;
  state: {
    moves?: string;
    status?: string;
    winner?: 'white' | 'black';
    wtime?: number;
    btime?: number;
    winc?: number;
    binc?: number;
    [key: string]: unknown;
  };
  updatedAt: number;
};

const CONTROL_URL = (typeof window !== 'undefined' && window.__CHESS_BACKEND_URL__) || import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';

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

export function setBotDemoMode(gameId: string, enabled: boolean): Promise<BotRuntimeStatus> {
  return jsonRequest(`/api/bot/game/${encodeURIComponent(gameId)}/demo-mode`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}

export function setBotLevel(level: string): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/level', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
}

export function joinSenseRoom(
  challengeId: string,
  color: 'white' | 'black',
  opponent: string,
): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/join-room', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      challengeId,
      color,
      opponent,
    }),
  });
}

export type SenseRoom = {
  challengeId: string;
  color: 'white' | 'black';
};

export function buildSenseRoomUrl(
  eightCharacterId: string,
  explicitBotColor: 'white' | 'black',
): string {
  if (!/^[a-zA-Z0-9]{8}$/.test(eightCharacterId)) {
    throw new Error('Invalid Lichess challenge ID.');
  }
  if (explicitBotColor !== 'white' && explicitBotColor !== 'black') {
    throw new Error('The room URL must specify white or black.');
  }
  return `https://lichess.org/${eightCharacterId}?color=${explicitBotColor}`;
}

export type SetupHealth = {
  ok: boolean;
  stockfish: string | null;
  warning?: string | null;
  coach?: { configured: boolean };
};

export function getSetupHealth(): Promise<SetupHealth> {
  return jsonRequest('/api/health', { signal: AbortSignal.timeout(5000) });
}

export function parseSenseRoomUrl(rawValue: string): SenseRoom {
  let url: URL;

  try {
    url = new URL(rawValue.trim());
  } catch {
    throw new Error('This QR code is not a valid URL.');
  }

  if (
    url.protocol !== 'https:' ||
    url.hostname.toLowerCase() !== 'lichess.org'
  ) {
    throw new Error('This is not a Lichess room QR code.');
  }

  const parts = url.pathname
    .split('/')
    .filter(Boolean);

  // SenseRobot invitations also use Lichess's /game/<id> route.
  const challengeId = parts.length === 1 ? parts[0]
    : parts.length === 2 && parts[0] === 'game' ? parts[1] : '';

  if (!challengeId) {
    throw new Error('Invalid Lichess room URL.');
  }

  // Lichess challenge/game IDs are 8 characters.
  if (!/^[a-zA-Z0-9]{8}$/.test(challengeId)) {
    throw new Error('Invalid Lichess challenge ID.');
  }

  const color = url.searchParams.get('color');

  if (color !== 'white' && color !== 'black') {
    throw new Error(
      'The room QR code does not specify white or black.'
    );
  }

  return {
    challengeId,
    color,
  };
}

export async function getCachedGameState(
  gameId: string,
): Promise<CachedGameState | null> {
  const response = await fetch(
    `${CONTROL_URL}/api/bot/game/${encodeURIComponent(gameId)}/state`,
  );

  if (response.status === 404) {
    return null;
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.message ||
        `${response.status} ${response.statusText}`,
    );
  }

  return data as CachedGameState;
}
