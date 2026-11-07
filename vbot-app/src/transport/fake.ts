/**
 * A deterministic simulated dog for rehearsing the app. It has no network or
 * robot code. Its clock, scheduler and durable store are injected, so tests can
 * model reconnects, restarts and faults exactly.
 */
import { CATALOG } from '../domain/catalog';
import { isTerminal, type CommandEnvelope, type CommandReceipt, type DeviceEvent, type DeviceSnapshot, type RejectionCode, type RunView } from '../domain/commands';
import type { KeyValueStore } from '../domain/library';
import { admitScore, buildTimeline, parseScore, type Capabilities, type TimelineItem } from '../domain/score';
import { emptySnapshot, NAVIGATION_MISSING, noCapabilities, SPEECH_MISSING, type ConnectOptions, type DeviceTransport } from './types';

export type FakeFault = 'none' | 'busy' | 'unknown-next-cue' | 'backend-down' | 'cleanup-fails' | 'no-motion' | 'connection-lost';

export const FAKE_FAULTS: readonly { id: FakeFault; label: string; detail: string }[] = [
  { id: 'none', label: 'No fault', detail: 'The simulated dog behaves normally.' },
  { id: 'busy', label: 'Controller busy', detail: 'Another owner holds the controller, so a new show is rejected.' },
  { id: 'unknown-next-cue', label: 'Unknown outcome', detail: 'The next cue is sent and no answer comes back.' },
  { id: 'connection-lost', label: 'Connection lost', detail: 'The link drops during the next cue.' },
  { id: 'backend-down', label: 'Backend unavailable', detail: 'The dog can’t be reached, so connecting fails.' },
  { id: 'cleanup-fails', label: 'Cleanup fails', detail: 'The display can’t be released after the show.' },
  { id: 'no-motion', label: 'No motion capability', detail: 'The dog reports head and body control unavailable.' },
];

const KEY = 'vbot-studio.fake-device.v1';
const SEEN_LIMIT = 512;

type Durable = {
  seen: Record<string, { state: CommandReceipt['state']; fingerprint: string; code?: RejectionCode; reason?: string }>;
  leaseGeneration: number; activeRun: RunView | null;
};

export type FakeOptions = {
  store: KeyValueStore; now?: () => number;
  schedule?: (callback: () => void, ms: number) => () => void;
  sessionId?: () => string;
};

const DEVICE = { id: 'simulated-dog', label: 'Simulated dog' };

function capabilities(fault: FakeFault): Capabilities {
  const allPresets = CATALOG.flatMap(entry => entry.preset ? [entry.preset] : []);
  const motion = fault === 'no-motion'
    ? { available: false, reason: 'Simulated fault: this dog reports head and body control unavailable.' }
    : { available: true, reason: null };
  return {
    face: { available: true, reason: null }, head: motion, body: motion, move: motion, drive: motion,
    driveLimits: motion.available ? { vx: 0.15, vy: 0.10, wz: 0.40 } : null,
    speech: { available: false, reason: SPEECH_MISSING }, navigation: { available: false, reason: NAVIGATION_MISSING },
    supportedFaceIds: null, rehearsedPresets: allPresets,
    armedMoves: CATALOG.flatMap(entry => entry.move ? [entry.move] : []),
  };
}

export class FakeTransport implements DeviceTransport {
  /** A simulated drive that only records what it was asked, so the UI can be rehearsed with no robot. */
  readonly driveLog: string[] = [];
  readonly drive = {
    start: async () => { this.driveLog.push('start'); return { ok: true as const }; },
    frame: async () => { this.driveLog.push('frame'); return true; },
    stop: async () => { this.driveLog.push('stop'); return { ok: true, reason: 'stopped' }; },
  };

  readonly kind = 'fake' as const;
  readonly simulated = true;
  fault: FakeFault = 'none';
  private readonly store: KeyValueStore;
  private readonly now: () => number;
  private readonly schedule: (callback: () => void, ms: number) => () => void;
  private readonly makeSession: () => string;
  private readonly listeners = new Set<(snapshot: DeviceSnapshot) => void>();
  private durable: Durable;
  private snapshot: DeviceSnapshot;
  private items: TimelineItem[] = [];
  private cancelTimer: (() => void) | null = null;

  constructor(options: FakeOptions) {
    this.store = options.store;
    this.now = options.now ?? Date.now;
    this.schedule = options.schedule ?? ((callback, ms) => {
      const timer = setTimeout(callback, ms);
      return () => clearTimeout(timer);
    });
    this.makeSession = options.sessionId ?? (() => crypto.randomUUID());
    this.durable = this.readDurable();
    this.snapshot = emptySnapshot();
    this.reconcileAfterRestart();
  }

