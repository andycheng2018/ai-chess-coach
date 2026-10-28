import React from 'react';
import { ChessBoard } from './ChessBoard';
import type { PlayingGame } from '../lichess';

type LevelItem = {
  id: string;
  label: string;
  elo: number;
  hint: string;
};

type TimeControlItem = {
  id: string;
  label: string;
  detail: string;
};

type Props = {
  username?: string | null;
  botConnected: boolean;
  botLabel: string;
  levels: readonly LevelItem[];
  level: string;
  onChangeLevel: (id: string) => void;
  timeControls: readonly TimeControlItem[];
  timeControlId: string;
  onChangeTimeControl: (id: any) => void;
  preferredColor: 'random' | 'white' | 'black';
  onChangeColor: (color: 'random' | 'white' | 'black') => void;
  onStartGame: () => void;
  startingGame: boolean;
  recoveryChecked: boolean;
  hasActiveGame: boolean;
  onEnterArena: () => void;
  onOpenAnalysis: () => void;
  onOpenSenseSetup: () => void;
  onOpenRooms?: () => void;
  onOpenProfile: () => void;
  onOpenMenu?: () => void;
  playingGames?: PlayingGame[];
  onLogin: () => void;
  isLoggedIn: boolean;
};

// Instructive demonstration position for Home Hub spotlight (Mikhail Tal's tactical brilliance)
const DEMO_FEN = 'r1bqk2r/pp2bppp/2n1pn2/2pp4/2PP4/2N1PN2/PP2BPPP/R1BQK2R w KQkq - 4 7';

// Inspiring Grandmaster advice and tactical principles for the Coach's corner
const COACH_TIPS = [
  {
    author: 'Emanuel Lasker',
    text: 'When you see a good move, take a breath and look for an even better one.',
  },
  {
    author: 'Garry Kasparov',
    text: 'Before every move, ask yourself: what is my opponent’s deepest counter-threat?',
  },
  {
    author: 'José Raúl Capablanca',
    text: 'You may learn much more from a game you lose than from a game you win.',
  },
  {
    author: 'Mikhail Tal',
    text: 'You must take your opponent into a deep dark forest where the path out is only wide enough for one.',
  },
  {
    author: 'Bobby Fischer',
    text: 'Tactics flow from a superior position. Coordinate your pieces first before launching the attack.',
  },
  {
    author: 'Tigran Petrosian',
    text: 'The best defense is vigilance. Deny your opponent any active play before pushing your advantage.',
  },
];

