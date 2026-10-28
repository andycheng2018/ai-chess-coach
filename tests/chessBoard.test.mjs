import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { createElement, Fragment } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const compiled = ts.transpileModule(readFileSync(new URL('../src/components/ChessBoard.tsx', import.meta.url),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX},
}).outputText;
const exports = {};
vm.runInNewContext(compiled,{exports,require});

test('simultaneous game and analysis boards own distinct SVG arrow definitions', () => {
  const props={fen:'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',orientation:'white',
    destinations:new Map(),coachArrows:[{from:'e2',to:'e4',kind:'best'}],coachHighlights:[],rollbackSignal:0,onMove:()=>{}};
  const html=renderToStaticMarkup(createElement(Fragment,null,
    createElement(exports.ChessBoard,props),createElement(exports.ChessBoard,{...props,orientation:'black'})));
  const ids=Array.from(html.matchAll(/<marker id="([^"]+)"/g),match=>match[1]);
  assert.equal(ids.length,8);
  assert.equal(new Set(ids).size,8);
  const targets=Array.from(html.matchAll(/marker-end="url\(#([^)]+)\)"/g),match=>match[1]);
  assert.equal(targets.length,2);
  assert.notEqual(targets[0],targets[1]);
  assert.ok(targets.every(id=>ids.includes(id)));
});
