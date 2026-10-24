import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const cache={};
function load(name) {
 if(cache[name]) return cache[name];
 const source=readFileSync(new URL(`../src/${name}.ts`,import.meta.url),'utf8').replaceAll('import.meta.env','({})');
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const exports={};cache[name]=exports;
 vm.runInNewContext(code,{exports,URL,AbortSignal,require:path=>load(path.replace('./',''))});
 return exports;
}
const {roomJoinPreview,recoverJoinedRoom,requireExactJoinedRoom}=load('roomJoin');
const target={gameId:'4TKUBiH1',color:'white',opponent:{username:'MonkeyKingZach'}};
test('room preview gives the invitation color to the bot and opposite color to the person',()=>{
 for(const [bot,human] of [['black','white'],['white','black']]) {
  const room=roomJoinPreview(`https://lichess.org/game/4TKUBiH1?color=${bot}`);
  assert.equal(room.color,bot);assert.equal(room.playerColor,human);assert.equal(room.challengeId,'4TKUBiH1');
 }
});
test('game-view QRs and foreign/private links cannot be presented as invitations',()=>{
 assert.throws(()=>roomJoinPreview('https://lichess.org/4TKUBiH1/white'),/game-viewing link/);
 for(const link of ['https://example.com/game/4TKUBiH1?color=black','https://lichess.org/game/4TKUBiH1seat?color=black','https://lichess.org/game/4TKUBiH1']) assert.throws(()=>roomJoinPreview(link));
});
test('accepted room recovery selects the exact game instead of another live game',()=>{
 const room=roomJoinPreview('https://lichess.org/game/4TKUBiH1?color=black');
 const other={...target,gameId:'xYDhW2TU'};
 assert.equal(recoverJoinedRoom(room,'MonkeyKingZach',[other,target]),'4TKUBiH1');
 assert.equal(recoverJoinedRoom(room,'MonkeyKingZach',[other]),null);
 assert.throws(()=>recoverJoinedRoom(room,'MonkeyKingZach',[{...target,color:'black'}]),/wrong bot color/);
 assert.throws(()=>recoverJoinedRoom(room,'MonkeyKingZach',[{...target,opponent:{username:'OtherPlayer'}}]),/did not confirm/);
});
test('late or unrelated backend results cannot switch to a different game',()=>{
 assert.equal(requireExactJoinedRoom('4TKUBiH1','4TKUBiH1'),'4TKUBiH1');
 for(const actual of [undefined,null,'','xYDhW2TU']) assert.throws(()=>requireExactJoinedRoom('4TKUBiH1',actual),/exact room/);
});