  private readDurable(): Durable {
    const empty: Durable = { seen: {}, leaseGeneration: 0, activeRun: null };
    try {
      const text = this.store.getItem(KEY);
      if (!text) return empty;
      const data = JSON.parse(text) as Durable;
      return typeof data.seen === 'object' && data.seen !== null ? { ...empty, ...data } : empty;
    } catch { return empty; }
  }

  private writeDurable() {
    const ids = Object.keys(this.durable.seen);
    for (const id of ids.slice(0, Math.max(0, ids.length - SEEN_LIMIT))) delete this.durable.seen[id];
    try { this.store.setItem(KEY, JSON.stringify(this.durable)); } catch { /* the simulator can run without storage */ }
  }

  /** A restart can't know how an in-flight command ended, so it is unknown and is never resumed. */
  private reconcileAfterRestart() {
    const run = this.durable.activeRun;
    if (!run) return;
    if (!isTerminal(run.state)) {
      const reason = 'The app restarted during this simulated show. It was not resumed or replayed.';
      this.durable.activeRun = { ...run, state: 'unknown', reason, cueEndsAt: null, finishedAt: this.now() };
      this.durable.seen[run.commandId] = { ...this.durable.seen[run.commandId], state: 'unknown', reason };
      this.writeDurable();
    }
    this.snapshot = { ...this.snapshot, run: this.durable.activeRun };
  }

  private publish() {
    const copy = this.current();
    for (const listener of this.listeners) listener(copy);
  }

  private current(): DeviceSnapshot {
    return { ...this.snapshot, events: [...this.snapshot.events] };
  }

  private event(message: string, extra: Partial<DeviceEvent> = {}) {
    this.snapshot = { ...this.snapshot, events: [{ time: this.now(), message, ...extra }, ...this.snapshot.events].slice(0, 80) };
  }

  setFault(fault: FakeFault) {
    this.fault = fault;
    if (this.snapshot.connection === 'connected') {
      this.snapshot = { ...this.snapshot, capabilities: capabilities(fault) };
      this.publish();
    }
  }

  async connect(_options: ConnectOptions): Promise<DeviceSnapshot> {
    if (this.fault === 'backend-down') {
      this.snapshot = { ...this.snapshot, connection: 'unavailable', detail: 'Simulated fault: the simulated dog could not be reached.', capabilities: noCapabilities() };
      this.publish();
      return this.current();
    }
    this.durable.leaseGeneration += 1;
    this.writeDurable();
    this.snapshot = {
      ...this.snapshot, connection: 'connected', detail: 'Nothing is sent to a real robot.', device: DEVICE,
      sessionId: this.makeSession(), leaseGeneration: this.durable.leaseGeneration,
      capabilities: capabilities(this.fault),
    };
    this.event('Connected to the simulated dog.');
    this.publish();
    return this.current();
  }

  async disconnect(): Promise<DeviceSnapshot> {
    this.stopTimer();
    const run = this.snapshot.run;
    if (run && !isTerminal(run.state)) this.finish('cancelled', 'Disconnected. No further cues will run.');
    this.snapshot = { ...this.snapshot, connection: 'disconnected', detail: null, device: null, sessionId: null, capabilities: noCapabilities() };
    this.event('Disconnected.');
    this.publish();
    return this.current();
  }

  async status(): Promise<DeviceSnapshot> { return this.current(); }

  private rejected(commandId: string, fingerprint: string, code: RejectionCode, reason: string): CommandReceipt {
    this.durable.seen[commandId] = { state: 'rejected', fingerprint, code, reason };
    this.writeDurable();
    this.event(`Rejected: ${reason}`, { commandId, state: 'rejected' });
    this.publish();
    return { commandId, state: 'rejected', duplicate: false, code, reason };
  }

