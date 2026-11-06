/**
 * Versioned performance scores. Custom v1 composes approved primitives only:
 * no scripts, SDK payloads, velocity streams or trajectories. Parsing rejects
 * unknown fields, so an import can't smuggle a payload through. Nothing here
 * contacts a robot.
 */
import { CATALOG, FACE_DEFAULT_MS, isRestrictedFace, MOTION_PRESET_NAMES, type CatalogEntry, type CapabilityKind } from './catalog';

export const SCORE_SCHEMA_VERSION = 1;
export const LIMITS = {
  maxCues: 64, maxExpandedCues: 128, maxRepeat: 5, maxTotalMs: 15 * 60 * 1000,
  faceMinMs: 500, faceMaxMs: 30000, waitMinMs: 100, waitMaxMs: 60000,
  titleLength: 80, notesLength: 500, captionLength: 140, idLength: 64,
} as const;

export type FaceCue = { id: string; type: 'face'; assetId: number; durationMs: number; caption?: string };
export type MotionCue = { id: string; type: 'head' | 'body'; preset: string; caption?: string };
export type WaitCue = { id: string; type: 'wait'; durationMs: number; caption?: string };
export type Cue = FaceCue | MotionCue | WaitCue;

export type Score = {
  schemaVersion: 1; id: string; title: string; notes: string; origin: 'custom' | 'canned';
  revision: number; repeat: number; createdAt: number; updatedAt: number; cues: Cue[];
};

export type ParseResult = { ok: true; score: Score } | { ok: false; errors: string[] };

const SCORE_KEYS = new Set(['schemaVersion', 'id', 'title', 'notes', 'origin', 'revision', 'repeat', 'createdAt', 'updatedAt', 'cues']);
const CUE_KEYS: Record<Cue['type'], ReadonlySet<string>> = {
  face: new Set(['id', 'type', 'assetId', 'durationMs', 'caption']),
  head: new Set(['id', 'type', 'preset', 'caption']),
  body: new Set(['id', 'type', 'preset', 'caption']),
  wait: new Set(['id', 'type', 'durationMs', 'caption']),
};
const ID = /^[A-Za-z0-9_-]+$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isInt = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value);
const inRange = (value: unknown, min: number, max: number): value is number => isInt(value) && value >= min && value <= max;
const validId = (value: unknown): value is string => typeof value === 'string' && value.length <= LIMITS.idLength && ID.test(value);

function parseCue(raw: unknown, index: number, errors: string[]): Cue | null {
  const where = `Cue ${index + 1}`;
  if (!isRecord(raw)) { errors.push(`${where} is not an object.`); return null; }
  const type = raw.type;
  if (type !== 'face' && type !== 'head' && type !== 'body' && type !== 'wait') {
    errors.push(`${where}: "${String(type)}" isn't a supported cue type in v1.`);
    return null;
  }
  const unknown = Object.keys(raw).filter(key => !CUE_KEYS[type].has(key));
  if (unknown.length) { errors.push(`${where} has unsupported fields: ${unknown.join(', ')}.`); return null; }
  if (!validId(raw.id)) { errors.push(`${where} needs a stable ID.`); return null; }
  let caption: string | undefined;
  if (raw.caption !== undefined) {
    if (typeof raw.caption !== 'string' || raw.caption.length > LIMITS.captionLength) {
      errors.push(`${where} has an invalid caption.`); return null;
    }
    caption = raw.caption;
  }
  const extra = caption === undefined ? {} : { caption };
  if (type === 'face') {
    if (!inRange(raw.assetId, 0, 255)) { errors.push(`${where} needs a face asset ID from 0 to 255.`); return null; }
    if (isRestrictedFace(raw.assetId)) { errors.push(`${where}: face ${raw.assetId} is a charging or diagnostic indicator and can't be used in a show.`); return null; }
    if (!inRange(raw.durationMs, LIMITS.faceMinMs, LIMITS.faceMaxMs)) {
      errors.push(`${where}: face duration must be ${LIMITS.faceMinMs}–${LIMITS.faceMaxMs} ms.`); return null;
    }
    return { id: raw.id, type, assetId: raw.assetId, durationMs: raw.durationMs, ...extra };
  }
  if (type === 'wait') {
    if (!inRange(raw.durationMs, LIMITS.waitMinMs, LIMITS.waitMaxMs)) {
      errors.push(`${where}: wait must be ${LIMITS.waitMinMs}–${LIMITS.waitMaxMs} ms.`); return null;
    }
    return { id: raw.id, type, durationMs: raw.durationMs, ...extra };
  }
  if (typeof raw.preset !== 'string' || !MOTION_PRESET_NAMES.has(raw.preset)) {
    errors.push(`${where}: "${String(raw.preset)}" isn't an approved preset.`); return null;
  }
  const expected = raw.preset.startsWith('atom/') ? 'head' : 'body';
  if (type !== expected) { errors.push(`${where}: ${raw.preset} is a ${expected} preset, not ${type}.`); return null; }
  return { id: raw.id, type, preset: raw.preset, ...extra };
}

