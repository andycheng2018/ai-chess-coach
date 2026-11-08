import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const compiled=ts.transpileModule(readFileSync(new URL('../vbot-app/src/transport/cloudPairing.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const api={};
vm.runInNewContext(compiled,{exports:api,URL,Headers,JSON,Promise,Error,fetch:()=>{}});
const token='k'.repeat(43), url='https://chess-api.urbot.ai';
test('pairing needs a plain HTTPS address and a full key',()=>{
 assert.equal(api.validatePairing({url:url+'/',token}).url,url);
 for(const bad of ['http://chess-api.urbot.ai','https://a.example/path','https://u:p@a.example','https://a.example/?k=1','nonsense'])assert.throws(()=>api.validatePairing({url:bad,token}),undefined,bad);
 assert.throws(()=>api.validatePairing({url,token:'short'}));
});
test('the QR format matches Chess Buddy and is checked like a typed pairing',()=>{
 const good=api.parsePairingQr(JSON.stringify({type:'chessbuddy-tablet-v1',url,token}));
 assert.equal(good.url,url);assert.equal(good.token,token);
 for(const bad of ['not json','null',JSON.stringify({type:'sense-room',url,token}),JSON.stringify({type:'chessbuddy-tablet-v1',url:'http://evil.example',token}),JSON.stringify({type:'chessbuddy-tablet-v1',url,token:'short'})])assert.throws(()=>api.parsePairingQr(bad),undefined,bad);
});
test('a saved pairing round-trips and can be forgotten',()=>{
 const values=new Map();const store={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
 assert.equal(api.readPairing(store),null);
 api.writePairing(store,{url,token});assert.equal(api.readPairing(store).token,token);
 api.writePairing(store,null);assert.equal(api.readPairing(store),null);
});
test('the key goes only to the paired server and never follows a redirect',async()=>{
 const calls=[];const send=api.cloudFetcher({url,token},async(input,init)=>{calls.push([input,init]);return 'ok';});
 assert.equal(await send(url+'/api/vbot/studio/status',{}),'ok');
 assert.equal(calls[0][1].headers.get(api.CLOUD_HEADER),token);
 assert.equal(calls[0][1].redirect,'error');
 await assert.rejects(send('https://evil.example/x',{}));
 assert.equal(calls.length,1);
});
