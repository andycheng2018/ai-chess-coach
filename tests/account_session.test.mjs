import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const text=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
const file=ts.createSourceFile('App.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let body;
function visit(node){
 if(ts.isCallExpression(node)&&node.expression.getText(file)==='useEffect'&&node.arguments[0]?.getText(file).includes('getAccount(token)')) body=node.arguments[0].getText(file);
 ts.forEachChild(node,visit);
}
visit(file);assert.ok(body);
class LichessHttpError extends Error{constructor(status){super(`HTTP ${status}`);this.status=status;}}
function setup(){
 const calls=[];let rejectAccount,resolveAccount;
 const context={token:'test-only',getToken:()=> 'test-only',LichessHttpError,getAccount:()=>new Promise((resolve,reject)=>{rejectAccount=reject;resolveAccount=resolve;}),logout:()=>calls.push(['logout'])};
 for(const name of ['setAccount','setAccountCheckError','setStatus','setSenseConnectionError','setToken'])context[name]=value=>calls.push([name,value]);
 vm.runInNewContext(ts.transpileModule('var effect='+body,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
 const cleanup=context.effect();return {calls,cleanup,reject:error=>rejectAccount(error),resolve:value=>resolveAccount(value)};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('network errors, rate limits and server errors preserve the existing sign-in',async()=>{
 for(const error of [new TypeError('network'),new LichessHttpError(429),new LichessHttpError(500)]){
  const run=setup();run.reject(error);await settle();
  assert.equal(run.calls.some(([name])=>name==='logout'||name==='setToken'),false);
  assert.ok(run.calls.some(([name,value])=>name==='setAccountCheckError'&&value));
 }
});
test('an authentication rejection clears the invalid sign-in',async()=>{
 const run=setup();run.reject(new LichessHttpError(401));await settle();
 assert.ok(run.calls.some(([name])=>name==='logout'));
 assert.ok(run.calls.some(([name,value])=>name==='setToken'&&value===null));
});
test('a cancelled account check cannot sign out or replace a newer session',async()=>{
 for(const fail of [true,false]){
  const run=setup();const before=run.calls.length;run.cleanup();
  if(fail)run.reject(new LichessHttpError(401));else run.resolve({username:'OldAccount'});
  await settle();
  assert.equal(run.calls.slice(before).some(([name])=>['logout','setToken','setAccount'].includes(name)),false);
 }
});
