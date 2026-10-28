import React from 'react';

export type AppView = 'home' | 'arena' | 'profile' | 'menu';

type Props = {
  currentView: AppView;
  onSelectView: (view: AppView) => void;
  username?: string | null;
  botConnected: boolean;
  botLabel: string;
  hasActiveGame: boolean;
  onOpenAnalysis: () => void;
  onOpenSenseSetup: () => void;
  onLogout: () => void;
  hidden?: boolean;
};

export const NavBar: React.FC<Props> = ({
  currentView,
  onSelectView,
  username,
  botConnected,
  botLabel,
  hasActiveGame,
  onOpenAnalysis,
  onOpenSenseSetup,
  hidden = false,
}) => {
  return (
    <header className={`main-navbar ${hidden ? 'navbar-hidden' : ''}`}>
      <div className="nav-brand" onClick={() => onSelectView('home')} role="button" tabIndex={0}>
        <span className="brand-badge">AI</span>
        <div className="brand-text">
          <span className="brand-title">CHESS COACH</span>
          <span className="brand-subtitle">Interactive Training Academy</span>
        </div>
      </div>

      <nav className="nav-links" aria-label="Main navigation">
        <button
          type="button"
          className={`nav-tab ${currentView === 'home' ? 'active' : ''}`}
          onClick={() => onSelectView('home')}
        >
          <span className="nav-icon">🏛️</span>
          <span>Home Hub</span>
        </button>

        <button
          type="button"
          className={`nav-tab ${currentView === 'arena' ? 'active' : ''} ${hasActiveGame ? 'has-live-game' : ''}`}
          onClick={() => onSelectView('arena')}
        >
          <span className="nav-icon">⚔️</span>
          <span>Training Arena</span>
          {hasActiveGame && <span className="live-game-dot" title="Active match in progress" />}
        </button>

        <button
          type="button"
          className="nav-tab"
          onClick={() => onOpenAnalysis()}
        >
          <span className="nav-icon">📚</span>
          <span>Analysis</span>
        </button>

        <button
          type="button"
          className="nav-tab"
          onClick={onOpenSenseSetup}
        >
          <span className="nav-icon">🤖</span>
          <span>SenseRobot</span>
        </button>

        <button
          type="button"
          className={`nav-tab ${currentView === 'profile' ? 'active' : ''}`}
          onClick={() => onSelectView('profile')}
        >
          <span className="nav-icon">👤</span>
          <span>Profile & Coach</span>
        </button>
      </nav>

      <div className="nav-actions">
        <div className="bot-status-pill" title={`Training bot: ${botLabel}`}>
          <span className={`status-dot ${botConnected ? 'online' : 'offline'}`} />
          <span className="bot-status-text">{botConnected ? 'Coach Bot Ready' : 'Bot Offline'}</span>
        </div>

        {username && (
          <button
            type="button"
            className="user-pill-btn"
            onClick={() => onSelectView('profile')}
            title="View player profile"
          >
            <span className="user-avatar-small">♟</span>
            <span className="username-text">{username}</span>
          </button>
        )}

        <button
          type="button"
          className={`icon-nav-btn ${currentView === 'menu' ? 'active' : ''}`}
          onClick={() => onSelectView(currentView === 'menu' ? 'home' : 'menu')}
          title="Settings and Menu"
          aria-label="Settings and Menu"
        >
          ☰
        </button>
      </div>
    </header>
  );
};
