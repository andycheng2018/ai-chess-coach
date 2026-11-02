import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadApp, memoryStore, validScore } from './vbotAppLoader.mjs';

const { FakeTransport } = loadApp('transport/fake.ts');
const { LocalFaceTransport } = loadApp('transport/localFace.ts');
const { CloudTransport } = loadApp('transport/cloud.ts');
const { makeEnvelope } = loadApp('domain/commands.ts');

/** A manual clock and scheduler make every simulated timing deterministic. */
function harness(store = memoryStore()) {
  const clock = { now: 1000, timers: [] };
  const transport = new FakeTransport({
    store, now: () => clock.now,
    schedule(callback, ms) {
      const timer = { at: clock.now + ms, callback, active: true };
      clock.timers.push(timer);
      return () => { timer.active = false; };
    },
    sessionId: () => `session-${clock.now}`,
  });
  const advance = ms => {
    const until = clock.now + ms;
    for (;;) {
      const next = clock.timers.filter(timer => timer.active && timer.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!next) break;
      clock.now = next.at;
      next.active = false;
      next.callback();
    }
    clock.now = until;
  };
  return { clock, transport, advance, store };
}

async function connected(store) {
  const h = harness(store);
  h.snapshot = await h.transport.connect({});
  h.envelope = (score = validScore(), snapshot = h.snapshot) => makeEnvelope(score, snapshot, h.clock.now);
  return h;
}

test('a show runs in order to completion and hands the screen back', async () => {
  const h = await connected();
  const receipt = await h.transport.submit(h.envelope());
  assert.equal(receipt.state, 'accepted');
  let run = (await h.transport.status()).run;
  assert.equal(run.state, 'running');
  assert.equal(run.cueIndex, 0);
  assert.equal(run.cueAck, 'started');
  h.advance(4500);
  run = (await h.transport.status()).run;
  assert.equal(run.cueIndex, 1);
  assert.equal(run.cueAck, 'waiting');
  h.advance(1000);
  run = (await h.transport.status()).run;
  assert.equal(run.state, 'completed');
  assert.equal(run.completedCues, 2);
  assert.equal(run.cleanup, 'released');
});

test('a duplicate submit returns the recorded state and starts nothing new', async () => {
  const h = await connected();
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  h.advance(100);
  const before = (await h.transport.status()).run.startedAt;
  const again = await h.transport.submit(envelope);
  assert.equal(again.duplicate, true);
  assert.equal(again.state, 'running');
  assert.equal((await h.transport.status()).run.startedAt, before);
});

test('reusing a command ID for a different show is refused', async () => {
  const h = await connected();
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  const conflict = await h.transport.submit({ ...envelope, score: validScore({ title: 'Other' }) });
  assert.equal(conflict.code, 'identity_conflict');
});

test('an expired command is rejected and never runs', async () => {
  const h = await connected();
  const envelope = h.envelope();
  h.clock.now = envelope.expiresAt;
  const receipt = await h.transport.submit(envelope);
  assert.equal(receipt.code, 'expired');
  assert.equal((await h.transport.status()).run, null);
});

test('a command from an earlier connection is rejected after reconnect', async () => {
  const h = await connected();
  const stale = h.envelope();
  await h.transport.disconnect();
  h.clock.now += 1;
  await h.transport.connect({});
  const receipt = await h.transport.submit(stale);
  assert.equal(receipt.code, 'stale_lease');
  assert.equal((await h.transport.status()).run, null);
});

test('a command for another dog is rejected', async () => {
  const h = await connected();
  assert.equal((await h.transport.submit({ ...h.envelope(), deviceId: 'other-dog' })).code, 'wrong_device');
});

test('submit while disconnected is rejected', async () => {
  const h = await connected();
  const envelope = h.envelope();
  await h.transport.disconnect();
  assert.equal((await h.transport.submit(envelope)).code, 'not_connected');
});

test('an invalid score is rejected at the transport too', async () => {
  const h = await connected();
  const receipt = await h.transport.submit({ ...h.envelope(), score: validScore({ repeat: 99 }) });
  assert.equal(receipt.code, 'invalid_score');
});

