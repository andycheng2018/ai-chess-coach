import { useEffect, useRef, type ReactNode } from 'react';

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
  startDisabled: boolean;
  busy: boolean;
  startError?: string;
  hostControls: ReactNode;
  onPractice: () => void;
  onExplore: () => void;
  onClose: () => void;
  onPerformance?: () => void;
};
export function DemoWelcome({ onStart, startDisabled, busy, startError, hostControls, onPractice, onExplore, onClose, onPerformance }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const start = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.showModal();
    start.current?.focus();
    return () => { node?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  return <dialog ref={dialog} className="game-qr-dialog demo-welcome" aria-labelledby="demo-welcome-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="modal-header"><span className="eyebrow">CHESS BUDDY · TRY IT HERE</span>
      <button className="ghost" disabled={busy} onClick={onClose} aria-label="Close demo welcome">✕</button></div>
    <div className="demo-welcome-body">
      <span className="demo-welcome-mascot" aria-hidden="true">♞ 🐾</span>
      <h1 id="demo-welcome-title">Your move. Your chess buddy.</h1>
      <p className="demo-welcome-intro">Press Start to meet your robot chess buddy. No game or sign-in needed.</p>
      <ol className="demo-welcome-steps">
        <li><span>1</span><div><strong>Start the demo</strong><p>Watch the dog’s show. Give him room to move.</p></div></li>
        <li><span>2</span><div><strong>Try an easy capture</strong><p>Tap your piece, then the square with the queen or rook.</p></div></li>
        <li><span>3</span><div><strong>Keep exploring</strong><p>Try another puzzle, or ask Luna a chess question in the coach’s chat.</p></div></li>
      </ol>
      <button ref={start} className="primary demo-welcome-start" disabled={startDisabled || busy} onClick={onStart}>{busy ? 'Checking the dog…' : 'Start demo →'}</button>
      {startError && <p className="inline-error" role="alert">{startError}</p>}
      {startDisabled && !busy && <p className="demo-welcome-help">Host: confirm the dog’s setup below to enable Start. You can try chess practice anytime.</p>}
      <div className="demo-welcome-alternatives">
        <button className="ghost" disabled={busy} onClick={onPractice}>Try an easy capture</button>
        {onPerformance && <button className="ghost" disabled={busy} onClick={onPerformance}>Dog performance →</button>}
        <button className="ghost" disabled={busy} onClick={onExplore}>Explore Chess Buddy</button>
      </div>
      <p className="demo-welcome-help">Using the physical robots? Ask your demo host to help. Give the dog room to move.</p>
      <details className="demo-welcome-host" open={startDisabled && !busy}><summary>For the demo host</summary>{hostControls}<p>Choose <strong>Next guest</strong> when someone finishes to bring this welcome back. Stop robot reactions and finish any live match first. Saved chess work and account settings are kept.</p></details>
    </div>
  </dialog>;
}
