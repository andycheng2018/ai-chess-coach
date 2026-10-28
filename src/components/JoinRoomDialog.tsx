import { useEffect, useRef, useState } from 'react';
import { roomJoinPreview, readRoomJoinDraft, saveRoomJoinDraft } from '../roomJoin';

type Props = { username?: string; botUsername: string; currentGameId: string | null; onJoin: (url: string) => Promise<string>; onClose: () => void;
  onLogin: () => Promise<void>; authChecking?: boolean; authError?: string; onRetryAccount: () => void };

export function JoinRoomDialog({ username, botUsername, currentGameId, onJoin, onClose, onLogin, authChecking, authError, onRetryAccount }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const [url, setUrl] = useState(() => readRoomJoinDraft() ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  let preview: ReturnType<typeof roomJoinPreview> | null = null;
  let parseError = '';
  try { if (url.trim()) preview = roomJoinPreview(url); }
  catch (cause) { parseError = cause instanceof Error ? cause.message : 'Invalid room link.'; }
  useEffect(() => {
    const node = dialog.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  async function join() {
    if (!preview || !username || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try { await onJoin(url.trim()); onClose(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not join this room.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function signIn() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    // A valid invitation is restored after OAuth. It is never joined automatically.
    saveRoomJoinDraft(url.trim());
    try { await onLogin(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not sign in.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <dialog ref={dialog} className="game-qr-dialog room-join-dialog" aria-labelledby="room-join-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="modal-header"><div><span className="modal-kicker">SENSEROBOT · LICHESS ROOM</span><h2 id="room-join-title">Join room link with coach bot</h2></div>
      <button type="button" className="ghost" disabled={busy} onClick={onClose} aria-label="Close room link">✕</button></div>
    <p>Create a room on SenseRobot, then paste the Lichess invitation it gives you. The color in that invitation is the seat for {botUsername}.</p>
    {!username && <div className="sense-notice" role="status">
      <p>{authChecking ? 'Checking your Lichess account…' : authError || 'Sign in with the same Lichess account linked on SenseRobot first.'}</p>
      {!authChecking && <>
        {authError && <button type="button" className="primary" disabled={busy} onClick={onRetryAccount}>Retry account check</button>}
        <button type="button" className={authError ? 'ghost' : 'primary'} disabled={busy} onClick={() => void signIn()}>{busy ? 'Opening Lichess…' : authError ? 'Sign in again' : 'Sign in with Lichess'}</button>
      </>}
    </div>}
    {username && <p className="muted">Signed in as <strong>{username}</strong>. Use the account linked on SenseRobot. <button type="button" className="ghost" disabled={busy} onClick={() => void signIn()}>Change Chess Buddy sign-in</button></p>}
    <form onSubmit={event => { event.preventDefault(); void join(); }}>
      <label htmlFor="join-room-url">SenseRobot room invitation</label>
      <input id="join-room-url" type="url" autoComplete="off" placeholder="https://lichess.org/game/AbCd1234?color=black" value={url} disabled={busy} onChange={event => { setUrl(event.target.value); setError(''); }} />
      {parseError && <p className="inline-error" role="status">{parseError}</p>}
      {preview && <p className="sense-notice">Room <strong>{preview.challengeId}</strong> · {botUsername} joins as <strong>{preview.color}</strong> · {username || 'You'} play <strong>{preview.playerColor}</strong>.</p>}
      {currentGameId && preview?.challengeId !== currentGameId && <p className="muted">Game {currentGameId} stays open. A successful join switches Chess Buddy to the supplied room.</p>}
      <button type="submit" className="primary wide" disabled={!preview || !username || busy}>{busy ? 'Working…' : !username ? authChecking ? 'Checking account…' : 'Sign in to join room' : preview ? `Join as ${preview.color}` : 'Paste a room invitation'}</button>
    </form>
    {error && <p className="inline-error" role="alert">{error}</p>}
    <p className="muted">Already joined? The app first checks this exact room in your active games. It never silently substitutes another game or automatically retries an acceptance.</p>
    <p className="muted">Joining Lichess does not prove the physical board has entered the game. Confirm SenseRobot shows the same game before playing.</p>
  </dialog>;
}
