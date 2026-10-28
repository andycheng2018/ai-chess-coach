import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source=readFileSync(new URL('../src/components/VbotCompanion.tsx',import.meta.url),'utf8');
const file=ts.createSourceFile('VbotCompanion.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let effect;
function visit(node){
 if(ts.isCallExpression(node)&&node.expression.getText(file)==='useEffect'&&node.arguments[0].getText(file).includes('networkSeen.current'))effect=node.arguments[0].getText(file);
 ts.forEachChild(node,visit);
}
visit(file);assert.ok(effect);
function apply(status,networkKey){
 const calls=[];const context={status,networkSeen:{current:networkKey}};
 for(const name of ['setTarget','setNetworkLabel','setSpace','setStop'])context[name]=value=>calls.push([name,value]);
 vm.runInNewContext(ts.transpileModule('var apply='+effect,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
 context.apply();return calls;
}
const home={target:'vbot@192.168.0.170',network:{current:{id:'home'},label:'Home'}};
test('new network fills its own remembered address and clears old supervision confirmations',()=>{
 assert.deepEqual(apply(home,'hotspot'),[['setTarget','vbot@192.168.0.170'],['setNetworkLabel','Home'],['setSpace',false],['setStop',false]]);
});
test('routine same-network status updates preserve an operator address draft',()=>{
 assert.deepEqual(apply(home,'home'),[]);
});
test('an unknown new network clears the old hotspot address instead of silently reusing it',()=>{
 const calls=apply({target:'',network:{current:{id:'new-network'},label:null}},'home');
 assert.deepEqual(calls[0],['setTarget','']);
 assert.deepEqual(calls.at(-1),['setStop',false]);
});
test('a gateway change still clears the draft when macOS cannot expose a full network identity',()=>{
 const calls=apply({target:'',network:{current:{id:null,subnet:'192.168.0.0/24',gateway:'192.168.0.2'}}},'192.168.0.0/24|192.168.0.1');
 assert.deepEqual(calls[0],['setTarget','']);assert.deepEqual(apply(null,null),[]);
});
