import { CONTROL_URL, type CoachResult } from './coach';

// This is an offline cache of the server journal, shared by review and reports.
export const HISTORY_CACHE_KEY = 'ai-chess-coach.history.v1';
const LEGACY_NOTES_KEY = 'ai-chess-coach.learning-log.v2';
const LEGACY_EVALUATIONS_KEY = 'ai-chess-coach.game-evaluations.v1';

type HistorySession = {
  gameId: string;
  username?: string;
  updatedAt: number;
  records: CoachResult[];
  synced?: boolean;
};

function readArray(key: string): unknown[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function validRecord(value: unknown): value is CoachResult {
  if (!value || typeof value !== 'object') return false;
  const record = value as Partial<CoachResult>;
  return Number.isInteger(record.ply) && typeof record.fenBefore === 'string'
    && typeof record.playedMoveUci === 'string';
}

export function mergeHistoryRecords(current: CoachResult[], incoming: CoachResult[]): CoachResult[] {
  const records = new Map(current.map(record => [record.ply, record]));
  for (const record of incoming) {
    const old = records.get(record.ply);
    const sameMove = old && old.fenBefore === record.fenBefore && old.playedMoveUci === record.playedMoveUci;
    if (sameMove && old.explanationPending === true && record.explanationPending === false) {
      records.set(record.ply, { ...old, ...record });
      continue;
    }
    if (old && (old.savedAt || 0) > (record.savedAt || 0)) continue;
    if (old && old.fenBefore === record.fenBefore && old.playedMoveUci === record.playedMoveUci
      && old.explanationPending === false && record.explanationPending === true) continue;
    records.set(record.ply, sameMove ? { ...old, ...record } : record);
  }
  return [...records.values()].sort((a, b) => a.ply - b.ply);
}

export function readHistorySessions(): HistorySession[] {
  const sessions = new Map<string, HistorySession>();
  for (const value of readArray(HISTORY_CACHE_KEY)) {
    const session = value as Partial<HistorySession> | null;
    if (session && typeof session.gameId === 'string' && Array.isArray(session.records)) {
      sessions.set(session.gameId, { ...session, gameId: session.gameId,
        updatedAt: session.updatedAt || 0, records: session.records.filter(validRecord) });
    }
  }
  let migrated = false;
  // Evaluations first; saved Learning notes contain the final wording for a ply.
  for (const key of [LEGACY_EVALUATIONS_KEY, LEGACY_NOTES_KEY]) {
    for (const value of readArray(key)) {
      const session = value as Partial<HistorySession> & { notes?: unknown[]; evaluations?: unknown[] };
      if (!session || typeof session.gameId !== 'string') continue;
      const values = key === LEGACY_NOTES_KEY ? session.notes : session.evaluations;
      if (!Array.isArray(values)) continue;
      const old = sessions.get(session.gameId);
      const records = values.filter(validRecord).map(record => ({
        ...record, gameId: session.gameId,
        recordId: record.recordId || record.analysisId
          || `legacy:${session.gameId}:${record.fenBefore}:${record.playedMoveUci}`,
        savedAt: Math.max(record.savedAt || 0, session.updatedAt || 0),
        wordingSource: record.wordingSource || 'legacy' as const,
      }));
      sessions.set(session.gameId, { gameId: session.gameId, username: session.username,
        updatedAt: Math.max(old?.updatedAt || 0, session.updatedAt || 0),
        records: mergeHistoryRecords(old?.records || [], records) });
      migrated = true;
    }
  }
  const result = [...sessions.values()].sort((a, b) => b.updatedAt - a.updatedAt);
  if (migrated) {
    try {
      // Remove the two older copies only after their merged cache is written.
      window.localStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify(result));
      window.localStorage.removeItem(LEGACY_NOTES_KEY);
      window.localStorage.removeItem(LEGACY_EVALUATIONS_KEY);
    } catch { /* Keep legacy records available if the cache cannot be written. */ }
  }
  return result;
}

export function readHistoryRecords(gameId: string): CoachResult[] {
  return readHistorySessions().find(session => session.gameId === gameId)?.records || [];
}

export function cacheHistoryRecords(gameId: string, username: string | undefined, records: CoachResult[], synced = false): boolean {
  try {
    const existing = readHistorySessions().filter(session => session.gameId !== gameId);
    const sessions = [{ gameId, username, updatedAt: Date.now(), records, synced }, ...existing];
    // Keep every pending upload, including migrated games, until acknowledged.
    let retained = 0;
    window.localStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify(sessions.filter(session => !session.synced || retained++ < 8)));
    return true;
  } catch { return false; }
}

const syncQueues = new Map<string, Promise<CoachResult[]>>();

export function syncHistory(gameId: string, records?: CoachResult[]): Promise<CoachResult[]> {
  const previous = syncQueues.get(gameId) || Promise.resolve([]);
  const task = previous.catch(() => []).then(async () => {
    const cached = readHistoryRecords(gameId);
    const upload = records ? mergeHistoryRecords(cached, records) : cached;
    // Large games exceed the backend's request limit; send bounded batches.
    let batch: CoachResult[] = [];
    const post = async () => {
      if (!batch.length) return;
      const response = await fetch(`${CONTROL_URL}/api/coach/history`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gameId, records: batch }),
      });
      if (!response.ok) throw new Error('Could not save coach history');
      batch = [];
    };
    for (const record of upload) {
      const bytes = new TextEncoder().encode(JSON.stringify({ gameId, records: [...batch, record] })).length;
      if (bytes > 48 * 1024) await post();
      batch.push(record);
    }
    await post();
    const response = await fetch(`${CONTROL_URL}/api/coach/history?gameId=${encodeURIComponent(gameId)}`);
    if (!response.ok) throw new Error('Could not load coach history');
    const data = await response.json() as { records?: unknown[] };
    const saved = (data.records || []).filter(validRecord);
    const merged = mergeHistoryRecords(readHistoryRecords(gameId), saved);
    const session = readHistorySessions().find(item => item.gameId === gameId);
    cacheHistoryRecords(gameId, session?.username, merged, JSON.stringify(saved) === JSON.stringify(merged));
    return merged;
  });
  syncQueues.set(gameId, task);
  void task.finally(() => {
    if (syncQueues.get(gameId) === task) syncQueues.delete(gameId);
  }).catch(() => {});
  return task;
}

export async function syncCachedHistory(): Promise<void> {
  for (const session of readHistorySessions()) await syncHistory(session.gameId, session.records);
}
