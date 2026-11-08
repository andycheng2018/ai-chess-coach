// The Android bridge under the same adapter. No device, network or robot.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadApp } from './vbotAppLoader.mjs';

const { LocalFaceTransport } = loadApp('transport/localFace.ts');
const { nativeFetcher, NATIVE_CONTROLLER_DOWN } = loadApp('transport/nativeFetch.ts');

const snapshot = connection => ({ connection, detail: null, device: null, sessionId: null, leaseGeneration: 0, run: null, events: [], supportedFaces: null, capabilities: {} });
const envelope = { commandId: 'a'.repeat(32) };

function adapter(call) {
  return new LocalFaceTransport({ fetcher: nativeFetcher(call), downMessage: NATIVE_CONTROLLER_DOWN });
}

test('routes reach the plugin by name, with the JSON body unchanged', async () => {
  const calls = [];
  const transport = adapter(async request => { calls.push(request); return { status: 200, body: snapshot('connected') }; });
  await transport.status();
  await transport.connect({ target: '192.168.1.5' });
  await transport.disconnect();
  await transport.cancelFutureCues('c'.repeat(32));
  assert.deepEqual(calls.map(call => call.path), ['status', 'connect', 'disconnect', 'cancel']);
  assert.equal(calls[0].body, '');
  assert.deepEqual(JSON.parse(calls[1].body), { target: '192.168.1.5' });
  assert.deepEqual(JSON.parse(calls[3].body), { commandId: 'c'.repeat(32) });
});

test('a plugin failure names the app, not the computer controller', async () => {
  const transport = adapter(async () => { throw new Error('no answer'); });
  const current = await transport.status();
  assert.equal(current.connection, 'unavailable');
  assert.equal(current.detail, NATIVE_CONTROLLER_DOWN);
  assert.doesNotMatch(current.detail, /npm/);
});

test('a non-2xx reply is not treated as a status', async () => {
  const transport = adapter(async () => ({ status: 404, body: { message: 'Unknown route.' } }));
  assert.equal((await transport.connect({ target: 'x' })).connection, 'unavailable');
});

test('a lost submit is unknown, happens once, and is never resent', async () => {
  let calls = 0;
  const transport = adapter(async () => { calls += 1; throw new Error('lost'); });
  const receipt = await transport.submit(envelope);
  assert.equal(receipt.state, 'unknown');
  assert.equal(calls, 1);
});

test('a refused submit keeps its reason from the controller', async () => {
  const transport = adapter(async () => ({ status: 200, body: { commandId: envelope.commandId, state: 'rejected', code: 'capability_unavailable', reason: 'Face only.', duplicate: false } }));
  const receipt = await transport.submit(envelope);
  assert.equal(receipt.state, 'rejected');
  assert.equal(receipt.reason, 'Face only.');
});

test('a failed Stop reports that future cues may still run', async () => {
  const transport = adapter(async () => { throw new Error('lost'); });
  const current = await transport.cancelFutureCues('c'.repeat(32));
  assert.match(current.detail, /may still run/);
});

test('a plugin call that never answers is abandoned at the signal deadline', async () => {
  const fetcher = nativeFetcher(() => new Promise(() => {}));
  // AbortSignal.timeout uses an unreferenced timer in Node, so it may not keep
  // the test process alive long enough to deliver the signal.
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(), 20);
  try {
    await assert.rejects(fetcher('/api/app/status', { signal: deadline.signal }), /aborted/);
  } finally {
    clearTimeout(timer);
  }
  const stopped = new AbortController();
  stopped.abort();
  await assert.rejects(fetcher('/api/app/status', { signal: stopped.signal }), /aborted/);
});
