import { useEffect, useMemo, useRef, useState } from 'react';
import { KIND_LABEL, type CatalogEntry } from '../domain/catalog';
import { exportShow } from '../domain/library';
import { buildTimeline, clampDuration, cueFromEntry, cueTitle, duplicateCue, formatDuration, LIMITS, moveCue, requiredKinds, type Cue, type Score } from '../domain/score';
import type { Studio } from '../useStudio';
import { KindChip, ViewHeader } from '../components/bits';
import { PreviewPanel } from '../components/PreviewPanel';
import { matchesSearch } from './ActionsView';

/** Keeps typing local and commits on blur, so a half-typed value is never saved. */
function CommitInput({ value, onCommit, ...rest }: { value: string; onCommit: (value: string) => void } & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return <input {...rest} value={draft} onChange={event => setDraft(event.target.value)}
    onBlur={() => { if (draft !== value) onCommit(draft); }}
    onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} />;
}

function CueRow({ cue, index, count, readOnly, blocker, onChange, onMove, onDuplicate, onRemove }: {
  cue: Cue; index: number; count: number; readOnly: boolean; blocker?: string;
  onChange: (cue: Cue) => void; onMove: (delta: number) => void; onDuplicate: () => void; onRemove: () => void;
}) {
  const hasDuration = cue.type === 'face' || cue.type === 'wait';
  return (
    <li className={`cue-row cue-${cue.type}`}>
      <span className="cue-index">{index + 1}</span>
      <div className="cue-main">
        <div className="cue-title"><KindChip kind={cue.type} /> <strong>{cueTitle(cue)}</strong></div>
        {!readOnly
          ? <CommitInput className="cue-caption" value={cue.caption ?? ''} maxLength={LIMITS.captionLength} placeholder="Stage note" aria-label={`Stage note for cue ${index + 1}`}
              onCommit={text => { const { caption: _omit, ...rest } = cue; onChange(text.trim() ? { ...rest, caption: text } as Cue : rest as Cue); }} />
          : cue.caption && <p className="fine">{cue.caption}</p>}
        {blocker && <p className="cue-blocker">{blocker}</p>}
      </div>
      <div className="cue-duration">
        {hasDuration && !readOnly
          ? <label>
              <span className="sr-only">Seconds for cue {index + 1}</span>
              <CommitInput type="number" inputMode="decimal" step="0.5" value={String(cue.durationMs / 1000)}
                onCommit={text => onChange({ ...cue, durationMs: clampDuration(cue, Number(text) * 1000) })} />
              <span>s</span>
            </label>
          : <span className="fine">{hasDuration ? formatDuration(cue.durationMs) : 'Preset length'}</span>}
      </div>
      {!readOnly && (
        <div className="cue-tools">
          <button className="icon-btn" disabled={index === 0} aria-label={`Move cue ${index + 1} up`} onClick={() => onMove(-1)}>↑</button>
          <button className="icon-btn" disabled={index === count - 1} aria-label={`Move cue ${index + 1} down`} onClick={() => onMove(1)}>↓</button>
          <button className="icon-btn" aria-label={`Duplicate cue ${index + 1}`} onClick={onDuplicate}>⧉</button>
          <button className="icon-btn danger" aria-label={`Remove cue ${index + 1}`} onClick={onRemove}>✕</button>
        </div>
      )}
    </li>
  );
}

