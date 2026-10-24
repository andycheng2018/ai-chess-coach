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
  readyForNext?: boolean; postflightReason?: string; durationMs?: number;
};
export type VbotStatus = {
  companionApiVersion?: number; generation: number; armed: boolean;
  mode: 'live' | 'rehearsal'; gameId: string; target: string; busy: boolean;
  cooldownRemaining: number; danceCooldownRemaining: number; events: VbotEvent[];
  readinessFresh?: boolean;
  readiness?: { ready: boolean; target: string; reason?: string; checkedAt: number } | null;
  verification?: { applicationVersion?: string | null } | null;
};

/** Mutations are deliberate single requests. Never retry a physical operation. */
export async function vbotRequest(path: 'status' | 'check' | 'connect' | 'disarm', body?: object): Promise<VbotStatus> {
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

export function vbotNeedsDetach(status: VbotStatus, context: { gameId: string | null; resolved: boolean; ended: boolean }): boolean {
  return status.armed && context.resolved && (status.gameId !== context.gameId || context.ended);
}

export function vbotEventText(event: VbotEvent): string {
  const name = event.preset?.split('/').pop()?.replace('.json', '').replaceAll('_', ' ');
  if (event.status === 'completed') return event.readyForNext === false
    ? `${name || 'Reaction'} finished; paused: ${event.postflightReason || 'robot needs attention'}`
    : `${name || 'Reaction'} completed`;
  if (event.status === 'requested') return `${name || 'Reaction'} requested; awaiting robot result`;
  if (event.status === 'armed') return 'Reactions enabled for this match';
  if (event.status === 'disarmed') return 'Reactions turned off';
  if (event.status === 'rehearsed') return `Preview: ${name || 'reaction'}; no robot motion`;
  return event.reason || event.message || event.status;
}


/** Adopt only a session for this tab's selected game. A different tab may own another. */
export function vbotManagedSession(status: VbotStatus, previous: { gameId: string; generation: number } | null, gameId: string | null) {
  if (!status.armed) return null;
  if (previous?.gameId === status.gameId && previous.generation === status.generation) return previous;
  return status.gameId === gameId ? { gameId: status.gameId, generation: status.generation } : null;
}
