import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { APP_SRC, loadApp, memoryStore, plain, validScore } from './vbotAppLoader.mjs';

const score = loadApp('domain/score.ts');
const catalog = loadApp('domain/catalog.ts');
const library = loadApp('domain/library.ts');
const perception = loadApp('domain/perception.ts');
const fixtures = JSON.parse(readFileSync(new URL('./fixtures/vbot_app_scores.json', import.meta.url), 'utf8'));

const caps = (over = {}) => {
  const off = { available: false, reason: 'off' };
  return { face: { available: true, reason: null }, head: off, body: off, speech: off, navigation: off, supportedFaceIds: null, rehearsedPresets: [], ...over };
};

test('shared fixtures: accepted scores parse', () => {
  for (const raw of fixtures.accepted) assert.equal(score.parseScore(raw).ok, true, raw.id);
});

test('shared fixtures: every malformed score is rejected', () => {
  for (const { why, score: raw } of fixtures.rejected) assert.equal(score.parseScore(raw).ok, false, why);
});

test('non-object input is rejected without throwing', () => {
  for (const raw of [null, 1, 'x', [], undefined]) assert.equal(score.parseScore(raw).ok, false);
});

test('cue count is bounded, including after repeats', () => {
  const cue = index => ({ id: `c${index}`, type: 'wait', durationMs: 100 });
  const many = Array.from({ length: 65 }, (_, index) => cue(index));
  assert.equal(score.parseScore(validScore({ cues: many })).ok, false);
  const repeated = Array.from({ length: 30 }, (_, index) => cue(index));
  assert.equal(score.parseScore(validScore({ cues: repeated, repeat: 5 })).ok, false);
  assert.equal(score.parseScore(validScore({ cues: repeated, repeat: 4 })).ok, true);
});

test('a preset cannot claim the wrong kind or be unlisted', () => {
  const body = (preset, type = 'body') => validScore({ cues: [{ id: 'a', type, preset }] });
  assert.equal(score.parseScore(body('actions/WAVE.json')).ok, true);
  assert.equal(score.parseScore(body('atom/look_left.json', 'head')).ok, true);
  assert.equal(score.parseScore(body('atom/look_left.json', 'body')).ok, false);
  assert.equal(score.parseScore(body('actions/WAVE.json', 'head')).ok, false);
  assert.equal(score.parseScore(body('actions/../../etc/passwd')).ok, false);
});

test('speech and navigation are not valid cues until a backend is verified', () => {
  assert.equal(score.parseScore(validScore({ cues: [{ id: 'a', type: 'speech', text: 'hi' }] })).ok, false);
  assert.equal(score.parseScore(validScore({ cues: [{ id: 'a', type: 'navigation' }] })).ok, false);
});

test('active snapshots are immutable and independent of later edits', () => {
  const original = validScore();
  const snapshot = score.snapshotScore(original);
  original.cues[0].durationMs = 999;
  original.title = 'Edited';
  assert.equal(snapshot.cues[0].durationMs, 4500);
  assert.equal(snapshot.title, 'Test show');
  assert.throws(() => { 'use strict'; snapshot.cues[0].durationMs = 1; }, TypeError);
  assert.throws(() => { 'use strict'; snapshot.cues.push({}); }, TypeError);
});

test('face tiles only produce face cues, even with a body-motion name', () => {
  for (const id of [68, 69, 51]) {
    const entry = catalog.CATALOG.find(item => item.id === `face:${id}`);
    assert.match(entry.resource, /ROCKYOU|high_five/);
    const cue = score.cueFromEntry(entry);
    assert.equal(cue.type, 'face');
    assert.equal(cue.assetId, id);
    assert.equal('preset' in cue, false);
  }
  const dance = catalog.CATALOG.find(item => item.id === 'body:actions/ROCKYOU.json');
  assert.equal(score.cueFromEntry(dance).type, 'body');
});

test('speech and navigation entries cannot make cues', () => {
  for (const id of ['speech', 'navigation']) assert.equal(score.cueFromEntry(catalog.CATALOG.find(item => item.id === id)), null);
});

test('every documented face is either in the catalog or restricted, never both', () => {
  const faces = new Set(catalog.CATALOG.filter(item => item.kind === 'face').map(item => item.assetId));
  for (let id = 0; id <= 116; id += 1) {
    if (id === 98) continue; // Not present in the SDK's list.
    const restricted = catalog.RESTRICTED_FACE_IDS.includes(id);
    assert.notEqual(faces.has(id), restricted, `face ${id}`);
  }
});

