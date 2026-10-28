import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const compiled=ts.transpileModule(readFileSync(new URL('../src/senseRecovery.ts',import.meta.url),'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText;
const exports={};
vm.runInNewContext(compiled,{exports});
const check=exports.requireSenseTrainingGame;

test('existing-game recovery requires the exact active training game',()=>{
  const game={gameId:'AbCd1234',opponent:{username:'CoachBot'}};
  assert.equal(check('AbCd1234','coachbot',[game]),game);
});

test('another game or human opponent cannot activate physical training mode',()=>{
  for(const games of [[],[{gameId:'Other123',opponent:{username:'CoachBot'}}],
    [{gameId:'AbCd1234',opponent:{username:'HumanPlayer'}}]]){
    assert.throws(()=>check('AbCd1234','CoachBot',games),/did not confirm/);
  }
});

test('missing identity and malformed public game IDs fail closed',()=>{
  for(const id of ['','AbCd1234abcd','../game','https://other.example/AbCd1234']){
    assert.throws(()=>check(id,'CoachBot',[]),/verified training game/);
  }
  assert.throws(()=>check('AbCd1234','',[]),/verified training game/);
});

test('incomplete account snapshots do not establish a recovery match',()=>{
  for(const game of [null,{}, {gameId:'AbCd1234'}, {gameId:'AbCd1234',opponent:{}}, {gameId:'AbCd1234',opponent:{username:42}}]){
    assert.throws(()=>check('AbCd1234','CoachBot',[game]),/did not confirm/);
  }
});
