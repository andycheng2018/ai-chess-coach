/**
 * The command contract every transport shares. A command is single-use: an
 * uncertain outcome stays `unknown` and is never replayed automatically.
 */
import { newId, snapshotScore, type Capabilities, type Score } from './score';

export const COMMAND_VERSION = 1;
export const COMMAND_TTL_MS = 30000;

export type CommandState = 'received' | 'accepted' | 'running' | 'completed' | 'rejected' | 'cancelled' | 'unknown';
export const TERMINAL_STATES: ReadonlySet<CommandState> = new Set(['completed', 'rejected', 'cancelled', 'unknown']);
export const isTerminal = (state: CommandState) => TERMINAL_STATES.has(state);

export type RejectionCode =
  | 'expired' | 'stale_lease' | 'wrong_device' | 'not_connected' | 'busy'
  | 'invalid_score' | 'capability_unavailable' | 'identity_conflict' | 'backend_unavailable';

export type CommandEnvelope = {
  v: 1; commandId: string; deviceId: string; sessionId: string; leaseGeneration: number;
  issuedAt: number; expiresAt: number; kind: 'run-score'; score: Readonly<Score>;
};

export type CommandReceipt = {
  commandId: string; state: CommandState; duplicate: boolean; code?: RejectionCode; reason?: string;
};

export type CueAck = 'idle' | 'sent' | 'started' | 'waiting' | 'finished';
export type CleanupState = 'not-needed' | 'pending' | 'released' | 'failed';

export type RunView = {
  commandId: string; state: CommandState; score: Readonly<Score>; cueIndex: number; completedCues: number;
  cueAck: CueAck; cueEndsAt: number | null; reason: string | null; cleanup: CleanupState;
  startedAt: number; finishedAt: number | null;
};

export type DeviceEvent = { time: number; message: string; commandId?: string; state?: CommandState };

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'lost' | 'unavailable';

export type DeviceSnapshot = {
  connection: ConnectionState; detail: string | null;
  device: { id: string; label: string } | null;
  sessionId: string | null; leaseGeneration: number;
  capabilities: Capabilities;
  /** Names the connected dog reported, or null if it hasn't been asked. */
  supportedFaces: string[] | null;
  run: RunView | null; events: DeviceEvent[];
};

export function makeEnvelope(score: Score, snapshot: DeviceSnapshot, now: number): CommandEnvelope {
  if (!snapshot.device || !snapshot.sessionId) throw new Error('Connect to a dog before sending a command.');
  return {
    v: COMMAND_VERSION, commandId: newId(), deviceId: snapshot.device.id, sessionId: snapshot.sessionId,
    leaseGeneration: snapshot.leaseGeneration, issuedAt: now, expiresAt: now + COMMAND_TTL_MS,
    kind: 'run-score', score: snapshotScore(score),
  };
}

export const STATE_LABEL: Record<CommandState, string> = {
  received: 'Received', accepted: 'Accepted', running: 'Running', completed: 'Completed',
  rejected: 'Rejected', cancelled: 'Future cues cancelled', unknown: 'Outcome unknown',
};