test('only the six faces watched onsite are marked confirmed', () => {
  const confirmed = catalog.CATALOG.filter(item => item.kind === 'face' && item.verification === 'exercised').map(item => item.assetId).sort((a, b) => a - b);
  assert.deepEqual(plain(confirmed), [70, 71, 76, 79, 81, 86]);
});

test('merging a device list adds extras but never restricted assets', () => {
  const merged = catalog.mergeDeviceFaces(catalog.CATALOG, ['086_THINK', '004_happy_10s', '130_NEW_THING', '131_CHARGE_Z', 'garbage']);
  assert.ok(merged.find(item => item.id === 'face:130'));
  assert.equal(merged.find(item => item.id === 'face:131'), undefined);
  assert.equal(merged.find(item => item.id === 'face:86').verification, 'exercised');
  assert.equal(merged.find(item => item.id === 'face:4').verification, 'device-listed');
  assert.equal(catalog.mergeDeviceFaces(catalog.CATALOG, null).length, catalog.CATALOG.length);
});

test('admission: a face-only show needs no motion capability or rehearsal', () => {
  assert.equal(score.admitScore(validScore(), caps()).ok, true);
});

test('admission: motion is blocked with a reason even when face works', () => {
  const show = validScore({ cues: [{ id: 'a', type: 'face', assetId: 86, durationMs: 4500 }, { id: 'b', type: 'body', preset: 'actions/WAVE.json' }] });
  const result = score.admitScore(show, caps({ body: { available: false, reason: 'face-only adapter' } }));
  assert.equal(result.ok, false);
  assert.deepEqual(plain(result.blockers), [{ cueId: 'b', kind: 'body', reason: 'face-only adapter' }]);
});

test('admission: a capable dog still needs a rehearsal for each preset', () => {
  const show = validScore({ cues: [{ id: 'b', type: 'body', preset: 'actions/WAVE.json' }] });
  const on = { available: true, reason: null };
  assert.equal(score.admitScore(show, caps({ body: on })).ok, false);
  assert.equal(score.admitScore(show, caps({ body: on, rehearsedPresets: ['actions/WAVE.json'] })).ok, true);
});

test('admission: a face this dog does not list is blocked', () => {
  assert.equal(score.admitScore(validScore(), caps({ supportedFaceIds: [1, 2] })).ok, false);
  assert.equal(score.admitScore(validScore(), caps({ supportedFaceIds: [86] })).ok, true);
});

test('timeline expands repeats in order and flags unmeasured presets', () => {
  const timeline = score.buildTimeline(validScore({ repeat: 2 }));
  assert.equal(timeline.items.length, 4);
  assert.equal(timeline.totalMs, 11000);
  assert.deepEqual(plain(timeline.items.map(item => item.startMs)), [0, 4500, 5500, 10000]);
  const unmeasured = score.buildTimeline(validScore({ cues: [{ id: 'a', type: 'body', preset: 'actions/CHEER_R.json' }] }));
  assert.equal(unmeasured.unknownDurations, 1);
  assert.equal(unmeasured.items[0].durationKnown, false);
});

test('editor helpers keep cue IDs stable and unique', () => {
  const cues = validScore().cues;
  assert.deepEqual(plain(score.moveCue(cues, 0, 1).map(cue => cue.id)), ['b', 'a']);
  assert.deepEqual(plain(score.moveCue(cues, 0, -1).map(cue => cue.id)), ['a', 'b']);
  const copied = score.duplicateCue(cues, 0);
  assert.equal(copied.length, 3);
  assert.equal(new Set(copied.map(cue => cue.id)).size, 3);
  assert.equal(score.clampDuration(cues[0], 999999), 30000);
  assert.equal(score.clampDuration(cues[1], Number.NaN), 100);
});

test('library persists across a reload and restores shows without running them', () => {
  const store = memoryStore();
  const show = score.makeScore('Mine', 5, [{ id: 'a', type: 'wait', durationMs: 100 }]);
  const state = library.upsertShow(library.loadLibrary(store), show);
  assert.equal(library.saveLibrary(store, { ...state, selectedId: show.id, favorites: new Set(['face:86']) }), true);
  const reloaded = library.loadLibrary(store);
  assert.equal(reloaded.shows.length, 1);
  assert.equal(reloaded.shows[0].title, 'Mine');
  assert.equal(reloaded.selectedId, show.id);
  assert.equal(reloaded.favorites.has('face:86'), true);
  assert.equal(Object.keys(reloaded).includes('run'), false);
});

