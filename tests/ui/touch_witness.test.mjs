// Touch witness: loads the real built app on Android-sized touch screens and proves
// a person can tap their way out of anything that opens at launch.
//
// Born from the demo where the visitor welcome popup ignored every tap on Android.
// Invariants, checked for every scenario below:
//   1. Every visible, enabled button in an open modal receives a tap at its centre
//      (nothing covers it, it is not inert, and it has pointer events).
//   2. A launch modal never shows a disabled primary button when nothing on screen can enable it
//      (the "big green button that never works" dead end).
//   3. Every launch modal can be dismissed with a real touch, and then the home screen
//      responds to touch (Capture Practice opens and closes).
//
// Run: npm run test:ui   (builds the app twice: popup off as shipped, and popup on)
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createReadStream, existsSync, mkdtempSync, rmSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { extname, join, normalize } from 'node:path';
import { after, before, describe, test } from 'node:test';
import { chromium, devices } from 'playwright';

const ROOT = new URL('../..', import.meta.url).pathname;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.wasm': 'application/wasm', '.mp3': 'audio/mpeg' };
const ANDROID_UA = 'Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const SCREENS = {
  'Android phone': { ...devices['Pixel 7'] },
  'Android tablet landscape': { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5, isMobile: true, hasTouch: true, userAgent: ANDROID_UA },
};
// The dog's status comes from the real Python controller (server/vbot_demo.py), never a
// hand-written fake, so this witness breaks if the backend and the UI drift apart.
const PYTHON = process.env.WITNESS_PYTHON || (existsSync(join(ROOT, '.venv/bin/python')) ? join(ROOT, '.venv/bin/python') : 'python3');
function realDogStatus() {
  const script = 'import json\nfrom unittest.mock import Mock\nfrom vbot_demo import VbotDemo\n'
    + "demo = VbotDemo(verification={}, sender=Mock(), checker=Mock())\ndemo.target = 'vbot@witness.invalid'\nprint(json.dumps(demo.status()))";
  return execFileSync(PYTHON, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONPATH: join(ROOT, 'server') }, encoding: 'utf8' });
}
let dogStatus;
// What the app's backend says at launch. "offline" is a phone with no coach server at all.
const BACKENDS = {
  offline: async route => route.abort('connectionrefused'),
  'dog connected': async route => route.request().url().includes('/api/vbot/status')
    ? route.fulfill({ status: 200, contentType: 'application/json', body: dogStatus })
    : route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"witness"}' }),
};

const work = mkdtempSync(join(tmpdir(), 'touch-witness-'));
const builds = { 'popup off (as shipped)': join(work, 'off'), 'popup on': join(work, 'on') };
let browser;
const servers = [];

function build(outDir, popup) {
  execFileSync(process.execPath, [join(ROOT, 'node_modules/vite/bin/vite.js'), 'build', '--outDir', outDir, '--emptyOutDir', '--logLevel', 'error'],
    { cwd: ROOT, stdio: 'inherit', env: { ...process.env, VITE_DEMO_WELCOME: popup ? 'on' : 'off' } });
}
function serve(dir) {
  return new Promise(resolve => {
    const server = createServer((req, res) => {
      const path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
      let file = join(dir, path);
      if (!existsSync(file) || statSync(file).isDirectory()) file = join(dir, 'index.html');
      res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' });
      createReadStream(file).pipe(res);
    }).listen(0, '127.0.0.1', () => resolve({ server, url: `http://127.0.0.1:${server.address().port}/` }));
    servers.push(server);
  });
}

/** Every open modal: native <dialog> in the top layer, or an aria-modal overlay. */
async function openModals(page) {
  return page.evaluate(() => [...document.querySelectorAll('dialog[open], [role="dialog"][aria-modal="true"]')]
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; })
    .map((el, i) => { el.dataset.witness = String(i); return { id: String(i), name: el.getAttribute('aria-label') || el.querySelector('h1,h2')?.textContent?.trim() || el.className }; }));
}

/** Invariant 1: each visible enabled button in the modal gets the tap. Returns the offenders. */
async function untappableButtons(page, modalId) {
  const buttons = page.locator(`[data-witness="${modalId}"] button:not([disabled])`);
  const offenders = [];
  for (let i = 0; i < await buttons.count(); i++) {
    const button = buttons.nth(i);
    if (!await button.isVisible()) continue; // e.g. inside a closed <details>
    await button.scrollIntoViewIfNeeded();
    const verdict = await button.evaluate(el => {
      const r = el.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return 'off screen';
      if (el.closest('[inert]')) return 'inert';
      if (getComputedStyle(el).pointerEvents === 'none') return 'pointer-events: none';
      const hit = document.elementFromPoint(x, y);
      return hit && (hit === el || el.contains(hit)) ? '' : `covered by <${hit?.tagName.toLowerCase()} class="${hit?.className}">`;
    });
    if (verdict) offenders.push(`"${(await button.innerText()).trim() || await button.getAttribute('aria-label')}": ${verdict}`);
  }
  return offenders;
}

