import { useEffect, useMemo, useRef, useState } from 'react';
import { Chess } from 'chess.js';
import exercises from '../captureExercises.json';
import { CONTROL_URL } from '../coach';
import { useVbotCompanion } from '../useVbotCompanion';
import { VbotCompanion } from './VbotCompanion';
import { ChessBoard } from './ChessBoard';

const PRACTICE_ID = 'CAPTURE1';
type Assessment = { correct: boolean; hint?: string; fenAfter?: string; captured?: string; points?: number;
  reward?: { status: string; reason?: string; requestId?: string } };
async function practiceRequest<T>(path: string, body: object): Promise<T> {
  const response = await fetch(`${CONTROL_URL}/api/vbot/practice/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(10000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || 'Practice server unavailable.');
  return result;
}

export function CapturePractice({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [index, setIndex] = useState(0);
  const [round, setRound] = useState(0);
  const lesson = exercises[index];
  const [fen, setFen] = useState(lesson.fen);
  const [attempt, setAttempt] = useState('');
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<Assessment | null>(null);
  const [error, setError] = useState('');
  const [hint, setHint] = useState(true);
  const [rollback, setRollback] = useState(0);
  const control = useVbotCompanion({ gameId: PRACTICE_ID, playerColor: 'white', resolved: true, ended: false, canArm: true, practice: true });
  const live = control.status?.armed && control.status.gameId === PRACTICE_ID && control.status.mode === 'live';
  const resting = Boolean(live && (control.status?.busy || (control.status?.cooldownRemaining || 0) > 0));
  const board = useMemo(() => new Chess(fen), [fen]);
  const destinations = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const move of board.moves({ verbose: true })) map.set(move.from, [...(map.get(move.from) || []), move.to]);
    return map;
  }, [board]);
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); opener?.focus(); };
  }, []);
  useEffect(() => {
    let current = true;
    setFen(lesson.fen); setResult(null); setAttempt(''); setError(''); setRollback(value => value + 1);
    void practiceRequest<{ attemptId: string }>('start', { exerciseId: lesson.id })
      .then(data => { if (current) setAttempt(data.attemptId); })
      .catch(cause => { if (current) setError(cause instanceof Error ? cause.message : 'Could not start this lesson.'); });
    return () => { current = false; };
  }, [lesson, round]);
  async function move(from: string, to: string) {
    if (!attempt || working || result?.correct || resting) return;
    setWorking(true); setError('');
    try {
      const assessment = await practiceRequest<Assessment>('capture', { attemptId: attempt, moveUci: `${from}${to}` });
      setResult(assessment);
      if (assessment.correct && assessment.fenAfter) setFen(assessment.fenAfter);
      else setRollback(value => value + 1);
    } catch (cause) {
      setRollback(value => value + 1);
      setError(cause instanceof Error ? `${cause.message} No reward is automatically retried.` : 'Could not confirm the result. No automatic retry.');
    } finally { setWorking(false); }
  }
  async function close() {
    if (control.status?.armed && control.status.gameId === PRACTICE_ID) await control.off();
    onClose();
  }
  return <dialog ref={dialog} className="game-qr-dialog capture-practice-dialog" aria-labelledby="capture-practice-title"
    onCancel={event => { event.preventDefault(); if (!working) void close(); }}>
    <div className="modal-header"><div><span className="modal-kicker">EASY CAPTURE PRACTICE</span>
      <h2 id="capture-practice-title">One move. One big capture.</h2></div>
      <button className="ghost" disabled={working} onClick={() => void close()} aria-label="Close Capture Practice">✕</button></div>
    <p>Learn to take queens and rooks on this practice board. Your Lichess game stays available.</p>
    <div className="capture-exercise-layout"><section aria-label="Capture exercise board">
      <label htmlFor="capture-exercise">Choose a lesson</label>
      <select id="capture-exercise" value={index} disabled={working || resting} onChange={event => setIndex(Number(event.target.value))}>
        {exercises.map((item, i) => <option key={item.id} value={i}>{i + 1}. {item.title}</option>)}</select>
      <p className="capture-prompt">{lesson.title}</p>
      <div className="board-panel capture-board"><ChessBoard fen={fen} orientation="white"
        movableColor={!working && !result?.correct && attempt && !resting ? 'white' : undefined}
        destinations={destinations} coachArrows={hint && !result?.correct ? [{ from: lesson.move.slice(0, 2), to: lesson.move.slice(2, 4), kind: 'best' }] : []}
        coachHighlights={hint && !result?.correct ? [lesson.move.slice(2, 4)] : []}
        rollbackSignal={rollback} onMove={(from, to) => void move(from, to)} /></div>
      <label className="capture-hint-toggle"><input type="checkbox" checked={hint} onChange={event => setHint(event.target.checked)} />Show me the capture</label>
      {hint && !result?.correct && <p>{lesson.hint}</p>}
      {working && <p role="status">Checking your capture…</p>}
      {result && <div className={result.correct ? 'capture-success' : 'sense-notice'} role="status">
        {result.correct ? <><strong>🎉 {result.captured === 'queen' ? 'Queen' : 'Rook'} captured — {result.points} points!</strong>
          <p>{result.reward?.status === 'requested' ? 'Rock You requested! Watch VBOT’s result below.'
            : result.reward?.status === 'rehearsed' ? 'Preview: this capture earns Rock You. No robot motion.' : result.reward?.reason}</p></>
          : result.hint}</div>}
      {resting && <p role="status">VBOT is finishing or resting. The next capture will unlock when he is ready.</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="vbot-actions"><button className="ghost" disabled={working || resting} onClick={() => setRound(value => value + 1)}>Try this lesson again</button>
        <button className="primary" disabled={!result?.correct || working || resting} onClick={() => { setIndex(value => (value + 1) % exercises.length); setRound(value => value + 1); }}>Next capture →</button></div>
    </section><aside><h3>Celebrate with VBOT</h3>
      <p>Turn on live rewards below for a full Rock You dance after each correct big-piece capture. Without live rewards, you can still practice.</p>
      <VbotCompanion control={control} gameId={PRACTICE_ID} canArm={true} ended={false} practice={true} />
    </aside></div>
  </dialog>;
}
