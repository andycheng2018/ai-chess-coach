import React from 'react';
import type { AppView } from './NavBar';

type Props = {
  open: boolean;
  onClose: () => void;
  onSelectView: (view: AppView) => void;
  onOpenAnalysis: () => void;
  onOpenSenseSetup: () => void;
  username?: string | null;
  botConnected: boolean;
  botLabel: string;
  hasActiveGame: boolean;
  onLogout: () => void;
};

export const MenuModal: React.FC<Props> = ({
  open,
  onClose,
  onSelectView,
  onOpenAnalysis,
  onOpenSenseSetup,
  username,
  botConnected,
  botLabel,
  hasActiveGame,
  onLogout,
}) => {
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card menu-modal-card custom-scroll" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <span className="modal-kicker">NAVIGATION & SETTINGS</span>
            <h2 className="modal-title">Academy Menu</h2>
          </div>
          <button type="button" className="ghost close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="menu-items-list">
          <button
            type="button"
            className="menu-item-row"
            onClick={() => { onSelectView('home'); onClose(); }}
          >
            <div className="menu-item-icon">🏛️</div>
            <div className="menu-item-text">
              <strong>Home Hub</strong>
              <span>Welcome stage, coach tip of the day & training setup</span>
            </div>
            <span className="menu-arrow">→</span>
          </button>

          <button
            type="button"
            className="menu-item-row"
            onClick={() => { onSelectView('arena'); onClose(); }}
          >
            <div className="menu-item-icon">⚔️</div>
            <div className="menu-item-text">
              <strong>Training Arena</strong>
              <span>Live chess match with full-screen AI coach companion window</span>
            </div>
            {hasActiveGame && <span className="menu-badge live">LIVE MATCH</span>}
            <span className="menu-arrow">→</span>
          </button>

          <button
            type="button"
            className="menu-item-row"
            onClick={() => { onOpenAnalysis(); onClose(); }}
          >
            <div className="menu-item-icon">📚</div>
            <div className="menu-item-text">
              <strong>Analysis Studio</strong>
              <span>Explore positions, import PGN, analyze with Stockfish</span>
            </div>
            <span className="menu-arrow">→</span>
          </button>

          <button
            type="button"
            className="menu-item-row"
            onClick={() => { onOpenSenseSetup(); onClose(); }}
          >
            <div className="menu-item-icon">🤖</div>
            <div className="menu-item-text">
              <strong>SenseRobot Setup</strong>
              <span>Pair and configure your physical AI robotic chessboard</span>
            </div>
            <span className="menu-arrow">→</span>
          </button>

          <button
            type="button"
            className="menu-item-row"
            onClick={() => { onSelectView('profile'); onClose(); }}
          >
            <div className="menu-item-icon">👤</div>
            <div className="menu-item-text">
              <strong>Profile & Coach Rapport</strong>
              <span>Review blunders prevented, mastery stats & voice preferences</span>
            </div>
            <span className="menu-arrow">→</span>
          </button>
        </div>

        {/* Backend & Bot Diagnostic Info */}
        <div className="menu-diagnostic-box">
          <div className="diag-row">
            <span>Training Bot</span>
            <strong>{botLabel} ({botConnected ? 'Online' : 'Offline'})</strong>
          </div>
          <div className="diag-row">
            <span>Lichess Account</span>
            <strong>{username || 'Not signed in'}</strong>
          </div>
        </div>

        <div className="modal-footer">
          {username && (
            <button
              type="button"
              className="ghost danger-btn"
              onClick={() => { onLogout(); onClose(); }}
            >
              Log Out
            </button>
          )}
          <button type="button" className="primary" onClick={onClose}>
            Close Menu
          </button>
        </div>
      </div>
    </div>
  );
};
