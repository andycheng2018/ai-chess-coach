import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=readFileSync(new URL('../src/roomDiscovery.ts',import.meta.url),'utf8');
const exports={};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports});
const {discoverRooms,nextAutomaticRoom}=exports;
const base={id:'AbCd1234',status:'created',challenger:{id:'zachzhang'},destUser:null,rated:false,variant:{key:'standard'},color:'white',timeControl:{type:'unlimited'}};
const discover=(overrides={})=>discoverRooms([{...base,...overrides}],'ZachZhang','MonkeyKingZach')[0];
test('account room gives bot the opposite fixed seat in either direction',()=>{
 assert.equal(discover().url,'https://lichess.org/game/AbCd1234?color=black');
 assert.equal(discover({color:'black'}).url,'https://lichess.org/game/AbCd1234?color=white');
 assert.equal(discover().timeControl,'Unlimited');
});
test('rejects rated, unknown, foreign, closed, nonstandard and ambiguous rooms',()=>{
 for(const change of [{rated:true},{rated:undefined},{status:'accepted'},{challenger:null},{challenger:{id:'stranger'}},{destUser:{id:'somebodyelse'}},{variant:{key:'chess960'}},{color:'random',finalColor:'white'},{color:undefined},{open:{userIds:['zachzhang','stranger']}}]) {
  assert.equal(discover(change).url,null,JSON.stringify(change)); assert.ok(discover(change).blockedReason);
 }
});
test('direct invitations to the configured bot remain eligible, other accounts do not',()=>{
 assert.ok(discover({destUser:{id:'monkeykingzach'}}).url);
 assert.equal(discoverRooms([base],'SecondAccount222','MonkeyKingZach')[0].url,null);
});
test('deduplicates and rejects malformed or private-seat IDs without using supplied URLs',()=>{
 const rooms=discoverRooms([base,base,{...base,id:'AbCd1234seat'},{...base,id:'../bad'},{...base,id:'EfGh5678',url:'https://evil.example'}],'ZachZhang','MonkeyKingZach');
 assert.equal(rooms.length,2);assert.equal(rooms[1].url,'https://lichess.org/game/EfGh5678?color=black');
});
test('auto-join ignores baseline and attempted IDs, stops on ambiguity, and never selects ineligible rooms',()=>{
 const old=discover(), fresh={...old,id:'EfGh5678'}, other={...old,id:'IjKl9012'};
 const baseline=new Set([old.id]), attempted=new Set();
 assert.equal(nextAutomaticRoom([old],baseline,attempted),null);
 assert.equal(nextAutomaticRoom([old,fresh],baseline,attempted)?.id,fresh.id);
 assert.equal(nextAutomaticRoom([fresh,other],baseline,attempted),null);
 attempted.add(fresh.id);assert.equal(nextAutomaticRoom([fresh],baseline,attempted),null);
 assert.equal(nextAutomaticRoom([{...fresh,url:null}],baseline,new Set()),null);
});

const {discoverJoinedRooms}=exports;
test('existing games are visible independently of new-invitation baselines',()=>{
 const game={gameId:'AbCd1234',color:'white',opponent:{id:'monkeykingzach'}};
 const rooms=discoverJoinedRooms([game,game,{...game,gameId:'EfGh5678',color:'black'},{...game,gameId:'IjKl9012',opponent:{id:'human'}},{...game,color:undefined},{...game,gameId:'AbCd1234private'}],'MonkeyKingZach');
 assert.equal(rooms.length,2);
 assert.equal(rooms[0].url,'https://lichess.org/game/AbCd1234?color=black');
 assert.equal(rooms[1].url,'https://lichess.org/game/EfGh5678?color=white');
});
