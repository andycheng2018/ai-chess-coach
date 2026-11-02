import { KIND_LABEL, type CapabilityKind } from '../domain/catalog';
import { CLOUD_MISSING } from '../transport/cloud';
import { FAKE_FAULTS, type FakeFault } from '../transport/fake';
import type { TransportKind } from '../transport/types';
import type { Studio } from '../useStudio';
import { FacePreview } from '../components/FacePreview';
import { ViewHeader } from '../components/bits';

const SOURCES: readonly { id: TransportKind; title: string; body: string }[] = [
  { id: 'fake', title: 'Simulated dog', body: 'Rehearse the whole app here. Nothing reaches a robot.' },
  { id: 'local-face', title: 'Real dog, through this computer', body: 'Face control only, over the local controller and pinned SSH.' },
  { id: 'cloud', title: 'Cloud', body: 'Not built yet. It needs the backend contract.' },
];

const CAPABILITY_ROWS: readonly Exclude<CapabilityKind, 'wait'>[] = ['face', 'head', 'body', 'speech', 'navigation'];

export function DogView({ studio, onBrowse }: { studio: Studio; onBrowse: () => void }) {
  const { snapshot, settings, simulated, running } = studio;
  const connected = snapshot.connection === 'connected';
  const needsTarget = settings.kind === 'local-face' && !settings.target.trim();
  return (
    <div className="view">
      <ViewHeader title="Your dog" subtitle="Connect, see what it can do right now, and find out why anything is unavailable." />
      <div className="dog-grid">
        <section className="card hero-card">
          <FacePreview label={connected ? 'happy' : 'sleep'} playing={connected} />
          <div className="hero-status">
            <h2>{snapshot.device?.label ?? (connected ? 'Connected' : 'No dog connected')}</h2>
            {snapshot.detail && <p role="status">{snapshot.detail}</p>}
            {running && snapshot.run && <p className="hero-busy">Now running: {snapshot.run.score.title}</p>}
            {snapshot.device && !simulated && <p className="mono" title="Stable identity from the dog's pinned SSH host key">{snapshot.device.id}</p>}
          </div>
          <div className="hero-actions">
            {connected
              ? <>
                  <button className="btn btn-primary" onClick={onBrowse}>Browse actions</button>
                  <button className="btn" disabled={running} onClick={() => void studio.disconnect()}>Disconnect</button>
                </>
              : <button className="btn btn-primary" disabled={studio.connecting || needsTarget || settings.kind === 'cloud'} onClick={() => void studio.connect()}>
                  {studio.connecting ? 'Connecting…' : snapshot.connection === 'lost' ? 'Reconnect and check status' : simulated ? 'Connect to simulated dog' : 'Connect'}
                </button>}
          </div>
        </section>

        <section className="card">
          <h2>Connection</h2>
          <div className="source-list" role="radiogroup" aria-label="How to reach the dog">
            {SOURCES.map(source => (
              <label key={source.id} className={`source ${settings.kind === source.id ? 'is-selected' : ''}`}>
                <input type="radio" name="source" checked={settings.kind === source.id} disabled={running} onChange={() => studio.setKind(source.id)} />
                <span><strong>{source.title}</strong><small>{source.body}</small></span>
              </label>
            ))}
          </div>
          {settings.kind === 'local-face' && (
            <label className="field">
              <span>Dog address on this network</span>
              <input value={settings.target} disabled={running || connected} placeholder="vbot@192.168.x.x" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                onChange={event => studio.setTarget(event.target.value)} />
              <small>Addresses change between networks. The dog is identified by its pinned SSH key, and an unknown or changed key is refused.</small>
            </label>
          )}
          {settings.kind === 'cloud' && <p className="notice">{CLOUD_MISSING}</p>}
        </section>

        <section className="card">
          <h2>What it can do now</h2>
          <ul className="capabilities">
            {CAPABILITY_ROWS.map(kind => {
              const capability = snapshot.capabilities[kind];
              return (
                <li key={kind} className={capability.available ? 'is-on' : 'is-off'}>
                  <span className="cap-mark" aria-hidden="true">{capability.available ? '✓' : '–'}</span>
                  <span><strong>{KIND_LABEL[kind]}</strong><small>{capability.available ? (simulated ? 'Available in simulation' : 'Available') : capability.reason}</small></span>
                </li>
              );
            })}
          </ul>
          {snapshot.supportedFaces && <p className="fine">This dog lists {snapshot.supportedFaces.length} usable expressions.</p>}
        </section>

        {simulated && (
          <section className="card">
            <h2>Rehearse a problem</h2>
            <p className="fine">Make the simulated dog misbehave, so you can see how the app reports it before a live demo.</p>
            <label className="field">
              <span>Simulated fault</span>
              <select value={studio.fault} onChange={event => studio.setFault(event.target.value as FakeFault)}>
                {FAKE_FAULTS.map(fault => <option key={fault.id} value={fault.id}>{fault.label}</option>)}
              </select>
              <small>{FAKE_FAULTS.find(fault => fault.id === studio.fault)?.detail}</small>
            </label>
          </section>
        )}
      </div>
    </div>
  );
}