export const HomeHub: React.FC<Props> = ({
  username,
  botConnected,
  botLabel,
  levels,
  level,
  onChangeLevel,
  timeControls,
  timeControlId,
  onChangeTimeControl,
  preferredColor,
  onChangeColor,
  onStartGame,
  startingGame,
  recoveryChecked,
  hasActiveGame,
  onEnterArena,
  onOpenAnalysis,
  onOpenSenseSetup,
  onOpenRooms,
  onOpenProfile,
  onOpenMenu,
  playingGames = [],
  onLogin,
  isLoggedIn,
}) => {
  const selectedLevel = levels.find((l) => l.id === level) || levels[0];

  const fullHeadline = isLoggedIn && username
    ? `Good to have you at the board, ${username}.`
    : "Pull up a chair. Let's play some chess.";

  const fullSubtext =
    "I'm right here in your corner for every game. Take your time, calculate your lines, and don't sweat mistakes — that's how we grow. Whenever you find yourself at a sharp tactical crossroads or an unnoticed trap, I'll pause to ask a question and help you see the move yourself.";

  // ChatGPT-style Typewriter streaming states
  const [headlineChars, setHeadlineChars] = React.useState(0);
  const [subtextChars, setSubtextChars] = React.useState(0);
  const [stage, setStage] = React.useState<'headline' | 'subtext' | 'done'>('headline');

  const [tipIndex, setTipIndex] = React.useState(0);
  const [tipChars, setTipChars] = React.useState(COACH_TIPS[0].text.length);
  const [isTypingTip, setIsTypingTip] = React.useState(false);

  // Typewriter streaming for Headline
  React.useEffect(() => {
    setHeadlineChars(0);
    setSubtextChars(0);
    setStage('headline');

    let currentHeadline = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const typeNextHeadlineChar = () => {
      if (currentHeadline < fullHeadline.length) {
        currentHeadline++;
        setHeadlineChars(currentHeadline);
        const nextChar = fullHeadline[currentHeadline - 1];
        const delay = (nextChar === ',' || nextChar === '.' || nextChar === '!') ? 90 : 25;
        timer = setTimeout(typeNextHeadlineChar, delay);
      } else {
        setStage('subtext');
      }
    };

    timer = setTimeout(typeNextHeadlineChar, 80);

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [fullHeadline]);

  // Typewriter streaming for Subtext (begins seamlessly after headline)
  React.useEffect(() => {
    if (stage !== 'subtext') return;

    let currentSubtext = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const typeNextSubtextChar = () => {
      if (currentSubtext < fullSubtext.length) {
        currentSubtext++;
        setSubtextChars(currentSubtext);
        const char = fullSubtext[currentSubtext - 1];
        const delay = (char === '.' || char === '?' || char === '—') ? 95 : char === ',' ? 55 : 16;
        timer = setTimeout(typeNextSubtextChar, delay);
      } else {
        setStage('done');
      }
    };

    timer = setTimeout(typeNextSubtextChar, 160);

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [stage, fullSubtext]);

  // Typewriter streaming for rotating coach tip
  React.useEffect(() => {
    if (!isTypingTip) return;

    const activeTipText = COACH_TIPS[tipIndex].text;
    let currentChars = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const typeNextTipChar = () => {
      if (currentChars < activeTipText.length) {
        currentChars++;
        setTipChars(currentChars);
        const char = activeTipText[currentChars - 1];
        const delay = (char === '.' || char === ',') ? 65 : 18;
        timer = setTimeout(typeNextTipChar, delay);
      } else {
        setIsTypingTip(false);
      }
    };

    timer = setTimeout(typeNextTipChar, 40);

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [isTypingTip, tipIndex]);

  const handleNextTip = (e: React.MouseEvent) => {
    e.stopPropagation();
    const nextIdx = (tipIndex + 1) % COACH_TIPS.length;
    setTipIndex(nextIdx);
    setTipChars(0);
    setIsTypingTip(true);
  };

  const handleSkipTyping = () => {
    setHeadlineChars(fullHeadline.length);
    setSubtextChars(fullSubtext.length);
    setStage('done');
  };

  return (
    <div className="home-hub-page">
      {/* Active Game Notice Banner if match in progress */}
      {hasActiveGame && (
        <div className="live-match-banner">
          <div className="live-banner-content">
            <span className="live-pulse" />
            <div>
              <strong>
                {playingGames.length > 1
                  ? `${playingGames.length} Training Matches in Progress`
                  : 'Training Match In Progress'}
              </strong>
              <span>
                {playingGames.length > 1
                  ? `You have ${playingGames.length} active games with ${botLabel}.`
                  : `Your game against ${botLabel} is active right now.`}
              </span>
            </div>
          </div>
          <div className="live-banner-actions">
            {playingGames.length > 1 && onOpenMenu && (
              <button type="button" className="primary live-banner-btn" onClick={onOpenMenu}>
                🎮 Choose Game ({playingGames.length})
              </button>
            )}
            <button
              type="button"
              className={playingGames.length > 1 ? 'ghost live-banner-btn' : 'primary live-banner-btn'}
              onClick={onEnterArena}
            >
              ⚔️ Return to Live Board
            </button>
          </div>
        </div>
      )}

      {/* Hero Welcome Stage */}
      <section className="home-hero-stage">
        <div className="hero-coach-profile">
          <div className="coach-avatar-large">
            <span className="coach-avatar-emoji">🧙‍♂️</span>
            <div className="coach-status-halo" />
          </div>

          <div className="hero-coach-text" onClick={handleSkipTyping} title="Click to reveal all text">
            <div className="hero-kicker-row">
              <span className="academy-kicker">YOUR PERSONAL MENTOR</span>
              <span className="coach-status-pill">
                <span className={`status-dot ${botConnected ? 'online' : 'offline'}`} />
                {botConnected ? 'Coach Ready at the Board' : 'Setting Up the Board'}
              </span>
            </div>

            <h1 className="hero-headline typewriter-container">
              <span>{fullHeadline.slice(0, headlineChars)}</span>
              {stage === 'headline' && <span className="chatgpt-cursor" />}
            </h1>

            <p className="hero-subtext typewriter-container">
              <span>{fullSubtext.slice(0, subtextChars)}</span>
              {stage === 'subtext' && <span className="chatgpt-cursor" />}
              {stage === 'done' && <span className="chatgpt-cursor soft-idle" />}
            </p>

            {/* ChatGPT-style Quick Thought Starters */}
            <div className="chatgpt-prompt-pills">
              <span className="prompt-pill-label">Quick Start:</span>
              <button
                type="button"
                className="chatgpt-pill"
                onClick={(e) => {
                  e.stopPropagation();
                  const rapid = timeControls.find((tc) => tc.id.includes('10')) || timeControls[0];
                  if (rapid) onChangeTimeControl(rapid.id);
                  onStartGame();
                }}
              >
                ⏱️ Rapid Match (10m)
              </button>
              <button
                type="button"
                className="chatgpt-pill"
                onClick={(e) => {
                  e.stopPropagation();
                  const blitz = timeControls.find((tc) => tc.id.includes('5') || tc.id.includes('3')) || timeControls[0];
                  if (blitz) onChangeTimeControl(blitz.id);
                  onStartGame();
                }}
              >
                ⚡ Fast Blitz (5m)
              </button>
              <button
                type="button"
                className="chatgpt-pill"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenAnalysis();
                }}
              >
                🔍 Analyze a Position
              </button>
              <button
                type="button"
                className="chatgpt-pill"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenSenseSetup();
                }}
              >
                🤖 Connect SenseRobot
              </button>
            </div>

            <div className="hero-quote-card" onClick={handleNextTip} title="Click for another piece of advice">
              <span className="quote-mark">“</span>
              <div className="quote-body">
                <div className="quote-header-row">
                  <strong>Coach's Advice ({COACH_TIPS[tipIndex].author}):</strong>
                  <button
                    type="button"
                    className="quote-cycle-btn"
                    onClick={handleNextTip}
                    aria-label="Next tip"
                  >
                    🔄 Another Thought
                  </button>
                </div>
                <span>
                  {COACH_TIPS[tipIndex].text.slice(0, tipChars)}
                  {isTypingTip && <span className="chatgpt-cursor mini" />}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Main Grid: Grand Showcase Board & Arena Launcher */}
      <section className="home-main-grid">
        {/* Showcase Board */}
        <div className="home-board-showcase">
          <div className="showcase-header">
            <div className="showcase-title-row">
              <span className="showcase-badge">WARM-UP</span>
              <h3>Tactical Preview</h3>
            </div>
            <span className="showcase-tag">Interactive Board</span>
          </div>

          <div className="showcase-board-wrapper">
            <ChessBoard
              fen={DEMO_FEN}
              orientation="white"
              destinations={new Map()}
              coachArrows={[{ from: 'c3', to: 'd5', kind: 'idea' }]}
              coachHighlights={['d5', 'f6']}
              rollbackSignal={0}
              onMove={() => {}}
            />
          </div>

          <div className="showcase-coach-note">
            <div className="coach-bubble-mini">
              <span className="coach-mini-avatar">🧙‍♂️</span>
              <div className="coach-mini-content">
                <strong>Observe the d5 central tension:</strong>
                <p>When the center is open, piece activity and King safety matter twice as much. Look for outposts on d5 and e4!</p>
              </div>
            </div>
          </div>
        </div>

        {/* Quick Arena Match Setup Card */}
        <div className="home-setup-card">
          <div className="setup-card-header">
            <div className="setup-badge-row">
              <span className="setup-step-num">⚔️</span>
              <h2 className="setup-card-title">Training Arena</h2>
            </div>
            <p className="setup-card-desc">
              Choose your bot difficulty and time control. The AI coach is active for the whole game.
            </p>
          </div>

          {onOpenRooms && <button type="button" className="ghost wide" onClick={onOpenRooms}>Lichess rooms & existing games</button>}

          {/* Level Grid */}
          <div className="setup-group">
            <label className="setup-label">Opponent Skill Level</label>
            <div className="level-grid-home">
              {levels.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`level-btn-home ${level === item.id ? 'active' : ''}`}
                  onClick={() => onChangeLevel(item.id)}
                >
                  <div className="level-btn-top">
                    <strong>{item.label}</strong>
                    <span className="level-elo">~{item.elo} Elo</span>
                  </div>
                  <small className="level-hint">{item.hint}</small>
                </button>
              ))}
            </div>
          </div>

          {/* Time Controls */}
          <div className="setup-group">
            <label className="setup-label">Time Control</label>
            <div className="time-grid-home">
              {timeControls.map((tc) => (
                <button
                  key={tc.id}
                  type="button"
                  className={`time-btn-home ${timeControlId === tc.id ? 'active' : ''}`}
                  onClick={() => onChangeTimeControl(tc.id)}
                >
                  <strong>{tc.label}</strong>
                  <small>{tc.detail}</small>
                </button>
              ))}
            </div>
          </div>

          {/* Color Selection */}
          <div className="setup-group">
            <label className="setup-label">Your Pieces</label>
            <div className="color-grid-home">
              {(['random', 'white', 'black'] as const).map((color) => (
                <button
                  key={color}
                  type="button"
                  className={`color-btn-home ${preferredColor === color ? 'active' : ''}`}
                  onClick={() => onChangeColor(color)}
                >
                  <span className="color-btn-icon">
                    {color === 'white' ? '⚪' : color === 'black' ? '⚫' : '🎲'}
                  </span>
                  <span>{color === 'random' ? 'Random' : color === 'white' ? 'White' : 'Black'}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Action Button */}
          <div className="setup-cta-area">
            {!isLoggedIn ? (
              <button
                type="button"
                className="primary wide hero-cta-btn"
                onClick={onLogin}
              >
                Sign In With Lichess to Play
              </button>
            ) : hasActiveGame ? (
              <button
                type="button"
                className="primary wide hero-cta-btn"
                onClick={onEnterArena}
              >
                ⚔️ Continue Match in Arena
              </button>
            ) : (
              <button
                type="button"
                className="primary wide hero-cta-btn"
                disabled={startingGame || !recoveryChecked}
                onClick={onStartGame}
              >
                {!recoveryChecked ? 'Checking status…' : startingGame ? 'Starting Game…' : `Start Training Game vs ${selectedLevel.label}`}
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Academy Feature Pillars */}
      <section className="home-feature-pillars">
        <div className="feature-card" onClick={onEnterArena} role="button" tabIndex={0}>
          <div className="feature-icon-wrap">⚔️</div>
          <h3>Training Arena</h3>
          <p>Step directly to the board with your coach analyzing moves, asking guiding questions, and noting key ideas beside you.</p>
          <span className="feature-link">Open Arena →</span>
        </div>

        <div className="feature-card" onClick={() => onOpenAnalysis()} role="button" tabIndex={0}>
          <div className="feature-icon-wrap">📚</div>
          <h3>Analysis Studio</h3>
          <p>Explore positions at your own pace, test alternative lines, and see what engine evaluations uncover.</p>
          <span className="feature-link">Explore Studio →</span>
        </div>

        <div className="feature-card" onClick={onOpenSenseSetup} role="button" tabIndex={0}>
          <div className="feature-icon-wrap">🤖</div>
          <h3>SenseRobot Hardware</h3>
          <p>Play on physical wooden or robotic pieces while your AI coach speaks moves and guidance out loud.</p>
          <span className="feature-link">Setup Robot →</span>
        </div>

        <div className="feature-card" onClick={onOpenProfile} role="button" tabIndex={0}>
          <div className="feature-icon-wrap">👤</div>
          <h3>Mastery & Profile</h3>
          <p>Review lessons learned, track blunders you successfully avoided, and adjust how your coach talks to you.</p>
          <span className="feature-link">View Profile →</span>
        </div>
      </section>
    </div>
  );
};
