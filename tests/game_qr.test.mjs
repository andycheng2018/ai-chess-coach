import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=readFileSync(new URL('../src/gameQr.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const exports={};vm.runInNewContext(compiled,{exports});
const {gameQrLink}=exports;
test('QR preserves actual player color for either side and contains only the public game ID',()=>{
  assert.equal(gameQrLink('bWbJuQWD','white'),'https://lichess.org/bWbJuQWD/white');
  assert.equal(gameQrLink('bWbJuQWD','black'),'https://lichess.org/bWbJuQWD/black');
});
test('private seat IDs, injected URLs, missing games and ambiguous colors cannot become game QRs',()=>{
  for(const id of ['', 'AbCd1234seat', 'https://lichess.org/AbCd1234', 'AbCd1234\n', '../x1234']) {
    assert.throws(()=>gameQrLink(id,'white'));
  }
  for(const color of ['random', '', 'WHITE', 'black&token=secret']) assert.throws(()=>gameQrLink('AbCd1234',color));
});
