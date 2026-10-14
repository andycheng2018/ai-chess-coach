import React, { useState } from 'react';
import type { AppView } from './NavBar';

type Props = {
  currentView: AppView;
  onSelectView: (view: AppView) => void;
  username?: string | null;
  botConnected: boolean;
  botLabel: string;
  hasActiveGame: boolean;
  onOpenAnalysis: () => void;
  onOpenSenseSetup: () => void;
  onOpenProfile: () => void;
  onOpenMenu: () => void;
  navHidden?: boolean;
};

export const SideBar: React.FC<Props> = ({
  currentView,
  onSelectView,
  username,
  botConnected,
  botLabel,
  hasActiveGame,
  onOpenAnalysis,
  onOpenSenseSetup,
  onOpenProfile,
  onOpenMenu,
  navHidden = false,
}) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <aside
      className={`hover-sidebar-rail ${navHidden ? 'top-offset-condensed' : ''} ${isHovered ? 'expanded' : ''}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      aria-label="Quick Navigation Sidebar"
    >
      {/* Top Handle / Badge */}
      <div className="sidebar-rail-header" onClick={() => onSelectView('home')} role="button" tabIndex={0}>
        <div className="sidebar-icon-cell">
          <span className="sidebar-brand-badge">AI</span>
        </div>
        <div className="sidebar-label-cell">
          <span className="sidebar-header-title">CHESS COACH</span>
          <span className="sidebar-header-sub">Academy</span>
        </div>
      </div>

      <div className="sidebar-divider" />

      {/* Navigation Items */}
      <nav className="sidebar-nav-list" aria-label="Sidebar navigation">
        <button
          type="button"
          className={`sidebar-nav-btn ${currentView === 'home' ? 'active' : ''}`}
          onClick={() => onSelectView('home')}
          title="Home Hub"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">🏛️</span>
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">Home Hub</span>
            <span className="sidebar-btn-hint">Academy Central</span>
          </div>
        </button>

        <button
          type="button"
          className={`sidebar-nav-btn ${currentView === 'arena' ? 'active' : ''} ${hasActiveGame ? 'has-live-game' : ''}`}
          onClick={() => onSelectView('arena')}
          title="Training Arena"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">⚔️</span>
            {hasActiveGame && <span className="sidebar-live-dot" />}
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">Training Arena</span>
            <span className="sidebar-btn-hint">{hasActiveGame ? 'Game Active' : 'Live Board'}</span>
          </div>
          {hasActiveGame && <span className="sidebar-live-tag">LIVE</span>}
        </button>

        <button
          type="button"
          className="sidebar-nav-btn"
          onClick={() => onOpenAnalysis()}
          title="Analysis Studio"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">📚</span>
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">Analysis Studio</span>
            <span className="sidebar-btn-hint">Engine Lines</span>
          </div>
        </button>

        <button
          type="button"
          className="sidebar-nav-btn"
          onClick={onOpenSenseSetup}
          title="SenseRobot Hardware"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">🤖</span>
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">SenseRobot</span>
            <span className="sidebar-btn-hint">Physical Board</span>
          </div>
        </button>

        <button
          type="button"
          className={`sidebar-nav-btn ${currentView === 'profile' ? 'active' : ''}`}
          onClick={onOpenProfile}
          title="Profile & Coaching Mastery"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">👤</span>
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">Profile & Mastery</span>
            <span className="sidebar-btn-hint">Stats & Insights</span>
          </div>
        </button>

        <button
          type="button"
          className="sidebar-nav-btn"
          onClick={onOpenMenu}
          title="Settings & Menu"
        >
          <div className="sidebar-icon-cell">
            <span className="sidebar-icon">☰</span>
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-btn-title">Menu & Settings</span>
            <span className="sidebar-btn-hint">Shortcuts & Audio</span>
          </div>
        </button>
      </nav>

      <div className="sidebar-spacer" />
      <div className="sidebar-divider" />

      {/* Bottom Status / Account */}
      <div className="sidebar-footer">
        <div className="sidebar-status-row" title={`Bot: ${botLabel}`}>
          <div className="sidebar-icon-cell">
            <span className={`status-dot ${botConnected ? 'online' : 'offline'}`} />
          </div>
          <div className="sidebar-label-cell">
            <span className="sidebar-status-text">{botConnected ? 'Coach Bot Ready' : 'Bot Offline'}</span>
          </div>
        </div>

        {username && (
          <div className="sidebar-user-row" onClick={onOpenProfile} role="button" tabIndex={0} title={username}>
            <div className="sidebar-icon-cell">
              <span className="user-avatar-mini">♟</span>
            </div>
            <div className="sidebar-label-cell">
              <span className="sidebar-username">{username}</span>
            </div>
          </div>
        )}
      </div>

      {/* Collapse hint tab */}
      <div className="sidebar-rail-handle" aria-hidden="true">
        <span className="sidebar-rail-chevron">›</span>
      </div>
    </aside>
  );
};
