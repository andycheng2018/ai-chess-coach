import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {test} from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const require=createRequire(import.meta.url);
function environment(initial={}) {
  const storage=new Map(Object.entries(initial));
  let fail=false;
  const modules={};
  const context={crypto:webcrypto,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>{if(fail)throw Error('Storage full');storage.set(key,value);}},window:{location:{hash:''}},setTimeout,clearTimeout,DOMException};
  for(const name of ['analysis','analysisLibrary']) {
    const exports={};
    const code=ts.transpileModule(readFileSync(new URL(`../src/${name}.ts`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    vm.runInNewContext(code,{...context,exports,require:path=>path==='./coach'?{CONTROL_URL:'http://test'}:path==='./analysis'?modules.analysis:require(path)});
    modules[name]=exports;
  }
  return {...modules,storage,fail:()=>{fail=true;}};
}
test('legacy draft migrates into the same library without losing branches or modifying backup',()=>{
  const first=environment();let draft=first.analysis.addAnalysisMove(first.analysis.emptyAnalysis(),'e2e4');
  draft=first.analysis.addAnalysisMove({...draft,current:'root'},'d2d4');
  const bytes=JSON.stringify(draft);const {analysisLibrary:l,storage}=environment({'ai-chess-coach.analysis-board.v1':bytes});
  let library=l.readAnalysisLibrary();assert.equal(library.saves.length,1);assert.equal(library.saves[0].workspace.nodes.root.children.length,2);
  library=l.writeAnalysisSave(library.saves[0]);assert.equal(library.saves[0].revision,1);
  assert.equal(storage.get('ai-chess-coach.analysis-board.v1'),bytes);
});
test('independent saves retain positions, settings, layouts, and survive reopening',()=>{
  const {analysis:a,analysisLibrary:l}=environment();
  const first=l.createAnalysisSave(null,'First study');let library=l.writeAnalysisSave(first);
  const second=l.createAnalysisSave(null,'Second study');second.workspace=a.addAnalysisMove(second.workspace,'d2d4');second.search={mode:'unlimited',detail:'deep',depth:24};second.view.layout='focus';
  l.writeAnalysisSave(second);const one=library.saves[0];one.workspace=a.addAnalysisMove(one.workspace,'e2e4');l.writeAnalysisSave(one);
  library=l.readAnalysisLibrary();assert.equal(library.saves.length,2);assert.equal(library.saves.find(s=>s.id===second.id).workspace.nodes.n1.san,'d4');assert.equal(library.saves.find(s=>s.id===second.id).search.mode,'unlimited');
  const copy={...library.saves.find(s=>s.id===first.id),id:webcrypto.randomUUID(),revision:0,title:'Copy'};l.writeAnalysisSave(copy);
  copy.workspace=a.addAnalysisMove(copy.workspace,'e7e5');copy.revision=1;l.writeAnalysisSave(copy);
  assert.equal(Object.keys(l.readAnalysisLibrary().saves.find(s=>s.id===first.id).workspace.nodes).length,2);
});
test('stale-tab writes and full storage preserve existing bytes',()=>{
  const {analysisLibrary:l,storage,fail}=environment();const save=l.createAnalysisSave();const original=l.writeAnalysisSave(save).saves[0];
  const latest=l.writeAnalysisSave({...original,title:'Changed elsewhere'});const bytes=storage.get(l.LIBRARY_KEY);
  assert.throws(()=>l.writeAnalysisSave({...original,title:'Stale'}),/another tab/);assert.equal(storage.get(l.LIBRARY_KEY),bytes);
  fail();assert.throws(()=>l.writeAnalysisSave({...latest.saves[0],title:'Local draft'}),/Storage full/);assert.equal(storage.get(l.LIBRARY_KEY),bytes);
});
test('archive, restore, library presentation and page routes share one storage system',()=>{
  const {analysisLibrary:l}=environment();let save=l.writeAnalysisSave(l.createAnalysisSave()).saves[0];save=l.writeAnalysisSave({...save,archived:true}).saves[0];assert.equal(save.archived,true);
  l.writeAnalysisSave({...save,archived:false});const list=l.writeLibraryPresentation('list');assert.equal(list.saves.length,1);assert.equal(list.saves[0].archived,false);assert.equal(list.presentation,'list');
  l.goToAnalysis(save.id); // mock location doesn't prepend '#' as browsers do
  assert.throws(()=>l.writeAnalysisSave({...list.saves[0],search:{mode:'depth',detail:'quick',depth:0}}),/invalid/);
});
test('corrupt libraries fail closed instead of overwriting saved work',()=>{
  const {analysisLibrary:l,storage}=environment({'ai-chess-coach.analysis-library.v2':'{broken'});
  assert.throws(()=>l.readAnalysisLibrary());assert.throws(()=>l.writeAnalysisSave(l.createAnalysisSave()));assert.equal(storage.get(l.LIBRARY_KEY),'{broken');
});
