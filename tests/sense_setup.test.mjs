import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function loadModule(name, initial = {}, unavailable = false) {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), 'utf8')
    .replaceAll('import.meta.env', '({})');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const storage = new Map(Object.entries(initial));
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, URL, AbortSignal, localStorage: {
      getItem: key => { if (unavailable) throw new Error('storage denied'); return storage.get(key) || null; },
      setItem: (key, value) => { if (unavailable) throw new Error('quota'); storage.set(key, value); },
    },
  });
  return { module: exports, storage };
}

test('setup survives the OAuth page handoff with progress and strength intact', () => {
  const { module: setup, storage } = loadModule('senseSetup');
  setup.saveSenseSetup({ ...setup.readSenseSetup(), open: true, networkReady: true, level: 'beginner' });
  const returned = loadModule('senseSetup', Object.fromEntries(storage)).module;
  const draft = returned.readSenseSetup();
  assert.equal(draft.open, true);
  assert.equal(draft.level, 'beginner');
  assert.equal(returned.senseSetupStep(draft, null, false), 'account');
  assert.equal(returned.senseSetupStep(draft, 'Human', false), 'account');
  draft.linkedUsername = 'Human';
  assert.equal(returned.senseSetupStep(draft, 'human', false), 'room');
  assert.equal(returned.senseSetupStep(draft, 'human', true), 'connected');
});

test('another account must confirm its own SenseRobot link', () => {
  const { module: setup } = loadModule('senseSetup');
  const draft = { ...setup.readSenseSetup(), networkReady: true, linkedUsername: 'Alice' };
  assert.equal(setup.senseSetupStep(draft, 'Bob', true), 'account');
});

test('remembered physical mode requires the exact successfully joined game and account', () => {
  const { module: setup } = loadModule('senseSetup');
  const draft = { ...setup.readSenseSetup(), joinedGameId: 'AbCd1234', joinedUsername: 'Alice' };
  assert.equal(setup.isRememberedSenseGame(draft, 'AbCd1234', 'alice'), true);
  assert.equal(setup.isRememberedSenseGame(draft, 'XyZa5678', 'Alice'), false);
  assert.equal(setup.isRememberedSenseGame(draft, 'AbCd1234', 'Bob'), false);
  assert.equal(setup.isRememberedSenseGame(draft, '', ''), false);
});

test('corrupt or unavailable browser storage does not crash setup or claim a connection', () => {
  for (const raw of ['null', '{broken', '[]', '{"networkReady":"yes","joinedGameId":"../../bad"}']) {
    const { module: setup } = loadModule('senseSetup', { 'ai-chess-coach.senserobot-setup.v1': raw });
    const draft = setup.readSenseSetup();
    assert.equal(draft.networkReady, false);
    assert.equal(draft.joinedGameId, '');
    assert.equal(setup.senseSetupStep(draft, null, false), 'network');
  }
  const { module: denied } = loadModule('senseSetup', {}, true);
  assert.equal(denied.readSenseSetup().open, false);
  assert.equal(denied.saveSenseSetup(denied.readSenseSetup()), false);
});

test('scanned and pasted room links preserve the invited bot color', () => {
  const { module: bot } = loadModule('botControl');
  assert.equal(bot.parseSenseRoomUrl(' https://lichess.org/AbCd1234?color=black ').color, 'black');
  assert.equal(bot.parseSenseRoomUrl('https://lichess.org/AbCd1234?color=white').challengeId, 'AbCd1234');
  for (const url of ['https://senserobotchess.com/setup', 'WIFI:T:WPA;S:Home;',
    'https://lichess.org/AbCd1234', 'https://lichess.org/AbCd1234?color=random',
    'https://lichess.org/tooLong123?color=white', 'http://lichess.org/AbCd1234?color=white']) {
    assert.throws(() => bot.parseSenseRoomUrl(url));
  }
});
