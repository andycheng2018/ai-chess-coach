import React from 'react';
import type { AppView } from './NavBar';
import type { PlayingGame } from '../lichess';

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
  playingGames?: PlayingGame[];
  activeGameId?: string | null;
  onSelectGame?: (gameId: string) => void;
  onRefreshGames?: () => void;
  refreshingGames?: boolean;
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
  playingGames = [],
  activeGameId,
  onSelectGame,
  onRefreshGames,
  refreshingGames = false,
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

        {/* Live Games Section */}
        {onSelectGame && (
          <div className="menu-live-games-section">
            <div className="menu-section-header">
              <div className="section-title-wrap">
                <span className="section-kicker">ALL LIVE MATCHES</span>
                <h3 className="section-title">
                  Active Games {playingGames.length > 0 ? `(${playingGames.length})` : ''}
                </h3>
              </div>
              {onRefreshGames && (
                <button
                  type="button"
                  className="icon-button refresh-games-btn"
                  onClick={onRefreshGames}
                  title="Refresh active games from Lichess"
                  disabled={refreshingGames}
                >
                  <span className={refreshingGames ? 'spin' : ''}>🔄</span>
                </button>
              )}
            </div>

            {playingGames.length > 0 ? (
              <div className="menu-live-games-list">
                {playingGames.map((game) => {
                  const isCurrent = game.gameId === activeGameId;
                  const isWhite = game.color === 'white';
                  const opponentName = game.opponent?.username || 'Opponent';
                  const isBot =
                    opponentName.toLowerCase() === botLabel.toLowerCase() ||
                    game.opponent?.title === 'BOT';
                  const variantName = game.variant?.name || 'Standard';

                  return (
                    <div
                      key={game.gameId}
                      className={`menu-live-game-card ${isCurrent ? 'current-active' : ''}`}
                      onClick={() => onSelectGame(game.gameId)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="game-card-left">
                        <span className="game-color-icon">{isWhite ? '♔' : '♚'}</span>
                        <div className="game-card-details">
                          <div className="game-card-header-line">
                            <strong className="game-card-opponent">
                              vs. {opponentName}
                              {isBot && <span className="game-bot-badge">BOT</span>}
                            </strong>
                            {game.opponent?.rating && (
                              <span className="game-card-rating">~{game.opponent.rating}</span>
                            )}
                          </div>
                          <div className="game-card-meta-line">
                            <span className="game-meta-item">You play {game.color}</span>
                            <span className="game-meta-dot">·</span>
                            <span className="game-meta-item">{variantName}</span>
                            <span className="game-meta-dot">·</span>
                            <span
                              className={`game-turn-pill ${
                                game.isMyTurn ? 'my-turn' : 'waiting-turn'
                              }`}
                            >
                              {game.isMyTurn ? '● Your turn' : 'Opponent turn'}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="game-card-right">
                        {isCurrent ? (
                          <span className="current-match-badge">ACTIVE NOW</span>
                        ) : (
                          <button
                            type="button"
                            className="primary small-action-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectGame(game.gameId);
                            }}
                          >
                            Play Match →
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="menu-no-games-box">
                <p>No active games in progress on Lichess.</p>
                {onRefreshGames && (
                  <button
                    type="button"
                    className="ghost small-btn"
                    onClick={onRefreshGames}
                    disabled={refreshingGames}
                  >
                    Check for Live Games
                  </button>
                )}
              </div>
            )}
          </div>
        )}

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
