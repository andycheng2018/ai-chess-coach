import type { BotAccount, NewBotAccount } from './botControl';

// Pure helpers for the bot account picker, kept DOM-free for node tests.

const USERNAME = /^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$/;
const TOKEN_ENV = /^LICHESS_[A-Z0-9_]{1,60}$/;

export type BotAccountDraft = {
  label: string;
  username: string;
  tokenMode: 'paste' | 'env';
  token: string;
  tokenEnv: string;
};

export const EMPTY_BOT_ACCOUNT_DRAFT: BotAccountDraft = {
  label: '', username: '', tokenMode: 'paste', token: '', tokenEnv: '',
};

/** Shows where a token lives without ever showing the token. */
export function maskedToken(account: Pick<BotAccount, 'tokenSource' | 'tokenEnv' | 'tokenHint' | 'tokenConfigured'>): string {
  if (!account.tokenConfigured) return account.tokenEnv ? `${account.tokenEnv} not set` : 'No token';
  const tail = account.tokenHint ? `••••${account.tokenHint}` : '••••';
  return account.tokenSource === 'env' && account.tokenEnv ? `${account.tokenEnv} · ${tail}` : `Saved · ${tail}`;
}

export function accountOptionLabel(account: Pick<BotAccount, 'label' | 'username'>): string {
  return account.label && account.label.toLowerCase() !== account.username.toLowerCase()
    ? `${account.label} (${account.username})`
    : account.username;
}

/** Why the bot account cannot change right now, or '' when it can. */
export function accountSwitchBlock(state: {
  gameId?: string | null;
  startingGame?: boolean;
  activeGames?: number;
  locked?: boolean;
  lockedReason?: string | null;
}): string {
  if (state.startingGame) return 'Wait for the game to start.';
  if (state.gameId || (state.activeGames ?? 0) > 0 || state.locked) {
    return state.lockedReason || 'Finish the current game before switching bot accounts.';
  }
  return '';
}

/** Validates the add form and builds the request; the token is trimmed but never echoed. */
export function buildNewAccount(draft: BotAccountDraft): { ok: true; account: NewBotAccount } | { ok: false; error: string } {
  const username = draft.username.trim();
  if (!USERNAME.test(username)) return { ok: false, error: 'Enter the bot’s Lichess username.' };
  const label = draft.label.trim();
  if (draft.tokenMode === 'env') {
    const tokenEnv = draft.tokenEnv.trim();
    if (!TOKEN_ENV.test(tokenEnv)) return { ok: false, error: 'Name an environment variable like LICHESS_BOT_TOKEN_2.' };
    return { ok: true, account: { label, username, tokenEnv, select: true } };
  }
  const token = draft.token.trim();
  if (token.length < 8 || /\s/.test(token)) return { ok: false, error: 'Paste the bot account’s Lichess API token.' };
  return { ok: true, account: { label, username, token, select: true } };
}

export type BotAccountsLoadProblem = { kind: 'unreachable' | 'unauthorized' | 'other'; text: string; retry: boolean; remote: boolean };

/** Explain a failed bot account load in words a demo host can act on. Accounts and their
 * tokens live on the backend, so an unreachable backend never means they were removed. */
export function describeBotAccountsLoadError(error: unknown, serverUrl: string): BotAccountsLoadProblem {
  const raw = typeof (error as { message?: unknown })?.message === 'string' ? (error as { message: string }).message : String(error);
  const host = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i.exec(serverUrl)?.[1] || serverUrl;
  const local = /^(127\.0\.0\.1|localhost|\[::1\])(:|$)/.test(host);
  const where = local ? 'the coach backend on this device' : `the Chess Buddy server at ${host}`;
  const status = Number(/^(\d{3})\b/.exec(raw)?.[1] || 0);
  const network = (error as { name?: unknown })?.name === 'TypeError' || /failed to fetch|load failed|networkerror|network request failed/i.test(raw);
  if (network || (status >= 500 && status <= 599)) {
    return { kind: 'unreachable', retry: true, remote: !local, text: `Can’t reach ${where}${status ? ` (HTTP ${status})` : ''}. `
      + 'Your bot accounts and their tokens are saved there and have not been removed; they come back as soon as it answers. '
      + (local ? 'Restart the app if this lasts.' : 'If that server is a computer, make sure it is on and signed in after any restart.') };
  }
  if (status === 401 || status === 403) {
    return { kind: 'unauthorized', retry: false, remote: !local, text: `${where[0].toUpperCase()}${where.slice(1)} refused this device (HTTP ${status}). `
      + 'Pair this device with the server again; the saved bot accounts on the server are unchanged.' };
  }
  return { kind: 'other', retry: true, remote: !local, text: `Could not load bot accounts: ${raw}` };
}
