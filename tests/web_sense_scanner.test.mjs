import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const compiled = ts.transpileModule(readFileSync(new URL('../src/webSenseScanner.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function fixture(startup = async () => {}, cameras = [{id:'front',label:'Front'}, {id:'rear',label:'Back camera'}], getCameras) {
  const nodes = new Map();
  for (const selector of ['select', '[role="status"]', '#sense-camera-start', '#sense-camera-cancel']) {
    nodes.set(selector, { hidden: false, disabled: false, textContent: '', length: 0, appendChild() { this.length++; } });
  }
  const dialog = {
    querySelector: selector => nodes.get(selector), setAttribute() {}, addEventListener() {},
    showModal() { this.open = true; }, close() { this.open = false; }, remove() { this.removed = true; },
  };
  let permissions = 0;
  let scanner;
  class Scanner {
    isScanning = false;
    stops = 0;
    constructor() { scanner = this; }
    static async getCameras() { permissions++; return getCameras ? getCameras() : cameras; }
    async start(id, config, decoded) { this.cameraId = id; this.decoded = decoded; await startup(); this.isScanning = true; }
    async stop() { this.stops++; this.isScanning = false; }
  }
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, require: () => ({Html5Qrcode: Scanner, Html5QrcodeSupportedFormats: {QR_CODE:0}}),
    navigator: {mediaDevices:{getUserMedia() {}}},
    document: { createElement: tag => tag === 'dialog' ? dialog : {}, body: {appendChild() {}} },
  });
  return { scan: exports.scanWebSenseRoom, dialog, nodes,
    get scanner() { return scanner; }, get permissions() { return permissions; } };
}

test('opening or cancelling the scanner does not request camera access', async () => {
  const camera = fixture();
  const result = camera.scan();
  const rejected = assert.rejects(result, /Scan cancelled/);
  assert.equal(camera.dialog.open, true);
  assert.equal(camera.permissions, 0);
  camera.nodes.get('#sense-camera-cancel').onclick();
  await rejected;
  assert.equal(camera.dialog.removed, true);
});

test('camera-start errors leave the overlay open so camera access can be retried', async () => {
  let attempts = 0;
  const camera = fixture(async () => { if (attempts++ === 0) throw new Error('Camera busy'); });
  const result = camera.scan();
  await camera.nodes.get('#sense-camera-start').onclick();
  assert.equal(camera.dialog.open, true);
  assert.match(camera.nodes.get('[role="status"]').textContent, /Camera busy.*choose another camera/i);
  assert.equal(camera.nodes.get('#sense-camera-start').hidden, false);
  assert.equal(camera.nodes.get('#sense-camera-start').disabled, false);
  assert.equal(camera.nodes.get('#sense-camera-start').textContent, 'Retry camera');
  await camera.nodes.get('#sense-camera-start').onclick();
  camera.scanner.decoded('https://lichess.org/AbCd1234?color=black');
  assert.equal(await result, 'https://lichess.org/AbCd1234?color=black');
  assert.equal(camera.dialog.removed, true);
});

test('camera enumeration errors leave an enabled retry action', async () => {
  let attempts = 0;
  const camera = fixture(async () => {}, undefined, async () => {
    if (attempts++ === 0) throw new Error('Permission prompt dismissed');
    return [{id:'rear',label:'Back camera'}];
  });
  const result = camera.scan();
  await camera.nodes.get('#sense-camera-start').onclick();
  assert.equal(camera.dialog.open, true);
  assert.match(camera.nodes.get('[role="status"]').textContent, /Permission prompt dismissed.*retry/i);
  assert.equal(camera.nodes.get('#sense-camera-start').disabled, false);
  await camera.nodes.get('#sense-camera-start').onclick();
  camera.scanner.decoded('https://lichess.org/AbCd1234?color=white');
  assert.equal(await result, 'https://lichess.org/AbCd1234?color=white');
  assert.equal(camera.dialog.removed, true);
});

test('QR decode closes the camera and returns the room link', async () => {
  const camera = fixture();
  const result = camera.scan();
  await camera.nodes.get('#sense-camera-start').onclick();
  assert.equal(camera.scanner.cameraId, 'rear');
  camera.scanner.decoded('https://lichess.org/AbCd1234?color=black');
  assert.equal(await result, 'https://lichess.org/AbCd1234?color=black');
  assert.equal(camera.scanner.stops, 1);
  assert.equal(camera.scanner.isScanning, false);
});

test('cancelling during camera startup still releases the eventual camera stream', async () => {
  let finishStartup;
  let signalStarted;
  const hasStarted = new Promise(resolve => { signalStarted = resolve; });
  const camera = fixture(() => new Promise(resolve => { finishStartup = resolve; signalStarted(); }));
  const result = camera.scan();
  const rejected = assert.rejects(result, /Scan cancelled/);
  const starting = camera.nodes.get('#sense-camera-start').onclick();
  await hasStarted;
  camera.nodes.get('#sense-camera-cancel').onclick();
  finishStartup();
  await starting; await rejected;
  assert.equal(camera.scanner.isScanning, false);
  assert.equal(camera.scanner.stops, 1);
  assert.equal(camera.dialog.removed, true);
});
