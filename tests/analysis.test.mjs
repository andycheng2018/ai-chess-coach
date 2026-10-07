import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const { Chess } = require('chess.js');
const compiled = ts.transpileModule(readFileSync(new URL('../src/analysis.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
function environment(initial, fetch) {
  let saved = initial || null;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: path => path === './coach' ? {CONTROL_URL:'http://test'} : require(path),
    localStorage: {getItem: () => saved, setItem: (_, value) => { saved = value; }},
    fetch, setTimeout, clearTimeout, DOMException });
  return { analysis: exports, readSaved: () => saved };
}

test('both sides can move; going back creates a branch and revisiting reuses it', () => {
  const {analysis:a} = environment();
  let w = a.emptyAnalysis();
  w = a.addAnalysisMove(w,'e2e4'); const e4 = w.current;
  w = a.addAnalysisMove(w,'e7e5'); const e5 = w.current;
  w = a.addAnalysisMove({...w,current:'root'},'d2d4');
  assert.equal(w.nodes.root.children.length,2);
  assert.equal(w.nodes[e4].children[0],e5);
  const size = Object.keys(w.nodes).length;
  w = a.addAnalysisMove({...w,current:'root'},'e2e4');
  assert.equal(w.current,e4);
  assert.equal(Object.keys(w.nodes).length,size);
  assert.throws(() => a.addAnalysisMove(w,'e2e5'));
});

test('game snapshots select historical positions and retain existing analysis branches', () => {
  const {analysis:a} = environment();
  const seed = {rootFen:new Chess().fen(),moves:['e2e4','e7e5'],ply:1,source:'game',sourceId:'game1'};
  let w = a.seedAnalysis(seed);
  assert.equal(w.nodes[w.current].san,'e4');
  w = a.addAnalysisMove(w,'c7c5');
  w = a.seedAnalysis({...seed,moves:['e2e4','e7e5','g1f3'],ply:3},w);
  assert.equal(w.nodes[w.current].san,'Nf3');
  const e4 = w.nodes[w.nodes.root.children[0]];
  assert.deepEqual(Array.from(e4.children,id => w.nodes[id].san),['e5','c5']);
});

test('underpromotion, black-to-move FEN, and PGN imports preserve the actual position', () => {
  const {analysis:a} = environment();
  let w = a.importAnalysis('7k/P7/8/8/8/8/8/K7 w - - 0 1');
  w = a.addAnalysisMove(w,'a7a8n');
  assert.equal(a.analysisPosition(w).get('a8').type,'n');
  const blackFen = new Chess().fen().replace(' w ',' b ').replace(' 0 1',' 0 23');
  w = a.addAnalysisMove(a.importAnalysis(blackFen),'e7e5');
  assert.match(a.exportAnalysisPgn(w),/23\.\.\. e5/);
  w = a.importAnalysis('1. e4 e5 2. Nf3 Nc6 *');
  assert.equal(a.analysisPath(w).length,4);
  assert.equal(w.nodes[w.current].fen,new Chess('r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3').fen());
});

test('PGN export includes alternatives and browser persistence restores every branch', () => {
  const {analysis:a,readSaved} = environment();
  let w = a.addAnalysisMove(a.emptyAnalysis(),'e2e4');
  w = a.addAnalysisMove(w,'e7e5');
  w = a.addAnalysisMove({...w,current:'root'},'d2d4');
  w = a.addAnalysisMove(w,'d7d5');
  const pgn = a.exportAnalysisPgn(w);
  assert.match(pgn,/1\. e4 \(1\. d4 1\.\.\. d5\) 1\.\.\. e5/);
  const main = new Chess(); main.loadPgn(pgn);
  assert.deepEqual(main.history(),['e4','e5']);
  assert.equal(a.saveAnalysis(w),true);
  const restored = environment(readSaved()).analysis.readAnalysis();
  assert.equal(restored.current,w.current);
  assert.equal(Object.keys(restored.nodes).length,5);
});

test('corrupt persisted branches fail closed and do not crash the board', () => {
  const {analysis:a} = environment();
  const w = a.addAnalysisMove(a.emptyAnalysis(),'e2e4');
  w.nodes[w.current].children=['root'];
  assert.equal(environment(JSON.stringify(w)).analysis.readAnalysis(),null);
  assert.equal(environment('{broken').analysis.readAnalysis(),null);
});

test('replaying a branch keeps repetition history and scores keep White perspective', () => {
  const {analysis:a} = environment();
  let w = a.emptyAnalysis();
  for(const uci of ['g1f3','g8f6','f3g1','f6g8','g1f3','g8f6','f3g1','f6g8']) w=a.addAnalysisMove(w,uci);
  assert.equal(a.analysisPosition(w).isThreefoldRepetition(),true);
  assert.equal(a.formatEngineScore({cp:120,mate:null}),'+1.20');
  assert.equal(a.formatEngineScore({cp:null,mate:-3}),'−M3');
  assert.equal(a.formatEngineScore({cp:null,mate:0},{terminal:true,winner:'black'}),'Black wins');
});

test('cancelling a busy-engine retry stops further analysis requests', async () => {
  let requests=0;
  const controller=new AbortController();
  const {analysis:a}=environment(null,async()=> { requests++; return {ok:false,status:503,json:async()=>({message:'The chess engine is busy.'})}; });
  const promise=a.analyzeBoard(a.emptyAnalysis(),'balanced',controller.signal);
  await Promise.resolve(); await Promise.resolve();
  controller.abort();
  await assert.rejects(promise,/Aborted/);
  assert.equal(requests,1);
});

test('an old backend gives restart instructions instead of an unhelpful 404', async () => {
  let requests=0;
  const {analysis:a}=environment(null,async()=> { requests++; return {ok:false,status:404}; });
  await assert.rejects(a.analyzeBoard(a.emptyAnalysis(),'balanced',new AbortController().signal),/backend is out of date.*Control-C.*Open Chess Coach.command/);
  assert.equal(requests,1);
});
