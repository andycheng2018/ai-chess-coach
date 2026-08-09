export type Account = { id: string; username: string };
export type Challenge = {
  id: string;
  challenger?: { name?: string; id?: string; title?: string };
  destUser?: { name?: string; id?: string; title?: string };
  status?: string;
};
export type StreamEvent = {
  type: string;
  challenge?: Challenge;
  game?: { id: string; fullId?: string; color?: 'white' | 'black'; opponent?: { username?: string } };
};
export type PlayingGame = {
  gameId: string;
  color?: 'white' | 'black';
  opponent?: { username?: string };
  isMyTurn?: boolean;
};

export class LichessHttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'LichessHttpError';
    this.status = status;
  }
}

const BASE_URL = 'https://lichess.org';

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function checkedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const message = (await response.text()).trim();
    throw new LichessHttpError(
      response.status,
      `${response.status} ${response.statusText}${message ? `: ${message}` : ''}`,
    );
  }
  return response;
}

export async function getAccount(token: string): Promise<Account> {
  return (await checkedFetch(`${BASE_URL}/api/account`, { headers: authHeaders(token) })).json();
}

export async function getPlayingGames(token: string): Promise<PlayingGame[]> {
  const payload = await (await checkedFetch(`${BASE_URL}/api/account/playing`, { headers: authHeaders(token) })).json();
  return Array.isArray(payload?.nowPlaying) ? payload.nowPlaying : [];
}

export type ChallengeTimeControl =
  | { type: 'clock'; limitSeconds: number; incrementSeconds: number }
  | { type: 'unlimited' };

export async function challengeBot(
  token: string,
  botUsername: string,
  options: { timeControl: ChallengeTimeControl; color: 'random' | 'white' | 'black' },
): Promise<Challenge> {
  const body = new URLSearchParams({
    rated: 'false',
    variant: 'standard',
    color: options.color,
    keepAliveStream: 'false',
  });
  // Lichess creates an unlimited challenge when both clock and correspondence
  // parameters are omitted. Clocked games send the standard clock fields.
  if (options.timeControl.type === 'clock') {
    body.set('clock.limit', String(options.timeControl.limitSeconds));
    body.set('clock.increment', String(options.timeControl.incrementSeconds));
  }
  const payload = await (await checkedFetch(`${BASE_URL}/api/challenge/${encodeURIComponent(botUsername)}`, {
    method: 'POST',
    headers: { ...authHeaders(token), 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })).json();
  const challenge = (payload?.challenge ?? payload) as Challenge;
  if (!challenge?.id) throw new Error('Lichess did not return a challenge id.');
  return challenge;
}

export async function makeMove(token: string, gameId: string, move: string): Promise<void> {
  await checkedFetch(`${BASE_URL}/api/board/game/${gameId}/move/${move}`, { method: 'POST', headers: authHeaders(token) });
}
export async function resignGame(token: string, gameId: string): Promise<void> {
  await checkedFetch(`${BASE_URL}/api/board/game/${gameId}/resign`, { method: 'POST', headers: authHeaders(token) });
}
export async function abortGame(token: string, gameId: string): Promise<void> {
  await checkedFetch(`${BASE_URL}/api/board/game/${gameId}/abort`, { method: 'POST', headers: authHeaders(token) });
}
export async function handleTakeback(token: string, gameId: string, accept: boolean): Promise<void> {
  await checkedFetch(`${BASE_URL}/api/board/game/${gameId}/takeback/${accept ? 'yes' : 'no'}`, { method: 'POST', headers: authHeaders(token) });
}

async function readNdjson(response: Response, onEvent: (event: any) => void, signal?: AbortSignal): Promise<void> {
  if (!response.body) throw new Error('Streaming response has no body.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (!signal?.aborted) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let breakAt = buffer.indexOf('\n');
    while (breakAt >= 0) {
      const line = buffer.slice(0, breakAt).trim();
      buffer = buffer.slice(breakAt + 1);
      if (line) onEvent(JSON.parse(line));
      breakAt = buffer.indexOf('\n');
    }
  }
  const tail = buffer.trim();
  if (tail && !signal?.aborted) onEvent(JSON.parse(tail));
}

export async function streamEvents(token: string, onEvent: (event: StreamEvent) => void, signal: AbortSignal): Promise<void> {
  const response = await checkedFetch(`${BASE_URL}/api/stream/event`, {
    headers: { ...authHeaders(token), Accept: 'application/x-ndjson' },
    signal,
  });
  await readNdjson(response, onEvent, signal);
}

export async function streamGame(token: string, gameId: string, onEvent: (event: any) => void, signal: AbortSignal): Promise<void> {
  const response = await checkedFetch(`${BASE_URL}/api/board/game/stream/${gameId}`, {
    headers: { ...authHeaders(token), Accept: 'application/x-ndjson' },
    signal,
  });
  await readNdjson(response, onEvent, signal);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function isRetryableStreamError(error: unknown): boolean {
  if (!(error instanceof LichessHttpError)) return true;

  return (
    error.status === 404 ||
    error.status === 408 ||
    error.status === 425 ||
    error.status === 429 ||
    error.status >= 500
  );
}

export async function retryingStream(
  open: (signal: AbortSignal) => Promise<void>,
  signal: AbortSignal,
  onReconnect?: (attempt: number) => void,
  onFatal?: (error: unknown) => void,
): Promise<void> {
  let attempt = 0;
  let notFoundAttempts = 0;

  while (!signal.aborted) {
    let lastError: unknown = null;

    try {
      await open(signal);

      if (signal.aborted) return;

      // A stream successfully opened and later ended.
      notFoundAttempts = 0;
    } catch (error) {
      if (signal.aborted || isAbortError(error)) {
        return;
      }

      lastError = error;

      if (error instanceof LichessHttpError && error.status === 404) {
        notFoundAttempts += 1;

        // Newly-created games can briefly return 404 before
        // their game stream becomes available.
        if (notFoundAttempts > 6) {
          onFatal?.(error);
          return;
        }
      } else if (!isRetryableStreamError(error)) {
        onFatal?.(error);
        return;
      }
    }

    attempt += 1;
    onReconnect?.(attempt);

    let delay = Math.min(
      5000,
      600 * 2 ** Math.min(attempt - 1, 3),
    );

    // Lichess asks us to back off significantly after rate limiting.
    if (
      lastError instanceof LichessHttpError &&
      lastError.status === 429
    ) {
      delay = 60_000;
    }

    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, delay);

      signal.addEventListener(
        'abort',
        () => {
          window.clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
    });
  }
}