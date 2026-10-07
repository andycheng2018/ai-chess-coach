import { useEffect, useRef, useState } from 'react';
import { Browser } from '@capacitor/browser';
import { Capacitor } from '@capacitor/core';
import { App as NativeApp } from '@capacitor/app';
import { getSetupHealth, type BotRuntimeStatus, type SetupHealth } from '../botControl';
import { isRememberedSenseGame, readSenseSetup, saveSenseSetup, senseSetupStep, type SenseSetupDraft, type SenseSetupStep } from '../senseSetup';

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
  onJoin: (roomUrl?: string) => Promise<string>;
  onRetryBot: () => Promise<void>;
  gameId: string | null;
  verified: boolean;
  busy: boolean;
  recoveryChecked: boolean;
  moves: number;
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
  const canJoin = Boolean(props.username && props.bot.connected && serviceReady
    && props.recoveryChecked && !props.gameId && !busy);

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
        'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex="0"]',
      ) || []);
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
            <p>On SenseRobot, open its Lichess friend / room option and display the <strong>game-room QR</strong>. You can scan it here or paste its link.</p>
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
            {blockedByGame && <p className="inline-error">You already have a game open. Close setup and finish that game before connecting a new room.</p>}
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
          <h3>Your game is connected.</h3>
          <p>Move on SenseRobot. Your board in Chess Coach follows the same Lichess game, and the coach watches your play.</p>
          <p className="sense-notice">{props.moves > 0 ? `${props.moves} move${props.moves === 1 ? '' : 's'} synced from Lichess.` : 'Waiting for the first move. The board will update automatically.'}</p>
          <button className="primary wide" onClick={props.onClose}>Go to my board</button>
        </>}
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
