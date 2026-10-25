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

let gameEventHandler;
function findGameEvents(node){
 if(ts.isCallExpression(node)&&node.expression.getText(file)==='streamEvents')gameEventHandler=node.arguments[1].getText(file);
 ts.forEachChild(node,findGameEvents);
}
findGameEvents(file);assert.ok(gameEventHandler);
function streamEventsFor(selected){
 const calls=[];const ctx={gameIdRef:{current:selected},BOT_USERNAME:'MonkeyKingZach',refreshPlayingGames:()=>{},pendingMoveRef:{current:null},forgetStoredGame:()=>{}};
 for(const name of ['setSenseRobotGameId','setActiveGameId','setGameStatus','setStatus','setMoveInFlight'])ctx[name]=value=>calls.push([name,value]);
 vm.runInNewContext(ts.transpileModule('var event='+gameEventHandler,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,ctx);
 return {calls,event:ctx.event};
}
test('replayed starts for other active games cannot steal the selected SenseRobot room',()=>{
 const run=streamEventsFor('n7aV30Jv');run.event({type:'gameStart',game:{id:'RRhxJyOf',opponent:{username:'MonkeyKingZach'}}});
 assert.equal(run.calls.length,0);
});
test('a duplicate start for the selected game cannot strand it in recovering',()=>{
 const run=streamEventsFor('n7aV30Jv');run.event({type:'gameStart',game:{id:'n7aV30Jv',opponent:{username:'MonkeyKingZach'}}});
 assert.equal(run.calls.length,0);
});
test('a new coach game can still attach when no room was selected',()=>{
 const run=streamEventsFor(null);run.event({type:'gameStart',game:{id:'n7aV30Jv',opponent:{username:'MonkeyKingZach'}}});
 assert.deepEqual(run.calls.find(([name])=>name==='setActiveGameId'),['setActiveGameId','n7aV30Jv']);
});
