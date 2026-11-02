/**
 * The saved show library. Persisting a show never runs it: a reload restores
 * shows and nothing else. Run history is kept separately by the transports.
 */
import canned from './cannedShows.json';
import { makeScore, newId, parseScore, type Cue, type Score } from './score';

export type KeyValueStore = { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem?(key: string): void };

const KEY = 'vbot-studio.library.v1';
const QUARANTINE = 'vbot-studio.library.quarantine';

type Persisted = { version: 1; shows: unknown[]; favorites: string[]; selectedId: string | null };

export type LibraryState = {
  canned: readonly Score[]; shows: readonly Score[]; favorites: ReadonlySet<string>;
  selectedId: string | null; warnings: readonly string[];
};

export function cannedShows(): Score[] {
  return (canned as unknown[]).flatMap(raw => {
    const parsed = parseScore(raw);
    if (!parsed.ok) throw new Error(`Bundled show is invalid: ${parsed.errors.join(' ')}`);
    return [parsed.score];
  });
}

export function loadLibrary(store: KeyValueStore): LibraryState {
  const empty: LibraryState = { canned: cannedShows(), shows: [], favorites: new Set(), selectedId: null, warnings: [] };
  let text: string | null;
  try { text = store.getItem(KEY); } catch { return { ...empty, warnings: ['Browser storage is unavailable, so shows will not be saved.'] }; }
  if (!text) return empty;
  let data: Partial<Persisted>;
  try {
    data = JSON.parse(text);
    if (typeof data !== 'object' || data === null || data.version !== 1 || !Array.isArray(data.shows)) throw new Error('shape');
  } catch {
    // Keep the original bytes: unreadable is not the same as disposable.
    try { store.setItem(QUARANTINE, text); } catch { /* best effort */ }
    return { ...empty, warnings: ['Saved shows could not be read. The original data was kept aside and nothing was overwritten.'] };
  }
  const warnings: string[] = [];
  const shows: Score[] = [];
  const rejected: unknown[] = [];
  for (const raw of data.shows) {
    const parsed = parseScore(raw);
    if (parsed.ok && parsed.score.origin === 'custom') shows.push(parsed.score);
    else rejected.push(raw);
  }
  if (rejected.length) {
    warnings.push(`${rejected.length} saved show(s) failed validation and were set aside.`);
    try { store.setItem(QUARANTINE, JSON.stringify(rejected)); } catch { /* best effort */ }
  }
  const favorites = Array.isArray(data.favorites) ? data.favorites.filter((id): id is string => typeof id === 'string') : [];
  return { ...empty, shows, favorites: new Set(favorites), selectedId: typeof data.selectedId === 'string' ? data.selectedId : null, warnings };
}

export function saveLibrary(store: KeyValueStore, state: LibraryState): boolean {
  const data: Persisted = { version: 1, shows: [...state.shows], favorites: [...state.favorites], selectedId: state.selectedId };
  try { store.setItem(KEY, JSON.stringify(data)); return true; } catch { return false; }
}

export function findShow(state: LibraryState, id: string | null): Score | null {
  return [...state.canned, ...state.shows].find(show => show.id === id) ?? null;
}

/** Canned shows are read-only, so an edit only ever replaces a custom show. */
export function upsertShow(state: LibraryState, show: Score): LibraryState {
  const exists = state.shows.some(item => item.id === show.id);
  return { ...state, shows: exists ? state.shows.map(item => item.id === show.id ? show : item) : [...state.shows, show] };
}

export function reviseShow(show: Score, change: Partial<Pick<Score, 'title' | 'notes' | 'repeat' | 'cues'>>, now: number): Score {
  return { ...show, ...change, revision: show.revision + 1, updatedAt: now };
}

/** Save-as: gives the show and every cue fresh identities and keeps the original. */
export function copyShow(show: Score, title: string, now: number): Score {
  const cues = show.cues.map((cue): Cue => ({ ...cue, id: newId() }));
  return { ...makeScore(title, now, cues), notes: show.notes, repeat: show.repeat };
}

export type ImportResult = { ok: true; show: Score } | { ok: false; errors: string[] };

/**
 * Imports validate fully and arrive as a new, unrun custom show. They can't
 * overwrite a show, claim to be canned, or start themselves.
 */
export function importShow(text: string, now: number): ImportResult {
  if (text.length > 256 * 1024) return { ok: false, errors: ['That file is too large to be a show.'] };
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { return { ok: false, errors: ['That file is not valid JSON.'] }; }
  const parsed = parseScore(raw);
  if (!parsed.ok) return parsed;
  return { ok: true, show: { ...parsed.score, id: newId(), origin: 'custom', revision: 1, createdAt: now, updatedAt: now } };
}

export function exportShow(show: Score): string {
  return JSON.stringify(show, null, 2);
}
