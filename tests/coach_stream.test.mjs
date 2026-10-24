import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { Chess } from 'chess.js';

const source = readFileSync(new URL('../src/coachStream.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports, require: createRequire(import.meta.url) });
const observe = (...args) => JSON.parse(JSON.stringify(exports.observeCoachStream(...args)));
const opening = ['e2e4', 'e7e5', 'g1f3', 'b8c6'];
const snapshot = (moves, extra = {}) => ({
  gameId: 'xYDhW2TU', account: 'ZachZhang', playerColor: 'white',
  initialFen: 'startpos', moves, status: 'started', ...extra,
});
function stream(extra = {}) {
  let cursor = null;
  return (moves, options = {}) => {
    const result = observe(cursor, snapshot(moves, { ...extra, ...options }));
    cursor = result.cursor;
    return result;
  };
}

test('physical and other-client moves trigger coaching without a pending Mac submission or SenseRobot mode', () => {
  const update = stream();
  assert.equal(update([], { resync: true }).move, null);
  const move = update(['e2e4']).move;
  assert.equal(move.uci, 'e2e4');
  assert.equal(move.fenBefore, new Chess().fen());
  assert.deepEqual(move.moves, ['e2e4']);
  assert.equal(update(opening.slice(0, 2)).move, null); // opponent only
  assert.equal(update(opening.slice(0, 3)).move.uci, 'g1f3');
});

test('a local move confirmed together with a fast bot reply is analyzed once', () => {
  const update = stream();
  update([], { resync: true });
  assert.equal(update(opening.slice(0, 2)).move.uci, 'e2e4');
  assert.equal(update(opening.slice(0, 2)).move, null);
  assert.equal(update(opening.slice(0, 2)).move, null); // clock-only event
});

test('batched updates select the newest student move and the exact pre-move FEN', () => {
  const update = stream(); update([]);
  const move = update(opening).move;
  const board = new Chess(); board.move('e4'); board.move('e5');
  assert.equal(move.uci, 'g1f3');
  assert.equal(move.fenBefore, board.fen());
  assert.deepEqual(move.moves, opening.slice(0, 3));
});

test('initial attachment and reconnect history never replay reactions', () => {
  const update = stream();
  assert.equal(update(opening).move, null);
  assert.equal(update([...opening, 'f1c4', 'g8f6'], { resync: true }).move, null);
  assert.equal(update([...opening, 'f1c4', 'g8f6']).move, null);
  assert.equal(update([...opening, 'f1c4', 'g8f6', 'd2d3']).move.uci, 'd2d3');
});

test('game, account, color and root-position changes each establish a new baseline', () => {
  for (const change of [{ gameId: 'nextGame' }, { account: 'OtherPlayer' },
    { playerColor: 'black' }, { initialFen: new Chess().fen() }]) {
    const update = stream(); update([]);
    const result = update(opening, change);
    assert.equal(result.move, null);
    assert.equal(result.invalidated, true);
  }
});

test('rewinds and divergent same-length or longer lines invalidate old analysis', () => {
  for (const alternative of [opening.slice(0, 2), ['d2d4', 'd7d5', 'c2c4', 'e7e6'],
    ['d2d4', 'd7d5', 'c2c4', 'e7e6', 'b1c3']]) {
    const update = stream(); update(opening);
    const result = update(alternative);
    assert.equal(result.move, null);
    assert.equal(result.invalidated, true);
  }
});

test('a genuinely new move after a takeback is analyzed from the new branch', () => {
  const update = stream(); update(opening); update(opening.slice(0, 2));
  assert.equal(update(['e2e4', 'e7e5', 'b1c3']).move.uci, 'b1c3');
});

test('Black student moves and custom FENs use the board turn rather than ply parity', () => {
  const update = stream({ playerColor: 'black' }); update([]);
  assert.equal(update(['e2e4']).move, null);
  assert.equal(update(opening.slice(0, 2)).move.uci, 'e7e5');
  const board = new Chess(); board.move('e4');
  const fromBlack = stream({ playerColor: 'black', initialFen: board.fen() });
  fromBlack([]);
  assert.equal(fromBlack(['e7e5']).move.fenBefore, board.fen());
});

test('promotion UCI and exact custom root reach analysis intact', () => {
  const root = '7k/P7/8/8/8/8/8/7K w - - 0 1';
  const update = stream({ initialFen: root }); update([]);
  const move = update(['a7a8q']).move;
  assert.equal(move.uci, 'a7a8q');
  assert.equal(move.fenBefore, root);
});

test('invalid chess moves never dispatch and require a new baseline', () => {
  const update = stream(); update([]);
  const result = update(['e2e5']);
  assert.equal(result.move, null);
  assert.equal(result.cursor, null);
  assert.equal(result.invalidated, true);
  assert.equal(update(['e2e4']).move, null);
});

test('finished and recovering snapshots cannot cause delayed robot reactions', () => {
  for (const status of ['mate', 'resign', 'aborted', 'recovering']) {
    const update = stream(); update([]);
    const result = update(opening, { status });
    assert.equal(result.move, null);
    assert.equal(result.invalidated, true);
  }
});