test('a busy controller rejects a second show, whether busy by fault or by a run', async () => {
  const h = await connected();
  await h.transport.submit(h.envelope());
  assert.equal((await h.transport.submit(h.envelope())).code, 'busy');
  const f = await connected();
  f.transport.setFault('busy');
  assert.equal((await f.transport.submit(f.envelope())).code, 'busy');
});

test('a missing capability rejects the show with the real reason', async () => {
  const h = await connected();
  h.transport.setFault('no-motion');
  const body = validScore({ cues: [{ id: 'a', type: 'body', preset: 'actions/WAVE.json' }] });
  const receipt = await h.transport.submit(h.envelope(body));
  assert.equal(receipt.code, 'capability_unavailable');
  assert.match(receipt.reason, /unavailable/);
  assert.equal((await h.transport.submit(h.envelope())).state, 'accepted');
});

test('cancel stops future cues and nothing further plays', async () => {
  const h = await connected();
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  await h.transport.cancelFutureCues(envelope.commandId);
  const run = (await h.transport.status()).run;
  assert.equal(run.state, 'cancelled');
  assert.equal(run.cleanup, 'released');
  h.advance(60000);
  const after = (await h.transport.status()).run;
  assert.equal(after.cueIndex, 0);
  assert.equal(after.completedCues, 0);
});

test('a cancel naming another command does nothing', async () => {
  const h = await connected();
  await h.transport.submit(h.envelope());
  await h.transport.cancelFutureCues('f'.repeat(32));
  assert.equal((await h.transport.status()).run.state, 'running');
});

test('an unknown outcome stops the show and is never retried', async () => {
  const h = await connected();
  h.transport.setFault('unknown-next-cue');
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  const run = (await h.transport.status()).run;
  assert.equal(run.state, 'unknown');
  assert.match(run.reason, /will not be retried/);
  h.transport.setFault('none');
  h.advance(60000);
  assert.equal((await h.transport.status()).run.completedCues, 0);
  assert.equal((await h.transport.submit(envelope)).state, 'unknown');
});

test('a lost connection needs a reconnect, which reconciles and replays nothing', async () => {
  const h = await connected();
  h.transport.setFault('connection-lost');
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  let status = await h.transport.status();
  assert.equal(status.connection, 'lost');
  assert.equal(status.capabilities.face.available, false);
  h.transport.setFault('none');
  await h.transport.connect({});
  h.advance(60000);
  status = await h.transport.status();
  assert.equal(status.connection, 'connected');
  assert.equal(status.run.commandId, envelope.commandId);
  assert.equal(status.run.state, 'unknown');
  assert.equal(status.run.completedCues, 0);
});

test('a failed cleanup is reported rather than hidden', async () => {
  const h = await connected();
  h.transport.setFault('cleanup-fails');
  await h.transport.submit(h.envelope());
  h.advance(5500);
  const status = await h.transport.status();
  assert.equal(status.run.state, 'completed');
  assert.equal(status.run.cleanup, 'failed');
  assert.ok(status.events.some(event => /could not be released/.test(event.message)));
});

test('an unavailable backend says so and does not fake a connection', async () => {
  const h = harness();
  h.transport.setFault('backend-down');
  const snapshot = await h.transport.connect({});
  assert.equal(snapshot.connection, 'unavailable');
  assert.equal(snapshot.device, null);
});

test('a reload during a run marks it unknown and never resumes or replays', async () => {
  const store = memoryStore();
  const h = await connected(store);
  const envelope = h.envelope();
  await h.transport.submit(envelope);
  h.advance(100);
  h.transport.dispose();

  const reloaded = harness(store);
  const status = await reloaded.transport.status();
  assert.equal(status.connection, 'disconnected');
  assert.equal(status.run.state, 'unknown');
  assert.match(status.run.reason, /not resumed or replayed/);
  reloaded.advance(60000);
  assert.equal((await reloaded.transport.status()).run.completedCues, 0);
  assert.equal(reloaded.clock.timers.length, 0);

  // Deduplication survives the restart.
  await reloaded.transport.connect({});
  const again = await reloaded.transport.submit(envelope);
  assert.equal(again.duplicate, true);
  assert.equal(again.state, 'unknown');
});