export function parseScore(raw: unknown): ParseResult {
  const errors: string[] = [];
  if (!isRecord(raw)) return { ok: false, errors: ['A score must be a JSON object.'] };
  const unknown = Object.keys(raw).filter(key => !SCORE_KEYS.has(key));
  if (unknown.length) errors.push(`Unsupported score fields: ${unknown.join(', ')}.`);
  if (raw.schemaVersion !== SCORE_SCHEMA_VERSION) errors.push(`Unsupported score version: ${String(raw.schemaVersion)}.`);
  if (!validId(raw.id)) errors.push('The score needs a stable ID.');
  if (typeof raw.title !== 'string' || !raw.title.trim() || raw.title.length > LIMITS.titleLength) errors.push(`The title must be 1–${LIMITS.titleLength} characters.`);
  if (typeof raw.notes !== 'string' || raw.notes.length > LIMITS.notesLength) errors.push(`Notes must be at most ${LIMITS.notesLength} characters.`);
  if (raw.origin !== 'custom' && raw.origin !== 'canned') errors.push('Unknown score origin.');
  if (!isInt(raw.revision) || raw.revision < 1) errors.push('The revision must be a positive integer.');
  if (!inRange(raw.repeat, 1, LIMITS.maxRepeat)) errors.push(`Repeat must be 1–${LIMITS.maxRepeat}.`);
  if (!isInt(raw.createdAt) || !isInt(raw.updatedAt)) errors.push('Timestamps must be integers.');
  if (!Array.isArray(raw.cues)) return { ok: false, errors: [...errors, 'Cues must be a list.'] };
  if (raw.cues.length > LIMITS.maxCues) return { ok: false, errors: [...errors, `A score can have at most ${LIMITS.maxCues} cues.`] };
  const cues: Cue[] = [];
  raw.cues.forEach((value, index) => { const cue = parseCue(value, index, errors); if (cue) cues.push(cue); });
  if (new Set(cues.map(cue => cue.id)).size !== cues.length) errors.push('Cue IDs must be unique.');
  if (errors.length) return { ok: false, errors };
  const score: Score = {
    schemaVersion: 1, id: raw.id as string, title: raw.title as string, notes: raw.notes as string,
    origin: raw.origin as Score['origin'], revision: raw.revision as number, repeat: raw.repeat as number,
    createdAt: raw.createdAt as number, updatedAt: raw.updatedAt as number, cues,
  };
  const bounds = scoreBoundsError(score);
  return bounds ? { ok: false, errors: [bounds] } : { ok: true, score };
}

/** The whole-performance limits, which depend on the score's repeat count. */
export function scoreBoundsError(score: Score): string | null {
  if (score.cues.length * score.repeat > LIMITS.maxExpandedCues) return `With repeats this show has more than ${LIMITS.maxExpandedCues} cues.`;
  const { totalMs } = buildTimeline(score);
  return totalMs > LIMITS.maxTotalMs ? `The show is longer than the ${LIMITS.maxTotalMs / 60000}-minute limit.` : null;
}

export type TimelineItem = {
  key: string; cue: Cue; entry: CatalogEntry | null; pass: number; startMs: number; durationMs: number; durationKnown: boolean;
};

const BY_ID = new Map(CATALOG.map(entry => [entry.id, entry]));

export function entryForCue(cue: Cue): CatalogEntry | null {
  if (cue.type === 'face') return BY_ID.get(`face:${cue.assetId}`) ?? null;
  if (cue.type === 'wait') return BY_ID.get('wait') ?? null;
  return BY_ID.get(`${cue.type}:${cue.preset}`) ?? null;
}

export function cueTitle(cue: Cue): string {
  if (cue.type === 'face') return entryForCue(cue)?.label ?? `Face ${cue.assetId}`;
  if (cue.type === 'wait') return 'Wait';
  return entryForCue(cue)?.label ?? cue.preset;
}

/** The whole show in playback order, repeats expanded. Pure: this is what Preview renders. */
export function buildTimeline(score: Pick<Score, 'cues' | 'repeat'>): { items: TimelineItem[]; totalMs: number; unknownDurations: number } {
  const items: TimelineItem[] = [];
  let cursor = 0;
  let unknownDurations = 0;
  for (let pass = 1; pass <= score.repeat; pass += 1) {
    for (const cue of score.cues) {
      const entry = entryForCue(cue);
      const measured = cue.type === 'face' || cue.type === 'wait' ? cue.durationMs : entry?.durationMs ?? null;
      if (measured === null) unknownDurations += 1;
      const durationMs = measured ?? 0;
      items.push({ key: `${cue.id}#${pass}`, cue, entry, pass, startMs: cursor, durationMs, durationKnown: measured !== null });
      cursor += durationMs;
    }
  }
  return { items, totalMs: cursor, unknownDurations };
}

