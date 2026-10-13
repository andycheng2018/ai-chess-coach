import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=readFileSync(new URL('../src/coach.ts',import.meta.url),'utf8').replace('import.meta.env.VITE_BOT_CONTROL_URL',"'http://test'");
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function environment() {
  const requests=[];const exports={};
  vm.runInNewContext(compiled,{exports,fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body),signal:options.signal});return {ok:true,json:async()=>({recordId:'record-1',openingEco:'C60',openingName:'Ruy Lopez'})};}});
  return {coach:exports,requests};
}
test('coaching request carries both journal game identity and opening move history',async()=>{
  const {coach,requests}=environment();const signal=new AbortController().signal;
  const moves=['e2e4','e7e5','g1f3','b8c6','f1b5'];
  const result=await coach.analyzeMove('position-before-Bb5','f1b5','balanced',signal,'en','game-1',moves);
  assert.equal(requests[0].url,'http://test/api/coach/analyze');
  assert.equal(requests[0].body.gameId,'game-1');assert.deepEqual(requests[0].body.moves,moves);assert.equal(requests[0].signal,signal);
  assert.equal(result.recordId,'record-1');assert.equal(result.openingEco,'C60');
});
test('existing game-id callers remain valid without an opening history',async()=>{
  const {coach,requests}=environment();await coach.analyzeMove('fen','e2e4','quick',undefined,'en','game-2');
  assert.equal(requests[0].body.gameId,'game-2');assert.deepEqual(requests[0].body.moves,[]);
});
