import { useCallback, useEffect, useRef, useState } from 'react';
import { runDrive, scaled, type DriveSpeed, type DriveVector } from '../domain/drive';
import type { Studio } from '../useStudio';

type Direction = Partial<Record<keyof DriveVector, -1 | 0 | 1>>;
type Button = { label: string; aria: string; direction: Direction };

/** Forward is +vx, left is +vy and counterclockwise (left) is +wz: ROS convention, UNCONFIRMED on this dog beyond the turn. */
const PAD: readonly (Button | null)[] = [
  { label: '↺', aria: 'Turn left while held', direction: { wz: 1 } },
  { label: '▲', aria: 'Walk forward while held', direction: { vx: 1 } },
  { label: '↻', aria: 'Turn right while held', direction: { wz: -1 } },
  { label: '◀', aria: 'Walk left while held', direction: { vy: 1 } }, null, { label: '▶', aria: 'Walk right while held', direction: { vy: -1 } },
  null, { label: '▼', aria: 'Walk back while held', direction: { vx: -1 } }, null,
];

const END_NOTE: Record<string, string | null> = {
  released: null,
  cap: 'Stopped at the hold limit. Press again to keep going.',
  refused: null,
  error: 'Stopped: the link to the dog dropped. The dog stops by itself within about half a second.',
};

/**
 * Hold a button to move; let go to stop. Frames stream while it is held, and the dog's own watchdog stops it the
 * moment they stop arriving (release, a dropped link, a closed tab). The units, response and run mode are not
 * documented, so the speeds are small and this has not yet been seen working on a dog.
 */
export function DrivePad({ studio }: { studio: Studio }) {
  const [speed, setSpeed] = useState<DriveSpeed>('slow');
  const [active, setActive] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const held = useRef(false);
  const looping = useRef(false);
  const { snapshot } = studio;
  const capability = snapshot.capabilities.drive;
  const limits = snapshot.capabilities.driveLimits ?? null;
  const control = studio.driver();
  const available = Boolean(capability?.available && limits && control);
  const busy = studio.running || studio.sending;

  const release = useCallback(() => { held.current = false; }, []);
  useEffect(() => {
    const hidden = () => { if (document.visibilityState !== 'visible') held.current = false; };
    window.addEventListener('blur', release);
    window.addEventListener('pagehide', release);
    document.addEventListener('visibilitychange', hidden);
    return () => {
      held.current = false; // unmounting is a release too
      window.removeEventListener('blur', release);
      window.removeEventListener('pagehide', release);
      document.removeEventListener('visibilitychange', hidden);
    };
  }, [release]);

  const press = (button: Button) => {
    if (!control || !limits || looping.current || busy) return;
    held.current = true;
    looping.current = true;
    setNote(null);
    setActive(button.aria);
    void runDrive({
      start: control.start, frame: control.frame, stop: control.stop,
      held: () => held.current && document.visibilityState === 'visible',
      vector: () => scaled(limits, button.direction, speed),
    }).then(outcome => {
      if (outcome.end === 'refused') setNote(outcome.detail ?? 'The dog did not start a drive.');
      else setNote(outcome.detail ?? END_NOTE[outcome.end]);
    }).finally(() => { looping.current = false; held.current = false; setActive(null); });
  };

  return (
    <section className="card move-pad" aria-labelledby="drive-pad-title">
      <h2 id="drive-pad-title">Drive (hold to move)</h2>
      <p className="fine">
        Hold a button to move; let go to stop. The dog stops itself the moment the stream of commands stops: on release,
        if the link drops, or if this page closes. Each press lasts at most 7 seconds, so press again to keep going.
        <strong> Not yet seen working on a real dog.</strong> Start with Slow, your hand on the dog.
      </p>
      <label className="field">
        <span>Speed</span>
        <select value={speed} disabled={Boolean(active)} onChange={event => setSpeed(event.target.value as DriveSpeed)}>
          <option value="slow">Slow</option>
          <option value="normal">Normal</option>
        </select>
      </label>
      <div className="pad-grid" role="group" aria-label="Drive pad">
        {PAD.map((button, index) => {
          if (!button) return <span key={index} className="pad-centre" aria-hidden="true">{index === 4 && active ? '●' : ''}</span>;
          return (
            <button key={button.aria} className="btn pad-button pad-hold" aria-label={button.aria} disabled={!available}
              onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); press(button); }}
              onPointerUp={release} onPointerCancel={release} onPointerLeave={release} onLostPointerCapture={release}
              onKeyDown={event => { if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) { event.preventDefault(); press(button); } }}
              onKeyUp={release} onBlur={release} onContextMenu={event => event.preventDefault()}>
              {button.label}
            </button>
          );
        })}
      </div>
      {note && <p className="notice notice-warn" role="status">{note}</p>}
      {!available && <p className="tile-reason">{capability?.reason ?? 'Driving needs motion enabled for this connection.'}</p>}
    </section>
  );
}
