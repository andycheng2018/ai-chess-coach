import { useEffect, useRef, useState } from 'react';
import { getOutgoingRoomChallenges, getPlayingGames, LichessHttpError } from '../lichess';
import { discoverRooms, discoverJoinedRooms, nextAutomaticRoom, type DiscoveredRoom } from '../roomDiscovery';
import { roomJoinPreview, readRoomJoinDraft, saveRoomJoinDraft } from '../roomJoin';
import { RoomInvitationInput } from './RoomInvitationInput';

type Props = { token?: string | null; autoJoinAllowed?: boolean; username?: string; botUsername: string; currentGameId: string | null; onJoin: (url: string) => Promise<string>; onClose: () => void;
  onLogin: () => Promise<void>; authChecking?: boolean; authError?: string; onRetryAccount: () => void };

export function JoinRoomDialog({ token, autoJoinAllowed = false, username, botUsername, currentGameId, onJoin, onClose, onLogin, authChecking, authError, onRetryAccount }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const [url, setUrl] = useState(() => readRoomJoinDraft() ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [joinedRooms, setJoinedRooms] = useState<DiscoveredRoom[]>([]);
  const [rooms, setRooms] = useState<DiscoveredRoom[]>([]);
  const [roomStatus, setRoomStatus] = useState('');
  const [listReady, setListReady] = useState(false);
  const [autoJoin, setAutoJoin] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const autoRef = useRef(false);
  const baseline = useRef(new Set<string>());
  const attempted = useRef(new Set<string>());
  const retryAfter = useRef(0);
  const latest = useRef({ onJoin, onClose, autoJoinAllowed });
  latest.current = { onJoin, onClose, autoJoinAllowed };
  useEffect(() => { if (!autoJoinAllowed) { autoRef.current = false; setAutoJoin(false); } }, [autoJoinAllowed]);
  useEffect(() => {
    autoRef.current = false; setAutoJoin(false); setListReady(false); setRooms([]); setJoinedRooms([]);
    if (!token || !username) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let abort: AbortController | null = null;
    async function poll() {
      if (disposed) return;
      if (inFlight.current || document.hidden || Date.now() < retryAfter.current) {
        timer = setTimeout(() => void poll(), 10000); return;
      }
      abort = new AbortController();
      const timeout = setTimeout(() => abort?.abort(), 10000);
      try {
        const found = discoverRooms(await getOutgoingRoomChallenges(token!, abort.signal), username!, botUsername);
        if (disposed) return;
        const active = discoverJoinedRooms(await getPlayingGames(token!, abort.signal), botUsername);
        if (disposed) return;
        setJoinedRooms(active);
        setRooms(found); setListReady(true);
        setRoomStatus(autoRef.current && found.filter(r => r.url && !baseline.current.has(r.id) && !attempted.current.has(r.id)).length > 1 ? 'Multiple new rooms found. Select the intended room manually; automatic joining is paused.' : found.length ? 'Account invitations updated.' : 'Lichess returned 0 outgoing invitations. Rooms created before Refresh are included too. This list checks every 10 seconds while open.');
        if (autoRef.current && found.filter(r => r.url && !baseline.current.has(r.id) && !attempted.current.has(r.id)).length > 1) {
          autoRef.current = false; setAutoJoin(false);
        }
        const next = autoRef.current && latest.current.autoJoinAllowed ? nextAutomaticRoom(found, baseline.current, attempted.current) : null;
        if (next?.url) {
          attempted.current.add(next.id);
          autoRef.current = false; setAutoJoin(false);
          inFlight.current = true; setBusy(true); setError('');
          try { await latest.current.onJoin(next.url); if (!disposed) latest.current.onClose(); }
          catch (cause) { if (!disposed) setError(cause instanceof Error ? cause.message : 'Room join failed. Automatic mode stopped; acceptance will not be retried.'); }
          finally { inFlight.current = false; if (!disposed) setBusy(false); }
        }
      } catch (cause) {
        if (disposed) return;
        setListReady(false); setRooms([]); setJoinedRooms([]); autoRef.current = false; setAutoJoin(false);
        if (cause instanceof LichessHttpError && cause.status === 429) retryAfter.current = Date.now() + 60000;
        setRoomStatus(cause instanceof LichessHttpError && cause.status === 403
          ? 'Room access needs challenge:read permission. Sign in again to grant it.'
          : cause instanceof LichessHttpError && cause.status === 429 ? 'Lichess rate limit: waiting at least one minute. Auto-join is off.'
          : 'Room discovery unavailable. Refresh later or use an invitation link. Auto-join is off.');
      } finally {
        clearTimeout(timeout);
        if (!disposed) timer = setTimeout(() => void poll(), 10000);
      }
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); abort?.abort(); autoRef.current = false; };
  }, [token, username, botUsername, refreshNonce]);

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
  async function join(raw = url.trim()) {
    if (!username || inFlight.current) return;
    try { roomJoinPreview(raw); } catch { return; }
    setUrl(raw);
    autoRef.current = false; setAutoJoin(false);
    inFlight.current = true; setBusy(true); setError('');
    try { await onJoin(raw); onClose(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not join this room.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function signIn() {
    if (inFlight.current) return;
    autoRef.current = false; setAutoJoin(false);
    inFlight.current = true; setBusy(true); setError('');
    // A valid invitation is restored after OAuth. It is never joined automatically.
    saveRoomJoinDraft(url.trim());
    try { await onLogin(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not sign in.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <dialog ref={dialog} className="game-qr-dialog room-join-dialog" aria-labelledby="room-join-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="modal-header"><div><span className="modal-kicker">SENSEROBOT · LICHESS ROOM</span><h2 id="room-join-title">Your Lichess rooms & games</h2></div>
      <button type="button" className="ghost" disabled={busy} onClick={onClose} aria-label="Close room link">✕</button></div>
    <p>Create a room on SenseRobot, then scan its invitation here using this device’s camera or a QR photo.</p>
    {username && <details className="room-discovery" aria-label="Account room selector"><summary>Find rooms & games from my Lichess account</summary>
      <h3>Outgoing invitations · {rooms.length}</h3>
      <p className="muted">All visible pending invitations from {username}, including rooms created before you opened this panel or clicked Refresh.</p>
      <p role="status">{roomStatus || 'Loading account invitations and games…'}</p>
      <button type="button" className="ghost" disabled={busy || Date.now() < retryAfter.current} onClick={() => setRefreshNonce(n => n + 1)}>Refresh all rooms & games</button>
      <ul>{rooms.map(room => <li key={room.id}>
        <strong>{room.id}</strong> · {room.timeControl} · You: {room.playerColor || 'unconfirmed'} · {botUsername}: {room.botColor || 'unconfirmed'}
        {room.blockedReason ? <p>{room.blockedReason}</p> : <button type="button" className="primary" disabled={busy || !listReady} onClick={() => { autoRef.current = false; setAutoJoin(false); setUrl(room.url!); setError(''); }}>Select room</button>}
      </li>)}</ul>
      <h3>Already joined games · {joinedRooms.length}</h3>
      <p className="muted">Existing active games against {botUsername}. Opening one recovers that exact game instead of accepting another invitation.</p>
      {listReady && !joinedRooms.length && <p>No active games against your coach bot were returned.</p>}
      <ul>{joinedRooms.map(room => <li key={room.id}><strong>{room.id}</strong> · You: {room.playerColor} · {botUsername}: {room.botColor}
        <button type="button" className="ghost" disabled={busy || !listReady} onClick={() => void join(room.url!)}>{room.id === currentGameId ? 'Reconnect this game' : 'Open this game'}</button>
      </li>)}</ul>
      <label><input type="checkbox" checked={autoJoin} disabled={busy || !listReady || !autoJoinAllowed} onChange={e => {
        baseline.current = new Set(rooms.map(r => r.id)); autoRef.current = e.target.checked; setAutoJoin(e.target.checked);
      }} />Automatically join the next new eligible room</label>
      <p className="muted">One room only, while this panel stays open. Only this automatic mode ignores existing rooms; multiple new rooms require selection. No acceptance retries. {autoJoinAllowed ? 'Create a new room after enabling this switch.' : 'Finish the current game before enabling automatic joining.'}</p>
      <p className="muted">This API cannot identify which device created an invitation. Use this mode only while you are creating the intended room on SenseRobot. Rooms not associated with your account may not appear.</p>
    </details>}
    <h3>Scan or bring a room invitation</h3>
    {!username && <div className="sense-notice" role="status">
      <p>{authChecking ? 'Checking your Lichess account…' : authError || 'Sign in with the same Lichess account linked on SenseRobot first.'}</p>
      {!authChecking && <>
        {authError && <button type="button" className="primary" disabled={busy} onClick={onRetryAccount}>Retry account check</button>}
        <button type="button" className={authError ? 'ghost' : 'primary'} disabled={busy} onClick={() => void signIn()}>{busy ? 'Opening Lichess…' : authError ? 'Sign in again' : 'Sign in with Lichess'}</button>
      </>}
    </div>}
    {username && <p className="muted">Signed in as <strong>{username}</strong>. Use the account linked on SenseRobot. <button type="button" className="ghost" disabled={busy} onClick={() => void signIn()}>Change Chess Buddy sign-in</button></p>}
    <form onSubmit={event => { event.preventDefault(); void join(); }}>
      <RoomInvitationInput id="join-room-url" value={url} disabled={busy} onChange={value => { setUrl(value); setError(''); }} onBusyChange={value => { autoRef.current = false; setAutoJoin(false); inFlight.current = value; setBusy(value); }} />
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
