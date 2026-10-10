import { Chess } from 'chess.js';
import { CONTROL_URL, type CoachDetail } from './coach';

export type AnalysisNode = { id: string; parent: string | null; children: string[]; uci: string; san: string; fen: string };
export type GameRecord = { white: string; black: string; result: '1-0' | '0-1' | '1/2-1/2' | '*'; site?: string };
export type AnalysisWorkspace = { rootFen: string; source: string; sourceId: string; nodes: Record<string, AnalysisNode>; current: string; nextId: number; game?: GameRecord };
export type AnalysisSeed = { rootFen: string; moves?: string[]; ply?: number; source: string; sourceId?: string; orientation?: 'white' | 'black'; game?: GameRecord };
export type EngineScore = { cp: number | null; mate: number | null };
export type PositionAnalysis = {
  fen: string; turn: 'white' | 'black'; terminal: boolean; winner: 'white' | 'black' | null;
  reason?: string; result?: string; score: EngineScore;
  lines: { moves: string[]; uci: string[]; depth: number; score: EngineScore }[];
};
const CACHE_KEY = 'ai-chess-coach.analysis-board.v1';

export function emptyAnalysis(rootFen = new Chess().fen(), source = 'New analysis', sourceId = ''): AnalysisWorkspace {
  const chess = new Chess(rootFen);
  const fen = chess.fen();
  return { rootFen: fen, source, sourceId, current: 'root', nextId: 1,
    nodes: { root: { id: 'root', parent: null, children: [], uci: '', san: '', fen } } };
}

export function analysisPath(workspace: AnalysisWorkspace, id = workspace.current): AnalysisNode[] {
  const path: AnalysisNode[] = [];
  let node = workspace.nodes[id];
  while (node?.parent) {
    if (path.length >= 512) throw new Error('Analysis path is too long.');
    path.unshift(node); node = workspace.nodes[node.parent];
  }
  return path;
}

export function analysisPosition(workspace: AnalysisWorkspace, id = workspace.current): Chess {
  const chess = new Chess(workspace.rootFen);
  for (const node of analysisPath(workspace, id)) chess.move(node.uci);
  return chess;
}

// Include move history: identical FENs can have different repetition outcomes.
export function analysisPositionKey(workspace: AnalysisWorkspace): string {
  return JSON.stringify([workspace.rootFen, analysisPath(workspace).map(node => node.uci)]);
}

export function evaluationWhitePercent(result: PositionAnalysis | null): number | null {
  if (!result) return null;
  if (result.terminal) return result.winner === 'white' ? 100 : result.winner === 'black' ? 0 : 50;
  if (result.score.mate !== null) return result.score.mate > 0 ? 100 : 0;
  if (result.score.cp === null || !Number.isFinite(result.score.cp)) return null;
  return 100 / (1 + Math.exp(-result.score.cp / 300));
}

export function addAnalysisMove(workspace: AnalysisWorkspace, uci: string): AnalysisWorkspace {
  const parent = workspace.nodes[workspace.current];
  const chess = analysisPosition(workspace);
  const move = chess.move(uci);
  const found = parent.children.find(id => workspace.nodes[id].uci === uci);
  if (found) return { ...workspace, current: found };
  if (Object.keys(workspace.nodes).length >= 513) throw new Error('This analysis has reached 512 moves. Export it and start a new board.');
  const id = `n${workspace.nextId}`;
  return { ...workspace, current: id, nextId: workspace.nextId + 1,
    nodes: { ...workspace.nodes,
      [parent.id]: { ...parent, children: [...parent.children, id] },
      [id]: { id, parent: parent.id, children: [], uci, san: move.san, fen: chess.fen() },
    } };
}

export function seedAnalysis(seed: AnalysisSeed, saved?: AnalysisWorkspace | null): AnalysisWorkspace {
  let workspace = saved && seed.sourceId && saved.sourceId === seed.sourceId
    && saved.rootFen === new Chess(seed.rootFen).fen()
    ? { ...saved, current: 'root', source: seed.source } : emptyAnalysis(seed.rootFen, seed.source, seed.sourceId);
  const path = ['root'];
  for (const uci of seed.moves || []) {
    const parent = workspace.current;
    workspace = addAnalysisMove(workspace, uci); path.push(workspace.current);
    // Played moves remain the exported main line; exploration branches survive.
    const node = workspace.nodes[parent];
    workspace = {...workspace, nodes: {...workspace.nodes, [parent]: {...node, children: [workspace.current, ...node.children.filter(id=>id!==workspace.current)]}}};
  }
  const ply = Math.max(0, Math.min(path.length - 1, seed.ply ?? path.length - 1));
  return { ...workspace, current: path[ply], game: seed.game || workspace.game };
}

