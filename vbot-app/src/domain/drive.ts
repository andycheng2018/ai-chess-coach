/**
 * Hold-to-drive. While a button is held the app streams short velocity frames; the DOG's own watchdog is what
 * actually keeps this safe (it publishes only while fresh frames arrive and sends zeros on every way a drive can
 * end), so a closed tab, a dropped link or a crash all stop the dog without this code's help. What this module
 * adds is the other half: it never sends a frame after release, it asks for the stop immediately on release, it
 * stops once per press at a cap shorter than the dog's, and it ends on any error. Nothing here contacts a robot.
 */
export const DRIVE_FRAME_MS = 100;
/** One press drives at most this long, always shorter than the dog's own per-press limit (8 s). Press again to continue. */
export const DRIVE_HOLD_MAX_MS = 7000;

/** Fractions of the dog's caps. The default is slow because the units and response are still unconfirmed. */
export const DRIVE_SPEEDS = { slow: 0.4, normal: 0.8 } as const;
export type DriveSpeed = keyof typeof DRIVE_SPEEDS;

export type DriveVector = { vx: number; vy: number; wz: number };
export type DriveLimits = DriveVector;
export type DriveFrame = DriveVector & { seq: number };
export type DriveEnd = 'released' | 'cap' | 'refused' | 'error';
export type DriveOutcome = { end: DriveEnd; frames: number; detail?: string };

export type DriveDeps = {
  start: () => Promise<{ ok: true } | { ok: false; reason: string }>;
  /** Resolves false (or throws) when the frame did not reach the controller. */
  frame: (frame: DriveFrame) => Promise<boolean>;
  stop: () => Promise<unknown>;
  /** True only while the button is still held AND the page is visible. */
  held: () => boolean;
  vector: () => DriveVector;
  now?: () => number;
  wait?: (ms: number) => Promise<void>;
  frameMs?: number;
  maxMs?: number;
};

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

export function scaled(limits: DriveLimits, direction: Partial<Record<keyof DriveVector, -1 | 0 | 1>>, speed: DriveSpeed): DriveVector {
  const k = DRIVE_SPEEDS[speed];
  return { vx: (direction.vx ?? 0) * limits.vx * k, vy: (direction.vy ?? 0) * limits.vy * k, wz: (direction.wz ?? 0) * limits.wz * k };
}

export async function runDrive(deps: DriveDeps): Promise<DriveOutcome> {
  const { start, frame, stop, held, vector } = deps;
  const now = deps.now ?? Date.now;
  const wait = deps.wait ?? sleep;
  const frameMs = deps.frameMs ?? DRIVE_FRAME_MS;
  const maxMs = deps.maxMs ?? DRIVE_HOLD_MAX_MS;
  if (!held()) return { end: 'released', frames: 0 };
  let started = false;
  let frames = 0;
  let end: DriveEnd = 'released';
  let detail: string | undefined;
  try {
    started = true; // from here on a stop is always requested, even if start's own answer never arrives
    const opened = await start();
    if (!opened.ok) { started = false; return { end: 'refused', frames: 0, detail: opened.reason }; }
    const startedAt = now();
    while (held()) {
      if (now() - startedAt >= maxMs) { end = 'cap'; break; }
      frames += 1;
      const sent = await frame({ seq: frames, ...vector() });
      if (!sent) { end = 'error'; detail = 'A frame did not reach the controller.'; break; }
      // Wait out the frame interval in short slices, so a release is noticed within ~20 ms rather than a whole interval.
      const until = now() + frameMs;
      while (held() && now() < until) await wait(Math.min(20, Math.max(1, until - now())));
    }
  } catch (error) {
    end = 'error';
    detail = error instanceof Error ? error.message : 'The drive failed.';
  } finally {
    if (started) { try { await stop(); } catch { /* the dog's watchdog still stops it; the controller reports the rest */ } }
  }
  return { end, frames, ...(detail ? { detail } : {}) };
}
