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
  return {notify:exports.notifyVbotMove,warnings:()=>warnings, ...exports};
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

test('native game lifecycle disarms on finish/switch but waits for initial recovery',()=>{
  const {vbotNeedsDetach}=load(async()=>({ok:true}));
  const state={armed:true,gameId:'AbCd1234'};
  assert.equal(vbotNeedsDetach(state,{gameId:'AbCd1234',resolved:true,ended:false}),false);
  assert.equal(vbotNeedsDetach(state,{gameId:'Other123',resolved:true,ended:false}),true);
  assert.equal(vbotNeedsDetach(state,{gameId:'AbCd1234',resolved:true,ended:true}),true);
  assert.equal(vbotNeedsDetach(state,{gameId:null,resolved:false,ended:false}),false);
});
test('native readiness probe cannot execute a motion or retry after transport failure',async()=>{
  const calls=[];
  const {vbotRequest}=load(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);throw Error('offline');});
  await assert.rejects(vbotRequest('check',{target:'vbot@robot.example'}),/offline/);
  assert.deepEqual(calls,[['http://127.0.0.1:8765/api/vbot/check',{target:'vbot@robot.example'}]]);
});
test('completed gesture and failed postflight remain distinct in the native history',()=>{
  const {vbotEventText}=load(async()=>({ok:true}));
  assert.match(vbotEventText({status:'completed',preset:'atom/look_left.json',readyForNext:false,postflightReason:'Head fault'}),/finished; paused: Head fault/);
  assert.match(vbotEventText({status:'requested',preset:'actions/ROCKYOU.json'}),/awaiting robot result/);
});

test('a stale tab cannot adopt or automatically disarm another game session',()=>{
  const {vbotManagedSession}=load(async()=>({ok:true}));
  const owned={gameId:'AbCd1234',generation:1};
  assert.equal(vbotManagedSession({armed:true,...owned},owned,'Other123'),owned);
  assert.equal(vbotManagedSession({armed:true,gameId:'Other123',generation:2},owned,'AbCd1234'),null);
  assert.equal(vbotManagedSession({armed:true,gameId:'Other123',generation:2},null,'AbCd1234'),null);
  assert.equal(vbotManagedSession({armed:false,...owned},owned,'AbCd1234'),null);
});

test('canonical blunder follows the same identity-only notification path',async()=>{
  const calls=[];const {notify}=load(async(url,options)=>{calls.push(JSON.parse(options.body));return {ok:true};});
  await notify({...record,classification:'blunder'},'AbCd1234','white');
  assert.deepEqual(calls,[{recordId:'engine-1',gameId:'AbCd1234',playerColor:'white'}]);
});
test('sad preview has a readable label and never claims physical completion',()=>{
  const {vbotEventText}=load(async()=>({ok:true}));
  assert.equal(vbotEventText({status:'rehearsed',preset:'actions/GRIEVANCE.json'}),'Preview: Sad reaction; no robot motion');
});


test('expanded gesture names are readable in live requests and completions',()=>{
  const {vbotReactionLabel,vbotEventText}=load(async()=>({ok:true}));
  assert.equal(vbotReactionLabel('actions/HIGH_FIVE_L.json'),'Left high-five');
  assert.equal(vbotReactionLabel('actions/SHAKEHAND.json'),'Handshake');
  assert.equal(vbotEventText({status:'completed',preset:'actions/SAYYES.json'}),'Approving yes completed');
  assert.equal(vbotEventText({status:'requested',preset:'atom/look_up.json'}),'Look up requested; awaiting robot result');
});

test('one explicit enable checks readiness before connecting, without an expiring manual precheck',async()=>{
  const calls=[];
  const {connectVbotWithReadiness}=load(async(url,options)=>{
    calls.push([url.split('/').pop(),JSON.parse(options.body)]);
    return {ok:true,json:async()=>({readinessFresh:true,readiness:{ready:true,target:'vbot@robot.example'},armed:url.endsWith('/connect')})};
  });
  const payload={gameId:'AbCd1234',playerColor:'white',mode:'live',target:'vbot@robot.example',preset:'actions/ROCKYOU.json',applicationVersion:'unknown',confirmSafeWorkspace:true,confirmHandsetStop:true};
  assert.equal((await connectVbotWithReadiness(payload,()=>true)).armed,true);
  assert.deepEqual(calls.map(c=>c[0]),['check','connect']);
  assert.deepEqual(calls[1][1],payload);
});

test('failed readiness or a changed match never arms or retries',async()=>{
  for(const mode of ['failed','changed','transport']) {
    let current=true;const calls=[];
    const {connectVbotWithReadiness}=load(async(url)=>{
      calls.push(url.split('/').pop());
      if(mode==='transport') throw new Error('offline');
      if(mode==='changed') current=false;
      return {ok:true,json:async()=>({readinessFresh:true,readiness:{ready:mode!=='failed',target:'vbot@robot.example',reason:'Not standing'}})};
    });
    await assert.rejects(()=>connectVbotWithReadiness({gameId:'AbCd1234',playerColor:'white',mode:'live',target:'vbot@robot.example',confirmSafeWorkspace:true,confirmHandsetStop:true},()=>current));
    assert.deepEqual(calls,['check']);
  }
});

test('preview connection skips the robot probe and missing onsite confirmation sends nothing',async()=>{
  const calls=[];const {connectVbotWithReadiness}=load(async(url)=>{
    calls.push(url.split('/').pop());return {ok:true,json:async()=>({armed:true,mode:'rehearsal'})};
  });
  await connectVbotWithReadiness({gameId:'AbCd1234',mode:'rehearsal'},()=>true);
  assert.deepEqual(calls,['connect']);
  await assert.rejects(()=>connectVbotWithReadiness({gameId:'AbCd1234',mode:'live',confirmSafeWorkspace:false,confirmHandsetStop:false},()=>true));
  assert.deepEqual(calls,['connect']);
});
