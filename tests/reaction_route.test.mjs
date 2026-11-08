import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const compiled = ts.transpileModule(readFileSync(new URL('../src/reactionRoute.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function api() {
  const values = new Map(), exports = {};
  vm.runInNewContext(compiled, { exports, URL, localStorage: {
    getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
  } });
  return exports;
}
test('cloud is the default and local requires an explicit choice', () => {
  const route = api();
  assert.equal(route.selectedReactionRoute(), 'cloud');
  route.saveReactionRoute('local');
  assert.equal(route.selectedReactionRoute(), 'local');
});
test('route must match the backend which owns the coach record', () => {
  const { reactionRouteMatches: matches } = api();
  assert.equal(matches('cloud', 'https://chess-api.urbot.ai'), true);
  assert.equal(matches('local', 'https://chess-api.urbot.ai'), false);
  for (const address of ['http://localhost:8765', 'http://192.168.1.5:8765', 'https://mac.local']) {
    assert.equal(matches('cloud', address), false);
    assert.equal(matches('local', address), true);
  }
  assert.equal(matches('cloud', 'http://example.com'), false);
  assert.equal(matches('local', 'invalid'), false);
});
