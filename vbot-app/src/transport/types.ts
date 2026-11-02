/**
 * The one control boundary. Products and networks differ only by adapter, so
 * there's no second scheduler. Preview is deliberately absent: it is the pure
 * `buildTimeline`, so a preview has no way to reach a device.
 */
import type { CommandEnvelope, CommandReceipt, DeviceSnapshot } from '../domain/commands';
import type { Capabilities, CapabilityState } from '../domain/score';

export type TransportKind = 'fake' | 'local-face' | 'cloud';

export type ConnectOptions = { target?: string };

export interface DeviceTransport {
  readonly kind: TransportKind;
  /** True when no real robot can be reached through this adapter. */
  readonly simulated: boolean;
  /** Reconnect reconciles status only. It never drains or replays commands. */
  connect(options: ConnectOptions): Promise<DeviceSnapshot>;
  disconnect(): Promise<DeviceSnapshot>;
  status(): Promise<DeviceSnapshot>;
  /** A failed or lost submit reports `unknown`. Adapters never retry it. */
  submit(envelope: CommandEnvelope): Promise<CommandReceipt>;
  /** Stops future cues. It doesn't claim to stop motion already underway. */
  cancelFutureCues(commandId: string): Promise<DeviceSnapshot>;
  subscribe(listener: (snapshot: DeviceSnapshot) => void): () => void;
  dispose(): void;
}

const off = (reason: string): CapabilityState => ({ available: false, reason });

export const SPEECH_MISSING = 'No speech backend has been verified on this dog.';
export const NAVIGATION_MISSING = 'Navigation has no demonstrated live provider. The schema exists, but that does not prove it works.';
export const MOTION_MISSING = 'This adapter is face-only. Motion needs its own authorization, a rehearsal on this dog and a verified stopping procedure.';
export const NOT_CONNECTED = 'Connect to a dog first.';

export function noCapabilities(reason = NOT_CONNECTED): Capabilities {
  return {
    face: off(reason), head: off(reason), body: off(reason),
    speech: off(SPEECH_MISSING), navigation: off(NAVIGATION_MISSING),
    supportedFaceIds: null, rehearsedPresets: [],
  };
}

export function emptySnapshot(detail: string | null = null): DeviceSnapshot {
  return {
    connection: 'disconnected', detail, device: null, sessionId: null, leaseGeneration: 0,
    capabilities: noCapabilities(), supportedFaces: null, run: null, events: [],
  };
}