function CuePicker({ catalog, onAdd }: { catalog: CatalogEntry[]; onAdd: (entry: CatalogEntry) => void }) {
  const [query, setQuery] = useState('');
  const options = useMemo(() => catalog.filter(entry => matchesSearch(entry, query)), [catalog, query]);
  return (
    <section className="card picker" aria-label="Add a cue">
      <h3>Add a cue</h3>
      <input className="search" type="search" value={query} placeholder="Search faces and actions" aria-label="Search cues" onChange={event => setQuery(event.target.value)} />
      <ul className="picker-list">
        {options.slice(0, 80).map(entry => {
          const addable = cueFromEntry(entry) !== null;
          return (
            <li key={entry.id}>
              <button className="picker-item" disabled={!addable} title={addable ? undefined : entry.note} onClick={() => onAdd(entry)}>
                <span className={`pip kind-${entry.kind}`} aria-hidden="true" />
                <span className="picker-label">{entry.label}<small>{addable ? `${KIND_LABEL[entry.kind]} · ${entry.resource}` : `${KIND_LABEL[entry.kind]}: not available yet`}</small></span>
                {addable && <span aria-hidden="true">+</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Editor({ show, studio, onStage }: { show: Score; studio: Studio; onStage: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const readOnly = show.origin !== 'custom';
  const timeline = useMemo(() => buildTimeline(show), [show]);
  const admission = studio.admission(show);
  const blockers = new Map(admission.blockers.map(blocker => [blocker.cueId, blocker.reason]));
  const kinds = requiredKinds(show);
  const edit = (change: Parameters<Studio['editShow']>[1]) => setError(studio.editShow(show, change));
  const setCues = (cues: Cue[]) => edit({ cues });

  function exportFile() {
    const url = URL.createObjectURL(new Blob([exportShow(show)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${show.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase() || 'show'}.vbotshow.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="editor">
      <div className="editor-main">
        <section className="card">
          <div className="editor-head">
            {readOnly
              ? <h2>{show.title}</h2>
              : <CommitInput className="title-input" aria-label="Show title" maxLength={LIMITS.titleLength} value={show.title}
                  onCommit={title => { if (title.trim()) edit({ title }); else setError('A show needs a title.'); }} />}
            <div className="editor-tools">
              <button className="btn btn-small" onClick={() => studio.saveAs(show, `${show.title.slice(0, LIMITS.titleLength - 5)} copy`)}>{readOnly ? 'Make my copy' : 'Save as copy'}</button>
              <button className="btn btn-small" onClick={exportFile}>Export</button>
              {!readOnly && <button className="btn btn-small danger" onClick={() => { if (window.confirm(`Delete “${show.title}”?`)) studio.removeShow(show); }}>Delete</button>}
            </div>
          </div>
          {readOnly && <p className="fine">Built-in show. Make a copy to change it.</p>}
          {show.notes && <p className="show-notes">{show.notes}</p>}
          <div className="show-facts">
            <span>{formatDuration(timeline.totalMs)}</span>
            <span>{timeline.items.length} cues</span>
            <span className="needs">Needs: {kinds.length ? kinds.map(kind => <KindChip key={kind} kind={kind} />) : 'nothing yet'}</span>
            {!readOnly && (
              <label className="repeat">Repeat
                <select value={show.repeat} onChange={event => edit({ repeat: Number(event.target.value) })}>
                  {Array.from({ length: LIMITS.maxRepeat }, (_, i) => i + 1).map(count => <option key={count} value={count}>{count}×</option>)}
                </select>
              </label>
            )}
            {!readOnly && <span className="saved" role="status">Saved · revision {show.revision}</span>}
          </div>
          {error && <p className="notice notice-warn" role="alert">{error}</p>}
          {show.cues.length === 0
            ? <p className="empty">No cues yet. Add one from the list.</p>
            : <ol className="cue-list">
                {show.cues.map((cue, index) => (
                  <CueRow key={cue.id} cue={cue} index={index} count={show.cues.length} readOnly={readOnly} blocker={blockers.get(cue.id)}
                    onChange={next => setCues(show.cues.map(item => item.id === cue.id ? next : item))}
                    onMove={delta => setCues(moveCue(show.cues, index, delta))}
                    onDuplicate={() => setCues(duplicateCue(show.cues, index))}
                    onRemove={() => setCues(show.cues.filter(item => item.id !== cue.id))} />
                ))}
              </ol>}
        </section>
        <PreviewPanel score={show} />
        <div className="send-row">
          {!admission.ok && show.cues.length > 0 && <p className="fine">Can’t run yet: {admission.blockers.length} cue(s) are blocked. Each one shows why.</p>}
          <button className="btn btn-primary" onClick={onStage}>Go to Stage</button>
        </div>
      </div>
      {!readOnly && <CuePicker catalog={studio.catalog} onAdd={entry => {
        const cue = cueFromEntry(entry);
        if (cue) setCues([...show.cues, cue]);
      }} />}
    </div>
  );
}

export function PerformancesView({ studio, onStage }: { studio: Studio; onStage: () => void }) {
  const { library, selected } = studio;
  const [importErrors, setImportErrors] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  async function onImportFile(file: File | undefined) {
    if (!file) return;
    const result = studio.importText(await file.text());
    setImportErrors(result.ok ? [] : result.errors);
    if (fileInput.current) fileInput.current.value = '';
  }

  const list = (title: string, shows: readonly Score[]) => (
    <div className="library-group">
      <h2>{title}</h2>
      {shows.length === 0 && <p className="fine">Nothing here yet.</p>}
      {shows.map(show => (
        <button key={show.id} className="library-item" aria-current={selected?.id === show.id ? 'true' : undefined} onClick={() => studio.select(show.id)}>
          <strong>{show.title}</strong>
          <small>{show.cues.length} cues · {formatDuration(buildTimeline(show).totalMs)}</small>
        </button>
      ))}
    </div>
  );

  return (
    <div className="view">
      <ViewHeader title="Shows" subtitle="Saved shows and your own sequences. Editing a show never changes a run already in progress."
        actions={<>
          <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={event => void onImportFile(event.target.files?.[0])} />
          <button className="btn" onClick={() => fileInput.current?.click()}>Import</button>
          <button className="btn btn-primary" onClick={() => studio.createShow()}>New show</button>
        </>} />
      {importErrors.length > 0 && (
        <div className="notice notice-warn" role="alert">
          <strong>That file wasn’t imported, and nothing changed.</strong>
          <ul>{importErrors.slice(0, 6).map(text => <li key={text}>{text}</li>)}</ul>
        </div>
      )}
      <div className="shows-layout">
        <aside className="library">
          {list('Built in', library.canned)}
          {list('My shows', library.shows)}
        </aside>
        {selected
          ? <Editor key={selected.id} show={selected} studio={studio} onStage={onStage} />
          : <div className="card empty-card"><h2>Pick a show</h2><p>Open a built-in show, or start a new one.</p></div>}
      </div>
    </div>
  );
}
