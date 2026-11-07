import { useEffect, useState } from 'react';
import { isTerminal } from '../domain/commands';
import { cueTitle } from '../domain/score';
import type { Studio } from '../useStudio';

const OUTCOME: Record<string, string> = {
  completed: 'The dog reported it finished',
  cancelled: 'Stopped before the next move',
  rejected: 'Not run',
  unknown: 'Outcome unknown. Check the dog',
};

/**
 * A bottom sheet for whatever is running or just ran, so a button press doesn't pull the page to another tab.
 * It says what the dog reported, not that the thing visibly happened: a finished report is not proof of motion.
 */
export function RunSheet({ studio, onOpenStage }: { studio: Studio; onOpenStage: () => void }) {
  const { snapshot, receipt } = studio;
  const run = snapshot.run;
  const [dismissed, setDismissed] = useState<string | null>(null);
  const live = run !== null && !isTerminal(run.state);

  // A clean finish tidies itself away after a moment; anything else stays until dismissed.
  useEffect(() => {
    if (!run || run.state !== 'completed') return undefined;
    const timer = setTimeout(() => setDismissed(run.commandId), 4000);
    return () => clearTimeout(timer);
  }, [run?.commandId, run?.state]);

  const refusal = receipt && receipt.state === 'rejected' && (!run || receipt.commandId !== run.commandId) ? receipt : null;
  const shown = run !== null && dismissed !== run.commandId;
  if (!shown && !refusal) return null;

  const current = run?.score.cues[Math.min(run.cueIndex, run.score.cues.length - 1)];
  const dismiss = () => { if (run) setDismissed(run.commandId); studio.clearReceipt(); };

  return (
    <aside className={`run-sheet ${live ? 'is-live' : ''}`} role="status" aria-live="polite" aria-label="Current action">
      <div className="run-sheet-main">
        {shown && run && (
          <>
            <strong>{run.score.title}</strong>
            <span className="fine">
              {live ? `Running${current ? `: ${cueTitle(current)}` : ''}` : (OUTCOME[run.state] ?? run.state)}
              {!live && run.reason ? ` — ${run.reason}` : ''}
            </span>
          </>
        )}
        {refusal && !shown && <><strong>Not sent</strong><span className="fine">{refusal.reason}</span></>}
      </div>
      <div className="run-sheet-actions">
        {live && <button className="btn btn-small" onClick={() => void studio.stopFuture()}>Stop</button>}
        {run && run.score.cues.length > 1 && <button className="btn btn-small" onClick={onOpenStage}>Open stage</button>}
        <button className="icon-btn" aria-label="Dismiss" onClick={dismiss}>✕</button>
      </div>
    </aside>
  );
}