export type CapabilityState = { available: boolean; reason: string | null };
export type Capabilities = {
  face: CapabilityState; head: CapabilityState; body: CapabilityState;
  speech: CapabilityState; navigation: CapabilityState;
  /** Asset IDs this dog reports; null means it hasn't been asked. */
  supportedFaceIds: number[] | null;
  /** Presets with a measured rehearsal on this exact dog. */
  rehearsedPresets: string[];
  /**
   * Presets the operator enabled for this one connection after the onsite checks. This is
   * permission to try them, not a rehearsal record, and it lapses with the connection.
   */
  armedPresets?: string[];
};
export type Blocker = { cueId: string; kind: CapabilityKind; reason: string };

/**
 * Each kind has its own rule. Face cues need the display, not a standing dog or
 * a dance rehearsal. Waits need nothing. Motion needs the capability and a
 * rehearsal on this dog.
 */
export function admitScore(score: Pick<Score, 'cues'>, capabilities: Capabilities): { ok: boolean; blockers: Blocker[] } {
  const blockers: Blocker[] = [];
  for (const cue of score.cues) {
    if (cue.type === 'wait') continue;
    const capability = capabilities[cue.type];
    if (!capability.available) {
      blockers.push({ cueId: cue.id, kind: cue.type, reason: capability.reason ?? `${cue.type} isn't available.` });
    } else if (cue.type === 'face') {
      if (capabilities.supportedFaceIds && !capabilities.supportedFaceIds.includes(cue.assetId)) {
        blockers.push({ cueId: cue.id, kind: 'face', reason: `This dog doesn't list face ${cue.assetId}.` });
      }
    } else if (!capabilities.rehearsedPresets.includes(cue.preset) && !(capabilities.armedPresets ?? []).includes(cue.preset)) {
      blockers.push({ cueId: cue.id, kind: cue.type, reason: `${cueTitle(cue)} needs a measured rehearsal on this dog, or motion enabled for this connection.` });
    }
  }
  return { ok: blockers.length === 0, blockers };
}

export function requiredKinds(score: Pick<Score, 'cues'>): CapabilityKind[] {
  return [...new Set(score.cues.map(cue => cue.type))];
}

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

/** Runs own this frozen copy, so editing a saved show can't alter an active run. */
export function snapshotScore(score: Score): Readonly<Score> {
  return deepFreeze(JSON.parse(JSON.stringify(score)) as Score);
}

export function newId(): string {
  return crypto.randomUUID().replaceAll('-', '');
}

export function makeScore(title: string, now: number, cues: Cue[] = []): Score {
  return { schemaVersion: 1, id: newId(), title, notes: '', origin: 'custom', revision: 1, repeat: 1, createdAt: now, updatedAt: now, cues };
}

/** Face tiles only ever make face cues, and body tiles only ever make body cues. */
export function cueFromEntry(entry: CatalogEntry): Cue | null {
  const id = newId();
  if (entry.kind === 'face' && entry.assetId !== undefined) return { id, type: 'face', assetId: entry.assetId, durationMs: entry.durationMs ?? FACE_DEFAULT_MS };
  if (entry.kind === 'wait') return { id, type: 'wait', durationMs: entry.durationMs ?? 1000 };
  if ((entry.kind === 'head' || entry.kind === 'body') && entry.preset) return { id, type: entry.kind, preset: entry.preset };
  return null;
}

export function clampDuration(cue: FaceCue | WaitCue, ms: number): number {
  const [min, max] = cue.type === 'face' ? [LIMITS.faceMinMs, LIMITS.faceMaxMs] : [LIMITS.waitMinMs, LIMITS.waitMaxMs];
  return Number.isFinite(ms) ? Math.min(max, Math.max(min, Math.round(ms))) : min;
}

export function moveCue(cues: readonly Cue[], index: number, delta: number): Cue[] {
  const next = [...cues];
  const target = index + delta;
  if (index < 0 || index >= next.length || target < 0 || target >= next.length) return next;
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function duplicateCue(cues: readonly Cue[], index: number): Cue[] {
  const next = [...cues];
  const source = next[index];
  if (source) next.splice(index + 1, 0, { ...source, id: newId() });
  return next;
}

export function formatDuration(ms: number): string {
  if (ms < 60000) return `${(ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 1)}s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}
