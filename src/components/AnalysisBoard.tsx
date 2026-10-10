import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { type Square } from 'chess.js';
import { ChessBoard } from './ChessBoard';
import { addAnalysisMove, analysisPath, analysisPosition, analysisPositionKey, analyzeBoard, emptyAnalysis, evaluationWhitePercent, exportAnalysisPgn,
  formatEngineScore, importAnalysis, readAnalysis, saveAnalysis, seedAnalysis,
  type AnalysisNode, type AnalysisSeed, type PositionAnalysis } from '../analysis';
import type { CoachDetail } from '../coach';

type Props = { seed: AnalysisSeed | null; onClose: () => void; liveGame: boolean };

export function AnalysisBoard({ seed, onClose, liveGame }: Props) {
  const [workspace, setWorkspace] = useState(() => seed ? seedAnalysis(seed, readAnalysis()) : readAnalysis() || emptyAnalysis());
  const [orientation, setOrientation] = useState<'white' | 'black'>(seed?.orientation || 'white');
  const [detail, setDetail] = useState<CoachDetail>('balanced');
  const [engineEnabled, setEngineEnabled] = useState(true);
  const [completed, setCompleted] = useState<{ key: string; data: PositionAnalysis } | null>(null);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [unsaved, setUnsaved] = useState(false);
  const [rollback, setRollback] = useState(0);
  const [promotion, setPromotion] = useState<{ from: string; to: string } | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [positionText, setPositionText] = useState('');
  const [retry, setRetry] = useState(0);
  const dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
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

  useEffect(() => { setUnsaved(!saveAnalysis(workspace)); }, [workspace]);
  useEffect(() => {
    setPromotion(null); setRollback(value => value + 1);
  }, [workspace.current, workspace.rootFen]);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    if (!engineEnabled) { setThinking(false); return () => controller.abort(); }
    setThinking(true);
    const timer = window.setTimeout(() => {
      void analyzeBoard(workspace, detail, controller.signal).then(data => {
        if (!controller.signal.aborted) { setCompleted({ key: positionKey, data }); setThinking(false); }
      }).catch(cause => {
        if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : String(cause)); setThinking(false); }
      });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [positionKey, detail, engineEnabled, retry]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const backdrop = dialog.current?.parentElement;
    const siblings = Array.from(backdrop?.parentElement?.children || []).filter(element => element !== backdrop) as HTMLElement[];
    const inert = siblings.map(element => element.inert);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    siblings.forEach(element => { element.inert = true; });
    dialog.current?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') { closeRef.current(); return; }
      if (event.key !== 'Tab') return;
      const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, select, summary') || [])
        .filter(element => element.getClientRects().length > 0);
      if (event.shiftKey && (document.activeElement === controls[0] || document.activeElement === dialog.current)) {
        event.preventDefault(); controls.at(-1)?.focus();
      } else if (!event.shiftKey && document.activeElement === controls.at(-1)) {
        event.preventDefault(); controls[0]?.focus();
      }
    }
    document.addEventListener('keydown', key);
    return () => {
      document.body.style.overflow = overflow;
      siblings.forEach((element, index) => { element.inert = inert[index]; });
      document.removeEventListener('keydown', key); previous?.focus();
    };
  }, []);

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

  return <div className="analysis-backdrop">
    <div className="analysis-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-title" tabIndex={-1} ref={dialog}>
      <div className="analysis-heading">
        <div><span className="eyebrow">EXPLORE · COMPARE · UNDERSTAND</span><h2 id="analysis-title">Analysis board</h2><p>{workspace.source}</p></div>
        <button className="ghost" onClick={onClose}>Back to {liveGame ? 'live game' : 'coach'}</button>
      </div>
      {liveGame && <p className="analysis-live-notice">Your live game and its clock continue while you analyze this copy.</p>}
      <div className="analysis-layout">
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
            <button className="ghost" onClick={() => setOrientation(orientation === 'white' ? 'black' : 'white')}>Flip board</button>
          </div>
          <p className="fine-print">Move either side to try an idea. Go back and choose another move to create a variation. Your branches are saved in this browser.</p>
          {unsaved && <p className="inline-error">Browser storage is unavailable. Export your PGN before closing to preserve these variations.</p>}
        </section>
        <aside className="analysis-tools">
          <section className="card analysis-engine">
            <div className="analysis-engine-heading"><h3>Stockfish</h3><label><input type="checkbox" checked={engineEnabled} onChange={event => setEngineEnabled(event.target.checked)} /> Engine</label></div>
            <div className="analysis-score" role="status"><strong>{score}</strong><span>{thinking ? result ? 'Updating analysis…' : 'Analyzing…' : !engineEnabled ? 'Engine paused' : error ? 'Analysis unavailable' : result?.terminal ? result.reason?.replaceAll('_', ' ') : result ? `Depth ${result.lines[0]?.depth || 0}` : 'Ready'}</span></div>
            <p className="fine-print">Positive scores favor White; negative scores favor Black. M means forced mate.</p>
            <div className="analysis-detail" role="group" aria-label="Engine analysis effort">{(['quick', 'balanced', 'deep'] as const).map(value => <button
              className={`ghost ${detail === value ? 'selected' : ''}`} key={value} aria-pressed={detail === value} onClick={() => setDetail(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div>
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
          <section className="card analysis-tree"><h3>Moves & variations</h3><button className={`ghost ${workspace.current === 'root' ? 'selected' : ''}`} onClick={() => setWorkspace({ ...workspace, current: 'root' })}>Starting position</button>
            {variationButtons(workspace.nodes.root)}{!workspace.nodes.root.children.length && <p className="fine-print">Make a move on the board to start exploring.</p>}
            <p className="fine-print">Selected path: {path.map(move => move.san).join(' ') || 'Starting position'}</p>
          </section>
          <section className="card analysis-position"><h3>Position tools</h3>
            <div className="analysis-navigation"><button className="ghost" onClick={() => void copyPosition('fen')}>Copy FEN</button><button className="ghost" onClick={() => void copyPosition('pgn')}>Copy PGN</button>
              <button className="ghost" onClick={() => { setWorkspace(emptyAnalysis()); setActionError(''); setNotice('New board ready.'); }}>New board</button></div>
            <details open={editorOpen} onToggle={event => setEditorOpen(event.currentTarget.open)}><summary>Import FEN / PGN</summary>
              <label className="sense-label" htmlFor="analysis-position-text">Position or game text</label><textarea id="analysis-position-text" value={positionText} onChange={event => setPositionText(event.target.value)} rows={5} />
              <p className="fine-print">PGN imports its main line. PGN exports include your variation branches.</p>
              <button className="primary wide" onClick={loadPosition}>Load position / game</button>
            </details>{actionError && <p className="inline-error" role="alert">{actionError}</p>}{notice && <p className="fine-print" role="status">{notice}</p>}
          </section>
        </aside>
      </div>
    </div>
  </div>;
}
