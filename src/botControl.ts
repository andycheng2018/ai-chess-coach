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

export function joinSenseRoom(
  challengeId: string,
  color: 'white' | 'black',
): Promise<BotRuntimeStatus> {
  return jsonRequest('/api/bot/join-room', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      challengeId,
      color,
    }),
  });
}

export type SenseRoom = {
  challengeId: string;
  color: 'white' | 'black';
};

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

  if (parts.length !== 1) {
    throw new Error('Invalid Lichess room URL.');
  }

  const challengeId = parts[0];

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