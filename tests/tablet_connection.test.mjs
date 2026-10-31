import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const compiled=ts.transpileModule(readFileSync(new URL('../src/nativeBackend.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function environment(){
 const values=new Map(),exports={};
 vm.runInNewContext(compiled,{exports,URL,Headers,Request,localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},window:{location:{href:'https://localhost/'}}});return exports;
}
const connection={url:'http://192.168.0.20:8765',token:'test-pairing-key-'+'x'.repeat(40)};
test('tablet pairing accepts LAN or HTTPS endpoints and rejects leaked/unsafe URL forms',()=>{
 const api=environment();
 assert.equal(api.validateConnection({...connection,url:connection.url+'/'}).url,connection.url);
 for(const url of ['http://example.com:8765','http://192.168.0.20:8765/?token=secret','http://user:pass@192.168.0.20:8765','javascript:alert(1)'])assert.throws(()=>api.validateConnection({...connection,url}));
 assert.throws(()=>api.validateConnection({...connection,token:'short'}));
 assert.equal(api.validateConnection({...connection,url:'https://coach.example.com'}).url,'https://coach.example.com');
});
test('pairing QR is typed, persists its connection, and forget removes it',()=>{
 const api=environment();assert.equal(api.readConnection(),null);
 const decoded=api.parsePairingQr(JSON.stringify({type:'chessbuddy-tablet-v1',...connection}));
 api.saveConnection(decoded);assert.equal(api.readConnection().url,connection.url);
 assert.throws(()=>api.parsePairingQr(JSON.stringify({type:'sense-room',...connection})));
 api.clearConnection();assert.equal(api.readConnection(),null);
});
test('pairing key stays on the backend origin and redirects cannot forward it',async()=>{
 const api=environment(),calls=[];
 const send=api.authenticatedBackendFetch(async(input,init)=>{calls.push({input,init});return {};},connection);
 await send(connection.url+'/api/vbot/status');
 await send('https://lichess.org/api/account',{headers:{Authorization:'Bearer lichess-only'}});
 await send('http://192.168.0.21:8765/api/health');
 assert.equal(calls[0].init.headers.get(api.TABLET_HEADER),connection.token);
 assert.equal(calls[0].init.redirect,'error');
 assert.equal(calls[1].init.headers.Authorization,'Bearer lichess-only');
 assert.equal(calls[1].init.headers[api.TABLET_HEADER],undefined);
 assert.equal(calls[2].init,undefined);
});
test('re-pair health checks can supply the new key instead of being overwritten by the old transport',async()=>{
 const api=environment();let seen;
 const send=api.authenticatedBackendFetch(async(_,init)=>{seen=init;return {};},connection);
 await send(connection.url+'/api/health',{headers:{[api.TABLET_HEADER]:'new-pairing-key'}});
 assert.equal(seen.headers.get(api.TABLET_HEADER),'new-pairing-key');
});
