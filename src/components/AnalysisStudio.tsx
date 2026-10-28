import { useEffect, useRef, useState } from 'react';
import { Chess } from 'chess.js';
import { AnalysisBoard } from './AnalysisBoard';
import { seedAnalysis, type AnalysisSeed } from '../analysis';
import { downloadAnalysis, analysisRoute, createAnalysisSave, goToAnalysis, readAnalysisLibrary, writeAnalysisSave, writeLibraryPresentation, type AnalysisLibrary, type AnalysisSave } from '../analysisLibrary';

function MiniBoard({ save }: {save: AnalysisSave}) {
  const rows = new Chess(save.workspace.nodes[save.workspace.current].fen).board();
  if (save.view.orientation === 'black') { rows.reverse(); rows.forEach(row=>row.reverse()); }
  const glyphs = {w:{k:'♔',q:'♕',r:'♖',b:'♗',n:'♘',p:'♙'},b:{k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'}};
  return <svg className="analysis-mini-board" viewBox="0 0 80 80" role="img" aria-label="Saved board position">{rows.flatMap((row,y)=>row.map((piece,x)=><g key={`${x}-${y}`}><rect x={x*10} y={y*10} width="10" height="10" fill={(x+y)%2 ? '#b58863':'#f0d9b5'}/>{piece && <text x={x*10+5} y={y*10+8} textAnchor="middle" fontSize="10" fill={piece.color === 'w' ? '#fff':'#171511'} stroke={piece.color==='w'?'#333':'none'} strokeWidth=".15">{glyphs[piece.color][piece.type]}</text>}</g>))}</svg>;
}
export function AnalysisStudio({ seed, onClose, liveGame }: {seed: AnalysisSeed | null; onClose:()=>void; liveGame:boolean}) {
  const [loaded] = useState(()=>{try{return {library:readAnalysisLibrary(),error:''};}catch(cause){return {library:{version:2,saves:[],presentation:'cards'} as AnalysisLibrary,error:String(cause)};}});
  const [library,setLibrary]=useState(loaded.library);
  const [error,setError]=useState(loaded.error);
  const [activeId,setActiveId]=useState(analysisRoute() || '');
  const [query,setQuery]=useState('');
  const [showArchived,setShowArchived]=useState(false);
  const [notice,setNotice]=useState('');
  const seeded=useRef(false);
  const panel=useRef<HTMLDivElement>(null);
  const closeRef=useRef(onClose); closeRef.current=onClose;
  function persist(save:AnalysisSave): boolean {
    try { setLibrary(writeAnalysisSave(save)); setError(''); return true; }
    catch(cause) { setLibrary(previous=>({...previous,saves:[...previous.saves.filter(item=>item.id!==save.id),save]})); setError(`Not saved: ${cause instanceof Error ? cause.message : String(cause)}`); return false; }
  }
  function open(id='') {setActiveId(id);goToAnalysis(id);setNotice('');}
  function add(seed?:AnalysisSeed|null) {
    const save=createAnalysisSave(seed,seed?.source || `Analysis ${library.saves.length+1}`);
    persist(save);open(save.id);
  }
  useEffect(()=>{
    if (!seed || seeded.current) return;
    seeded.current=true;
    try {
      const existing=library.saves.find(item=>!item.archived && seed.sourceId && item.workspace.sourceId===seed.sourceId && item.workspace.rootFen===new Chess(seed.rootFen).fen());
      const save=existing ? {...existing,workspace:seedAnalysis(seed,existing.workspace)} : createAnalysisSave(seed);
      persist(save);open(save.id);
    } catch(cause) {setError(String(cause));}
  },[seed]);
  useEffect(()=>{
    const change=()=>setActiveId(analysisRoute() || '');
    window.addEventListener('hashchange',change);
    return ()=>window.removeEventListener('hashchange',change);
  },[]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const siblings=Array.from(panel.current?.parentElement?.parentElement?.children || []).filter(el=>el!==panel.current?.parentElement) as HTMLElement[];
    const inert=siblings.map(el=>el.inert);const overflow=document.body.style.overflow;
    siblings.forEach(el=>{el.inert=true;});document.body.style.overflow='hidden';panel.current?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){closeRef.current();return;}
      if(event.key!=='Tab')return;
      const controls=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input,textarea,select,summary,[role="separator"]') || []).filter(el=>el.getClientRects().length>0);
      if(event.shiftKey&&(document.activeElement===controls[0]||document.activeElement===panel.current)){event.preventDefault();controls.at(-1)?.focus();}
      else if(!event.shiftKey&&document.activeElement===controls.at(-1)){event.preventDefault();controls[0]?.focus();}
    };
    document.addEventListener('keydown',key);
    return ()=>{siblings.forEach((el,i)=>{el.inert=inert[i];});document.body.style.overflow=overflow;document.removeEventListener('keydown',key);previous?.focus();};
  },[]);
  useEffect(()=>{panel.current?.scrollTo(0,0);panel.current?.focus();},[activeId]);
  const active=library.saves.find(item=>item.id===activeId && !item.archived);
  const saves=library.saves.filter(save=>save.archived===showArchived && `${save.title} ${save.workspace.source}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>b.updatedAt-a.updatedAt);
  return <div className="analysis-backdrop"><div className="analysis-modal analysis-studio" role="dialog" aria-modal="true" aria-labelledby="analysis-title" tabIndex={-1} ref={panel}>
    {error && <p className="inline-error" role="alert">{error} {active && <button className="ghost" onClick={()=>downloadAnalysis(active)}>Download PGN backup</button>}</p>}
    {active ? <AnalysisBoard key={active.id} save={active} onChange={persist} onClose={onClose} onLibrary={()=>open()} liveGame={liveGame}
      onNew={()=>add()} onSaveAs={()=>{const copy={...active,id:crypto.randomUUID(),revision:0,title:`${active.title} (copy)`.slice(0,120),createdAt:Date.now(),workspace:{...active.workspace,sourceId:''}};persist(copy);open(copy.id);}}
      onSave={()=>{if(persist(active))setNotice('Saved to this browser.');}} notice={notice}/>
      : <>
        <div className="analysis-heading"><div><span className="eyebrow">YOUR GAMES · YOUR IDEAS</span><h2 id="analysis-title">Analysis library</h2><p>Every save has its own board, variations, search settings, and layout.</p></div><button className="ghost" onClick={onClose}>Back to coach</button></div>
        {activeId && <p role="status" className="inline-error">This save is unavailable or archived. Choose a saved page below.</p>}
        {liveGame && <p className="analysis-live-notice">Your live game and its clock continue while you browse.</p>}
        <div className="analysis-library-toolbar"><button className="primary" onClick={()=>add()}>＋ New analysis</button><input aria-label="Search saved analyses" placeholder="Search games and analyses…" value={query} onChange={event=>setQuery(event.target.value)}/>
          <label>Library layout <select value={library.presentation} onChange={event=>{try{setLibrary(writeLibraryPresentation(event.target.value as AnalysisLibrary['presentation']));setError('');}catch(cause){setError(String(cause));}}}><option value="cards">Cards</option><option value="list">List</option><option value="compact">Compact</option></select></label>
          <button className="ghost" aria-pressed={showArchived} onClick={()=>setShowArchived(!showArchived)}>{showArchived?'Show active saves':'Archive'}</button></div>
        <p className="fine-print">Saved locally in this browser. Download PGN files for portable backups. Editing a page autosaves; Save a copy keeps an independent version.</p>
        <div className={`analysis-library-grid ${library.presentation}`}>{saves.map(save=><article className="card analysis-save-card" key={save.id}>
          <button className="analysis-open-save" onClick={()=>open(save.id)} disabled={save.archived}><MiniBoard save={save}/><div><h3>{save.title}</h3><p>{save.kind==='game'?'Saved game':'Analysis'} · {Object.keys(save.workspace.nodes).length-1} moves</p><small>{new Date(save.updatedAt).toLocaleString()}</small></div></button>
          <div className="analysis-save-actions">{save.archived ? <button className="ghost" onClick={()=>persist({...save,archived:false})}>Restore</button> : <button className="ghost" onClick={()=>open(save.id)}>Open →</button>}<button className="ghost" onClick={()=>downloadAnalysis(save)}>Download PGN</button>{!save.archived && <button className="ghost" onClick={()=>persist({...save,archived:true})}>Archive</button>}</div>
        </article>)}</div>
        {!saves.length && <div className="analysis-library-empty"><h3>{showArchived?'No archived saves':query?'No matching saves':'A home for your chess ideas'}</h3><p>{showArchived?'Archived pages can be restored here.':'Add an analysis, import a PGN on its page, or use Save game after a training game.'}</p>{!showArchived&&!query&&<button className="primary" onClick={()=>add()}>Add your first analysis</button>}</div>}
      </>}
  </div></div>;
}