  async submit(envelope: CommandEnvelope): Promise<CommandReceipt> {
    const { commandId } = envelope;
    const fingerprint = JSON.stringify(envelope.score);
    const seen = this.durable.seen[commandId];
    if (seen) {
      if (seen.fingerprint !== fingerprint) {
        return { commandId, state: 'rejected', duplicate: true, code: 'identity_conflict', reason: 'This command ID already belongs to a different show.' };
      }
      return { commandId, state: seen.state, duplicate: true, code: seen.code, reason: seen.reason };
    }
    const reject = (code: RejectionCode, reason: string) => this.rejected(commandId, fingerprint, code, reason);
    if (this.snapshot.connection !== 'connected') return reject('not_connected', 'The simulated dog is not connected.');
    if (envelope.deviceId !== this.snapshot.device?.id) return reject('wrong_device', 'This command is for a different dog.');
    if (envelope.sessionId !== this.snapshot.sessionId || envelope.leaseGeneration !== this.snapshot.leaseGeneration) {
      return reject('stale_lease', 'This command is from an earlier connection.');
    }
    if (this.now() >= envelope.expiresAt) return reject('expired', 'This command expired before it was received.');
    const parsed = parseScore(envelope.score);
    if (!parsed.ok) return reject('invalid_score', parsed.errors[0] ?? 'The show failed validation.');
    if (this.fault === 'busy' || (this.snapshot.run && !isTerminal(this.snapshot.run.state))) {
      return reject('busy', 'The controller is busy with another operation.');
    }
    const admission = admitScore(parsed.score, this.snapshot.capabilities);
    if (!admission.ok) return reject('capability_unavailable', admission.blockers[0].reason);

    this.items = buildTimeline(parsed.score).items;
    const run: RunView = {
      commandId, state: 'running', score: envelope.score, cueIndex: 0, completedCues: 0, cueAck: 'idle', cueEndsAt: null,
      reason: null, cleanup: parsed.score.cues.some(cue => cue.type !== 'wait') ? 'pending' : 'not-needed',
      startedAt: this.now(), finishedAt: null,
    };
    this.durable.seen[commandId] = { state: 'running', fingerprint };
    this.durable.activeRun = run;
    this.writeDurable();
    this.snapshot = { ...this.snapshot, run };
    this.event(`Started “${parsed.score.title}” (simulated).`, { commandId, state: 'running' });
    this.playCue(0);
    this.publish();
    return { commandId, state: 'accepted', duplicate: false };
  }

  private playCue(index: number) {
    const run = this.snapshot.run;
    if (!run) return;
    if (index >= this.items.length) { this.finish('completed', null); return; }
    const item = this.items[index];
    if (this.fault === 'unknown-next-cue' || this.fault === 'connection-lost') {
      const lost = this.fault === 'connection-lost';
      const reason = lost
        ? 'Simulated: the connection dropped during this cue. Its outcome is unknown and it will not be retried.'
        : 'Simulated: this cue got no answer. Its outcome is unknown and it will not be retried.';
      this.patchRun({ cueIndex: index, cueAck: 'sent' });
      this.finish('unknown', reason, 'failed');
      if (lost) this.snapshot = { ...this.snapshot, connection: 'lost', detail: 'Simulated: connection lost. Reconnect to check status. Nothing is replayed.', capabilities: noCapabilities('Reconnect to check status.') };
      return;
    }
    const ends = this.now() + item.durationMs;
    this.patchRun({ cueIndex: index, cueAck: item.cue.type === 'wait' ? 'waiting' : 'started', cueEndsAt: ends });
    this.stopTimer();
    this.cancelTimer = this.schedule(() => {
      this.patchRun({ completedCues: index + 1, cueAck: 'finished', cueEndsAt: null });
      this.playCue(index + 1);
      this.publish();
    }, item.durationMs);
  }

  private patchRun(change: Partial<RunView>) {
    if (!this.snapshot.run) return;
    const run = { ...this.snapshot.run, ...change };
    this.snapshot = { ...this.snapshot, run };
    this.durable.activeRun = run;
    this.writeDurable();
  }

  private stopTimer() {
    this.cancelTimer?.();
    this.cancelTimer = null;
  }

  private finish(state: 'completed' | 'cancelled' | 'unknown', reason: string | null, forcedCleanup?: RunView['cleanup']) {
    this.stopTimer();
    const run = this.snapshot.run;
    if (!run) return;
    const cleanup = forcedCleanup ?? (run.cleanup === 'not-needed' ? 'not-needed' : this.fault === 'cleanup-fails' ? 'failed' : 'released');
    this.patchRun({ state, reason, cleanup, cueEndsAt: null, finishedAt: this.now() });
    const seen = this.durable.seen[run.commandId];
    if (seen) this.durable.seen[run.commandId] = { ...seen, state, reason: reason ?? undefined };
    this.writeDurable();
    this.event(state === 'completed' ? 'Show complete (simulated).' : reason ?? `Show ended: ${state}.`, { commandId: run.commandId, state });
    if (cleanup === 'failed' && state !== 'unknown') this.event('Simulated: the display could not be released.', { commandId: run.commandId });
  }

  async cancelFutureCues(commandId: string): Promise<DeviceSnapshot> {
    const run = this.snapshot.run;
    if (run && run.commandId === commandId && !isTerminal(run.state)) {
      this.finish('cancelled', 'Future cues cancelled. The simulated dog is idle.');
      this.publish();
    }
    return this.current();
  }

  subscribe(listener: (snapshot: DeviceSnapshot) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  dispose() {
    this.stopTimer();
    this.listeners.clear();
  }
}