test('leases keep increasing across a restart', async () => {
  const store = memoryStore();
  const first = await connected(store);
  const lease = first.snapshot.leaseGeneration;
  first.transport.dispose();
  const second = await connected(store);
  assert.ok(second.snapshot.leaseGeneration > lease);
});

test('a running show keeps its snapshot when the saved show is edited', async () => {
  const h = await connected();
  const show = validScore();
  const envelope = h.envelope(show);
  await h.transport.submit(envelope);
  show.title = 'Edited later';
  show.cues[0].durationMs = 500;
  const run = (await h.transport.status()).run;
  assert.equal(run.score.title, 'Test show');
  assert.equal(run.score.cues[0].durationMs, 4500);
});

// --- Local adapter ---------------------------------------------------------

const envelopeFor = () => ({ v: 1, commandId: 'a'.repeat(32), deviceId: 'd', sessionId: 's', leaseGeneration: 1, issuedAt: 1, expiresAt: 2, kind: 'run-score', score: validScore() });
const reply = (body, ok = true) => ({ ok, json: async () => body });

test('local submit: a lost reply is unknown and is sent exactly once', async () => {
  let posts = 0;
  const transport = new LocalFaceTransport({ fetcher: async () => { posts += 1; throw new Error('network'); } });
  const receipt = await transport.submit(envelopeFor());
  assert.equal(receipt.state, 'unknown');
  assert.match(receipt.reason, /won’t be resent/);
  assert.equal(posts, 1);
});

test('local submit: an unreadable or mismatched reply is unknown, not a failure', async () => {
  const unreadable = new LocalFaceTransport({ fetcher: async () => ({ ok: true, json: async () => { throw new Error('bad'); } }) });
  assert.equal((await unreadable.submit(envelopeFor())).state, 'unknown');
  const mismatched = new LocalFaceTransport({ fetcher: async () => reply({ commandId: 'b'.repeat(32), state: 'accepted' }) });
  assert.equal((await mismatched.submit(envelopeFor())).state, 'unknown');
});

test('local submit: the controller’s rejection passes through', async () => {
  const transport = new LocalFaceTransport({ fetcher: async () => reply({ commandId: 'a'.repeat(32), state: 'rejected', code: 'busy', reason: 'Busy', duplicate: false }) });
  const receipt = await transport.submit(envelopeFor());
  assert.equal(receipt.state, 'rejected');
  assert.equal(receipt.code, 'busy');
});

test('local status: polling only reads, and a missing controller explains itself', async () => {
  const calls = [];
  const transport = new LocalFaceTransport({ fetcher: async (url, init) => { calls.push([url, init?.method]); throw new Error('down'); } });
  const snapshot = await transport.status();
  assert.equal(snapshot.connection, 'unavailable');
  assert.match(snapshot.detail, /vbot:controller/);
  assert.equal(snapshot.capabilities.face.available, false);
  assert.deepEqual(calls[0], ['/api/app/status', undefined]);
});

test('local stop: a failed request is reported, never silently dropped', async () => {
  const transport = new LocalFaceTransport({ fetcher: async () => { throw new Error('down'); } });
  const snapshot = await transport.cancelFutureCues('a'.repeat(32));
  assert.equal(snapshot.connection, 'unavailable');
  assert.match(snapshot.detail, /may still run/);
  const refused = new LocalFaceTransport({ fetcher: async () => reply({ message: 'no' }, false) });
  assert.match((await refused.cancelFutureCues('a'.repeat(32))).detail, /may still run/);
});

test('cloud adapter refuses honestly and never claims success', async () => {
  const transport = new CloudTransport();
  assert.equal((await transport.connect()).connection, 'unavailable');
  const receipt = await transport.submit(envelopeFor());
  assert.equal(receipt.state, 'rejected');
  assert.equal(receipt.code, 'backend_unavailable');
  assert.equal((await transport.status()).capabilities.face.available, false);
});
