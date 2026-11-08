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
