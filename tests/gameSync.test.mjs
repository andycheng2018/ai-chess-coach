import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/gameSync.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports });
const shouldApplyBackupSnapshot = input => exports.shouldApplyBackupSnapshot(input);
const moveLineChanged = (previous, next) => exports.moveLineChanged(previous, next);

function input(updates = {}) {
  return {
    primaryConnected: false,
    gameId: 'game-1',
    cachedGameId: 'game-1',
    updatedAt: 90_000,
    now: 100_000,
    currentMoves: ['e2e4', 'e7e5'],
    cachedMoves: ['e2e4', 'e7e5', 'g1f3'],
    ...updates,
  };
}

test('move-line changes detect rewind and divergence but allow equality and extensions', () => {
  assert.equal(moveLineChanged(['e2e4', 'e7e5'], ['e2e4', 'e7e5']), false);
  assert.equal(moveLineChanged(['e2e4'], ['e2e4', 'e7e5']), false);
  assert.equal(moveLineChanged(['e2e4', 'e7e5'], ['e2e4']), true);
  assert.equal(moveLineChanged(['e2e4', 'e7e5'], ['e2e4', 'c7c5']), true);
  assert.equal(moveLineChanged(['e2e4', 'e7e5'], ['d2d4', 'd7d5', 'c2c4']), true);
  assert.equal(moveLineChanged([], ['e2e4']), false);
});

test('applies a fresh backup snapshot that strictly extends the full current prefix', () => {
  assert.equal(shouldApplyBackupSnapshot(input()), true);
});

test('does not apply backup while the primary stream is connected', () => {
  assert.equal(shouldApplyBackupSnapshot(input({ primaryConnected: true })), false);
});

test('rejects missing or mismatched game identity', () => {
  assert.equal(shouldApplyBackupSnapshot(input({ gameId: '' })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ cachedGameId: '' })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ cachedGameId: 'game-2' })), false);
});

test('accepts cache ages at both boundaries and rejects stale or future snapshots', () => {
  assert.equal(shouldApplyBackupSnapshot(input({ updatedAt: 100_000 })), true);
  assert.equal(shouldApplyBackupSnapshot(input({ updatedAt: 70_000 })), true);
  assert.equal(shouldApplyBackupSnapshot(input({ updatedAt: 69_999 })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ updatedAt: 100_001 })), false);
});

test('rejects rewind, same-length, and divergent cached lines', () => {
  assert.equal(shouldApplyBackupSnapshot(input({ cachedMoves: ['e2e4'] })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ cachedMoves: ['e2e4', 'e7e5'] })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ cachedMoves: ['e2e4', 'c7c5', 'g1f3'] })), false);
  assert.equal(shouldApplyBackupSnapshot(input({ cachedMoves: ['d2d4', 'd7d5', 'c2c4'] })), false);
});

test('rejects a stale cache that extends the prefix immediately after a rewind', () => {
  const previousLine = ['e2e4', 'e7e5', 'g1f3', 'b8c6'];
  const rewoundLine = ['e2e4', 'e7e5'];
  assert.equal(moveLineChanged(previousLine, rewoundLine), true);
  assert.equal(shouldApplyBackupSnapshot(input({
    currentMoves: rewoundLine,
    cachedMoves: [...rewoundLine, 'g1f3', 'b8c6'],
    branchChanged: true,
  })), false);
});
