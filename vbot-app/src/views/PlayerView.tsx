import { useState } from 'react';
import { trackingStatus, type Detection, type PlayerSelection } from '../domain/perception';
import type { Studio } from '../useStudio';
import { ViewHeader } from '../components/bits';

/** Made-up boxes so the selection flow can be rehearsed. Shown only for the simulated dog. */
function simulatedDetections(now: number): Detection[] {
  return [
    { trackId: 'sim-a', box: { x: 14, y: 18, width: 22, height: 70 }, score: .81, observedAt: now },
    { trackId: 'sim-b', box: { x: 58, y: 24, width: 20, height: 64 }, score: .76, observedAt: now },
  ];
}

const FACTS: readonly string[] = [
  'The dog’s detector reports people as 2D image boxes and 17-point poses.',
  'Those detections have no stable identity and no measured 3D position. Pose z=0 is not depth.',
  'Map-coordinate queries have not been demonstrated, and /slam/status reports odometry mode with no map.',
  'Depth association, distance keeping and sideline pacing are later supervised milestones.',
];

export function PlayerView({ studio }: { studio: Studio }) {
  const { simulated, snapshot } = studio;
  const [selection, setSelection] = useState<PlayerSelection | null>(null);
  const [personLeft, setPersonLeft] = useState(false);
  const live = simulated && snapshot.connection === 'connected';
  const now = Date.now();
  const detections = live ? simulatedDetections(now).filter(item => !(personLeft && item.trackId === selection?.trackId)) : [];
  const tracking = trackingStatus(selection, detections, now);

  return (
    <div className="view">
      <ViewHeader title="Player" subtitle="Staged for later. The host chooses the player, and the dog never guesses." />
      <div className="dog-grid">
        <section className="card">
          <h2>Current detections</h2>
          {!live && <p className="notice">No perception feed is connected. The real adapter is not built yet, so no detections are shown.</p>}
          {live && (
            <>
              <p className="sim-tag">Simulated people, made up for this rehearsal</p>
              <div className="camera" role="group" aria-label="Simulated camera view">
                {detections.map((item, index) => (
                  <button key={item.trackId} className={`person-box ${selection?.trackId === item.trackId ? 'is-player' : ''}`}
                    style={{ left: `${item.box.x}%`, top: `${item.box.y}%`, width: `${item.box.width}%`, height: `${item.box.height}%` }}
                    aria-pressed={selection?.trackId === item.trackId}
                    onClick={() => { setPersonLeft(false); setSelection({ sessionId: snapshot.sessionId ?? '', selectedAt: now, trackId: item.trackId, chosenBy: 'host' }); }}>
                    <span>{selection?.trackId === item.trackId ? 'My player' : `Person ${index + 1}`}</span>
                  </button>
                ))}
              </div>
              <p className="fine">Tap a person to say “this is my player”.</p>
            </>
          )}
        </section>
        <section className="card">
          <h2>Tracking</h2>
          <dl className="facts">
            <div><dt>Selected player</dt><dd>{selection ? 'Chosen by the host' : 'None'}</dd></div>
            <div><dt>Status</dt><dd role="status">{tracking.message}</dd></div>
            <div><dt>Location</dt><dd>Unknown. Depth association isn’t verified.</dd></div>
            <div><dt>Last-seen memory</dt><dd>Not available yet.</dd></div>
          </dl>
          {live && selection && !personLeft && <button className="btn btn-small" onClick={() => setPersonLeft(true)}>Simulate the player walking away</button>}
          {selection && <button className="btn btn-small" onClick={() => { setSelection(null); setPersonLeft(false); }}>Clear selection</button>}
        </section>
        <section className="card">
          <h2>What’s actually known</h2>
          <ul className="plain-list">{FACTS.map(fact => <li key={fact}>{fact}</li>)}</ul>
        </section>
      </div>
    </div>
  );
}
