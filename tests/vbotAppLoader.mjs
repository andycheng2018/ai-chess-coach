// Loads VBOT app TypeScript modules into a sandbox. No browser, network or robot.
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

export const APP_SRC = fileURLToPath(new URL('../vbot-app/src/', import.meta.url));

export function loadApp(relative, globals = {}) {
  const cache = new Map();
  const context = { crypto: globalThis.crypto, Date, JSON, Math, AbortSignal, setTimeout, clearTimeout, setInterval, clearInterval, ...globals };
  function load(path) {
    if (cache.has(path)) return cache.get(path).exports;
    const module = { exports: {} };
    cache.set(path, module);
    const source = readFileSync(path, 'utf8');
    if (path.endsWith('.json')) {
      module.exports = JSON.parse(source);
      return module.exports;
    }
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    const require = name => {
      if (!name.startsWith('.')) throw new Error(`Unexpected dependency in a pure module: ${name}`);
      const base = join(dirname(path), name);
      const found = [base, `${base}.ts`, `${base}.tsx`].find(candidate => existsSync(candidate) && !candidate.endsWith('/'));
      if (!found) throw new Error(`Cannot resolve ${name} from ${path}`);
      return load(found);
    };
    vm.runInNewContext(`(function (exports, require, module) {${code}\n})`, context)(module.exports, require, module);
    return module.exports;
  }
  return load(join(APP_SRC, relative));
}

export const memoryStore = (initial = {}) => {
  const data = new Map(Object.entries(initial));
  return { data, getItem: key => data.has(key) ? data.get(key) : null, setItem: (key, value) => { data.set(key, value); } };
};

/** Round-trips through JSON so sandbox objects compare cleanly with assert.deepEqual. */
export const plain = value => JSON.parse(JSON.stringify(value));

export const validScore = (overrides = {}) => ({
  schemaVersion: 1, id: 'show-1', title: 'Test show', notes: '', origin: 'custom', revision: 1, repeat: 1, createdAt: 1, updatedAt: 1,
  cues: [{ id: 'a', type: 'face', assetId: 86, durationMs: 4500 }, { id: 'b', type: 'wait', durationMs: 1000 }],
  ...overrides,
});