export function importAnalysis(text: string): AnalysisWorkspace {
  const value = text.trim();
  if (!value || value.length > 64000) throw new Error('Paste a FEN or PGN of at most 64,000 characters.');
  // A FEN contains eight slash-separated ranks, followed by side to move.
  if (/^\S+\/\S+\s+[wb]\s/.test(value)) return emptyAnalysis(value, 'Imported position');
  const chess = new Chess();
  try { chess.loadPgn(value); }
  catch { throw new Error('This is not a valid PGN. Check its move sequence, or paste a FEN instead.'); }
  const moves = chess.history({ verbose: true });
  const rootFen = moves[0]?.before || chess.fen();
  return seedAnalysis({ rootFen, moves: moves.map(move => move.from + move.to + (move.promotion || '')), source: 'Imported PGN (main line)', game: {white: chess.getHeaders().White || '?', black: chess.getHeaders().Black || '?', result: (['1-0','0-1','1/2-1/2'].includes(chess.getHeaders().Result) ? chess.getHeaders().Result : '*') as GameRecord['result']} });
}

function moveText(workspace: AnalysisWorkspace, node: AnalysisNode): string {
  const parentFen = workspace.nodes[node.parent!].fen.split(' ');
  return `${parentFen[5]}${parentFen[1] === 'w' ? '.' : '...'} ${node.san}`;
}

export function exportAnalysisPgn(workspace: AnalysisWorkspace): string {
  function branch(id: string): string {
    const node = workspace.nodes[id];
    return `${moveText(workspace, node)} ${children(node)}`.trim();
  }
  function children(node: AnalysisNode): string {
    const [main, ...alternatives] = node.children;
    if (!main) return '';
    return [moveText(workspace, workspace.nodes[main]), ...alternatives.map(id => `(${branch(id)})`), children(workspace.nodes[main])].filter(Boolean).join(' ');
  }
  const outcome = workspace.game?.result || '*';
  const quote = (value: string) => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\r\n]/g, ' ');
  const headers = ['[Event "Chess Coach analysis"]', `[Result "${outcome}"]`];
  if (workspace.game) {
    headers.push(`[White "${quote(workspace.game.white)}"]`, `[Black "${quote(workspace.game.black)}"]`);
    if (workspace.game.site) headers.push(`[Site "${quote(workspace.game.site)}"]`);
  }
  if (workspace.rootFen !== new Chess().fen()) headers.push('[SetUp "1"]', `[FEN "${workspace.rootFen}"]`);
  return `${headers.join('\n')}\n\n${children(workspace.nodes.root)} ${outcome}`;
}

export function validateAnalysis(saved: AnalysisWorkspace): AnalysisWorkspace | null {
  try {
    if (!saved || typeof saved.rootFen !== 'string' || typeof saved.source !== 'string'
      || typeof saved.sourceId !== 'string' || !saved.nodes?.root || !saved.nodes[saved.current]
      || !Number.isInteger(saved.nextId) || Object.keys(saved.nodes).length > 513) return null;
    if (saved.game && (typeof saved.game.white !== 'string' || typeof saved.game.black !== 'string' || !['1-0','0-1','1/2-1/2','*'].includes(saved.game.result) || (saved.game.site !== undefined && typeof saved.game.site !== 'string'))) return null;
    new Chess(saved.rootFen);
    if (saved.nodes.root.parent !== null || saved.nodes.root.fen !== saved.rootFen) return null;
    const visited = new Set<string>();
    function validate(id: string, chess: Chess): void {
      if (visited.has(id)) throw new Error('Invalid variation tree');
      visited.add(id);
      const node = saved.nodes[id];
      if (!node || node.id !== id || !Array.isArray(node.children) || node.fen !== chess.fen()) throw new Error('Invalid node');
      for (const childId of node.children) {
        const child = saved.nodes[childId];
        if (!child || child.parent !== id) throw new Error('Invalid parent');
        const copy = new Chess(chess.fen());
        const move = copy.move(child.uci);
        if (move.san !== child.san) throw new Error('Invalid move');
        validate(childId, copy);
      }
    }
    validate('root', new Chess(saved.rootFen));
    if (visited.size !== Object.keys(saved.nodes).length || !visited.has(saved.current)) return null;
    const ids = Object.keys(saved.nodes).filter(id => id !== 'root').map(id => Number(id.slice(1)));
    if (ids.some(id => !Number.isInteger(id) || id < 1 || id >= saved.nextId)) return null;
    return saved;
  } catch { return null; }
}