test('corrupt or invalid saved data is set aside and never overwritten silently', () => {
  const corrupt = memoryStore({ 'vbot-studio.library.v1': '{not json' });
  const state = library.loadLibrary(corrupt);
  assert.equal(state.shows.length, 0);
  assert.equal(state.warnings.length, 1);
  assert.equal(corrupt.data.get('vbot-studio.library.quarantine'), '{not json');

  const mixed = memoryStore({ 'vbot-studio.library.v1': JSON.stringify({ version: 1, shows: [validScore(), { bad: true }], favorites: [], selectedId: null }) });
  const partial = library.loadLibrary(mixed);
  assert.equal(partial.shows.length, 1);
  assert.equal(partial.warnings.length, 1);
  assert.match(mixed.data.get('vbot-studio.library.quarantine'), /bad/);
});

test('storage failures degrade to a warning instead of crashing', () => {
  const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(library.loadLibrary(broken).warnings.length, 1);
  assert.equal(library.saveLibrary(broken, library.loadLibrary(memoryStore())), false);
});

test('import validates, assigns a new identity and cannot pose as canned', () => {
  const raw = JSON.stringify(validScore({ id: 'canned-mood-swing', origin: 'canned', revision: 9 }));
  const result = library.importShow(raw, 42);
  assert.equal(result.ok, true);
  assert.notEqual(result.show.id, 'canned-mood-swing');
  assert.equal(result.show.origin, 'custom');
  assert.equal(result.show.revision, 1);
  for (const { score: bad } of fixtures.rejected) assert.equal(library.importShow(JSON.stringify(bad), 42).ok, false);
  assert.equal(library.importShow('not json', 42).ok, false);
  assert.equal(library.importShow('x'.repeat(300 * 1024), 42).ok, false);
});

test('export round-trips through import', () => {
  const show = library.cannedShows()[0];
  assert.equal(library.importShow(library.exportShow(show), 1).ok, true);
});

test('save-as gives fresh identities and leaves the original alone', () => {
  const original = validScore();
  const copy = library.copyShow(original, 'Copy', 7);
  assert.notEqual(copy.id, original.id);
  assert.notEqual(copy.cues[0].id, original.cues[0].id);
  assert.equal(copy.title, 'Copy');
  assert.equal(original.title, 'Test show');
});

test('bundled shows are valid and the face show is face-only', () => {
  const shows = library.cannedShows();
  assert.equal(shows.length, 3);
  const moods = shows.find(show => show.id === 'canned-mood-swing');
  assert.equal(moods.cues.every(cue => cue.type === 'face'), true);
  assert.equal(score.admitScore(moods, caps()).ok, true);
  const mischief = shows.find(show => show.id === 'canned-midnight-mischief');
  assert.equal(score.admitScore(mischief, caps()).ok, false);
  // Rock You is its own show: exactly the one dance cue, and it needs motion like any dance.
  const rock = shows.find(show => show.id === 'canned-rock-you');
  assert.deepEqual(plain(rock.cues.map(cue => [cue.type, cue.preset])), [['body', 'actions/ROCKYOU.json']]);
  assert.equal(rock.origin, 'canned');
  assert.equal(score.admitScore(rock, caps()).ok, false);
  const on = { available: true, reason: null };
  assert.equal(score.admitScore(rock, caps({ body: on, armedPresets: ['actions/ROCKYOU.json'] })).ok, true);
  assert.equal(catalog.CATALOG.find(entry => entry.preset === 'actions/ROCKYOU.json').category, 'Dances');
});

test('player tracking never switches to another person or invents a location', () => {
  const selection = { sessionId: 's', selectedAt: 0, trackId: 'a', chosenBy: 'host' };
  const box = { x: 0, y: 0, width: 1, height: 1 };
  const other = { trackId: 'b', box, score: .9, observedAt: 100 };
  assert.equal(perception.trackingStatus(null, [other], 100).state, 'none');
  assert.equal(perception.trackingStatus(selection, [other], 100).state, 'lost');
  const mine = { trackId: 'a', box, score: .8, observedAt: 100 };
  assert.equal(perception.trackingStatus(selection, [mine, other], 100).state, 'tracking');
  assert.equal(perception.trackingStatus(selection, [mine], 100 + perception.TRACK_STALE_MS + 1).state, 'stale');
  assert.equal(perception.trackingStatus(selection, [mine], 100 + perception.TRACK_LOST_MS + 1).state, 'lost');
  const location = { x: 1, y: 1, z: 0, frameId: 'map', frameRevision: 1, localizationEpoch: 1, observedAt: 0, uncertaintyM: 1, provenance: 'estimated' };
  assert.equal(perception.usableLocation(location, 2, 1), null);
  assert.equal(perception.usableLocation(location, 1, 2), null);
  assert.ok(perception.usableLocation(location, 1, 1));
});

