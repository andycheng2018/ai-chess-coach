import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { Browser } from '@capacitor/browser';

const AUTHORIZE_URL = 'https://lichess.org/oauth';
const TOKEN_URL = 'https://lichess.org/api/token';

const TOKEN_KEY = 'lichess_access_token';
const VERIFIER_KEY = 'lichess_pkce_verifier';
const STATE_KEY = 'lichess_oauth_state';

// Lichess requires an HTTPS redirect. This tiny GitHub Pages bridge immediately
// forwards the OAuth query string back into the installed iOS app.
const NATIVE_OAUTH_REDIRECT =
  'https://andycheng2018.github.io/chessbuddy-oauth/oauth-callback.html';

// Registered in Xcode under Target > Info > URL Types > URL Schemes.
const APP_CALLBACK = 'chessbuddy://oauth/callback';

const clientId =
  import.meta.env.VITE_LICHESS_CLIENT_ID || 'ai-chess-coach-local';

function getRedirectUri(): string {
  if (Capacitor.isNativePlatform()) {
    return NATIVE_OAUTH_REDIRECT;
  }

  return (
    import.meta.env.VITE_LICHESS_REDIRECT_URI ||
    `${window.location.origin}/`
  );
}

function randomUrlSafe(bytesLength: number): string {
  const bytes = new Uint8Array(bytesLength);
  crypto.getRandomValues(bytes);

  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });

  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });

  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

async function sha256(value: string): Promise<Uint8Array> {
  const encoded = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', encoded);
  return new Uint8Array(digest);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(VERIFIER_KEY);
  localStorage.removeItem(STATE_KEY);
}

export async function loginWithLichess(): Promise<void> {
  const verifier = randomUrlSafe(48);
  const challenge = base64UrlEncode(await sha256(verifier));
  const state = randomUrlSafe(18);

  // localStorage is intentional here. sessionStorage is unreliable across the
  // native-browser handoff on iOS.
  localStorage.setItem(VERIFIER_KEY, verifier);
  localStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: getRedirectUri(),
    code_challenge_method: 'S256',
    code_challenge: challenge,
    scope: 'board:play challenge:read challenge:write',
    state,
  });

  const url = `${AUTHORIZE_URL}?${params.toString()}`;

  if (Capacitor.isNativePlatform()) {
    await Browser.open({ url });
    return;
  }

  window.location.assign(url);
}

export async function finishOAuthCallback(
  callbackUrl?: string,
): Promise<boolean> {
  const url = callbackUrl
    ? new URL(callbackUrl)
    : new URL(window.location.href);

  const params = url.searchParams;
  const oauthError = params.get('error');

  if (oauthError) {
    throw new Error(`Lichess sign-in failed: ${oauthError}`);
  }

  const code = params.get('code');
  if (!code) return false;

  const returnedState = params.get('state');
  const expectedState = localStorage.getItem(STATE_KEY);
  const verifier = localStorage.getItem(VERIFIER_KEY);

  if (!verifier || !expectedState || returnedState !== expectedState) {
    throw new Error('OAuth state validation failed. Please sign in again.');
  }

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    code_verifier: verifier,
    // This must exactly match the HTTPS redirect URI used in the authorization
    // request, not the chessbuddy:// callback used by the bridge page.
    redirect_uri: getRedirectUri(),
    client_id: clientId,
  });

  const response = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Lichess OAuth failed: ${response.status} ${detail}`);
  }

  const payload = (await response.json()) as { access_token?: string };
  if (!payload.access_token) {
    throw new Error('Lichess OAuth returned no access token.');
  }

  localStorage.setItem(TOKEN_KEY, payload.access_token);
  localStorage.removeItem(VERIFIER_KEY);
  localStorage.removeItem(STATE_KEY);

  if (Capacitor.isNativePlatform()) {
    try {
      await Browser.close();
    } catch {
      // Safe to ignore if the browser has already closed.
    }
  } else {
    window.history.replaceState(
      {},
      document.title,
      window.location.pathname,
    );
  }

  return true;
}

export async function listenForNativeOAuth(
  onSuccess: () => void,
  onError: (message: string) => void,
): Promise<() => void> {
  if (!Capacitor.isNativePlatform()) {
    return () => {};
  }

  let lastHandledUrl: string | null = null;

  const handleUrl = async (url?: string) => {
    if (!url || !url.startsWith(APP_CALLBACK)) return;
    if (url === lastHandledUrl) return;

    lastHandledUrl = url;

    try {
      const completed = await finishOAuthCallback(url);
      if (completed) onSuccess();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  };

  const listener = await App.addListener('appUrlOpen', ({ url }) => {
    void handleUrl(url);
  });

  // Covers the case where Chess Buddy was fully closed when the callback URL
  // opened it.
  const launchUrl = await App.getLaunchUrl();
  if (launchUrl?.url) {
    void handleUrl(launchUrl.url);
  }

  return () => {
    void listener.remove();
  };
}