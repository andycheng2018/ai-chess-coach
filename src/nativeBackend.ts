export type TabletConnection = { url: string; token: string };
const KEY = 'chessbuddy.tablet-connection.v1';
export const TABLET_HEADER = 'X-Chess-Buddy-Token';

declare global { interface Window { __CHESS_BACKEND_URL__?: string } }

export function validateConnection(value: TabletConnection): TabletConnection {
  const url = new URL(value.url.trim());
  const host = url.hostname;
  const privateHost = host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
    || /^10\.\d+\.\d+\.\d+$/.test(host) || /^192\.168\.\d+\.\d+$/.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/.test(host) || host.endsWith('.local');
  if (!['http:', 'https:'].includes(url.protocol) || (url.protocol === 'http:' && !privateHost)
    || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) {
    throw new Error('Use an HTTPS server address or your Mac’s private LAN address, such as http://192.168.0.20:8765.');
  }
  const token = value.token.trim();
  if (!/^[A-Za-z0-9_-]{40,128}$/.test(token)) throw new Error('Copy the pairing key shown on the Mac.');
  return { url: url.origin, token };
}

export function readConnection(): TabletConnection | null {
  try { return validateConnection(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch { return null; }
}
export function saveConnection(value: TabletConnection): TabletConnection {
  const connection = validateConnection(value);
  localStorage.setItem(KEY, JSON.stringify(connection));
  return connection;
}
export function clearConnection() { localStorage.removeItem(KEY); }

export function parsePairingQr(raw: string): TabletConnection {
  const payload = JSON.parse(raw);
  if (payload.type !== 'chessbuddy-tablet-v1') throw new Error('Scan the pairing QR on your Mac, not a chess-room QR.');
  return validateConnection(payload);
}

// Scope authentication to this one origin. Lichess and external URLs never receive the key.
export function authenticatedBackendFetch(original: typeof fetch, connection: TabletConnection): typeof fetch {
  return async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.href);
    if (url.origin !== connection.url) return original(input, init);
    const headers = new Headers(input instanceof Request ? input.headers : undefined);
    new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
    if (!headers.has(TABLET_HEADER)) headers.set(TABLET_HEADER, connection.token);
    return original(input, { ...init, headers, redirect: 'error' });
  };
}

export function installTabletTransport() {
  const connection = readConnection();
  if (!connection) return;
  window.__CHESS_BACKEND_URL__ = connection.url;
  window.fetch = authenticatedBackendFetch(window.fetch.bind(window), connection);
}
