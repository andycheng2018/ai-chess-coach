import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/coachHistory.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function environment(initial = {}, fetch = async () => { throw new Error('offline'); }, quotaFailure = false) {
  const storage = new Map(Object.entries(initial));
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, require: path => path === './coach' ? { CONTROL_URL: 'http://coach.test' } : require(path),
    window: { localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => { if (quotaFailure) throw new Error('quota'); storage.set(key, value); },
      removeItem: key => storage.delete(key),
    } }, fetch, TextEncoder, console,
  });
  return { history: exports, storage };
}

function record(updates = {}) {
  return { gameId: 'a', recordId: 'analysis-1', ply: 1, fenBefore: 'before', fenAfter: 'after',
    playedMoveUci: 'e2e4', shouldCoach: true, savedAt: 100,
    explanationPending: false, feedback: 'Accepted lesson', ...updates };
}

test('legacy notes merge with evaluations and migrate without losing final wording', () => {
  const notesKey = 'ai-chess-coach.learning-log.v2';
  const evaluationsKey = 'ai-chess-coach.game-evaluations.v1';
  const { history, storage } = environment({
    [notesKey]: JSON.stringify([{ gameId: 'a', updatedAt: 100, notes: [record({ feedback: 'Saved fallback', wordingSource: 'fallback' })] }]),
    [evaluationsKey]: JSON.stringify([{ gameId: 'a', updatedAt: 200, evaluations: [
      record({ explanationPending: true, feedback: 'Checking…' }), record({ ply: 2, shouldCoach: false }),
    ] }]),
  });
  const saved = history.readHistoryRecords('a');
  assert.equal(saved.length, 2);
  assert.equal(saved[0].feedback, 'Saved fallback');
  assert.equal(saved[1].shouldCoach, false);
  assert.ok(storage.has(history.HISTORY_CACHE_KEY));
  assert.equal(storage.has(notesKey), false);
  assert.equal(storage.has(evaluationsKey), false);
});

test('failed migration retains original browser records', () => {
  const key = 'ai-chess-coach.learning-log.v2';
  const { history, storage } = environment({ [key]: JSON.stringify([{ gameId: 'a', notes: [record()] }]) }, undefined, true);
  assert.equal(history.readHistoryRecords('a')[0].feedback, 'Accepted lesson');
  assert.ok(storage.has(key));
});

test('pending uploads cannot overwrite final wording; takebacks replace the same ply', () => {
  const { history } = environment();
  const saved = history.mergeHistoryRecords([record()], [record({ savedAt: 200, explanationPending: true, feedback: 'Checking…' })]);
  assert.equal(saved[0].feedback, 'Accepted lesson');
  const replacement = history.mergeHistoryRecords(saved, [record({ savedAt: 300, recordId: 'analysis-2', playedMoveUci: 'd2d4' })]);
  assert.equal(replacement.length, 1);
  assert.equal(replacement[0].recordId, 'analysis-2');
});

test('offline sessions remain cached and are uploaded on reconnect', async () => {
  let online = false;
  const server = new Map();
  const fetch = async (url, options) => {
    if (!online) throw new Error('offline');
    if (options?.method === 'POST') {
      const { gameId, records } = JSON.parse(options.body);
      server.set(gameId, records);
      return { ok: true };
    }
    const gameId = new URL(url).searchParams.get('gameId');
    return { ok: true, json: async () => ({ records: server.get(gameId) || [] }) };
  };
  const { history, storage } = environment({}, fetch);
  history.cacheHistoryRecords('a', 'player', [record()]);
  await assert.rejects(history.syncHistory('a'), /offline/);
  assert.equal(history.readHistoryRecords('a')[0].feedback, 'Accepted lesson');
  online = true;
  await history.syncHistory('a');
  assert.equal(server.get('a')[0].feedback, 'Accepted lesson');
  assert.ok(storage.has(history.HISTORY_CACHE_KEY));
});

test('large games are batched below the request limit and pending migrations survive cache pruning', async () => {
  const server = new Map();
  const lengths = [];
  const fetch = async (url, options) => {
    if (options?.method === 'POST') {
      lengths.push(Buffer.byteLength(options.body));
      const { gameId, records } = JSON.parse(options.body);
      const old = new Map((server.get(gameId) || []).map(record => [record.ply, record]));
      records.forEach(record => old.set(record.ply, record));
      server.set(gameId, [...old.values()]);
      return { ok: true };
    }
    return { ok: true, json: async () => ({ records: server.get(new URL(url).searchParams.get('gameId')) || [] }) };
  };
  const { history } = environment({}, fetch);
  for (let index = 0; index < 16; index++) history.cacheHistoryRecords(`game-${index}`, 'player', [record({ gameId: `game-${index}` })]);
  history.cacheHistoryRecords('large', 'player', Array.from({ length: 30 }, (_, index) => record({ ply: index + 1, feedback: 'x'.repeat(6000) })));
  assert.equal(history.readHistorySessions().length, 17);
  await history.syncCachedHistory();
  assert.equal(server.size, 17);
  assert.equal(server.get('large').length, 30);
  assert.ok(lengths.every(length => length < 64 * 1024));
  assert.ok(history.readHistorySessions().length <= 8);
});

test('an older sync response preserves a newer local completion', async () => {
  let release;
  let captured;
  const waiting = new Promise(resolve => { release = resolve; });
  const { history } = environment({}, async (_url, options) => {
    if (options?.method === 'POST') { captured = JSON.parse(options.body).records; return { ok: true }; }
    await waiting;
    return { ok: true, json: async () => ({ records: captured }) };
  });
  history.cacheHistoryRecords('a', undefined, [record({ explanationPending: true })]);
  const syncing = history.syncHistory('a');
  // Let the pending record upload, then save the final local result.
  await new Promise(resolve => setImmediate(resolve));
  history.cacheHistoryRecords('a', undefined, [record({ feedback: 'New final lesson', savedAt: 200 })]);
  release();
  const result = await syncing;
  assert.equal(result[0].feedback, 'New final lesson');
  assert.equal(history.readHistorySessions()[0].synced, false);
});
