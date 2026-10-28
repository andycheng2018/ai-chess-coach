import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/pendingMove.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports });
const reconcilePendingMove = (...args) =>
  JSON.parse(JSON.stringify(exports.reconcilePendingMove(...args)));
const resolveMoveFailure = (...args) => exports.resolveMoveFailure(...args);

function pending(updates = {}) {
  const movesBefore = ['e2e4', 'e7e5'];
  return { uci: 'g1f3', basePly: movesBefore.length, movesBefore, ...updates };
}

test('unchanged authoritative snapshots keep the move pending', () => {
  assert.deepEqual(reconcilePendingMove(pending(), ['e2e4', 'e7e5']), { outcome: 'waiting' });
  assert.deepEqual(reconcilePendingMove(pending(), ['e2e4', 'e7e5']), { outcome: 'waiting' });
});

test('the exact submitted move confirms even when the opponent has already replied', () => {
  assert.deepEqual(
    reconcilePendingMove(pending(), ['e2e4', 'e7e5', 'g1f3', 'b8c6']),
    { outcome: 'confirmed', observedUci: 'g1f3' },
  );
});

test('an authoritative rewind of the pre-submit prefix requests rollback', () => {
  assert.deepEqual(
    reconcilePendingMove(pending(), ['e2e4']),
    { outcome: 'rollback', reason: 'rewind' },
  );
});

test('a same-length or longer alternate branch requests rollback', () => {
  assert.deepEqual(
    reconcilePendingMove(pending(), ['d2d4', 'd7d5']),
    { outcome: 'rollback', reason: 'divergence' },
  );
  assert.deepEqual(
    reconcilePendingMove(pending(), ['e2e4', 'c7c5', 'g1f3']),
    { outcome: 'rollback', reason: 'divergence' },
  );
});

test('a different move at the pending ply requests rollback', () => {
  assert.deepEqual(
    reconcilePendingMove(pending(), ['e2e4', 'e7e5', 'b1c3']),
    { outcome: 'rollback', reason: 'divergence' },
  );
});

test('move comparison is case- and whitespace-insensitive', () => {
  assert.deepEqual(
    reconcilePendingMove(pending({ uci: 'G1F3' }), [' e2e4 ', 'e7e5', 'G1F3']),
    { outcome: 'confirmed', observedUci: 'g1f3' },
  );
});

test('inconsistent base ply and saved prefix request rollback', () => {
  assert.deepEqual(
    reconcilePendingMove(pending({ basePly: 1 }), ['e2e4', 'e7e5']),
    { outcome: 'rollback', reason: 'invalid-base-ply' },
  );
});

test('move failures ignore a request already resolved by the stream', () => {
  const attempt = pending();
  assert.equal(resolveMoveFailure(null, attempt, 400), 'ignore');
});

test('late errors from an older attempt cannot affect a newer attempt with the same UCI', () => {
  const oldAttempt = pending();
  const newAttempt = pending();
  assert.notEqual(oldAttempt, newAttempt);
  assert.equal(oldAttempt.uci, newAttempt.uci);
  assert.equal(resolveMoveFailure(newAttempt, oldAttempt, 409), 'ignore');
});

test('definitive move response statuses request rollback', () => {
  for (const status of [400, 401, 403, 404, 409, 410, 422, 429]) {
    const attempt = pending();
    assert.equal(resolveMoveFailure(attempt, attempt, status), 'rollback', `status ${status}`);
  }
});

test('transport and uncertain server failures keep waiting for stream confirmation', () => {
  for (const status of [undefined, 408, 500, 502, 503]) {
    const attempt = pending();
    assert.equal(resolveMoveFailure(attempt, attempt, status), 'wait', `status ${status}`);
  }
});
