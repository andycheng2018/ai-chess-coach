import { useCallback, useEffect, useState } from 'react';
import {
  addBotAccount, getBotAccounts, removeBotAccount, selectBotAccount,
  type BotAccountList, type BotRuntimeStatus,
} from '../botControl';
import { EMPTY_BOT_ACCOUNT_DRAFT, accountOptionLabel, buildNewAccount, maskedToken, type BotAccountDraft } from '../botAccounts';

type Props = {
  /** Non-empty when the account cannot change (a game is starting or running). */
  blockedReason: string;
  onStatus: (status: BotRuntimeStatus) => void;
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function BotAccountPicker({ blockedReason, onStatus }: Props) {
  const [list, setList] = useState<BotAccountList | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState(false);
  const [managing, setManaging] = useState(false);
  const [draft, setDraft] = useState<BotAccountDraft>(EMPTY_BOT_ACCOUNT_DRAFT);

  const apply = useCallback((next: BotAccountList) => {
    setList(next);
    onStatus(next.bot);
    if (next.message) setNotice(next.message);
  }, [onStatus]);

  useEffect(() => {
    let alive = true;
    getBotAccounts().then(next => { if (alive) { setList(next); setError(''); } })
      .catch(err => { if (alive) setError(`Could not load bot accounts: ${message(err)}`); });
    return () => { alive = false; };
  }, []);

  async function run(action: () => Promise<BotAccountList>) {
    setPending(true); setError(''); setNotice('');
    try { apply(await action()); return true; }
    catch (err) { setError(message(err)); return false; }
    finally { setPending(false); }
  }

  async function submit(useNow: boolean) {
    const built = buildNewAccount(draft);
    if (!built.ok) { setError(built.error); return; }
    // Drop the pasted token from component state whether or not the save works.
    setDraft(current => ({ ...current, token: '' }));
    if (await run(() => addBotAccount({ ...built.account, select: useNow }))) {
      setDraft(EMPTY_BOT_ACCOUNT_DRAFT);
    }
  }

  if (!list) {
    return <div className="setup-group bot-account-picker">
      <label className="setup-label">Bot account</label>
      {error ? <div className="inline-error">{error}</div> : <small className="muted">Loading bot accounts…</small>}
    </div>;
  }

  const locked = Boolean(blockedReason) || list.locked;
  const selected = list.accounts.find(account => account.id === list.selectedId);

  return <div className="setup-group bot-account-picker">
    <label className="setup-label" htmlFor="bot-account-select">Bot account</label>
    <div className="bot-account-row">
      <select id="bot-account-select" value={list.selectedId || ''} disabled={locked || pending || !list.canManage}
        onChange={event => { const id = event.target.value; void run(() => selectBotAccount(id)); }}>
        {!list.selectedId && <option value="">No bot account</option>}
        {list.accounts.map(account => <option key={account.id} value={account.id}>{accountOptionLabel(account)}</option>)}
      </select>
      {list.canManage && <button type="button" className="ghost" disabled={pending}
        onClick={() => { setManaging(open => !open); setError(''); }}>{managing ? 'Done' : 'Manage'}</button>}
    </div>
    {selected && <small className="bot-account-token">{maskedToken(selected)}</small>}
    {(blockedReason || list.lockedReason) && <small className="muted">{blockedReason || list.lockedReason}</small>}
    {!list.canManage && <small className="muted">Bot accounts are managed on the coach computer or a paired tablet.</small>}
    {pending && <small className="muted">Checking bot account with Lichess…</small>}
    {notice && !error && <small className="muted">{notice}</small>}
    {error && <div className="inline-error">{error}</div>}

    {managing && list.canManage && <div className="bot-account-manage">
      <ul>
        {list.accounts.map(account => <li key={account.id}>
          <span><strong>{accountOptionLabel(account)}</strong><small>{maskedToken(account)}</small></span>
          <button type="button" className="ghost" disabled={pending || (locked && account.active)}
            title={account.isDefault ? 'Hides the .env account here; the token stays in .env.' : 'Removes the account and its saved token.'}
            onClick={() => void run(() => removeBotAccount(account.id))}>Remove</button>
        </li>)}
      </ul>
      <form className="bot-account-form" autoComplete="off" onSubmit={event => { event.preventDefault(); void submit(!locked); }}>
        <strong>Add a Lichess BOT account</strong>
        <label>Label<input value={draft.label} placeholder="Optional" onChange={e => setDraft({ ...draft, label: e.target.value })} /></label>
        <label>Bot username<input value={draft.username} autoCapitalize="none" spellCheck={false}
          onChange={e => setDraft({ ...draft, username: e.target.value })} /></label>
        <div className="color-choice" role="group" aria-label="Where the token is kept">
          <button type="button" className={draft.tokenMode === 'paste' ? 'active' : ''}
            onClick={() => setDraft({ ...draft, tokenMode: 'paste' })}>Paste token</button>
          <button type="button" className={draft.tokenMode === 'env' ? 'active' : ''}
            onClick={() => setDraft({ ...draft, tokenMode: 'env', token: '' })}>From .env</button>
        </div>
        {draft.tokenMode === 'paste'
          ? <label>API token<input type="password" value={draft.token} autoComplete="new-password" spellCheck={false}
              onChange={e => setDraft({ ...draft, token: e.target.value })} /></label>
          : <label>Variable name<input value={draft.tokenEnv} placeholder="LICHESS_BOT_TOKEN_2" autoCapitalize="characters" spellCheck={false}
              onChange={e => setDraft({ ...draft, tokenEnv: e.target.value })} /></label>}
        <small className="muted">The token stays on the coach backend and is never shown again.</small>
        <button type="submit" className="primary" disabled={pending}>{locked ? 'Add (use after this game)' : 'Add and use'}</button>
      </form>
    </div>}
  </div>;
}
