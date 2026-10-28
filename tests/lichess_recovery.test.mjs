import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function compile(path) {
  return ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
}
const clientCode = compile('../src/lichess.ts');
const recovery = {};
vm.runInNewContext(compile('../src/senseRecovery.ts'), { exports: recovery });
function client(response) {
  const exports = {};
  vm.runInNewContext(clientCode, {
    exports, fetch: async () => response, TextDecoder, AbortSignal,
  });
  return exports;
}

test('title-prefixed BOT display name recovers the actual active training game', async () => {
  const api = client({ ok: true, json: async () => ({ nowPlaying: [{
    gameId: 'bWbJuQWD', color: 'white',
    opponent: { id: 'monkeykingzach', username: 'BOT MonkeyKingZach', rating: 3000 },
  }] }) });
  const games = await api.getPlayingGames('test-token');
  assert.equal(recovery.requireSenseTrainingGame('bWbJuQWD', 'MonkeyKingZach', games).gameId, 'bWbJuQWD');
  assert.equal(games[0].color, 'white');
});

test('display name cannot override a different stable account identity', async () => {
  const api = client({ ok: true, json: async () => ({ nowPlaying: [{
    gameId: 'bWbJuQWD', opponent: { id: 'anotheraccount', username: 'MonkeyKingZach' },
  }] }) });
  const games = await api.getPlayingGames('test-token');
  assert.throws(() => recovery.requireSenseTrainingGame('bWbJuQWD', 'MonkeyKingZach', games), /did not confirm/);
});

test('legacy account responses without an ID still recover by exact username', async () => {
  const api = client({ ok: true, json: async () => ({ nowPlaying: [{
    gameId: 'bWbJuQWD', opponent: { username: 'MonkeyKingZach' },
  }] }) });
  const games = await api.getPlayingGames('test-token');
  assert.equal(recovery.requireSenseTrainingGame('bWbJuQWD', 'MonkeyKingZach', games).gameId, 'bWbJuQWD');
});

test('gameStart events also identify a titled opponent by stable ID', async () => {
  const line = JSON.stringify({ type: 'gameStart', game: {
    id: 'bWbJuQWD', color: 'white',
    opponent: { id: 'monkeykingzach', username: 'BOT MonkeyKingZach' },
  } }) + '\n';
  const api = client({ ok: true, body: new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(line)); controller.close();
  } }) });
  const events = [];
  await api.streamEvents('test-token', event => events.push(event), new AbortController().signal);
  assert.equal(events[0].game.opponent.username, 'monkeykingzach');
  assert.equal(events[0].game.id, 'bWbJuQWD');
  assert.equal(events[0].game.color, 'white');
});

test('outgoing discovery uses the full returned list, including preexisting invitations', async () => {
  const api=client({ok:true,json:async()=>({in:[{id:'Incoming'}],out:[{id:'Existing'},{id:'NewRoom1'}]})});
  const rooms=await api.getOutgoingRoomChallenges('test-token');
  assert.equal(rooms.length,2);assert.equal(rooms[0].id,'Existing');
});
test('invalid invitation snapshots fail instead of reporting a successful empty list', async () => {
  const api=client({ok:true,json:async()=>({in:[]})});
  await assert.rejects(api.getOutgoingRoomChallenges('test-token'),/invalid room list/);
});