function appSources(dir = APP_SRC) {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? appSources(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

test('the app has no chess, Lichess or Chess Buddy dependency', () => {
  for (const path of appSources()) {
    const source = readFileSync(path, 'utf8');
    assert.doesNotMatch(source, /from ['"][^'"]*(chess|lichess|\.\.\/\.\.\/\.\.\/src)[^'"]*['"]/i, path);
  }
  const html = readFileSync(new URL('../vbot-app/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /chess|lichess/i);
});

test('the app has its own identity, separate from Chess Buddy', () => {
  const config = readFileSync(new URL('../vbot-app/capacitor.config.ts', import.meta.url), 'utf8');
  assert.match(config, /appId: 'com\.andy\.vbotstudio'/);
  const root = readFileSync(new URL('../capacitor.config.ts', import.meta.url), 'utf8');
  assert.match(root, /appId: 'com\.andy\.chessbuddy'/);
});

test('preview cannot reach a device: no transport import and no network calls', () => {
  const source = readFileSync(join(APP_SRC, 'components/PreviewPanel.tsx'), 'utf8');
  assert.doesNotMatch(source, /from ['"][^'"]*(transport|useStudio)[^'"]*['"]/);
  assert.doesNotMatch(source.replace(/\/\*[\s\S]*?\*\//, ''), /\bfetch\b|XMLHttpRequest|WebSocket|\.submit\(/);
  const types = readFileSync(join(APP_SRC, 'transport/types.ts'), 'utf8');
  assert.doesNotMatch(types.replace(/\/\*[\s\S]*?\*\//g, ''), /preview/i);
});

test('frontend sources contain no credentials or a hardcoded dog address', () => {
  for (const path of appSources()) {
    const source = readFileSync(path, 'utf8');
    assert.doesNotMatch(source, /192\.168\.0\.170|172\.20\.10\.5|2c:f8:ec|BEGIN .*PRIVATE KEY|api[_-]?key\s*[:=]/i, path);
  }
});

test('admission: motion enabled for this connection admits an approved preset without claiming a rehearsal', () => {
  const show = validScore({ cues: [{ id: 'b', type: 'body', preset: 'actions/WAVE.json' }] });
  const on = { available: true, reason: null };
  assert.equal(score.admitScore(show, caps({ body: on, armedPresets: ['actions/WAVE.json'] })).ok, true);
  assert.equal(score.admitScore(show, caps({ body: on, armedPresets: ['actions/SAYYES.json'] })).ok, false);
  assert.equal(score.admitScore(show, caps({ body: { available: false, reason: 'off' }, armedPresets: ['actions/WAVE.json'] })).ok, false);
  assert.deepEqual(plain(caps({ body: on, armedPresets: [] }).rehearsedPresets), []);
});

// --- bounded basic moves -----------------------------------------------------------------------

const MOVE = { id: 'm1', type: 'move', move: 'step_forward' };
const moveShow = (...cues) => validScore({ cues });
const movesOn = (over = {}) => caps({ move: { available: true, reason: null }, armedMoves: catalog.MOVE_NAMES.slice(), ...over });

test('moves: the catalog names are exactly the dog-side table, in the same order', () => {
  const source = readFileSync(new URL('../vbot-demo/robot_studio.py', import.meta.url), 'utf8');
  const block = source.slice(source.indexOf('\nMOVES = {'), source.indexOf('\n}\n', source.indexOf('\nMOVES = {')));
  const dog = [...block.matchAll(/^\s+"([a-z0-9_]+)":/gm)].map(match => match[1]);
  assert.deepEqual([...catalog.MOVE_NAMES], dog);
  assert.ok(dog.length >= 8);
});

test('moves: the controller names the same moves', () => {
  const source = readFileSync(new URL('../server/vbot_app_control.py', import.meta.url), 'utf8');
  const line = source.slice(source.indexOf('MOVES = ('), source.indexOf(')', source.indexOf('MOVES = (')));
  assert.deepEqual([...line.matchAll(/'([a-z0-9_]+)'/g)].map(match => match[1]), [...catalog.MOVE_NAMES]);
});

test('moves: a turn parses with or without an allowed face, and a step never carries one', () => {
  const TURN = { id: 't1', type: 'move', move: 'turn_left_30' };
  assert.equal(score.parseScore(moveShow(MOVE)).ok, true);
  assert.equal(score.parseScore(moveShow(TURN)).ok, true);
  assert.equal(score.parseScore(moveShow({ ...TURN, faceId: 86 })).ok, true);
  assert.equal(score.parseScore(moveShow({ ...TURN, faceId: 0, caption: 'Hello' })).ok, true);
  for (const step of catalog.FACELESS_MOVE_NAMES) assert.equal(score.parseScore(moveShow({ ...MOVE, move: step, faceId: 86 })).ok, false, step);
  assert.equal('faceId' in score.withMoveFace(MOVE, 86), false);
});

test('moves: the faceless steps are exactly the dog-side and controller sets', () => {
  const dog = readFileSync(new URL('../vbot-demo/robot_studio.py', import.meta.url), 'utf8');
  const ctl = readFileSync(new URL('../server/vbot_app_control.py', import.meta.url), 'utf8');
  const names = text => [...text.matchAll(/(step_[a-z]+)/g)].map(match => match[1]);
  const dogSet = names(dog.slice(dog.indexOf('STEP_TASKS = {'), dog.indexOf('}', dog.indexOf('STEP_TASKS = {'))));
  const ctlSet = names(ctl.slice(ctl.indexOf('FACELESS_MOVES = ('), ctl.indexOf(')', ctl.indexOf('FACELESS_MOVES = ('))));
  assert.deepEqual([...catalog.FACELESS_MOVE_NAMES].sort(), [...new Set(dogSet)].sort());
  assert.deepEqual([...catalog.FACELESS_MOVE_NAMES].sort(), [...new Set(ctlSet)].sort());
});

test('moves: unapproved moves, extra fields and bad faces are rejected', () => {
  for (const bad of [
    { id: 'a', type: 'move' }, { ...MOVE, move: 'backflip' }, { ...MOVE, move: 'actions/WAVE.json' }, { ...MOVE, move: 3 },
    { ...MOVE, distance: 5 }, { ...MOVE, angle: 1 }, { ...MOVE, durationMs: 1000 }, { ...MOVE, preset: 'actions/WAVE.json' },
    { ...MOVE, faceId: 66 }, { ...MOVE, faceId: 256 }, { ...MOVE, faceId: -1 }, { ...MOVE, faceId: '86' }, { ...MOVE, faceId: 1.5 }, { ...MOVE, faceId: null },
  ]) assert.equal(score.parseScore(moveShow(bad)).ok, false, JSON.stringify(bad));
});

test('moves: a move counts toward no hidden duration, so the timeline reports it as unmeasured', () => {
  const timeline = score.buildTimeline({ cues: [MOVE], repeat: 1 });
  assert.equal(timeline.unknownDurations, 1);
  assert.equal(timeline.items[0].durationKnown, false);
  assert.equal(score.cueTitle(MOVE), 'Step forward');
});

test('moves: admission needs the move capability and the move to be armed for this connection', () => {
  const show = moveShow(MOVE);
  assert.equal(score.admitScore(show, movesOn()).ok, true);
  assert.equal(score.admitScore(show, movesOn({ armedMoves: ['step_back'] })).ok, false);
  assert.equal(score.admitScore(show, movesOn({ armedMoves: [] })).ok, false);
  assert.equal(score.admitScore(show, movesOn({ move: { available: false, reason: 'off' } })).ok, false);
  assert.equal(score.admitScore(show, caps()).ok, false); // an older controller reports no move capability at all
  assert.equal(score.admitScore(show, caps({ armedMoves: ['step_forward'] })).ok, false);
  // rehearsedPresets and armedPresets never admit a move
  assert.equal(score.admitScore(show, movesOn({ armedMoves: [], rehearsedPresets: ['step_forward'], armedPresets: ['step_forward'] })).ok, false);
});

test('moves: a face on a move must be one the dog lists', () => {
  const show = moveShow({ id: 't', type: 'move', move: 'turn_left_30', faceId: 86 });
  assert.equal(score.admitScore(show, movesOn({ supportedFaceIds: [86] })).ok, true);
  const refused = score.admitScore(show, movesOn({ supportedFaceIds: [70] }));
  assert.equal(refused.ok, false);
  assert.equal(refused.blockers[0].kind, 'face');
});

test('moves: a catalog tile makes exactly a bare move cue, and the face helper adds or clears the face', () => {
  const entry = catalog.CATALOG.find(item => item.id === 'move:turn_left_30');
  const cue = score.cueFromEntry(entry);
  assert.deepEqual(plain({ ...cue, id: 'x' }), { id: 'x', type: 'move', move: 'turn_left_30' });
  assert.equal(score.withMoveFace(cue, 86).faceId, 86);
  assert.equal('faceId' in score.withMoveFace(score.withMoveFace(cue, 86), null), false);
  assert.equal(score.parseScore(moveShow(score.withMoveFace(cue, 86))).ok, true);
  for (const item of catalog.CATALOG.filter(entry => entry.kind === 'move')) {
    // Only the left 30° turn was watched onsite; nothing else may claim more than "documented".
    assert.equal(item.verification, /^turn_(left|right)_(30|90)$/.test(item.move) ? 'exercised' : 'documented', item.move);
    assert.equal(item.category, 'Moves');
    assert.equal(item.durationMs, null);
  }
});

const hold = loadApp('domain/hold.ts');

/** A scripted hold: `held` says whether the button is down at each check, `states` the result of each command. */
function scriptedHold({ held, states = [], max }) {
  const sent = []; let inFlight = 0; let maxInFlight = 0; let check = 0;
  return {
    sent,
    run: () => hold.runHold({
      maxChunks: max,
      holding: () => held(check++, sent.length),
      send: async () => { inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight); sent.push(sent.length); return { commandId: `c${sent.length}` }; },
      settled: async () => { inFlight -= 1; return states[sent.length - 1] ?? 'completed'; },
    }),
    maxInFlight: () => maxInFlight,
  };
}

test('hold: it keeps sending one move at a time while held and stops the moment it is released', async () => {
  const h = scriptedHold({ held: (_, sent) => sent < 3 });
  const outcome = await h.run();
  assert.deepEqual(plain(outcome), { chunks: 3, end: 'released' });
  assert.equal(h.maxInFlight(), 1); // the next move is never sent before the last one settled
});

test('hold: nothing is sent if the button is not held to begin with', async () => {
  const h = scriptedHold({ held: () => false });
  assert.deepEqual(plain(await h.run()), { chunks: 0, end: 'released' });
  assert.equal(h.sent.length, 0);
});

test('hold: a held button still stops at the chunk cap and needs a fresh press', async () => {
  const h = scriptedHold({ held: () => true });
  const outcome = await h.run();
  assert.equal(outcome.end, 'cap');
  assert.equal(outcome.chunks, hold.HOLD_MAX_CHUNKS);
  assert.ok(hold.HOLD_MAX_CHUNKS <= 20, 'the cap stays small');
  assert.equal(h.sent.length, hold.HOLD_MAX_CHUNKS);
});

test('hold: any result but a clean completion ends the hold and is never repeated', async () => {
  for (const state of ['rejected', 'cancelled', 'unknown', 'running']) {
    const h = scriptedHold({ held: () => true, states: ['completed', state] });
    const outcome = await h.run();
    assert.deepEqual(plain(outcome), { chunks: 2, end: 'not-clean', state }, state);
    assert.equal(h.sent.length, 2, state);
  }
});

test('hold: a refused send ends the hold without retrying', async () => {
  let attempts = 0;
  const outcome = await hold.runHold({ holding: () => true, send: async () => { attempts += 1; return null; }, settled: async () => 'completed' });
  assert.deepEqual(plain(outcome), { chunks: 0, end: 'refused' });
  assert.equal(attempts, 1);
});

test('hold: the pad wires every release path, repeats only small turns, and uses no timers of its own', () => {
  const source = readFileSync(join(APP_SRC, 'components/MovePad.tsx'), 'utf8');
  for (const needed of ['onPointerUp', 'onPointerCancel', 'onPointerLeave', 'onLostPointerCapture', 'onKeyUp', 'onBlur',
    "'blur'", "'pagehide'", "'visibilitychange'", "document.visibilityState === 'visible'", 'removeEventListener', 'setPointerCapture', 'onContextMenu']) {
    assert.ok(source.includes(needed), `MovePad must handle ${needed}`);
  }
  assert.doesNotMatch(source, /setInterval|setTimeout|requestAnimationFrame/); // no clock can keep a hold alive
  // Only the two 10° nudges repeat. Steps and the larger turns are one move per tap.
  const holds = [...source.matchAll(/move: '([a-z0-9_]+)'[^}]*hold: (true|false)/g)].filter(match => match[2] === 'true').map(match => match[1]);
  assert.deepEqual(holds.sort(), ['turn_left_10', 'turn_right_10']);
  assert.match(source, /runHold\(/);
});

test('hold: nothing in the app streams a velocity or keeps a move going on a timer', () => {
  for (const path of appSources()) {
    const source = readFileSync(path, 'utf8');
    assert.doesNotMatch(source, /setInterval\([^)]*(move|step|turn|hold)/i, path);
  }
  const types = readFileSync(join(APP_SRC, 'domain/hold.ts'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(types, /setInterval|setTimeout|fetch|WebSocket/);
});

test('ux: motion can be armed from a live connection, and actions no longer pull the page to another tab', () => {
  const dog = readFileSync(join(APP_SRC, 'views/DogView.tsx'), 'utf8');
  assert.match(dog, /Reconnect with motion/);
  assert.doesNotMatch(dog, /settings\.kind === 'local-face' && !connected && \(\s*<section/);
  for (const file of ['views/ActionsView.tsx', 'components/MovePad.tsx']) {
    assert.doesNotMatch(readFileSync(join(APP_SRC, file), 'utf8'), /onStage/, `${file} must not navigate away`);
  }
  const app = readFileSync(join(APP_SRC, 'App.tsx'), 'utf8');
  assert.match(app, /<RunSheet /);
});

test('ux: the run sheet words outcomes as what the dog reported, never as proof it happened', () => {
  const sheet = readFileSync(join(APP_SRC, 'components/RunSheet.tsx'), 'utf8');
  assert.match(sheet, /The dog reported it finished/);
  assert.doesNotMatch(sheet, /Success|Succeeded/i);
});

// --- hold-to-drive ---------------------------------------------------------------------------------

const drive = loadApp('domain/drive.ts');

/** A virtual clock whose `wait` advances time, so the loop runs instantly and deterministically. */
function driveHarness({ heldUntil = Infinity, startResult = { ok: true }, frameOk = () => true, stopThrows = false, maxMs, releaseAfterFrames } = {}) {
  const clock = { t: 0 };
  const log = [];
  let frames = 0;
  const deps = {
    now: () => clock.t,
    wait: async ms => { clock.t += ms; },
    frameMs: 100,
    maxMs,
    held: () => clock.t < heldUntil && !(releaseAfterFrames !== undefined && frames >= releaseAfterFrames),
    vector: () => ({ vx: 0.1, vy: 0, wz: 0 }),
    start: async () => { log.push('start'); return startResult; },
    frame: async frame => { frames += 1; log.push(`frame:${frame.seq}`); return frameOk(frame.seq); },
    stop: async () => { log.push('stop'); if (stopThrows) throw new Error('gone'); return {}; },
  };
  return { deps, log, clock };
}

test('drive: frames stream while held, in order, and the stop comes right after release', async () => {
  const h = driveHarness({ heldUntil: 450 });
  const outcome = await drive.runDrive(h.deps);
  assert.equal(outcome.end, 'released');
  assert.deepEqual(plain(h.log), ['start', 'frame:1', 'frame:2', 'frame:3', 'frame:4', 'frame:5', 'stop']);
  assert.equal(h.log.at(-1), 'stop');
});

test('drive: nothing starts if the button is not held, and no frame is ever sent after release', async () => {
  const none = driveHarness({ heldUntil: 0 });
  assert.deepEqual(plain(await drive.runDrive(none.deps)), { end: 'released', frames: 0 });
  assert.deepEqual(plain(none.log), []);
  const h = driveHarness({ releaseAfterFrames: 3 });
  await drive.runDrive(h.deps);
  assert.deepEqual(plain(h.log), ['start', 'frame:1', 'frame:2', 'frame:3', 'stop']);
});

test('drive: one press is capped well under the dog’s own limit, then it stops', async () => {
  const h = driveHarness({});
  const outcome = await drive.runDrive(h.deps);
  assert.equal(outcome.end, 'cap');
  assert.ok(drive.DRIVE_HOLD_MAX_MS <= 7500, 'the app cap stays below the dog’s 8 s');
  assert.ok(h.clock.t >= drive.DRIVE_HOLD_MAX_MS && h.clock.t < drive.DRIVE_HOLD_MAX_MS + 300);
  assert.equal(h.log.at(-1), 'stop');
});

test('drive: a refused start sends no frames and no stop', async () => {
  const h = driveHarness({ startResult: { ok: false, reason: 'Stand it first.' } });
  const outcome = await drive.runDrive(h.deps);
  assert.deepEqual(plain(outcome), { end: 'refused', frames: 0, detail: 'Stand it first.' });
  assert.deepEqual(plain(h.log), ['start']);
});

test('drive: a start that throws still asks for a stop, because the dog may have started', async () => {
  const h = driveHarness({});
  h.deps.start = async () => { h.log.push('start'); throw new Error('no answer'); };
  const outcome = await drive.runDrive(h.deps);
  assert.equal(outcome.end, 'error');
  assert.deepEqual(plain(h.log), ['start', 'stop']);
});

test('drive: a frame that does not get through ends the drive with a stop', async () => {
  const h = driveHarness({ frameOk: seq => seq < 3 });
  const outcome = await drive.runDrive(h.deps);
  assert.equal(outcome.end, 'error');
  assert.deepEqual(plain(h.log), ['start', 'frame:1', 'frame:2', 'frame:3', 'stop']);
});

test('drive: a thrown frame or a failing stop never leaves the loop hanging', async () => {
  const h = driveHarness({ stopThrows: true });
  h.deps.frame = async () => { throw new Error('boom'); };
  const outcome = await drive.runDrive(h.deps);
  assert.equal(outcome.end, 'error');
  assert.equal(h.log.at(-1), 'stop');
});

test('drive: speeds are fractions of the dog’s caps and never exceed them', () => {
  const limits = { vx: 0.15, vy: 0.1, wz: 0.4 };
  for (const speed of Object.keys(drive.DRIVE_SPEEDS)) {
    for (const direction of [{ vx: 1 }, { vx: -1 }, { vy: 1 }, { vy: -1 }, { wz: 1 }, { wz: -1 }]) {
      const v = drive.scaled(limits, direction, speed);
      assert.ok(Math.abs(v.vx) <= limits.vx && Math.abs(v.vy) <= limits.vy && Math.abs(v.wz) <= limits.wz, `${speed} ${JSON.stringify(direction)}`);
    }
  }
  assert.ok(drive.DRIVE_SPEEDS.slow < drive.DRIVE_SPEEDS.normal && drive.DRIVE_SPEEDS.normal <= 0.8);
  assert.deepEqual(plain(drive.scaled(limits, { wz: 1 }, 'slow')), { vx: 0, vy: 0, wz: 0.4 * drive.DRIVE_SPEEDS.slow });
});

test('drive: the app’s caps equal the controller’s and the dog’s', () => {
  const dog = readFileSync(new URL('../vbot-demo/robot_studio.py', import.meta.url), 'utf8');
  const caps = Object.fromEntries([...dog.slice(dog.indexOf('DRIVE_MAX = {'), dog.indexOf('}', dog.indexOf('DRIVE_MAX = {'))).matchAll(/"(\w+)": ([0-9.]+)/g)].map(m => [m[1], Number(m[2])]));
  const ctl = readFileSync(new URL('../server/vbot_app_control.py', import.meta.url), 'utf8');
  const ctlCaps = Object.fromEntries([...ctl.slice(ctl.indexOf('DRIVE_MAX = {'), ctl.indexOf('}', ctl.indexOf('DRIVE_MAX = {'))).matchAll(/'(\w+)': ([0-9.]+)/g)].map(m => [m[1], Number(m[2])]));
  assert.deepEqual(caps, ctlCaps);
  assert.deepEqual(Object.keys(caps), ['vx', 'vy', 'wz']);
});

test('drive: the pad wires every release path and holds nothing on its own', () => {
  const source = readFileSync(join(APP_SRC, 'components/DrivePad.tsx'), 'utf8');
  for (const needed of ['onPointerUp', 'onPointerCancel', 'onPointerLeave', 'onLostPointerCapture', 'onKeyUp', 'onBlur', "'blur'", "'pagehide'",
    "'visibilitychange'", "document.visibilityState === 'visible'", 'removeEventListener', 'setPointerCapture', 'onContextMenu', 'runDrive(']) {
    assert.ok(source.includes(needed), `DrivePad must handle ${needed}`);
  }
  assert.doesNotMatch(source, /setInterval|setTimeout|requestAnimationFrame/); // only runDrive's loop paces frames
  const loop = readFileSync(join(APP_SRC, 'domain/drive.ts'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(loop, /setInterval|fetch\(|WebSocket/);
  assert.match(loop, /finally\s*\{\s*if \(started\)[^}]*await stop\(\)/s); // the stop is in a finally, so no path skips it
});
