import { exportAnalysisPgn, emptyAnalysis, readAnalysis, seedAnalysis, validateAnalysis, type AnalysisSeed, type AnalysisWorkspace } from './analysis';
import type { CoachDetail } from './coach';

export type SearchSettings = { mode: 'preset' | 'depth' | 'unlimited'; detail: CoachDetail; depth: number };
export type AnalysisView = { layout: 'classic' | 'focus' | 'stacked'; orientation: 'white' | 'black'; boardPercent: number; boardSize: number; engineHeight: number; treeHeight: number };
export type AnalysisSave = { id: string; title: string; kind: 'game' | 'analysis'; createdAt: number; updatedAt: number; revision: number; archived: boolean; workspace: AnalysisWorkspace; view: AnalysisView; search: SearchSettings };
export type AnalysisLibrary = { version: 2; saves: AnalysisSave[]; presentation: 'cards' | 'list' | 'compact' };
export const LIBRARY_KEY = 'ai-chess-coach.analysis-library.v2';
const defaults: AnalysisView = { layout: 'classic', orientation: 'white', boardPercent: 45, boardSize: 440, engineHeight: 380, treeHeight: 300 };
export function createAnalysisSave(seed?: AnalysisSeed | null, title?: string): AnalysisSave {
  const now = Date.now();
  return { id: crypto.randomUUID(), title: title || seed?.source || 'Untitled analysis', kind: seed?.sourceId && seed.source.startsWith('Copy of training game') ? 'game' : 'analysis',
    createdAt: now, updatedAt: now, revision: 0, archived: false,
    workspace: seed ? seedAnalysis(seed) : emptyAnalysis(), view: { ...defaults, orientation: seed?.orientation || 'white' },
    search: { mode: 'preset', detail: 'balanced', depth: 18 } };
}
function validSave(save: AnalysisSave): boolean {
  return Boolean(save && typeof save.id === 'string' && /^[a-zA-Z0-9-]{1,80}$/.test(save.id)
    && typeof save.title === 'string' && save.title.length <= 120 && typeof save.archived === 'boolean'
    && ['game','analysis'].includes(save.kind) && Number.isFinite(save.createdAt) && Number.isFinite(save.updatedAt)
    && Number.isInteger(save.revision) && save.revision >= 0 && validateAnalysis(save.workspace)
    && save.view && ['classic','focus','stacked'].includes(save.view.layout) && ['white','black'].includes(save.view.orientation)
    && Number.isFinite(save.view.boardPercent) && save.view.boardPercent >= 25 && save.view.boardPercent <= 75
    && Number.isFinite(save.view.boardSize) && save.view.boardSize >= 240 && save.view.boardSize <= 800
    && Number.isFinite(save.view.engineHeight) && save.view.engineHeight >= 180 && save.view.engineHeight <= 800
    && Number.isFinite(save.view.treeHeight) && save.view.treeHeight >= 140 && save.view.treeHeight <= 800
    && save.search && ['preset','depth','unlimited'].includes(save.search.mode) && ['quick','balanced','deep'].includes(save.search.detail)
    && Number.isInteger(save.search.depth) && save.search.depth >= 1 && save.search.depth <= 128);
}
export function readAnalysisLibrary(): AnalysisLibrary {
  const raw = localStorage.getItem(LIBRARY_KEY);
  if (raw) {
    const library = JSON.parse(raw) as AnalysisLibrary;
    if (library.version !== 2 || !Array.isArray(library.saves) || !library.saves.every(validSave)
      || new Set(library.saves.map(save => save.id)).size !== library.saves.length) throw new Error('The saved library could not be read. Export your current work before changing browser storage.');
    return { ...library, presentation: ['cards','list','compact'].includes(library.presentation) ? library.presentation : 'cards' };
  }
  const legacy = readAnalysis();
  const saves: AnalysisSave[] = [];
  if (legacy) { const save = createAnalysisSave(null,'Recovered analysis'); save.id = 'recovered-draft'; save.workspace = legacy; saves.push(save); }
  return { version: 2, saves, presentation: 'cards' };
}
export function writeAnalysisSave(save: AnalysisSave): AnalysisLibrary {
  if (!validSave(save)) throw new Error('This save contains invalid analysis data.');
  const library = readAnalysisLibrary();
  const existing = library.saves.find(item => item.id === save.id);
  if (existing && existing.revision !== save.revision) throw new Error('This save changed in another tab. Your local work is still open; download its PGN before reopening that save.');
  if (!existing && library.saves.length >= 100) throw new Error('This browser library has reached 100 saves. Download a PGN backup before clearing browser storage.');
  const updated = { ...save, title: save.title.trim() || 'Untitled analysis', updatedAt: Date.now(), revision: save.revision + 1 };
  const next = { ...library, saves: [...library.saves.filter(item => item.id !== save.id), updated] };
  localStorage.setItem(LIBRARY_KEY, JSON.stringify(next));
  return next;
}
export function writeLibraryPresentation(presentation: AnalysisLibrary['presentation']): AnalysisLibrary {
  const next = { ...readAnalysisLibrary(), presentation };
  localStorage.setItem(LIBRARY_KEY, JSON.stringify(next));
  return next;
}
export function analysisRoute(): string | null {
  const match = /^#analysis(?:\/([a-zA-Z0-9-]{1,80}))?$/.exec(window.location.hash);
  return match ? match[1] || '' : null;
}
export function goToAnalysis(id = '') { window.location.hash = `analysis${id ? `/${id}` : ''}`; }

export function downloadAnalysis(save: AnalysisSave) {
  const blob = new Blob([exportAnalysisPgn(save.workspace)], {type:'application/x-chess-pgn'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = `${save.title.replace(/[^a-zA-Z0-9 _-]/g,'').slice(0,80) || 'analysis'}.pgn`;
  link.click(); window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
