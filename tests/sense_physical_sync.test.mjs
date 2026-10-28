import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=readFileSync(new URL('../src/sensePhysicalSync.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const exports={};vm.runInNewContext(code,{exports});
const {canConfirmPhysicalExchange,physicalWitnessMatches}=exports;
test('a human move plus subsequent bot reply is required for either player color',()=>{
 assert.equal(canConfirmPhysicalExchange('','white'),false);
 assert.equal(canConfirmPhysicalExchange('e2e4','white'),false);
 assert.equal(canConfirmPhysicalExchange('e2e4 e7e5','white'),true);
 assert.equal(canConfirmPhysicalExchange('e2e4 e7e5','black'),false);
 assert.equal(canConfirmPhysicalExchange('e2e4 e7e5 g1f3','black'),true);
});
test('move histories alone cannot confirm physical synchronization without a person witness',()=>{
 assert.equal(physicalWitnessMatches(null,'xYDhW2TU','ZachZhang','e2e4 e7e5'),false);
});
test('confirmation follows only the witnessed game/account/branch and survives later extensions',()=>{
 const w={gameId:'xYDhW2TU',username:'ZachZhang',moves:['e2e4','e7e5']};
 assert.equal(physicalWitnessMatches(w,'xYDhW2TU','zachzhang','e2e4 e7e5 g1f3 b8c6'),true);
 assert.equal(physicalWitnessMatches(w,'4TKUBiH1','ZachZhang','e2e4 e7e5'),false);
 assert.equal(physicalWitnessMatches(w,'xYDhW2TU','SecondAccount222','e2e4 e7e5'),false);
 assert.equal(physicalWitnessMatches(w,'xYDhW2TU','ZachZhang','e2e4'),false);
 assert.equal(physicalWitnessMatches(w,'xYDhW2TU','ZachZhang','e2e4 c7c5'),false);
});
