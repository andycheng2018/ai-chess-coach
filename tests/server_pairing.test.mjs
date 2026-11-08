import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const compiled = ts.transpileModule(readFileSync(new URL('../src/nativeBackend.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function api() {
  const values = new Map(), exports = {}, window = { location: { href: 'http://localhost:5173/' }, fetch: async () => ({}) };
  vm.runInNewContext(compiled, { exports, URL, Headers, Request, window,
    localStorage: { getItem: k => values.get(k) || null, setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) } });
  return { ...exports, window };
}
// Same shape as Python's secrets.token_urlsafe(32), which the hosted server uses.
const hosted = { url: 'https://chess-api.urbot.ai', token: 'Ab-_' + 'x'.repeat(39) };

test('a hosted HTTPS server and its URL-safe key are accepted as-is', () => {
  const { validateConnection } = api();
  assert.deepEqual({ ...validateConnection({ ...hosted, url: hosted.url + '/' }) }, hosted);
  assert.throws(() => validateConnection({ ...hosted, url: 'http://chess-api.urbot.ai' }));
});

test('a saved hosted server becomes the backend URL on a computer', async () => {
  const { saveConnection, installTabletTransport, TABLET_HEADER, window } = api();
  const calls = [];
  window.fetch = async (input, init) => { calls.push({ input, init }); return {}; };
  saveConnection(hosted);
  installTabletTransport();
  assert.equal(window.__CHESS_BACKEND_URL__, hosted.url);
  await window.fetch(hosted.url + '/api/vbot/status');
  assert.equal(calls[0].init.headers.get(TABLET_HEADER), hosted.token);
});
