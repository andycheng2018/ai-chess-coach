import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url),exports={};
const compiled=ts.transpileModule(readFileSync(new URL('../src/components/CoachWindow.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
vm.runInNewContext(compiled,{exports,require});
const props={openingLabel:'Ruy Lopez · C60',openingStatus:'In book · transposed',historyStatus:'synced',
 coachResult:null,coachThinking:false,coachError:null,criticalPrompt:null,coachNotes:[{gameId:'g',ply:5,playedMove:'Bb5',classification:'good',title:'Develop safely',feedback:'Keep the bishop active.'}],
 isMyTurn:true,voiceEnabled:false,ttsStatus:{state:'idle'},hintsEnabled:true,coachDetail:'balanced',coachLanguage:'en',currentPly:null,themeLabel:theme=>theme};
test('new coach window retains opening recognition and the unified learning timeline',()=>{
 const html=renderToStaticMarkup(createElement(exports.CoachWindow,props));
 assert.match(html,/Ruy Lopez · C60/);assert.match(html,/In book · transposed/);assert.match(html,/Game Coaching Timeline/);assert.match(html,/Saved to coaching history/);assert.match(html,/Develop safely/);
});
test('new timeline keeps an offline save distinct from a synchronized record',()=>{
 const html=renderToStaticMarkup(createElement(exports.CoachWindow,{...props,openingLabel:'',historyStatus:'offline'}));
 assert.match(html,/Saved on this device · waiting to sync/);assert.doesNotMatch(html,/Saved to coaching history/);assert.doesNotMatch(html,/coach-opening-badge/);
});
