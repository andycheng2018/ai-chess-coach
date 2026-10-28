import { useEffect, useRef, useState } from 'react';
import { Browser } from '@capacitor/browser';
import { Capacitor } from '@capacitor/core';
import { App as NativeApp } from '@capacitor/app';
import { buildSenseRoomUrl, getSetupHealth, type BotRuntimeStatus, type SetupHealth } from '../botControl';
import { isPrivateIPv4, normalizeMacAddress, isRememberedSenseGame, readSenseSetup, saveSenseSetup, senseSetupStep, type SenseSetupDraft, type SenseSetupStep } from '../senseSetup';

const SENSE_APP = 'https://www.senserobotchess.com/pages/app-download';
const SENSE_HELP = 'https://www.senserobotchess.com/pages/help-center-page';
const steps: SenseSetupStep[] = ['network', 'account', 'room', 'connected'];
const labels = ['Wi-Fi', 'Lichess', 'Room', 'Play'];

type Props = {
  open: boolean;
  onClose: () => void;
  username: string | null;
  bot: BotRuntimeStatus;
  level: string;
  levels: readonly { id: string; label: string; elo: number }[];
  onLevel: (level: string) => void;
  onLogin: () => Promise<void>;
  onFindRooms?: () => void;
  onJoin: (roomUrl?: string) => Promise<string>;
  onRetryBot: () => Promise<void>;
  canUseExistingGame: boolean;
  onUseExistingGame: () => Promise<string>;
  onUseScreen: () => void;
  gameId: string | null;
  verified: boolean;
  busy: boolean;
  recoveryChecked: boolean;
  moves: number;
  positionKey: string;
  connectionMessage: string;
  connectionError: string;
  signingIn: boolean;
};

