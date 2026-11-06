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
  assert.equal(shows.length, 2);
  const moods = shows.find(show => show.id === 'canned-mood-swing');
  assert.equal(moods.cues.every(cue => cue.type === 'face'), true);
  assert.equal(score.admitScore(moods, caps()).ok, true);
  const mischief = shows.find(show => show.id === 'canned-midnight-mischief');
  assert.equal(score.admitScore(mischief, caps()).ok, false);
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
