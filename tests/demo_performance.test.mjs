import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
function load(preview) {
  const source=readFileSync(new URL('../src/demoPerformance.ts',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const exports={};vm.runInNewContext(code,{exports,Date,crypto:{randomUUID:()=> 'a'.repeat(32)},require:()=>({vbotRequest:preview})});return exports;
}
const target='vbot@demo.invalid';
const grant=()=>({target,space:true,stop:true,checkedAt:Date.now()});
const plan={performancePreview:{target,allRehearsed:true}};
const readyControl=(start)=>({status:{target,armed:false,busy:false},offline:false,pending:false,startPerformance:start});
test('visitor Start launches a standalone performance with no account or game',async()=>{
  const requests=[]; const api=load(async(...args)=>{requests.push(args);return plan;});
  let payload;const control=readyControl(async value=>{payload=value;return {armed:true,sessionKind:'performance'};});
  await api.createDemoStarter()(grant(),()=>control);
  assert.equal(requests.length,1);assert.equal(requests[0][0],'performance/preview');
  assert.equal(payload.target,target);assert.equal(payload.gameId,undefined);
  assert.equal(payload.confirmSafeWorkspace,true);assert.equal(payload.confirmHandsetStop,true);
  assert.equal(payload.requestId,'a'.repeat(32));
});
test('missing, expired or mismatched host confirmation cannot issue any request',async()=>{
  let calls=0;const api=load(async()=>{calls++;return plan;});
  for(const value of [{...grant(),space:false},{...grant(),stop:false},{...grant(),target:'other'}, {...grant(),checkedAt:Date.now()-16*60*1000}]) {
    await assert.rejects(api.createDemoStarter()(value,()=>readyControl(async()=>{})));
  }
  assert.equal(calls,0);
});
test('changing the dog while preview loads refuses to start',async()=>{
  let current;let starts=0;const control=readyControl(async()=>{starts++;});current=control;
  const api=load(async()=>{current={...control,status:{...control.status,target:'other'}};return plan;});
  await assert.rejects(api.createDemoStarter()(grant(),()=>current));assert.equal(starts,0);
});
test('double clicks cannot start parallel shows',async()=>{
  let resolvePreview;const api=load(()=>new Promise(resolve=>{resolvePreview=resolve;}));
  let starts=0;const control=readyControl(async()=>{starts++;return {armed:true,sessionKind:'performance'};});
  const start=api.createDemoStarter();const first=start(grant(),()=>control);
  await assert.rejects(start(grant(),()=>control),/already starting/);
  resolvePreview(plan);await first;assert.equal(starts,1);
});
test('unknown start outcome is reported once and is never automatically retried',async()=>{
  const api=load(async()=>plan);let starts=0;
  await assert.rejects(api.createDemoStarter()(grant(),()=>readyControl(async()=>{starts++;return undefined;})),/did not confirm/);
  assert.equal(starts,1);
});
test('busy robots and missing rehearsal evidence cannot start',async()=>{
  const control=readyControl(async()=>assert.fail('must not send movement'));
  const api=load(async()=>({performancePreview:{target,allRehearsed:false}}));
  await assert.rejects(api.createDemoStarter()(grant(),()=>control),/rehearsal profile/);
  await assert.rejects(api.createDemoStarter()(grant(),()=>({...control,status:{...control.status,armed:true}})));
});
