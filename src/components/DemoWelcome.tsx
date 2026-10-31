import { useEffect, useRef } from 'react';

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
  onPractice: () => void;
  onExplore: () => void;
  onClose: () => void;
  onPerformance?: () => void;
};
export function DemoWelcome({ onPractice, onExplore, onClose, onPerformance }: Props) {
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
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="modal-header"><span className="eyebrow">CHESS BUDDY · TRY IT HERE</span>
      <button className="ghost" onClick={onClose} aria-label="Close demo welcome">✕</button></div>
    <div className="demo-welcome-body">
      <span className="demo-welcome-mascot" aria-hidden="true">♞ 🐾</span>
      <h1 id="demo-welcome-title">Your move. Your chess buddy.</h1>
      <p className="demo-welcome-intro">New to chess? Start with one easy capture. No sign-in needed.</p>
      <ol className="demo-welcome-steps">
        <li><span>1</span><div><strong>Open easy practice</strong><p>We’ll put a queen or rook in reach.</p></div></li>
        <li><span>2</span><div><strong>Tap your piece, then its destination</strong><p>Take the other piece. You can try again if you miss.</p></div></li>
        <li><span>3</span><div><strong>Keep exploring</strong><p>Try another puzzle, or ask Luna a chess question in the coach’s chat.</p></div></li>
      </ol>
      <button ref={start} className="primary demo-welcome-start" onClick={onPractice}>Try an easy capture →</button>
      <div className="demo-welcome-alternatives">
        {onPerformance && <button className="ghost" onClick={onPerformance}>Dog performance →</button>}
        <button className="ghost" onClick={onExplore}>Explore Chess Buddy</button>
      </div>
      <p className="demo-welcome-help">Using the physical robots? Ask your demo host to help. Give the dog room to move.</p>
      <details className="demo-welcome-host"><summary>For the demo host</summary><p>Choose <strong>Next guest</strong> when someone finishes to bring this welcome back. Stop robot reactions and finish any live match first. Saved chess work and account settings are kept.</p></details>
    </div>
  </dialog>;
}
