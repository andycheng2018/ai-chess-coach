import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CATALOG, EXERCISED_FACE_IDS, FACELESS_MOVE_NAMES, type CatalogEntry } from '../domain/catalog';
import { runHold } from '../domain/hold';
import { admitScore, cueFromEntry, makeScore, withMoveFace, type Cue } from '../domain/score';
import type { Studio } from '../useStudio';

type Button = { move: string; label: string; aria: string; hold: boolean };

/** The pad is 3×3. A hold button repeats one small bounded turn while it is held; a tap button sends one move. */
const PAD: readonly (Button | null)[] = [
  { move: 'turn_left_10', label: '↺', aria: 'Turn left, hold to keep turning', hold: true },
  { move: 'step_forward', label: '▲', aria: 'Step forward', hold: false },
  { move: 'turn_right_10', label: '↻', aria: 'Turn right, hold to keep turning', hold: true },
  { move: 'step_left', label: '◀', aria: 'Step left', hold: false }, null, { move: 'step_right', label: '▶', aria: 'Step right', hold: false },
  { move: 'turn_left_90', label: '↺ 90°', aria: 'Turn left 90 degrees', hold: false },
  { move: 'step_back', label: '▼', aria: 'Step back', hold: false },
  { move: 'turn_right_90', label: '↻ 90°', aria: 'Turn right 90 degrees', hold: false },
];

const BY_MOVE = new Map(CATALOG.filter(entry => entry.kind === 'move').map(entry => [entry.move!, entry]));

export function MovePad({ studio }: { studio: Studio }) {
  const [faceId, setFaceId] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const { snapshot } = studio;
  const pressed = useRef(false);
  const looping = useRef(false);
  const faces = useMemo(() => {
    const listed = snapshot.capabilities.supportedFaceIds;
    return CATALOG.filter((entry): entry is CatalogEntry & { assetId: number } =>
      entry.kind === 'face' && entry.assetId !== undefined && EXERCISED_FACE_IDS.includes(entry.assetId) && (!listed || listed.includes(entry.assetId)));
  }, [snapshot.capabilities.supportedFaceIds]);

  const cueFor = useCallback((move: string): Cue | null => {
    const entry = BY_MOVE.get(move);
    const cue = entry ? cueFromEntry(entry) : null;
    // Steps run a vendor preset that controls the screen, so they never carry the chosen face.
    return cue && cue.type === 'move' ? withMoveFace(cue, FACELESS_MOVE_NAMES.has(move) ? null : faceId) : null;
  }, [faceId]);

  const first = cueFor('turn_left_30');
  const blocker = first ? admitScore(makeScore('check', 0, [first]), snapshot.capabilities).blockers[0]?.reason ?? null : null;
  const busy = studio.running || studio.sending;

  // Every way a hold can end other than letting go. Each one clears `pressed`, which the loop checks before every send.
  const release = useCallback(() => { pressed.current = false; }, []);
  useEffect(() => {
    const hide = () => { if (document.visibilityState !== 'visible') pressed.current = false; };
    window.addEventListener('blur', release);
    window.addEventListener('pagehide', release);
    document.addEventListener('visibilitychange', hide);
    return () => {
      pressed.current = false;
      window.removeEventListener('blur', release);
      window.removeEventListener('pagehide', release);
      document.removeEventListener('visibilitychange', hide);
    };
  }, [release]);

  const send = useCallback(async (move: string, label: string) => {
    const cue = cueFor(move);
    if (!cue) return null;
    const result = await studio.startShow(makeScore(`Move: ${label}`, Date.now(), [cue]));
    return result && result.state === 'accepted' && !result.duplicate ? { commandId: result.commandId } : null;
  }, [cueFor, studio]);

  const tap = (button: Button) => { void send(button.move, button.aria); };

  const press = (button: Button) => {
    // Never start a hold while another command is running. A hold button is not disabled mid-hold, because a
    // disabled element drops its pointer events and could miss the release.
    if (!looping.current && busy) return;
    pressed.current = true;
    if (looping.current) return; // a quick re-press during the move in flight just keeps that hold going
    looping.current = true;
    setNote(null);
    void runHold({
      send: () => send(button.move, button.aria),
      settled: studio.waitForRun,
      holding: () => pressed.current && document.visibilityState === 'visible',
    }).then(outcome => {
      if (outcome.end === 'cap') setNote('Stopped after the hold limit. Press again to keep turning.');
      else if (outcome.end === 'not-clean') setNote('Stopped: the last turn did not finish cleanly. Check the dog.');
    }).finally(() => { looping.current = false; pressed.current = false; });
  };

  return (
    <section className="card move-pad" aria-labelledby="move-pad-title">
      <h2 id="move-pad-title">Move pad</h2>
      <p className="fine">
        Hold ↺ or ↻ to keep turning; let go to stop. It sends one small 10° turn at a time (about 2 s each), and
        the next goes only while the button is still held, so letting go stops it after the turn already underway.
        Other buttons send one move per tap. A turn can show a face while it moves.
      </p>
      <label className="field">
        <span>Face during a turn</span>
        <select value={faceId ?? ''} disabled={busy} onChange={event => setFaceId(event.target.value === '' ? null : Number(event.target.value))}>
          <option value="">None</option>
          {faces.map(entry => <option key={entry.assetId} value={entry.assetId}>{entry.label}</option>)}
        </select>
      </label>
      <div className="pad-grid" role="group" aria-label="Move pad">
        {PAD.map((button, index) => {
          if (!button) return <span key={index} className="pad-centre" aria-hidden="true" />;
          const unavailable = Boolean(blocker) || !cueFor(button.move);
          if (!button.hold) {
            return <button key={button.move} className="btn pad-button" aria-label={button.aria} disabled={busy || unavailable} onClick={() => tap(button)}>{button.label}</button>;
          }
          return (
            <button key={button.move} className="btn pad-button pad-hold" aria-label={button.aria} disabled={unavailable}
              onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); press(button); }}
              onPointerUp={release} onPointerCancel={release} onPointerLeave={release} onLostPointerCapture={release}
              onKeyDown={event => { if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) { event.preventDefault(); press(button); } }}
              onKeyUp={release} onBlur={release} onContextMenu={event => event.preventDefault()}>
              {button.label}
            </button>
          );
        })}
      </div>
      <p className="fine">Steps can’t show a face (they run the vendor’s own step preset) and aren’t confirmed to move the dog yet.</p>
      {note && <p className="notice notice-warn" role="status">{note}</p>}
      {blocker && <p className="tile-reason">{blocker}</p>}
    </section>
  );
}
