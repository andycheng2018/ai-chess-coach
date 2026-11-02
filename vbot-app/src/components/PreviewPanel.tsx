/**
 * Preview is a local simulation built only from the pure timeline. This file must
 * never import a transport or call the network: a test enforces that.
 */
import { useEffect, useMemo, useState } from 'react';
import { buildTimeline, cueTitle, formatDuration, type Score } from '../domain/score';
import { FacePreview } from './FacePreview';
import { KindChip } from './bits';

const TICK_MS = 100;

export function PreviewPanel({ score }: { score: Pick<Score, 'cues' | 'repeat' | 'revision' | 'id'> }) {
  const timeline = useMemo(() => buildTimeline(score), [score]);
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => { setElapsed(null); }, [score.id, score.revision]);

  useEffect(() => {
    if (elapsed === null) return;
    if (elapsed >= timeline.totalMs) { setElapsed(null); return; }
    const timer = window.setTimeout(() => setElapsed(value => value === null ? null : value + TICK_MS), TICK_MS);
    return () => window.clearTimeout(timer);
  }, [elapsed, timeline.totalMs]);

  const current = elapsed === null ? null
    : timeline.items.find(item => elapsed >= item.startMs && elapsed < item.startMs + item.durationMs) ?? null;
  const canPreview = timeline.totalMs > 0;

  return (
    <section className="preview" aria-label="Show preview">
      <div className="preview-head">
        <div>
          <h3>Preview</h3>
          <p>A simulation on this screen. Nothing is sent to a dog.</p>
        </div>
        <button className="btn" disabled={!canPreview} onClick={() => setElapsed(value => value === null ? 0 : null)}>
          {elapsed === null ? 'Play preview' : 'Stop preview'}
        </button>
      </div>
      {current && (
        <div className="preview-stage" role="status">
          {current.cue.type === 'face' || current.cue.type === 'wait'
            ? <FacePreview label={current.cue.type === 'wait' ? 'rest' : cueTitle(current.cue)} />
            : <div className="preview-motion"><strong>{cueTitle(current.cue)}</strong><span>Physical motion. There’s no animation for this cue, and it doesn’t move anything in preview.</span></div>}
          <div className="preview-now">
            <KindChip kind={current.cue.type} />
            <strong>{cueTitle(current.cue)}</strong>
            {current.cue.caption && <em>{current.cue.caption}</em>}
          </div>
        </div>
      )}
      <div className="timeline" role="img" aria-label={`Timeline, ${formatDuration(timeline.totalMs)} total`}>
        {timeline.items.map(item => (
          <span key={item.key} className={`timeline-bar kind-${item.cue.type} ${current?.key === item.key ? 'is-current' : ''}`}
            style={{ flexGrow: Math.max(item.durationMs, 300) }} title={`${cueTitle(item.cue)} · ${formatDuration(item.durationMs)}`} />
        ))}
      </div>
      <p className="preview-total">
        {timeline.items.length} cues · about {formatDuration(timeline.totalMs)}
        {timeline.unknownDurations > 0 && ` · ${timeline.unknownDurations} with unmeasured duration`}
      </p>
    </section>
  );
}
