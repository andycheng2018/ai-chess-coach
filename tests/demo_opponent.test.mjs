import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const text=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
const file=ts.createSourceFile('App.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let handler;
function visit(node){
 if(ts.isFunctionDeclaration(node)&&node.name?.text==='changeDemoOpponent')handler=node.getText(file);
 ts.forEachChild(node,visit);
}
visit(file);assert.ok(handler);
function setup({gameId='AbCd1234',pending=false,fail=false}={}){
 const calls=[];const context={gameId,demoModePending:pending,gameIdRef:{current:gameId},
  setBotDemoMode:async(id,enabled)=>{calls.push(['request',id,enabled]);if(fail)throw new Error('Unrated required');return {demoGames:[id]};}};
 for(const name of ['setBot','setStatus','setDemoModePending','setDemoModeError'])context[name]=value=>calls.push([name,value]);
 vm.runInNewContext(ts.transpileModule(handler+';var change=changeDemoOpponent;',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
 return {calls,change:context.change};
}
test('demo selection targets the exact current game without robot arming or moves',async()=>{
 const {change,calls}=setup();await change(true);
 assert.deepEqual(calls.find(([kind])=>kind==='request'),['request','AbCd1234',true]);
 assert.ok(calls.some(([kind])=>kind==='setBot'));
});
test('no game or pending selection cannot submit a demo-mode mutation',async()=>{
 for(const config of [{gameId:null},{pending:true}]){
  const {change,calls}=setup(config);await change(true);assert.equal(calls.length,0);
 }
});
test('rejected mode change shows the server error and does not claim enabled',async()=>{
 const {change,calls}=setup({fail:true});await change(true);
 assert.equal(calls.some(([kind])=>kind==='setBot'),false);
 assert.ok(calls.some(([kind,value])=>kind==='setDemoModeError'&&value.includes('Unrated required')));
 assert.deepEqual(calls.at(-1),['setDemoModePending',false]);
});
