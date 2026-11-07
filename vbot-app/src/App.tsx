import { useState } from 'react';
import { useStudio } from './useStudio';
import { DogView } from './views/DogView';
import { ActionsView } from './views/ActionsView';
import { PerformancesView } from './views/PerformancesView';
import { StageView } from './views/StageView';
import { PlayerView } from './views/PlayerView';
import { RunSheet } from './components/RunSheet';

type Tab = 'dog' | 'actions' | 'shows' | 'stage' | 'player';

const TABS: readonly { id: Tab; label: string; icon: string }[] = [
  { id: 'dog', label: 'Dog', icon: '◉' },
  { id: 'actions', label: 'Actions', icon: '✦' },
  { id: 'shows', label: 'Shows', icon: '☰' },
  { id: 'stage', label: 'Stage', icon: '▶' },
  { id: 'player', label: 'Player', icon: '◎' },
];

const CONNECTION_LABEL = {
  disconnected: 'Not connected', connecting: 'Connecting', connected: 'Connected', lost: 'Connection lost', unavailable: 'Unavailable',
} as const;

export function App() {
  const studio = useStudio();
  const [tab, setTab] = useState<Tab>('dog');
  const { snapshot, simulated, running } = studio;

  return (
    <div className={`app ${simulated ? 'is-simulated' : ''}`}>
      {simulated && (
        <div className="sim-banner" role="status">
          <strong>Simulated dog</strong>
          <span>Nothing here reaches a real robot.</span>
        </div>
      )}
      <div className="shell">
        <nav className="rail" aria-label="Main">
          <div className="brand" aria-label="VBOT Studio">
            <span className="brand-eyes" aria-hidden="true"><i /><i /></span>
            <span className="brand-name">VBOT Studio</span>
          </div>
          {TABS.map(item => (
            <button key={item.id} className="rail-item" aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}>
              <span aria-hidden="true" className="rail-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.id === 'stage' && running && <span className="rail-live" aria-label="A show is running" />}
            </button>
          ))}
          <div className={`rail-status conn-${snapshot.connection}`} role="status">
            <span className="dot" aria-hidden="true" />
            {CONNECTION_LABEL[snapshot.connection]}
          </div>
        </nav>
        <main className="content">
          {studio.library.warnings.map(warning => <p key={warning} className="notice notice-warn" role="alert">{warning}</p>)}
          {!studio.storageOk && <p className="notice notice-warn" role="alert">This browser isn’t saving changes. Export any show you want to keep.</p>}
          {tab === 'dog' && <DogView studio={studio} onBrowse={() => setTab('actions')} />}
          {tab === 'actions' && <ActionsView studio={studio} />}
          {tab === 'shows' && <PerformancesView studio={studio} onStage={() => setTab('stage')} />}
          {tab === 'stage' && <StageView studio={studio} onShows={() => setTab('shows')} />}
          {tab === 'player' && <PlayerView studio={studio} />}
        </main>
      </div>
      {tab !== 'stage' && <RunSheet studio={studio} onOpenStage={() => setTab('stage')} />}
    </div>
  );
}
