import { useEffect, useRef, type ReactNode } from 'react';
import type { DemoWelcomeState } from '../demoPerformance';

export const DEMO_WELCOME_KEY = 'chessbuddy.demo-welcome.seen.v1';
export function needsDemoWelcome() {
  try { return sessionStorage.getItem(DEMO_WELCOME_KEY) !== '1'; }
  catch { return true; }
}
export function acknowledgeDemoWelcome() {
  try { sessionStorage.setItem(DEMO_WELCOME_KEY, '1'); } catch { /* The welcome still works without storage. */ }
}
export function resetDemoWelcome() {
  try { sessionStorage.removeItem(DEMO_WELCOME_KEY); } catch { /* A host can always reopen it. */ }
}

type Props = {
  onStart: () => void;
  /** Whether the dog show can be offered, and if not, why. */
  state: DemoWelcomeState;
  /** A visitor start is in flight: every control waits for it. */
  starting: boolean;
  /** A robot request is running in the background: only Start waits for it. */
  checking: boolean;
  startError?: string;
  hostControls: ReactNode;
  onPractice: () => void;
  onExplore: () => void;
  onClose: () => void;
  onPerformance?: () => void;
};
export function DemoWelcome({ onStart, state, starting, checking, startError, hostControls, onPractice, onExplore, onClose, onPerformance }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const showAvailable = state.kind === 'ready' || state.kind === 'needs-host';
  const hostCanConfirm = state.kind !== 'no-dog' && state.kind !== 'offline';
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.showModal();
    primary.current?.focus();
    return () => { node?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  const startBusy = starting || checking;
  return <dialog ref={dialog} className="game-qr-dialog demo-welcome" aria-labelledby="demo-welcome-title"
    onCancel={event => { event.preventDefault(); if (!starting) onClose(); }}>
    <div className="modal-header"><span className="eyebrow">CHESS BUDDY · TRY IT HERE</span>
      <button className="ghost" disabled={starting} onClick={onClose} aria-label="Close demo welcome">✕</button></div>
    <div className="demo-welcome-body">
      <span className="demo-welcome-mascot" aria-hidden="true">♞ 🐾</span>
      <h1 id="demo-welcome-title">Your move. Your chess buddy.</h1>
      <p className="demo-welcome-intro">{showAvailable
        ? 'Press Start to meet your robot chess buddy. No game or sign-in needed.'
        : 'Jump straight into chess with your coach. No game or sign-in needed.'}</p>
      <ol className="demo-welcome-steps">
        {showAvailable && <li><span>1</span><div><strong>Start the demo</strong><p>Watch the dog’s show. Give him room to move.</p></div></li>}
        <li><span>{showAvailable ? 2 : 1}</span><div><strong>Try an easy capture</strong><p>Tap your piece, then the square with the queen or rook.</p></div></li>
        <li><span>{showAvailable ? 3 : 2}</span><div><strong>Keep exploring</strong><p>Try another puzzle, or ask Luna a chess question in the coach’s chat.</p></div></li>
      </ol>
      {showAvailable ? <>
        <button ref={primary} className="primary demo-welcome-start" disabled={state.kind !== 'ready' || startBusy} onClick={onStart}>
          {startBusy ? 'Checking the dog…' : state.kind === 'ready' ? 'Start demo →' : 'Start demo · host check needed'}</button>
        {startError && <p className="inline-error" role="alert">{startError}</p>}
        {state.kind === 'needs-host' && !startBusy && <p className="demo-welcome-help">Host: confirm the dog’s setup below to enable Start. You can try chess practice anytime.</p>}
        <div className="demo-welcome-alternatives">
          <button className="ghost" disabled={starting} onClick={onPractice}>Try an easy capture</button>
          {onPerformance && <button className="ghost" disabled={starting} onClick={onPerformance}>Dog performance →</button>}
          <button className="ghost" disabled={starting} onClick={onExplore}>Explore Chess Buddy</button>
        </div>
      </> : <>
        <p className="demo-welcome-notice" role="status">{'message' in state && state.message}</p>
        <button ref={primary} className="primary demo-welcome-start" disabled={starting} onClick={onPractice}>Try an easy capture →</button>
        <div className="demo-welcome-alternatives">
          <button className="ghost" disabled={starting} onClick={onExplore}>Explore Chess Buddy</button>
          {onPerformance && <button className="ghost" disabled={starting} onClick={onPerformance}>Dog performance →</button>}
        </div>
      </>}
      <p className="demo-welcome-help">Using the physical robots? Ask your demo host to help. Give the dog room to move.</p>
      <details className="demo-welcome-host" open={state.kind === 'needs-host' && !startBusy}><summary>For the demo host</summary>
        {hostCanConfirm ? hostControls
          : <p>Connect the dog first: set its address in <strong>Dog performance</strong> (on the Android app, <strong>Tablet settings → VBOT direct connection</strong>). Then choose <strong>Next guest</strong> to bring this welcome back with Start enabled.</p>}
        <p>Choose <strong>Next guest</strong> when someone finishes to bring this welcome back. Stop robot reactions and finish any live match first. Saved chess work and account settings are kept.</p></details>
    </div>
  </dialog>;
}
