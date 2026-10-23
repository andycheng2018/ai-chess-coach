import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function load(fetch) {
  const source=readFileSync(new URL('../src/vbotDemo.ts',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const exports={};let warnings=0;
  vm.runInNewContext(compiled,{exports,fetch,AbortSignal,console:{warn:()=>warnings++},require:()=>({CONTROL_URL:'http://127.0.0.1:8765'})});
  return {notify:exports.notifyVbotMove,warnings:()=>warnings};
}
const record={recordId:'engine-1',gameId:'AbCd1234',playerColor:'white',classification:'good'};
test('live accepted result sends only a server identity, never a client verdict',async()=>{
  const calls=[];const {notify}=load(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);return {ok:true};});
  await notify(record,'AbCd1234','white');
  assert.deepEqual(calls,[['http://127.0.0.1:8765/api/vbot/celebrate',{recordId:'engine-1',gameId:'AbCd1234',playerColor:'white'}]]);
});
test('another game, opponent, and imported records cannot notify the robot',async()=>{
  let calls=0;const {notify}=load(async()=>{calls++;return {ok:true};});
  await notify(record,'Other123','white');await notify(record,'AbCd1234','black');
  await notify({...record,recordId:undefined},'AbCd1234','white');await notify(record,'','white');
  assert.equal(calls,0);
});
test('failed transport is nonfatal and never automatically retried',async()=>{
  let calls=0;const {notify,warnings}=load(async()=>{calls++;throw Error('offline');});
  await notify(record,'AbCd1234','white');assert.equal(calls,1);assert.equal(warnings(),1);
});
