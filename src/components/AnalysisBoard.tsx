import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { type Square } from 'chess.js';
import { ChessBoard } from './ChessBoard';
import { addAnalysisMove, analysisPath, analysisPosition, analysisPositionKey, analyzeBoard, watchAnalysis, evaluationWhitePercent, exportAnalysisPgn,
  formatEngineScore, importAnalysis,
  type AnalysisNode, type AnalysisWorkspace, type PositionAnalysis } from '../analysis';
import { downloadAnalysis, type AnalysisSave } from '../analysisLibrary';
import { ResizeHandle } from './ResizeHandle';

type Props = { save: AnalysisSave; onChange: (save: AnalysisSave) => boolean; onClose: () => void; onLibrary: () => void; onNew: () => void; onSaveAs: () => void; onSave: () => void; notice: string; liveGame: boolean };

export function AnalysisBoard({ save, onChange, onClose, onLibrary, onNew, onSaveAs, onSave, notice: savedNotice, liveGame }: Props) {
  const [titleText, setTitleText] = useState(save.title);
  useEffect(() => setTitleText(save.title), [save.title]);
  const workspace = save.workspace;
  const { orientation } = save.view;
  const detail = save.search.detail;
  function setWorkspace(next: AnalysisWorkspace) { onChange({ ...save, workspace: next }); }
  function setView(view: Partial<AnalysisSave['view']>) { onChange({ ...save, view: { ...save.view, ...view } }); }
  const [depthText, setDepthText] = useState(String(save.search.depth));
  const [engineEnabled, setEngineEnabled] = useState(true);
  const [completed, setCompleted] = useState<{ key: string; data: PositionAnalysis } | null>(null);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [rollback, setRollback] = useState(0);
  const [promotion, setPromotion] = useState<{ from: string; to: string } | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [positionText, setPositionText] = useState('');
  const [retry, setRetry] = useState(0);
  const node = workspace.nodes[workspace.current];
  const chess = useMemo(() => analysisPosition(workspace), [workspace]);
  const turn = chess.turn() === 'w' ? 'white' : 'black';
  const path = analysisPath(workspace);
  const positionKey = analysisPositionKey(workspace);
  const result = completed?.key === positionKey ? completed.data : null;
  const destinations = useMemo(() => {
    const moves = new Map<string, string[]>();
    for (const move of chess.moves({ verbose: true })) moves.set(move.from, [...(moves.get(move.from) || []), move.to]);
    return moves;
  }, [chess]);

  useEffect(() => {
    setPromotion(null); setRollback(value => value + 1);
  }, [workspace.current, workspace.rootFen]);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    if (!engineEnabled) { setThinking(false); return () => controller.abort(); }
    setThinking(true);
    const timer = window.setTimeout(() => {
      const update = (data: PositionAnalysis) => { if (!controller.signal.aborted) setCompleted({ key: positionKey, data }); };
      const request = save.search.mode === 'preset'
        ? analyzeBoard(workspace, detail, controller.signal).then(update)
        : watchAnalysis(workspace, { mode: save.search.mode, depth: save.search.depth }, controller.signal, update);
      void request.then(() => { if (!controller.signal.aborted) setThinking(false); }).catch(cause => {
        if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : String(cause)); setThinking(false); }
      });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [positionKey, detail, save.search.mode, save.search.depth, engineEnabled, retry]);

  function applyMove(uci: string) {
    try { setWorkspace(addAnalysisMove(workspace, uci)); setActionError(''); setNotice(''); }
    catch (cause) { setActionError(cause instanceof Error ? cause.message : String(cause)); setRollback(value => value + 1); }
    setPromotion(null);
  }

  function move(from: string, to: string) {
    const legal = chess.moves({ square: from as Square, verbose: true }).filter(move => move.to === to);
    if (!legal.length) { setRollback(value => value + 1); return; }
    if (legal.some(move => move.promotion)) {
      setPromotion({ from, to }); setRollback(value => value + 1);
    } else applyMove(from + to);
  }

  function loadPosition() {
    try { setWorkspace(importAnalysis(positionText)); setActionError(''); setNotice('Position loaded.'); setEditorOpen(false); }
    catch (cause) { setActionError(`Could not import: ${cause instanceof Error ? cause.message : String(cause)}`); }
  }

  async function copyPosition(kind: 'fen' | 'pgn') {
    const text = kind === 'fen' ? chess.fen() : exportAnalysisPgn(workspace);
    setPositionText(text); setEditorOpen(true);
    try { await navigator.clipboard.writeText(text); setNotice(`${kind.toUpperCase()} copied.`); }
    catch { setNotice(`Your ${kind.toUpperCase()} is in the text field below. Select it to copy.`); }
  }

  function playLine(moves: string[], count: number) {
    try {
      let next = workspace;
      for (const uci of moves.slice(0, count)) next = addAnalysisMove(next, uci);
      setWorkspace(next); setActionError(''); setNotice('Engine line added to your variations.');
    } catch (cause) { setActionError(cause instanceof Error ? cause.message : String(cause)); }
  }

  function variationButtons(parent: AnalysisNode, depth = 0): ReactNode {
    return parent.children.map((id, index) => {
      const child = workspace.nodes[id];
      const parts = parent.fen.split(' ');
      return <div key={id} className={`analysis-variation ${index > 0 ? 'alternative' : ''}`} style={{ marginLeft: index > 0 ? Math.min(depth + 1, 3) * 10 : 0 }}>
        <button className={`ghost ${workspace.current === id ? 'selected' : ''}`} aria-current={workspace.current === id ? 'step' : undefined}
          onClick={() => setWorkspace({ ...workspace, current: id })}>{parts[5]}{parts[1] === 'w' ? '.' : '...'} {child.san}</button>
        {index > 0 && <span className="variation-tag">Variation</span>}
        {variationButtons(child, depth + (index > 0 ? 1 : 0))}
      </div>;
    });
  }

  const advantage = evaluationWhitePercent(result);
  const score = result ? formatEngineScore(result.score, result) : '—';
  const bestUci = result?.lines[0]?.uci[0];

  return <>
      <div className="analysis-heading">
        <div><span className="eyebrow">EXPLORE · COMPARE · UNDERSTAND</span><h2 id="analysis-title">{save.title}</h2><p>{workspace.source}</p></div>
        <div className="analysis-heading-actions"><button className="ghost" onClick={onLibrary}>← Library</button><button className="ghost" onClick={onClose}>Back to {liveGame ? 'live game' : 'coach'}</button></div>
      </div>
      {liveGame && <p className="analysis-live-notice">Your live game and its clock continue while you analyze this copy.</p>}
      <div className="analysis-workspace-toolbar">
        <label>Save name <input aria-label="Save name" maxLength={120} value={titleText} onChange={event=>setTitleText(event.target.value)} onBlur={()=>onChange({...save,title:titleText})} onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();}}/></label>
        <button className="primary" onClick={onSave}>Save</button><button className="ghost" onClick={onSaveAs}>Save a copy</button><button className="ghost" onClick={()=>downloadAnalysis(save)}>Download PGN</button><button className="ghost" onClick={onNew}>＋ New analysis</button>
        <label>Board layout <select aria-label="Board layout" value={save.view.layout} onChange={event=>setView({layout:event.target.value as AnalysisSave['view']['layout']})}><option value="classic">Board left</option><option value="focus">Board right</option><option value="stacked">Stacked</option></select></label>
      </div>
      {savedNotice && <p className="fine-print" role="status">{savedNotice}</p>}
      <div className={`analysis-layout layout-${save.view.layout}`} style={{'--columns':save.view.layout==='focus' ? `minmax(280px, ${100-save.view.boardPercent}fr) 18px minmax(220px, ${save.view.boardPercent}fr)` : `minmax(220px, ${save.view.boardPercent}fr) 18px minmax(280px, ${100-save.view.boardPercent}fr)`,'--board-size':`${save.view.boardSize}px`} as CSSProperties}>
        <section className="analysis-board-column">
          <div className="analysis-board-row">
            <div className={`analysis-eval-bar ${orientation === 'black' ? 'flipped' : ''} ${advantage === null ? 'unknown' : ''}`} role="img" aria-label={advantage === null ? 'Evaluation unavailable for this position' : `Evaluation from White’s perspective: ${score}`}>
              {advantage !== null && <div style={{ height: `${advantage}%` }} />}
            </div>
            <div className="analysis-chess-wrap"><ChessBoard fen={node.fen} orientation={orientation}
              movableColor={!destinations.size || promotion ? undefined : turn} destinations={destinations}
              lastMove={node.uci ? [node.uci.slice(0, 2), node.uci.slice(2, 4)] : undefined}
              coachArrows={bestUci ? [{ from: bestUci.slice(0, 2), to: bestUci.slice(2, 4), kind: 'best' }] : []}
              coachHighlights={[]} rollbackSignal={rollback} onMove={move} /></div>
          </div>
          <div className="analysis-board-status"><strong>{chess.isCheckmate() ? 'Checkmate' : chess.isDraw() ? 'Draw' : `${turn === 'white' ? 'White' : 'Black'} to move${chess.isCheck() ? ' · Check' : ''}`}</strong><span>Moves stay on this analysis board.</span></div>
          {promotion && <div className="analysis-promotion" role="group" aria-label="Choose promotion piece">
            <span>Promote to</span>{(['q', 'r', 'b', 'n'] as const).map(piece => <button className="ghost" key={piece}
              onClick={() => applyMove(promotion.from + promotion.to + piece)}>{({ q: 'Queen', r: 'Rook', b: 'Bishop', n: 'Knight' })[piece]}</button>)}
            <button className="ghost" onClick={() => setPromotion(null)}>Cancel</button>
          </div>}
          <div className="analysis-navigation" aria-label="Analysis move navigation">
            <button className="ghost" disabled={workspace.current === 'root'} onClick={() => setWorkspace({ ...workspace, current: 'root' })}>Start</button>
            <button className="ghost" disabled={!node.parent} onClick={() => setWorkspace({ ...workspace, current: node.parent! })}>← Back</button>
            <button className="ghost" disabled={!node.children.length} onClick={() => setWorkspace({ ...workspace, current: node.children[0] })}>Forward →</button>
            <button className="ghost" onClick={() => setView({orientation:orientation === 'white' ? 'black' : 'white'})}>Flip board</button>
          </div>
          <p className="fine-print">Move either side to try an idea. Go back and choose another move to create a variation. Your branches are saved in this browser.</p>
        </section>
        <ResizeHandle label="Resize board and tools" axis={save.view.layout==='stacked'?'y':'x'} value={save.view.layout==='stacked'?save.view.boardSize:save.view.boardPercent} min={save.view.layout==='stacked'?240:25} max={save.view.layout==='stacked'?800:75} percent={save.view.layout!=='stacked'} reversed={save.view.layout==='focus'} onChange={value=>setView(save.view.layout==='stacked'?{boardSize:value}:{boardPercent:value})}/>
        <aside className="analysis-tools">
          <section className="card analysis-engine" style={{height:save.view.engineHeight}}>
            <div className="analysis-engine-heading"><h3>Stockfish</h3><label><input type="checkbox" checked={engineEnabled} onChange={event => setEngineEnabled(event.target.checked)} /> Engine</label></div>
            <div className="analysis-score" role="status"><strong>{score}</strong><span>{thinking ? result ? `Searching · Depth ${result.lines[0]?.depth || 0}` : 'Analyzing…' : !engineEnabled ? 'Engine paused' : error ? 'Analysis unavailable' : result?.terminal ? result.reason?.replaceAll('_', ' ') : result ? `Depth ${result.lines[0]?.depth || 0}` : 'Ready'}</span></div>
            <p className="fine-print">Positive scores favor White; negative scores favor Black. M means forced mate.</p>
            <label className="analysis-search-mode">Search mode <select aria-label="Search mode" value={save.search.mode} onChange={event=>{onChange({...save,search:{...save.search,mode:event.target.value as AnalysisSave['search']['mode']}});setEngineEnabled(true);}}><option value="preset">Time presets</option><option value="depth">Exact depth</option><option value="unlimited">Unlimited</option></select></label>
            {save.search.mode==='depth' && <div className="analysis-depth-control"><label>Target depth <input aria-label="Target depth" type="number" min="1" max="128" value={depthText} onChange={event=>setDepthText(event.target.value)}/></label><button className="ghost" onClick={()=>{const depth=Number(depthText);if(!Number.isInteger(depth)||depth<1||depth>128){setActionError('Enter a whole-number depth from 1 to 128.');return;}onChange({...save,search:{...save.search,depth}});setActionError('');setEngineEnabled(true);setRetry(value=>value+1);}}>Apply depth</button></div>}
            {save.search.mode==='unlimited' && <p className="fine-print">No depth or time cap. Results update until you stop, leave this page, or change the position.</p>}
            {save.search.mode!=='preset' && <button className="ghost" onClick={()=>{if(engineEnabled&&thinking)setEngineEnabled(false);else{setEngineEnabled(true);setRetry(value=>value+1);}}}>{engineEnabled&&thinking?'Stop search':'Resume search'}</button>}
            {save.search.mode==='preset' && <div className="analysis-detail" role="group" aria-label="Engine analysis effort">{(['quick', 'balanced', 'deep'] as const).map(value => <button
              className={`ghost ${detail === value ? 'selected' : ''}`} key={value} aria-pressed={detail === value} onClick={() => onChange({...save,search:{...save.search,detail:value}})}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div>}
            {result?.lines.map((line, lineIndex) => <div className="analysis-engine-line" key={lineIndex}>
              <strong>{formatEngineScore(line.score)}</strong>
              <div>{line.moves.map((san, index) => {
                const black = (chess.turn() === 'b' ? index % 2 === 0 : index % 2 === 1);
                const moveNumber = Number(node.fen.split(' ')[5]) + Math.floor((index + (chess.turn() === 'b' ? 1 : 0)) / 2);
                return <button key={index} title="Explore this continuation" onClick={() => playLine(line.uci, index + 1)}>{!black || index === 0 ? <span className="analysis-line-number">{moveNumber}{black ? '…' : '.'} </span> : null}{san}</button>;
              })}</div>
            </div>)}
            {result?.lines.length ? <p className="fine-print">Click a move in an engine line to explore up to that move.</p> : null}
            {error && <div className="inline-error" role="alert">{error}<button className="ghost" onClick={() => setRetry(value => value + 1)}>Retry analysis</button></div>}
          </section>
          <ResizeHandle label="Resize engine panel" axis="y" value={save.view.engineHeight} min={180} max={800} onChange={engineHeight=>setView({engineHeight})}/>
          <section className="card analysis-tree" style={{height:save.view.treeHeight}}><h3>Moves & variations</h3><button className={`ghost ${workspace.current === 'root' ? 'selected' : ''}`} onClick={() => setWorkspace({ ...workspace, current: 'root' })}>Starting position</button>
            {variationButtons(workspace.nodes.root)}{!workspace.nodes.root.children.length && <p className="fine-print">Make a move on the board to start exploring.</p>}
            <p className="fine-print">Selected path: {path.map(move => move.san).join(' ') || 'Starting position'}</p>
          </section>
          <ResizeHandle label="Resize variations panel" axis="y" value={save.view.treeHeight} min={140} max={800} onChange={treeHeight=>setView({treeHeight})}/>
          <section className="card analysis-position"><h3>Position tools</h3>
            <div className="analysis-navigation"><button className="ghost" onClick={() => void copyPosition('fen')}>Copy FEN</button><button className="ghost" onClick={() => void copyPosition('pgn')}>Copy PGN</button>
</div>
            <details open={editorOpen} onToggle={event => setEditorOpen(event.currentTarget.open)}><summary>Import FEN / PGN</summary>
              <label className="sense-label" htmlFor="analysis-position-text">Position or game text</label><textarea id="analysis-position-text" value={positionText} onChange={event => setPositionText(event.target.value)} rows={5} />
              <p className="fine-print">PGN imports its main line. PGN exports include your variation branches.</p>
              <button className="primary wide" onClick={loadPosition}>Load position / game</button>
            </details>{actionError && <p className="inline-error" role="alert">{actionError}</p>}{notice && <p className="fine-print" role="status">{notice}</p>}
          </section>
        </aside>
      </div>
  </>;
}
