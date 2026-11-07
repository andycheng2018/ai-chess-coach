import { useMemo, useState } from 'react';
import { KIND_LABEL, type CapabilityKind, type CatalogEntry } from '../domain/catalog';
import { admitScore, cueFromEntry, formatDuration, makeScore } from '../domain/score';
import type { Studio } from '../useStudio';
import { KindChip, VerificationTag, ViewHeader } from '../components/bits';
import { FacePreview } from '../components/FacePreview';
import { DrivePad } from '../components/DrivePad';
import { MovePad } from '../components/MovePad';

const FILTERS: readonly (CapabilityKind | 'all' | 'favorites')[] = ['all', 'favorites', 'face', 'head', 'body', 'move', 'speech', 'navigation'];
const filterLabel = (id: (typeof FILTERS)[number]) => id === 'all' ? 'All' : id === 'favorites' ? 'Favorites' : KIND_LABEL[id];

export function matchesSearch(entry: CatalogEntry, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return !needle || [entry.label, entry.resource, entry.category, KIND_LABEL[entry.kind]].some(text => text.toLowerCase().includes(needle));
}

export function ActionsView({ studio }: { studio: Studio }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const { library, snapshot, selected, catalog } = studio;

  const visible = useMemo(() => catalog.filter(entry => {
    if (entry.kind === 'wait' || !matchesSearch(entry, query)) return false;
    if (filter === 'favorites') return library.favorites.has(entry.id);
    return filter === 'all' || entry.kind === filter;
  }), [catalog, query, filter, library.favorites]);

  const groups = useMemo(() => {
    const byCategory = new Map<string, CatalogEntry[]>();
    for (const entry of visible) byCategory.set(`${entry.kind}|${entry.category}`, [...(byCategory.get(`${entry.kind}|${entry.category}`) ?? []), entry]);
    return [...byCategory.entries()];
  }, [visible]);

  const editable = selected?.origin === 'custom' ? selected : null;

  function reasonFor(entry: CatalogEntry): string | null {
    if (entry.kind === 'speech' || entry.kind === 'navigation') return snapshot.capabilities[entry.kind].reason;
    const cue = cueFromEntry(entry);
    if (!cue) return 'This action can’t be used yet.';
    const result = admitScore(makeScore('check', 0, [cue]), snapshot.capabilities);
    return result.ok ? null : result.blockers[0].reason;
  }

  return (
    <div className="view">
      <ViewHeader title="Expressions & actions" subtitle="Faces only change the screen. Head, body and move actions physically move the dog, even when they share a name." />
      <DrivePad studio={studio} />
      <MovePad studio={studio} />
      <div className="toolbar">
        <input className="search" type="search" value={query} placeholder="Search actions" aria-label="Search actions" onChange={event => setQuery(event.target.value)} />
        <div className="filter-row" role="group" aria-label="Filter by type">
          {FILTERS.map(id => <button key={id} className="filter" aria-pressed={filter === id} onClick={() => setFilter(id)}>{filterLabel(id)}</button>)}
        </div>
      </div>
      <p className="fine">{editable ? `+ Show adds to “${editable.title}”.` : 'Open one of your shows under Shows to add actions to it.'}</p>
      {groups.length === 0 && <p className="empty">{filter === 'favorites' ? 'No favorites yet. Tap a star to save an action here.' : 'Nothing matches that search.'}</p>}
      {groups.map(([key, entries]) => (
        <section key={key} className="catalog-group">
          <h2><KindChip kind={entries[0].kind} /> {entries[0].category} <small>{entries.length}</small></h2>
          <div className="tile-grid">
            {entries.map(entry => {
              const reason = reasonFor(entry);
              const cue = cueFromEntry(entry);
              const favorite = library.favorites.has(entry.id);
              return (
                <article key={entry.id} className={`tile tile-${entry.kind}`}>
                  <button className={`star ${favorite ? 'is-on' : ''}`} aria-pressed={favorite} aria-label={`${favorite ? 'Remove' : 'Add'} ${entry.label} ${favorite ? 'from' : 'to'} favorites`} onClick={() => studio.toggleFavorite(entry.id)}>{favorite ? '★' : '☆'}</button>
                  {entry.kind === 'face' ? <FacePreview label={entry.label} playing={false} size="small" /> : <div className="tile-glyph" aria-hidden="true">{entry.kind === 'head' ? '↻' : entry.kind === 'body' ? '⇅' : entry.kind === 'move' ? '⇄' : '…'}</div>}
                  <h3>{entry.label}</h3>
                  <p className="mono tile-res">{entry.resource}</p>
                  <div className="tile-meta">
                    <KindChip kind={entry.kind} />
                    {entry.durationMs !== null && <span className="fine">{entry.kind === 'face' ? 'Default ' : 'Measured '}{formatDuration(entry.durationMs)}</span>}
                  </div>
                  <VerificationTag value={entry.verification} />
                  {reason && <p className="tile-reason">{reason}</p>}
                  <div className="tile-actions">
                    <button className="btn btn-small" disabled={Boolean(reason) || studio.running || studio.sending || !cue}
                      onClick={() => void studio.tryEntry(entry)}>Try</button>
                    <button className="btn btn-small" disabled={!editable || !cue}
                      onClick={() => { if (editable && cue) studio.editShow(editable, { cues: [...editable.cues, cue] }); }}>+ Show</button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
