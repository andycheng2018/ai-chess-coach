/** Studio's link to a hosted server. The key is typed in once per device, never built in. */
export type CloudPairing = { url: string; token: string };
type Store = { getItem(key: string): string | null; setItem(key: string, value: string): void };

export const CLOUD_PAIRING_KEY = 'vbot-studio.cloud-pairing.v1';
export const DEFAULT_CLOUD_URL = 'https://chess-api.urbot.ai';
export const CLOUD_HEADER = 'X-Chess-Buddy-Token';

export function validatePairing(value: CloudPairing): CloudPairing {
  let url: URL;
  try { url = new URL(value.url.trim()); } catch { throw new Error('Enter the server address, such as https://chess-api.urbot.ai.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) {
    throw new Error('Use the server’s plain HTTPS address, such as https://chess-api.urbot.ai.');
  }
  const token = value.token.trim();
  if (!/^[A-Za-z0-9_-]{40,128}$/.test(token)) throw new Error('Paste the full pairing key from the server.');
  return { url: url.origin, token };
}

/** Same QR format as Chess Buddy's server pairing, so one code works for both apps. */
export function parsePairingQr(raw: string): CloudPairing {
  let payload: { type?: unknown; url?: unknown; token?: unknown };
  try { payload = JSON.parse(raw); } catch { throw new Error('That isn’t a Chess Buddy server pairing QR.'); }
  if (payload?.type !== 'chessbuddy-tablet-v1' || typeof payload.url !== 'string' || typeof payload.token !== 'string') {
    throw new Error('That isn’t a Chess Buddy server pairing QR.');
  }
  return validatePairing({ url: payload.url, token: payload.token });
}

export function readPairing(store: Store): CloudPairing | null {
  try { return validatePairing(JSON.parse(store.getItem(CLOUD_PAIRING_KEY) ?? 'null')); } catch { return null; }
}

export function writePairing(store: Store, pairing: CloudPairing | null) {
  store.setItem(CLOUD_PAIRING_KEY, pairing ? JSON.stringify(pairing) : 'null');
}

/** Adds the key only for the paired server, and refuses redirects so it can't be carried elsewhere. */
export function cloudFetcher(pairing: CloudPairing, request: typeof fetch = (input, init) => fetch(input, init)) {
  return (input: string, init: RequestInit = {}) => {
    if (new URL(input).origin !== pairing.url) return Promise.reject(new Error('Refusing to send the pairing key to another server.'));
    const headers = new Headers(init.headers);
    headers.set(CLOUD_HEADER, pairing.token);
    return request(input, { ...init, headers, redirect: 'error' });
  };
}
