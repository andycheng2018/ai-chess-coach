import { useEffect, useMemo, useState } from 'react';
import { isTerminal, STATE_LABEL, type CleanupState, type CueAck } from '../domain/commands';
import { buildTimeline, cueTitle, formatDuration, type Score } from '../domain/score';
import type { Studio } from '../useStudio';
import { FacePreview } from '../components/FacePreview';
import { KindChip, ViewHeader } from '../components/bits';

const ACK_LABEL: Record<CueAck, string> = {
  idle: 'Waiting', sent: 'Sent, waiting for the dog', started: 'Playback started', waiting: 'Pausing', finished: 'Finished',
};
const CLEANUP_LABEL: Record<CleanupState, string> = {
  'not-needed': 'No cleanup needed', pending: 'Cleanup pending', released: 'Screen handed back', failed: 'Screen release not confirmed. Check the dog.',
};

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function NowPlaying({ studio }: { studio: Studio }) {
  const { snapshot, simulated } = studio;
  const run = snapshot.run!;
  const timeline = useMemo(() => buildTimeline(run.score), [run.score]);
  const active = !isTerminal(run.state);
  const now = useNow(active);
  const current = timeline.items[run.cueIndex];
  const upcoming = active ? timeline.items.slice(run.cueIndex + 1, run.cueIndex + 6) : [];
  const percent = timeline.items.length ? Math.round((run.completedCues / timeline.items.length) * 100) : 0;
  const remaining = run.cueEndsAt ? Math.max(0, Math.ceil((run.cueEndsAt - now) / 1000)) : null;
  const usesMotion = run.score.cues.some(cue => cue.type === 'head' || cue.type === 'body' || cue.type === 'move');

  return (
    <div className="stage-grid">
      <section className={`card now-card state-${run.state}`}>
        <div className="now-head">
          <div>
            <p className="eyebrow">{active ? 'Now playing' : 'Last run'}</p>
            <h2>{run.score.title}</h2>
          </div>
          <span className={`state-pill state-${run.state}`} role="status">{STATE_LABEL[run.state]}</span>
        </div>
        {current && (
          <div className="now-cue">
            {current.cue.type === 'face' ? <FacePreview label={cueTitle(current.cue)} playing={active} /> : <FacePreview label={current.cue.type === 'wait' ? 'rest' : 'neutral'} playing={active} />}
            <div className="now-cue-text">
              <div><KindChip kind={current.cue.type} /></div>
              <h3>{cueTitle(current.cue)}</h3>
              {current.cue.caption && <p>{current.cue.caption}</p>}
              {active && <p className="ack" role="status">{ACK_LABEL[run.cueAck]}{remaining !== null ? ` · ${remaining}s left` : ''}</p>}
            </div>
          </div>
        )}
        <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={timeline.items.length} aria-valuenow={run.completedCues} aria-label="Cues completed">
          <span style={{ width: `${percent}%` }} />
        </div>
        <p className="fine">{run.completedCues} of {timeline.items.length} cues finished</p>
        {run.reason && <p className={`notice ${run.state === 'unknown' || run.state === 'rejected' ? 'notice-warn' : ''}`}>{run.reason}</p>}
        {!active && <p className="fine">{CLEANUP_LABEL[run.cleanup]}</p>}
        {run.state === 'unknown' && !simulated && <p className="notice notice-warn">Check the dog in person before starting anything else. This show won’t be replayed.</p>}
        {active && (
          <div className="stop-block">
            <button className="btn btn-stop" onClick={() => void studio.stopFuture()}>Stop future cues</button>
            <p className="fine">{usesMotion
              ? 'This cancels cues that haven’t started. It doesn’t stop a motion already underway. Use the onsite handset Stop for that.'
              : 'This cancels cues that haven’t started and hands the screen back.'}</p>
          </div>
        )}
      </section>
      <section className="card">
        <h2>Up next</h2>
        {upcoming.length === 0 && <p className="fine">{active ? 'This is the last cue.' : 'Nothing queued.'}</p>}
        <ol className="upcoming">
          {upcoming.map(item => (
            <li key={item.key}><KindChip kind={item.cue.type} /> <span>{cueTitle(item.cue)}</span> <small>{item.durationKnown ? formatDuration(item.durationMs) : 'length unmeasured'}</small></li>
          ))}
        </ol>
        <h2 className="log-title">Activity</h2>
        <ul className="event-log">
          {snapshot.events.slice(0, 8).map((event, index) => (
            <li key={`${event.time}-${index}`}><time>{new Date(event.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time> {event.message}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ShowStarter({ studio, onShows }: { studio: Studio; onShows: () => void }) {
  const { library, selected, snapshot } = studio;
  const shows: readonly Score[] = [...library.canned, ...library.shows];
  const [chosenId, setChosenId] = useState<string | null>(selected?.id ?? null);
  const chosen = shows.find(show => show.id === chosenId) ?? selected ?? library.canned[0];
  const admission = studio.admission(chosen);
  const connected = snapshot.connection === 'connected';
  const distinct = [...new Set(admission.blockers.map(blocker => blocker.reason))];
  return (
    <section className="card starter">
      <h2>Start a show</h2>
      <label className="field">
        <span>Show</span>
        <select value={chosen.id} onChange={event => setChosenId(event.target.value)}>
          {shows.map(show => <option key={show.id} value={show.id}>{show.title}</option>)}
        </select>
      </label>
      <p className="fine">{chosen.cues.length} cues · about {formatDuration(buildTimeline(chosen).totalMs)}</p>
      {chosen.cues.length === 0 && <p className="notice">This show has no cues yet. <button className="link" onClick={onShows}>Add some</button>.</p>}
      {distinct.length > 0 && (
        <div className="notice notice-warn">
          <strong>This show can’t run right now.</strong>
          <ul>{distinct.slice(0, 4).map(reason => <li key={reason}>{reason}</li>)}</ul>
        </div>
      )}
      <button className="btn btn-primary btn-large" disabled={!connected || !admission.ok || chosen.cues.length === 0 || studio.sending} onClick={() => void studio.startShow(chosen)}>
        {studio.sending ? 'Sending…' : studio.simulated ? 'Start simulated show' : 'Start show'}
      </button>
    </section>
  );
}

export function StageView({ studio, onShows }: { studio: Studio; onShows: () => void }) {
  const { snapshot, receipt, running } = studio;
  const showReceipt = receipt && (receipt.state === 'rejected' || receipt.state === 'unknown') && receipt.commandId !== snapshot.run?.commandId;
  return (
    <div className="view">
      <ViewHeader title="Stage" subtitle="What’s playing, what the dog has acknowledged, and what comes next." />
      {showReceipt && (
        <p className={`notice notice-warn`} role="alert"><strong>{STATE_LABEL[receipt.state]}.</strong> {receipt.reason}</p>
      )}
      {snapshot.run && snapshot.connection !== 'connected' && snapshot.detail && <p className="notice notice-warn" role="alert">{snapshot.detail}</p>}
      {snapshot.run?.state === 'unknown' && <NowPlaying studio={studio} />}
      {!running && <ShowStarter studio={studio} onShows={onShows} />}
      {snapshot.run && snapshot.run.state !== 'unknown' && <NowPlaying studio={studio} />}
    </div>
  );
}
