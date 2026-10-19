import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const clientSource = compile('../src/lunaChat.ts');
const componentSource = compile('../src/components/LunaChat.tsx');
const fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const turn = (sessionId = 'analysis:a', updates = {}) => ({ sessionId, requestId: 'r1', recordId: 'audit1', fen,
  message: 'Why develop?', reply: 'Compare your pieces.', savedAt: 1, language: 'en', ...updates });

function environment(fetch = async () => { throw new Error('offline'); }, quota = false) {
  const storage = new Map();
  const window = { localStorage: {
    getItem: key => storage.get(key), setItem: (key, value) => { if (quota) throw new Error('Full'); storage.set(key, value); },
  } };
  const client = {};
  vm.runInNewContext(clientSource, { exports: client, require: path => path === './coach' ? { CONTROL_URL: 'http://coach.test' } : require(path),
    window, fetch, AbortSignal });
  const component = {};
  vm.runInNewContext(componentSource, { exports: component, require: path => path === '../lunaChat' ? client : require(path), window });
  return { client, component, storage };
}

test('chat caches keep different games and saves separate and retain uncertain request IDs', () => {
  const { client } = environment();
  client.writeChatCache('analysis:a', { turns: [turn()], draft: 'Follow up', attempt: { sessionId: 'analysis:a', requestId: 'retry-original' } });
  client.writeChatCache('game:g', { turns: [turn('game:g', { reply: 'Game advice' })], draft: '' });
  assert.equal(client.readChatCache('analysis:a').turns[0].reply, 'Compare your pieces.');
  assert.equal(client.readChatCache('analysis:a').attempt.requestId, 'retry-original');
  assert.equal(client.readChatCache('game:g').turns[0].reply, 'Game advice');
  assert.equal(client.readChatCache('analysis:b').turns.length, 0);
});

test('a confirmed retry and a delayed history load do not duplicate replies', () => {
  const { client } = environment();
  const saved = client.mergeChatTurns([turn(), turn('analysis:a', { requestId: 'r2', savedAt: 2 })], [turn()]);
  assert.equal(saved.length, 2);
  assert.equal(saved[1].requestId, 'r2');
});

test('unavailable browser storage is reported instead of claiming an offline copy', () => {
  const { client } = environment(undefined, true);
  assert.equal(client.writeChatCache('analysis:a', { turns: [turn()], draft: '' }), false);
  assert.equal(client.readChatCache('analysis:a').turns.length, 0);
});

test('API sends the exact snapshot, language, and retry ID and surfaces server setup errors', async () => {
  const calls = [];
  const { client } = environment(async (url, options) => {
    calls.push({ url, options });
    return { ok: false, status: 503, json: async () => ({ message: 'Luna needs OPENAI_API_KEY' }) };
  });
  const request = { sessionId: 'analysis:a', requestId: 'same-retry-id', message: 'Why?', fen,
    rootFen: fen, moves: [], detail: 'deep', language: 'zh-CN' };
  await assert.rejects(client.sendChat(request), /OPENAI_API_KEY/);
  assert.deepEqual(JSON.parse(calls[0].options.body), request);
  assert.equal(calls[0].url, 'http://coach.test/api/coach/chat');
});

test('rendered conversation escapes user and model text and labels earlier positions', () => {
  const { client, component } = environment();
  client.writeChatCache('analysis:a', { turns: [turn('analysis:a', { message: '<script>alert(1)</script>', reply: '<img src=x onerror=alert(2)>' })], draft: '' });
  const html = renderToStaticMarkup(createElement(component.LunaChat, { sessionId: 'analysis:a', position: { fen: fen.replace('0 1', '0 2'), rootFen: fen, moves: [] } }));
  assert.match(html, /Earlier position/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /Message Luna/);
  assert.match(html, /role="log"/);
});

test('Chinese chat has a labeled composer and localized position context', () => {
  const { component } = environment();
  const html = renderToStaticMarkup(createElement(component.LunaChat, { sessionId: 'analysis:a', position: { fen, rootFen: fen, moves: [] }, language: 'zh-CN' }));
  assert.match(html, /给 Luna 的消息/);
  assert.match(html, /白方/);
  assert.match(html, /与 Luna 聊天/);
});
