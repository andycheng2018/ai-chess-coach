import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const compiled=ts.transpileModule(readFileSync(new URL('../src/diagnostics.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exports={};
vm.runInNewContext(compiled,{exports,URL,performance,AbortSignal,fetch:()=>{}});
const url='https://chess-api.urbot.ai';
const reply=(status,body)=>async()=>({status,ok:status<400,json:async()=>{if(body===undefined)throw new Error('bad');return body;}});
test('only a public HTTPS server counts as the cloud',()=>{
 assert.equal(exports.isCloudBackend(url),true);
 for(const local of ['http://127.0.0.1:8765','http://localhost:5173','http://192.168.0.20:8765','https://localhost','https://mac.local','nonsense'])assert.equal(exports.isCloudBackend(local),false,local);
});
test('a report passes through, and the backend card uses this device\'s round trip',async()=>{
 const body={check:'qwen',status:'pass',summary:'ok',latencyMs:4242,steps:[]};
 assert.equal((await exports.runDiagnostic('qwen',url,reply(200,body))).latencyMs,4242);
 assert.notEqual((await exports.runDiagnostic('backend',url,reply(200,{...body,check:'backend'}))).latencyMs,4242);
});
test('connection problems become failed reports with a reason',async()=>{
 for(const [status,word] of [[403,'Pair'],[404,'older'],[500,'500']]){
  const report=await exports.runDiagnostic('vbot',url,reply(status,{}));
  assert.equal(report.status,'fail');assert.match(report.summary,new RegExp(word));
 }
 assert.match((await exports.runDiagnostic('vbot',url,async()=>{throw new TypeError('network');})).summary,/Could not reach/);
 assert.match((await exports.runDiagnostic('vbot',url,async()=>{throw Object.assign(new Error('x'),{name:'TimeoutError'});})).summary,/in time/);
 assert.equal((await exports.runDiagnostic('vbot',url,reply(200))).status,'fail');
});
