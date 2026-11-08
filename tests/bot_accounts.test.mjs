import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function load(name) {
  const source = readFileSync(new URL(`../src/${name}.ts`, import.meta.url), 'utf8').replaceAll('import.meta.env', '({})');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require: () => ({}) });
  return exports;
}

const { maskedToken, accountOptionLabel, accountSwitchBlock, buildNewAccount, EMPTY_BOT_ACCOUNT_DRAFT } = load('botAccounts');
const draft = (fields) => ({ ...EMPTY_BOT_ACCOUNT_DRAFT, ...fields });

test('token display only ever shows where the token lives and its last four characters', () => {
  assert.equal(maskedToken({ tokenSource: 'env', tokenEnv: 'LICHESS_BOT_TOKEN', tokenHint: 'ab12', tokenConfigured: true }), 'LICHESS_BOT_TOKEN · ••••ab12');
  assert.equal(maskedToken({ tokenSource: 'saved', tokenEnv: null, tokenHint: 'cd34', tokenConfigured: true }), 'Saved · ••••cd34');
  assert.equal(maskedToken({ tokenSource: 'env', tokenEnv: 'LICHESS_BOT_TOKEN_2', tokenHint: '', tokenConfigured: false }), 'LICHESS_BOT_TOKEN_2 not set');
  assert.equal(maskedToken({ tokenSource: 'saved', tokenEnv: null, tokenHint: '', tokenConfigured: false }), 'No token');
});

test('option labels avoid repeating the username', () => {
  assert.equal(accountOptionLabel({ label: 'Default (.env)', username: 'bot_2435' }), 'Default (.env) (bot_2435)');
  assert.equal(accountOptionLabel({ label: 'secondbot', username: 'SecondBot' }), 'SecondBot');
});

test('the account cannot change while a game is starting or running', () => {
  assert.equal(accountSwitchBlock({}), '');
  assert.equal(accountSwitchBlock({ gameId: null, activeGames: 0 }), '');
  assert.match(accountSwitchBlock({ startingGame: true }), /Wait/);
  assert.match(accountSwitchBlock({ gameId: 'AbCd1234' }), /Finish the current game/);
  assert.match(accountSwitchBlock({ activeGames: 1 }), /Finish the current game/);
  assert.equal(accountSwitchBlock({ locked: true, lockedReason: 'Busy.' }), 'Busy.');
});

test('new accounts need a username and exactly one token source', () => {
  assert.equal(buildNewAccount(draft({ username: '', token: 'lip_abcdefgh' })).ok, false);
  assert.equal(buildNewAccount(draft({ username: 'Second Bot', token: 'lip_abcdefgh' })).ok, false);
  assert.equal(buildNewAccount(draft({ username: 'SecondBot', token: 'short' })).ok, false);
  assert.equal(buildNewAccount(draft({ username: 'SecondBot', tokenMode: 'env', tokenEnv: 'PATH' })).ok, false);
  const pasted = buildNewAccount(draft({ label: ' Club bot ', username: ' SecondBot ', token: ' lip_abcdefgh ', tokenEnv: 'LICHESS_IGNORED' }));
  assert.deepEqual({ ...pasted.account }, { label: 'Club bot', username: 'SecondBot', token: 'lip_abcdefgh', select: true });
  const env = buildNewAccount(draft({ username: 'EnvBot', tokenMode: 'env', tokenEnv: 'LICHESS_BOT_TOKEN_2', token: 'stale' }));
  assert.deepEqual({ ...env.account }, { label: '', username: 'EnvBot', tokenEnv: 'LICHESS_BOT_TOKEN_2', select: true });
});

test('errors never echo the pasted token', () => {
  const secret = 'lip_ has whitespace';
  const result = buildNewAccount(draft({ username: 'SecondBot', token: secret }));
  assert.equal(result.ok, false);
  assert.ok(!result.error.includes(secret));
});