export function readAnalysis(): AnalysisWorkspace | null {
  try { return validateAnalysis(JSON.parse(localStorage.getItem(CACHE_KEY) || 'null')); }
  catch { return null; }
}

export function saveAnalysis(workspace: AnalysisWorkspace): boolean {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(workspace)); return true; }
  catch { return false; }
}

export function formatEngineScore(score: EngineScore, terminal?: PositionAnalysis): string {
  if (terminal?.terminal) return terminal.winner ? `${terminal.winner === 'white' ? 'White' : 'Black'} wins` : 'Draw';
  if (score.mate !== null) return `${score.mate < 0 ? '−' : '+'}M${Math.abs(score.mate)}`;
  if (score.cp === null) return '—';
  return `${score.cp > 0 ? '+' : ''}${(score.cp / 100).toFixed(2)}`;
}

export async function analyzeBoard(workspace: AnalysisWorkspace, detail: CoachDetail, signal: AbortSignal): Promise<PositionAnalysis> {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(`${CONTROL_URL}/api/analysis/position`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
      body: JSON.stringify({ rootFen: workspace.rootFen, moves: analysisPath(workspace).map(node => node.uci), detail }),
    });
    if (response.status === 404) throw new Error('The running Chess Coach backend is out of date. Stop the app in its Terminal window (Control-C), reopen Open Chess Coach.command, then retry analysis.');
    const data = await response.json();
    if (response.ok) return data;
    if (response.status !== 503 || !String(data.message).includes('engine is busy') || attempt >= 4) throw new Error(data.message || 'Analysis failed.');
    await new Promise<void>((resolve, reject) => {
      if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
      const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, 500 * (attempt + 1));
      function cancel() { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); }
      signal.addEventListener('abort', cancel, { once: true });
    });
  }
}

export async function watchAnalysis(workspace: AnalysisWorkspace, settings: {mode: 'depth' | 'unlimited'; depth: number}, signal: AbortSignal, onResult: (result: PositionAnalysis) => void): Promise<void> {
  const credentials = { id: crypto.randomUUID(), owner: searchOwner() };
  async function request(path: string, body: object) {
    const response = await fetch(`${CONTROL_URL}/api/analysis/search${path}`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body), signal,
    });
    if (response.status === 404) throw new Error('Restart the Chess Coach backend to enable depth and unlimited searches.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'Search failed.');
    return data as {running: boolean; result: PositionAnalysis | null; error: string | null};
  }
  try {
    let snapshot = await request('', { ...credentials, ...settings, rootFen: workspace.rootFen, moves: analysisPath(workspace).map(node => node.uci) });
    while (!signal.aborted) {
      if (snapshot.error) throw new Error(snapshot.error);
      if (snapshot.result) onResult(snapshot.result);
      if (!snapshot.running) return;
      await abortableDelay(500, signal);
      snapshot = await request('/status', credentials);
    }
  } finally {
    // Also stops a request that reached the server just before the fetch aborted.
    void fetch(`${CONTROL_URL}/api/analysis/search/stop`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(credentials),keepalive:true}).catch(()=>{});
  }
}
let owner: string | undefined;
function searchOwner() { return owner ||= crypto.randomUUID(); }
// Lazy so browsing/importing saved games does not need an engine session.
function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve,reject)=>{
    if (signal.aborted) { reject(new DOMException('Aborted','AbortError')); return; }
    const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},ms);
    signal.addEventListener('abort',cancel,{once:true});
  });
}