/** Invariant 2: a disabled primary button needs something enabled on screen that could turn it on. */
async function deadPrimary(page, modalId) {
  return page.evaluate(id => {
    const modal = document.querySelector(`[data-witness="${id}"]`);
    const dead = [...modal.querySelectorAll('button.primary:disabled')];
    if (!dead.length) return '';
    const enablers = [...modal.querySelectorAll('input:not([disabled]), select:not([disabled]), textarea:not([disabled])')];
    return enablers.length ? '' : dead.map(b => b.textContent.trim()).join(', ');
  }, modalId);
}

/** Invariant 3: dismiss with a real touch at the control's centre. */
async function dismissByTouch(page, modalId) {
  const modal = page.locator(`[data-witness="${modalId}"]`);
  const candidates = [
    modal.locator('button[aria-label^="Close" i]:not([disabled])'),
    modal.getByRole('button', { name: /^(✕|close|cancel|not now|continue|explore)/i }),
  ];
  for (const candidate of candidates) {
    const control = candidate.first();
    if (!await control.count() || !await control.isVisible() || await control.isDisabled()) continue;
    await control.scrollIntoViewIfNeeded();
    const box = await control.boundingBox();
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForFunction(id => !document.querySelector(`[data-witness="${id}"]`)?.matches('dialog[open], [role="dialog"][aria-modal="true"]'), modalId, { timeout: 3000 });
    return;
  }
  assert.fail('no enabled close/continue control a person could tap');
}

async function tapByText(page, text) {
  const target = page.getByRole('button', { name: text }).first();
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
}

before(async () => {
  dogStatus = realDogStatus();
  build(builds['popup off (as shipped)'], false);
  build(builds['popup on'], true);
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  for (const server of servers) server.close();
  rmSync(work, { recursive: true, force: true });
});

for (const [buildName, dir] of Object.entries(builds)) {
  describe(buildName, () => {
    let site;
    before(async () => { site = await serve(dir); });
    for (const [screenName, device] of Object.entries(SCREENS)) {
      for (const [backendName, backend] of Object.entries(BACKENDS)) {
        test(`${screenName}, backend ${backendName}: launch is fully touchable`, async () => {
          const context = await browser.newContext(device);
          const page = await context.newPage();
          const errors = [];
          page.on('pageerror', error => errors.push(error.message));
          // Nothing leaves the machine: the app's backend is faked, everything external is refused.
          await page.route('**/*', route => {
            const url = route.request().url();
            if (url.startsWith(site.url)) return route.continue();
            if (url.includes('/api/')) return backend(route);
            return route.abort('blockedbyclient');
          });
          try {
            await page.goto(site.url);
            await page.getByRole('button', { name: /Capture Practice/ }).first().waitFor({ state: 'attached', timeout: 15000 });
            await page.waitForTimeout(2500); // let launch polling (robot status every 2s) settle

            const seen = [];
            for (let round = 0; round < 5; round++) {
              const modals = await openModals(page);
              if (!modals.length) break;
              const top = modals.at(-1);
              seen.push(top.name);
              const covered = [];
              for (const modal of modals) covered.push(...(await untappableButtons(page, modal.id)).map(o => `${modal.name}: ${o}`));
              assert.deepEqual(covered, [], `buttons a person cannot tap at launch:\n  ${covered.join('\n  ')}`);
              const dead = await deadPrimary(page, top.id);
              assert.equal(dead, '', `"${top.name}" shows a disabled primary button with nothing on screen to enable it: ${dead}`);
              await dismissByTouch(page, top.id);
            }
            assert.deepEqual(await openModals(page), [], `modals still open after 5 dismissals: ${seen.join(', ')}`);
            if (buildName === 'popup on') assert.ok(seen.some(name => /Your move/.test(name)), 'the welcome popup should open at launch in this build');

            // Home responds to touch: open Capture Practice and close it again with taps.
            await tapByText(page, /Capture Practice/);
            const practice = page.locator('dialog.capture-practice-dialog[open]');
            await practice.waitFor({ timeout: 3000 });
            const close = practice.locator('button[aria-label="Close Capture Practice"]');
            const box = await close.boundingBox();
            await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
            await practice.waitFor({ state: 'detached', timeout: 3000 });
            assert.deepEqual(errors, [], 'uncaught page errors during launch');
          } catch (error) {
            const shot = join(ROOT, `touch-witness-failure-${buildName}-${screenName}-${backendName}.png`.replace(/[^\w.-]+/g, '-'));
            await page.screenshot({ path: shot }).catch(() => {});
            error.message += `\n(screenshot: ${shot})`;
            throw error;
          } finally {
            await context.close();
          }
        });
      }
    }
  });
}
