import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the production handler so a second robot-control path cannot silently
// be introduced beside the native companion again.
const text=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
const file=ts.createSourceFile('App.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let handler;
function visit(node){
  if(ts.isVariableDeclaration(node)&&node.name.getText(file)==='handleSelectGame') handler=node.initializer.arguments[0].getText(file);
  ts.forEachChild(node,visit);
}
visit(file);assert.ok(handler);
function setup(gameId){
  const calls=[];const context={gameIdRef:{current:gameId},CONTROL_URL:'http://localhost',
    fetch:()=>{calls.push(['robot-api']);throw new Error('Game selection must not control the robot');}};
  for(const name of ['setActiveGameId','setGameStatus','setCurrentView','setMenuModalOpen','setStatus']) context[name]=value=>calls.push([name,value]);
  vm.runInNewContext(ts.transpileModule(`var select=${handler}`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
  return {calls,select:context.select};
}
test('opening the already-selected game preserves its stream status and robot session',()=>{
  const {select,calls}=setup('AbCd1234');select('AbCd1234');
  assert.equal(calls.some(([name])=>['robot-api','setActiveGameId','setGameStatus'].includes(name)),false);
  assert.deepEqual(calls.find(([name])=>name==='setCurrentView'),['setCurrentView','arena']);
});
test('switching games never implicitly arms VBOT beside the companion lifecycle',()=>{
  const {select,calls}=setup('Previous');select('AbCd1234');
  assert.equal(calls.some(([name])=>name==='robot-api'),false);
  assert.deepEqual(calls.find(([name])=>name==='setActiveGameId'),['setActiveGameId','AbCd1234']);
  assert.deepEqual(calls.find(([name])=>name==='setGameStatus'),['setGameStatus','recovering']);
});
