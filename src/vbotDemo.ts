import { CONTROL_URL, type CoachResult } from './coach';

/** Fire once from accepted live coaching; never block the chess/voice pipeline. */
export async function notifyVbotMove(
  result: CoachResult, gameId: string, playerColor: 'white' | 'black',
): Promise<void> {
  if (!gameId || result.gameId !== gameId || !result.recordId || result.playerColor !== playerColor) return;
  try {
    const response = await fetch(`${CONTROL_URL}/api/vbot/celebrate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recordId: result.recordId, gameId, playerColor }),
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) console.warn('VBOT demo unavailable; chess continues normally.');
  } catch {
    // The demo dashboard shows accepted events. Do not retry a physical command.
    console.warn('VBOT demo unavailable; chess continues normally.');
  }
}


export type VbotEvent = {
  time: number; status: string; gameId?: string; playedMove?: string;
  reason?: string; message?: string; preset?: string; requestId?: string;
  paceReason?: string; classification?: string; tier?: string;
  readyForNext?: boolean; postflightReason?: string; durationMs?: number;
};
export type VbotNetwork = {
  current: { id: string | null; ssid?: string | null; localIp?: string; subnet?: string; gateway?: string; message?: string | null };
  label?: string | null; suggestedTarget?: string | null; error?: string | null;
  addresses: { target: string; lastVerifiedAt?: number | null }[];
  profiles: { id: string; label: string; targets: string[] }[];
};
export type ReactionProfile = 'quiet' | 'balanced' | 'showmanship';
export type VbotStatus = {
  reactionProfile?: ReactionProfile;
  network?: VbotNetwork | null;
  companionApiVersion?: number; generation: number; armed: boolean;
  mode: 'live' | 'rehearsal'; gameId: string; target: string; busy: boolean;
  cooldownRemaining: number; danceCooldownRemaining: number; events: VbotEvent[];
  readinessFresh?: boolean; sadPresetVerified?: boolean; finishPending?: boolean; victoryPending?: boolean;
  smallPresets?: string[]; smallPresetCandidates?: string[]; operatorApprovedPresets?: string[];
  readiness?: { ready: boolean; target: string; reason?: string; code?: string; checkedAt: number } | null;
  verification?: { applicationVersion?: string | null } | null;
};

/** Mutations are deliberate single requests. Never retry a physical operation. */
export async function vbotRequest(path: 'status' | 'check' | 'connect' | 'disarm' | 'finish' | 'networks/remember', body?: object): Promise<VbotStatus> {
  const response = await fetch(`${CONTROL_URL}/api/vbot/${path}`, {
    ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(path === 'check' ? 30000 : 10000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.message || 'VBOT controller unavailable. Chess can continue.');
  }
  return response.json();
}

export type VbotConnectPayload = {
  gameId: string; playerColor: 'white' | 'black'; mode: 'live' | 'rehearsal';
  target: string; preset: string; applicationVersion: string; practice?: boolean;
  reactionProfile?: ReactionProfile;
  confirmSafeWorkspace: boolean; confirmHandsetStop: boolean;
};

/** One explicit enable action performs its own fresh check. No polling-time
 * probes, retries, or automatic rearming of an expired/disarmed session. */
export async function connectVbotWithReadiness(payload: VbotConnectPayload, isCurrent: () => boolean): Promise<VbotStatus> {
  if (!isCurrent()) throw new Error('The selected match changed. Enable reactions from the current match.');
  if (payload.mode === 'live') {
    if (!payload.confirmSafeWorkspace || !payload.confirmHandsetStop) {
      throw new Error('Confirm the workspace and onsite Stop before enabling reactions.');
    }
    const checked = await vbotRequest('check', { target: payload.target });
    if (!isCurrent()) throw new Error('The selected match changed during the check. No reactions enabled.');
    if (!checked.readinessFresh || !checked.readiness?.ready || checked.readiness.target !== payload.target) {
      throw new Error(checked.readiness?.reason || 'Robot is not ready. Inspect VBOT before trying again.');
    }
  }
  return vbotRequest('connect', payload);
}

export function vbotNeedsDetach(status: VbotStatus, context: { gameId: string | null; resolved: boolean; ended: boolean }): boolean {
  return status.armed && context.resolved && (status.gameId !== context.gameId || context.ended);
}

export function vbotReactionLabel(preset: string): string {
  const labels: Record<string, string> = {
    'actions/HAPPY_LITTLE_JUMP.json': 'Small happy jump', 'actions/HAPPY_JUMP.json': 'Happy jump',
    'actions/JUMP_IN_PLACE.json': 'Jump in place', 'actions/WAVE.json': 'Wave', 'atom/look_left.json': 'Look left',
    'atom/look_right.json': 'Look right', 'atom/look_forward.json': 'Look forward',
    'atom/look_up.json': 'Look up', 'atom/look_down.json': 'Look down',
    'actions/SHAKEHAND.json': 'Handshake', 'actions/SHAKEHAND_L.json': 'Left handshake',
    'actions/HIGH_FIVE_R.json': 'Right high-five', 'actions/HIGH_FIVE_L.json': 'Left high-five',
    'actions/SAYYES.json': 'Approving yes', 'actions/ROCKYOU.json': 'Rock You',
    'actions/GRIEVANCE.json': 'Sad reaction',
  };
  return labels[preset] || preset.split('/').pop()?.replace('.json', '').replaceAll('_', ' ') || 'Reaction';
}

export function vbotEventText(event: VbotEvent): string {
  const name = event.preset ? vbotReactionLabel(event.preset) : undefined;
  if (event.status === 'completed') return event.readyForNext === false
    ? `${name || 'Reaction'} finished; paused: ${event.postflightReason || 'robot needs attention'}`
    : `${name || 'Reaction'} completed`;
  if (event.status === 'requested') return `${name || 'Reaction'} requested; awaiting robot result`;
  if (event.status === 'armed') return 'Reactions enabled for this match';
  if (event.status === 'disarmed') return event.reason || 'Reactions turned off';
  if (event.status === 'rehearsed') return `Preview: ${name || 'reaction'}; no robot motion`;
  return event.reason || event.message || event.status;
}


/** Adopt only a session for this tab's selected game. A different tab may own another. */
export function vbotManagedSession(status: VbotStatus, previous: { gameId: string; generation: number } | null, gameId: string | null) {
  if (!status.armed) return null;
  if (previous?.gameId === status.gameId && previous.generation === status.generation) return previous;
  return status.gameId === gameId ? { gameId: status.gameId, generation: status.generation } : null;
}
