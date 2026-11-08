import { useState } from 'react';
import { Browser } from '@capacitor/browser';
import { Capacitor } from '@capacitor/core';
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
  const [updatesOpen, setUpdatesOpen] = useState(false);
  const [updateError, setUpdateError] = useState('');
  const [tab, setTab] = useState<Tab>('dog');
  const { snapshot, simulated, running } = studio;

  async function openStudioUpdates() {
    if (running || snapshot.connection === 'connected') return;
    setUpdateError('');
    const url = 'https://github.com/andycheng2018/ai-chess-coach/releases?q=vbot-studio-v&expanded=true';
    try {
      if (Capacitor.isNativePlatform()) await Browser.open({ url });
      else window.open(url, '_blank', 'noopener,noreferrer');
    } catch { setUpdateError('Could not open GitHub. Try again when internet is available.'); }
  }

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
          <button className="rail-item" onClick={() => setUpdatesOpen(value => !value)} aria-expanded={updatesOpen}>
            <span className="rail-icon" aria-hidden="true">↓</span><span>App updates</span>
          </button>
          <div className={`rail-status conn-${snapshot.connection}`} role="status">
            <span className="dot" aria-hidden="true" />
            {CONNECTION_LABEL[snapshot.connection]}
          </div>
        </nav>
        <main className="content">
          {updatesOpen && <section className="card" aria-label="VBOT Studio app updates">
            <h2>VBOT Studio updates</h2>
            <p>Open the newest Studio release and download <strong>VBOT-Studio-Android.apk</strong>. Install it as an update over this app to keep your saved shows and pairing. No update token is needed.</p>
            <p>Older debug-signed builds may need a one-time migration. Export your shows before removing an older app; do not uninstall this permanently signed version for ordinary updates.</p>
            <button disabled={running || snapshot.connection === 'connected'} onClick={() => void openStudioUpdates()}>Open Studio releases</button>
            {(running || snapshot.connection === 'connected') && <p>Finish the show and disconnect the dog before updating.</p>}
            {updateError && <p role="alert">{updateError}</p>}
          </section>}

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
