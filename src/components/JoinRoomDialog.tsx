import { useEffect, useRef, useState } from 'react';
import { roomJoinPreview } from '../roomJoin';

type Props = { username?: string; botUsername: string; currentGameId: string | null; onJoin: (url: string) => Promise<string>; onClose: () => void };

export function JoinRoomDialog({ username, botUsername, currentGameId, onJoin, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const [url, setUrl] = useState('');
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
  return <dialog ref={dialog} className="game-qr-dialog room-join-dialog" aria-labelledby="room-join-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="modal-header"><div><span className="modal-kicker">SENSEROBOT · LICHESS ROOM</span><h2 id="room-join-title">Join room link with coach bot</h2></div>
      <button type="button" className="ghost" disabled={busy} onClick={onClose} aria-label="Close room link">✕</button></div>
    <p>Create a room on SenseRobot, then paste the Lichess invitation it gives you. The color in that invitation is the seat for {botUsername}.</p>
    {!username && <p role="status">Sign in with the same Lichess account linked on SenseRobot first.</p>}
    <form onSubmit={event => { event.preventDefault(); void join(); }}>
      <label htmlFor="join-room-url">SenseRobot room invitation</label>
      <input id="join-room-url" type="url" autoComplete="off" placeholder="https://lichess.org/game/AbCd1234?color=black" value={url} disabled={busy} onChange={event => { setUrl(event.target.value); setError(''); }} />
      {parseError && <p className="inline-error" role="status">{parseError}</p>}
      {preview && <p className="sense-notice">Room <strong>{preview.challengeId}</strong> · {botUsername} joins as <strong>{preview.color}</strong> · {username || 'You'} play <strong>{preview.playerColor}</strong>.</p>}
      {currentGameId && preview?.challengeId !== currentGameId && <p className="muted">Game {currentGameId} stays open. A successful join switches Chess Buddy to the supplied room.</p>}
      <button type="submit" className="primary wide" disabled={!preview || !username || busy}>{busy ? 'Joining or recovering this room…' : preview ? `Join as ${preview.color}` : 'Join room'}</button>
    </form>
    {error && <p className="inline-error" role="alert">{error}</p>}
    <p className="muted">Already joined? The app first checks this exact room in your active games. It never silently substitutes another game or automatically retries an acceptance.</p>
    <p className="muted">Joining Lichess does not prove the physical board has entered the game. Confirm SenseRobot shows the same game before playing.</p>
  </dialog>;
}
