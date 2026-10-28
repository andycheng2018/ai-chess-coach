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

const {saveRoomJoinDraft,readRoomJoinDraft,clearRoomJoinDraft}=load('roomJoin');
function draftStorage(){const values=new Map();return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};}
test('the supplied n7aV30Jv invitation parses as bot Black and player White',()=>{
 const room=roomJoinPreview('https://lichess.org/game/n7aV30Jv?color=black');
 assert.equal(room.challengeId,'n7aV30Jv');assert.equal(room.color,'black');assert.equal(room.playerColor,'white');
});
test('OAuth room draft restores only public room/color and does not auto-join',()=>{
 const storage=draftStorage();
 assert.equal(saveRoomJoinDraft('https://lichess.org/game/n7aV30Jv?color=black&unrelated=discard',storage,1000),true);
 assert.equal(readRoomJoinDraft(storage,1001),'https://lichess.org/game/n7aV30Jv?color=black');
 clearRoomJoinDraft(storage);assert.equal(readRoomJoinDraft(storage,1002),null);
});
test('room draft expires and rejects private/foreign links or unavailable storage',()=>{
 const storage=draftStorage();saveRoomJoinDraft('https://lichess.org/game/n7aV30Jv?color=black',storage,1000);
 assert.equal(readRoomJoinDraft(storage,999),null);
 assert.equal(readRoomJoinDraft(storage,1000+30*60*1000+1),null);
 for(const url of ['https://example.com/n7aV30Jv?color=black','https://lichess.org/game/n7aV30Jvseat?color=black']) assert.equal(saveRoomJoinDraft(url,storage,1000),false);
 const blocked={getItem:()=>{throw Error('unavailable');},setItem:()=>{throw Error('unavailable');},removeItem:()=>{throw Error('unavailable');}};
 assert.equal(saveRoomJoinDraft('',blocked,1000),false);assert.equal(readRoomJoinDraft(blocked,1000),null);assert.doesNotThrow(()=>clearRoomJoinDraft(blocked));
});
test('starting sign-in before pasting still restores the room dialog',()=>{
 const storage=draftStorage();assert.equal(saveRoomJoinDraft('',storage,1000),true);
 assert.equal(readRoomJoinDraft(storage,1001),'');
});

const {requireUnjoinedRoom}=load('roomJoin');
test('already-created game without a confirmed player seat cannot submit another acceptance',()=>{
 const room=roomJoinPreview('https://lichess.org/game/n7aV30Jv?color=black');
 const cached={gameId:'n7aV30Jv',state:{status:'started'}};
 assert.throws(()=>requireUnjoinedRoom(room,cached,'SecondAccount222'),/already joined.*SecondAccount222.*same player account/);
 assert.doesNotThrow(()=>requireUnjoinedRoom(room,null,'ZachZhang'));
 assert.doesNotThrow(()=>requireUnjoinedRoom(room,{...cached,gameId:'Other123'},'ZachZhang'));
 assert.throws(()=>requireUnjoinedRoom(room,{...cached,state:{status:'mate'}},'ZachZhang'),/already finished/);
});