export function SenseRobotSetup(props: Props) {
  const [draft, setDraft] = useState(readSenseSetup);
  const [health, setHealth] = useState<SetupHealth | null>(null);
  const [healthError, setHealthError] = useState('');
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [roomUrl, setRoomUrl] = useState('');
  const [roomCode, setRoomCode] = useState('');
  const [botColor, setBotColor] = useState<'' | 'white' | 'black'>('');
  const [boardMatchesGame, setBoardMatchesGame] = useState(false);
  const [deviceIp, setDeviceIp] = useState(draft.deviceIp);
  const [deviceMac, setDeviceMac] = useState(draft.deviceMac);
  const [deviceSaved, setDeviceSaved] = useState(false);
  const [showWifiHelp, setShowWifiHelp] = useState(false);
  const [editing, setEditing] = useState<SenseSetupStep | null>(null);
  const [returned, setReturned] = useState(false);
  const [storageFailed, setStorageFailed] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const handoff = useRef(false);
  const closeRef = useRef(props.onClose);
  closeRef.current = props.onClose;
  const current = senseSetupStep(draft, props.username, props.verified);
  const step = editing || current;
  const waitingForGame = Boolean(props.gameId && props.username
    && isRememberedSenseGame(draft, props.gameId, props.username) && !props.verified);
  const blockedByGame = Boolean(props.gameId && !waitingForGame && !props.verified);
  const busy = props.busy || working;
  const serviceReady = health?.ok && health.stockfish && health.coach?.configured;
  const accountConfirmed = Boolean(props.username && draft.networkReady &&
    draft.linkedUsername.toLowerCase() === props.username.toLowerCase());
  const canJoin = Boolean(accountConfirmed && props.bot.connected && serviceReady
    && props.recoveryChecked && !props.gameId && !busy);
  const canAttach = Boolean(props.canUseExistingGame && accountConfirmed &&
    props.bot.connected && serviceReady && !busy);

  useEffect(() => { setBoardMatchesGame(false); }, [props.gameId, props.username, props.open, props.positionKey]);

  function update(changes: Partial<SenseSetupDraft>) {
    const next = { ...draft, ...changes, open: props.open, level: props.level };
    setStorageFailed(!saveSenseSetup(next));
    setDraft(next);
    setError('');
  }

  useEffect(() => {
    setStorageFailed(!saveSenseSetup({ ...draft, open: props.open, level: props.level }));
  }, [draft, props.open, props.level]);

  // Recheck on return from the companion app or an external website. Device
  // Wi-Fi/linking remain user confirmations; only service/game checks are live.
  useEffect(() => {
    if (!props.open) return;
    let cancelled = false;
    let inFlight = false;
    let removeNativeListener: (() => void) | undefined;
    async function refresh() {
      if (inFlight || document.visibilityState === 'hidden') return;
      inFlight = true;
      try {
        const next = await getSetupHealth();
        if (!cancelled) { setHealth(next); setHealthError(''); }
      } catch {
        if (!cancelled) { setHealth(null); setHealthError('Cannot reach the coach server. Keep the launcher’s Terminal window open, then retry.'); }
      } finally { inFlight = false; }
    }
    function onReturn() {
      if (document.visibilityState === 'hidden') return;
      if (handoff.current) { setReturned(true); handoff.current = false; }
      void refresh();
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    window.addEventListener('focus', onReturn);
    document.addEventListener('visibilitychange', onReturn);
    if (Capacitor.isNativePlatform()) {
      void NativeApp.addListener('appStateChange', ({ isActive }) => { if (isActive) onReturn(); })
        .then(listener => {
          if (cancelled) void listener.remove();
          else removeNativeListener = () => { void listener.remove(); };
        });
    }
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('focus', onReturn);
      document.removeEventListener('visibilitychange', onReturn);
      removeNativeListener?.();
    };
  }, [props.open]);

  useEffect(() => {
    if (!props.open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const backdrop = panel.current?.parentElement;
    const siblings = Array.from(backdrop?.parentElement?.children || [])
      .filter(element => element !== backdrop) as HTMLElement[];
    const previousInert = siblings.map(element => element.inert);
    siblings.forEach(element => { element.inert = true; });
    document.body.style.overflow = 'hidden';
    panel.current?.focus();
    function keydown(event: KeyboardEvent) {
      // A camera dialog owns focus while the room scanner is open.
      if (props.busy) return;
      if (event.key === 'Escape' && !props.busy) { closeRef.current(); return; }
      if (event.key !== 'Tab') return;
      const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]',
      ) || []).filter(element => element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    }
    document.addEventListener('keydown', keydown);
    return () => {
      document.body.style.overflow = overflow;
      siblings.forEach((element, index) => { element.inert = previousInert[index]; });
      document.removeEventListener('keydown', keydown);
      previous?.focus();
    };
  }, [props.open, props.busy]);

  async function external(url: string) {
    handoff.current = true;
    setReturned(false);
    if (Capacitor.isNativePlatform()) await Browser.open({ url });
    else window.open(url, '_blank', 'noopener,noreferrer');
  }

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setWorking(true); setError('');
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setWorking(false); }
  }

  async function join(url?: string) {
    const username = props.username;
    if (!username) return;
    await run(async () => {
      const gameId = await props.onJoin(url);
      update({ joinedGameId: gameId, joinedUsername: username });
      setRoomUrl(''); setEditing(null);
    });
  }

  async function joinManualRoom() {
    try {
      if (botColor !== 'white' && botColor !== 'black') throw new Error('Choose the training bot’s color from the room invitation.');
      await join(buildSenseRoomUrl(roomCode.trim(), botColor));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }

  function saveDeviceDetails() {
    const ip = deviceIp.trim();
    const mac = deviceMac.trim() ? normalizeMacAddress(deviceMac.trim()) : '';
    if (ip && !isPrivateIPv4(ip)) { setError('Enter a private LAN IPv4 address, such as 192.168.1.20.'); return; }
    if (mac === null) { setError('Enter a MAC address using six pairs of hexadecimal digits.'); return; }
    update({ deviceIp: ip, deviceMac: mac });
    setDeviceIp(ip); setDeviceMac(mac); setDeviceSaved(true);
  }

  if (!props.open) return null;
  return <div className="sense-setup-backdrop">
    <div className="sense-setup" role="dialog" aria-modal="true" aria-labelledby="sense-title" tabIndex={-1} ref={panel}>
      <div className="sense-heading">
        <div><span className="eyebrow">PHYSICAL BOARD · LIVE COACH</span><h2 id="sense-title">Connect your SenseRobot</h2></div>
        <button className="ghost" disabled={busy} onClick={props.onClose} aria-label="Close setup">✕</button>
      </div>
      <p className="section-copy">We’ll keep your place and connect the game as soon as the pieces are ready.</p>
      <ol className="sense-steps" aria-label="Setup progress">
        {steps.map((item, index) => <li key={item} aria-current={step === item ? 'step' : undefined}
          className={`${step === item ? 'current' : ''} ${steps.indexOf(current) > index ? 'done' : ''}`}>
          <span>{steps.indexOf(current) > index ? '✓' : index + 1}</span>{labels[index]}
        </li>)}
      </ol>
      <div className="sense-body" aria-live="polite">
        {returned && <p className="sense-notice">Welcome back. Your setup is still here; live connections are being checked.</p>}
        {storageFailed && <p className="inline-error">This browser cannot save setup progress. Keep this page open; signing in may require repeating these confirmations.</p>}
        {step === 'network' && <>
          <h3>Is your robot connected to Wi-Fi?</h3>
          <p>Use the robot’s screen or SenseRobot app to check its connection.</p>
          <button className="primary wide" onClick={() => { update({ networkReady: true }); setEditing(null); }}>Yes, my robot is online</button>
          <button className="ghost wide" onClick={() => setShowWifiHelp(true)}>Help me connect it</button>
          {showWifiHelp && <div className="sense-handoff">
            <h4>Choose Wi-Fi in the SenseRobot app</h4>
            <p>Open <strong>Settings → Device Management → your robot → Switch Network</strong>. Choose your network there and generate its setup QR. On the robot, open <strong>System Settings → Switch Network</strong> and scan that QR.</p>
            <button className="ghost wide" onClick={() => void run(() => external(SENSE_APP))}>Open SenseRobot app download / setup ↗</button>
            <p className="fine-print">Network choices and the Wi-Fi password stay in SenseRobot’s app. Chess Coach cannot scan nearby Wi-Fi or configure the robot from this browser.</p>
          </div>}
          <p className="fine-print">This is your confirmation. We’ll verify the game connection through Lichess later.</p>
        </>}
        {step === 'account' && <>
          <h3>{props.username ? 'Use the same account on your robot' : 'Connect your Lichess account'}</h3>
          {!props.username ? <>
            <p>Sign in on Lichess. When it sends you back, this setup will pick up here automatically.</p>
            <button className="primary wide" disabled={busy || props.signingIn} onClick={() => void run(async () => {
              saveSenseSetup({ ...draft, open: true, level: props.level });
              await props.onLogin();
            })}>{props.signingIn ? 'Confirming your Lichess account…' : 'Sign in with Lichess ↗'}</button>
          </> : <>
            <div className="sense-account"><span>✓ Signed in to Chess Coach</span><strong>{props.username}</strong></div>
            <p>In SenseRobot’s app, open <strong>Play → Planet League → My Account</strong> and link <strong>{props.username}</strong>.</p>
            <button className="primary wide" onClick={() => { update({ linkedUsername: props.username || '' }); setEditing(null); }}>SenseRobot uses {props.username}</button>
            <button className="ghost wide" disabled={busy} onClick={() => void run(() => external(SENSE_APP))}>Open SenseRobot app page ↗</button>
            <p className="fine-print">Lichess confirms your Chess Coach sign-in automatically. SenseRobot account linking needs your confirmation here.</p>
          </>}
          <button className="sense-back" onClick={() => setEditing('network')}>← Wi-Fi setup</button>
        </>}
        {step === 'room' && <>
          <h3>{waitingForGame ? 'Waiting for the game to sync…' : 'Bring your robot’s room here'}</h3>
          {waitingForGame ? <>
            <p>The bot joined your room. We’re waiting for Lichess to confirm the players and board. This page updates automatically.</p>
            <p className="sense-notice">{props.connectionMessage}</p>
            <a className="ghost sense-link" href={`https://lichess.org/${props.gameId}`} target="_blank" rel="noreferrer">Check this game on Lichess ↗</a>
          </> : <>
            <p>Create a Lichess room on SenseRobot, then find its invitation directly from your account.</p>
            {props.onFindRooms && <button className="primary wide" disabled={busy} onClick={props.onFindRooms}>Find my Lichess rooms</button>}
            <p className="fine-print">If Lichess does not list the room, scanning its QR or pasting the link remains available below.</p>
            <label className="sense-label" htmlFor="sense-level">Opponent strength</label>
            <select id="sense-level" value={props.level} disabled={busy || Boolean(props.gameId)} onChange={event => props.onLevel(event.target.value)}>
              {props.levels.map(level => <option key={level.id} value={level.id}>{level.label} · ~{level.elo}</option>)}
            </select>
            <p className="fine-print">The room sets your color and clock; we apply the strength you choose here.</p>
            <button className="primary wide" disabled={!canJoin} onClick={() => void join()}>Scan room QR & connect</button>
            <form onSubmit={event => { event.preventDefault(); if (canJoin && roomUrl.trim()) void join(roomUrl); }}>
              <label className="sense-label" htmlFor="sense-room">Or paste the room link</label>
              <input id="sense-room" type="url" inputMode="url" autoComplete="off" placeholder="https://lichess.org/…?color=…"
                value={roomUrl} disabled={busy || Boolean(props.gameId)} onChange={event => setRoomUrl(event.target.value)} />
              <button type="submit" className="ghost wide" disabled={!canJoin || !roomUrl.trim()}>Connect this room</button>
            </form>
            {blockedByGame && <p className="inline-error">A game is already open. Use the existing-game option below if it is on SenseRobot, or finish it before joining a new room.</p>}
            {!props.recoveryChecked && props.username && <p className="fine-print">Checking for an existing training game…</p>}
            <details className="sense-help"><summary>Can’t find the room QR?</summary>
              <p>Room menu names vary by model and firmware. Look for a friend invitation / create-room option in the robot’s Lichess mode. The app-download and Wi-Fi QR codes won’t join a game.</p>
              <button className="ghost" disabled={busy} onClick={() => void run(() => external(SENSE_HELP))}>Open model guides ↗</button>
            </details>
          </>}
          <button className="sense-back" disabled={busy} onClick={() => setEditing('account')}>← Check linked account</button>
        </>}
        {step === 'connected' && <>
          <div className="sense-success">✓</div>
          <h3>Lichess game connected.</h3>
          <p>Chess Buddy follows this Lichess game. Confirm a physical move and the robot’s reply match its move list before treating the board as synchronized.</p>
          <p className="fine-print">A QR invitation can remain visible while gameplay works. Check actual moves and the game ID before attempting another join.</p>
          <p className="sense-notice">{props.moves > 0 ? `${props.moves} move${props.moves === 1 ? '' : 's'} synced from Lichess.` : 'Waiting for the first move. The board will update automatically.'}</p>
          <button className="primary wide" onClick={props.onClose}>Go to my board</button>
        </>}
        <details className="sense-help sense-fallback">
          <summary>Other ways to connect or continue</summary>
          <h4>Enter a room code manually</h4>
          <p>If scanning is unavailable, use the eight-character room code and the bot color shown in the invitation. The room must still exist on Lichess.</p>
          <form onSubmit={event => { event.preventDefault(); if (canJoin) void joinManualRoom(); }}>
            <label className="sense-label" htmlFor="sense-room-code">Room code</label>
            <input id="sense-room-code" autoComplete="off" maxLength={8} pattern="[A-Za-z0-9]{8}"
              placeholder="AbCd1234" value={roomCode} disabled={!canJoin}
              onChange={event => setRoomCode(event.target.value)} />
            <label className="sense-label" htmlFor="sense-bot-color">Training bot’s color</label>
            <select id="sense-bot-color" value={botColor} disabled={!canJoin}
              onChange={event => setBotColor(event.target.value as typeof botColor)}>
              <option value="">Choose from the room invitation…</option>
              <option value="white">Bot plays White</option><option value="black">Bot plays Black</option>
            </select>
            <button type="submit" className="ghost wide" disabled={!canJoin || roomCode.trim().length !== 8 || !botColor}>Connect using room code</button>
          </form>
          {!accountConfirmed && <p className="fine-print">Complete the Wi-Fi and matching-account confirmations above before joining or attaching a physical-board game.</p>}
          <h4>Use a game that is already running</h4>
          {props.gameId ? <>
            <a className="sense-link" href={`https://lichess.org/${props.gameId}`} target="_blank" rel="noreferrer">Check game {props.gameId} on Lichess ↗</a>
            <label className="sense-confirm"><input type="checkbox" checked={boardMatchesGame} disabled={!canAttach}
              onChange={event => setBoardMatchesGame(event.target.checked)} />
              My SenseRobot board shows this same game and uses {props.username || 'my signed-in account'}.</label>
            <button className="ghost wide" disabled={!canAttach || !boardMatchesGame} onClick={() => void run(async () => {
              const gameId = await props.onUseExistingGame();
              update({ joinedGameId: gameId, joinedUsername: props.username || '' }); setEditing(null);
            })}>Use this game with SenseRobot</button>
            <button className="ghost wide" disabled={!props.canUseExistingGame || busy} onClick={props.onUseScreen}>Continue this game on-screen</button>
            <p className="fine-print">Switching input keeps the same game. Match the physical pieces before switching back to SenseRobot. It does not configure or disconnect the robot.</p>
          </> : <p>No active training game is connected yet. Join a room first, or close setup and start an on-screen training game.</p>}
        </details>
        <details className="sense-help sense-device-details">
          <summary>Device IP and MAC for network troubleshooting</summary>
          <p>Keep the board’s router details here as a reference. These details stay in this browser and do not establish a game connection or change Wi-Fi settings.</p>
          <form onSubmit={event => { event.preventDefault(); saveDeviceDetails(); }}>
            <label className="sense-label" htmlFor="sense-device-ip">SenseRobot LAN IPv4 address</label>
            <input id="sense-device-ip" autoComplete="off" inputMode="decimal" placeholder="192.168.1.20"
              value={deviceIp} onChange={event => { setDeviceIp(event.target.value); setDeviceSaved(false); }} />
            <label className="sense-label" htmlFor="sense-device-mac">SenseRobot MAC address</label>
            <input id="sense-device-mac" autoComplete="off" placeholder="AA:BB:CC:DD:EE:FF"
              value={deviceMac} onChange={event => { setDeviceMac(event.target.value); setDeviceSaved(false); }} />
            <button type="submit" className="ghost wide">Save device details on this browser</button>
          </form>
          {deviceSaved && !storageFailed && <p className="sense-notice" role="status">Device details saved locally. Compare the MAC address with the router’s device list if the IP changes.</p>}
          <p className="fine-print">Game moves still synchronize through Lichess. Direct LAN game control has not been verified for this board.</p>
        </details>
        {busy && <p className="sense-notice" role="status">{props.busy ? props.connectionMessage : 'Working…'}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        {!error && (step === 'room' || step === 'account') && props.connectionError && <p className="inline-error" role="alert">{props.connectionError}</p>}
      </div>
      <div className="sense-checks" aria-label="Live connection checks">
        <span className={health?.ok ? 'ready' : ''}>{health?.ok ? '✓' : '○'} Coach server</span>
        <span className={health?.stockfish ? 'ready' : ''}>{health?.stockfish ? '✓' : '○'} Chess engine</span>
        <span className={health?.coach?.configured ? 'ready' : ''}>{health?.coach?.configured ? '✓' : '○'} AI configured</span>
        <span className={props.bot.connected ? 'ready' : ''}>{props.bot.connected ? '✓' : '○'} Training bot</span>
      </div>
      {healthError && <p className="inline-error">{healthError}</p>}
      {health?.ok && (!health.stockfish || !health.coach?.configured) && <details className="sense-help">
        <summary>Coach server needs setup</summary>
        <p>{!health.stockfish ? 'Stockfish is unavailable. Install it or configure STOCKFISH_PATH in the server’s .env file, then restart the launcher. ' : ''}
          {!health.coach?.configured ? 'Configure OPENAI_API_KEY in the server’s .env file and restart the launcher to enable AI explanations.' : ''}</p>
      </details>}
      {props.username && !props.bot.connected && <div className="sense-retry">
        <p className="fine-print">{props.bot.error || 'Connecting the training bot to Lichess…'}</p>
        <button className="ghost" disabled={busy} onClick={() => void run(props.onRetryBot)}>Retry bot connection</button>
      </div>}
    </div>
  </div>;
}
