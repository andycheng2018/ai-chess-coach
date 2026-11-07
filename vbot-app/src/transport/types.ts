/**
 * The one control boundary. Products and networks differ only by adapter, so
 * there's no second scheduler. Preview is deliberately absent: it is the pure
 * `buildTimeline`, so a preview has no way to reach a device.
 */
import type { CommandEnvelope, CommandReceipt, DeviceSnapshot } from '../domain/commands';
import type { Capabilities, CapabilityState } from '../domain/score';
import type { DriveFrame } from '../domain/drive';

export type TransportKind = 'fake' | 'local-face' | 'cloud';

/** Every field must be true. The operator confirms these in person; they are never stored. */
export type MotionConfirmation = { onsite: boolean; standing: boolean; clear: boolean };

/** Hold-to-drive on the controller. A frame is fire-and-forget; the dog's own watchdog is what stops it. */
export interface DriveControl {
  start(): Promise<{ ok: true } | { ok: false; reason: string }>;
  /** False means the frame did not get through, and the caller must stop. */
  frame(frame: DriveFrame): Promise<boolean>;
  stop(): Promise<{ ok: boolean; reason: string | null }>;
}

export type ConnectOptions = { target?: string; motion?: MotionConfirmation };

export interface DeviceTransport {
  readonly kind: TransportKind;
  /** True when no real robot can be reached through this adapter. */
  readonly simulated: boolean;
  /** Present only on adapters that can stream a drive. */
  readonly drive?: DriveControl;
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
export const MOTION_MISSING = 'Motion is off for this connection. Reconnect with motion enabled, after the onsite checks.';
export const NOT_CONNECTED = 'Connect to a dog first.';

export function noCapabilities(reason = NOT_CONNECTED): Capabilities {
  return {
    face: off(reason), head: off(reason), body: off(reason), move: off(reason), drive: off(reason), driveLimits: null,
    speech: off(SPEECH_MISSING), navigation: off(NAVIGATION_MISSING),
    supportedFaceIds: null, rehearsedPresets: [], armedPresets: [], armedMoves: [],
  };
}

export function emptySnapshot(detail: string | null = null): DeviceSnapshot {
  return {
    connection: 'disconnected', detail, device: null, sessionId: null, leaseGeneration: 0,
    capabilities: noCapabilities(), supportedFaces: null, run: null, events: [],
  };
}
