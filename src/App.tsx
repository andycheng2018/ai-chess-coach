import { scanSenseRoom } from './senseScanner';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Chess, type Move, type Square } from 'chess.js';
import { ChessBoard, type Arrow } from './components/ChessBoard';
import { finishOAuthCallback, getToken, loginWithLichess, logout, listenForNativeOAuth } from './auth';
import { acceptBotChallenge, getBotStatus, getCachedGameState, setBotLevel, startBot, type BotRuntimeStatus } from './botControl';
import {
  analyzeMove,
  type CoachLanguage,
  type CoachResult,
} from './coach';
import {
  speakCoach,
  stopCoachSpeech,
  unlockCoachAudio,
} from './tts';
import {
  abortGame,
  challengeBot,
  getAccount,
  getPlayingGames,
  handleTakeback,
  LichessHttpError,
  makeMove,
  resignGame,
  retryingStream,
  streamEvents,
  streamGame,
  type Account,
  type StreamEvent,
} from './lichess';

const BOT_USERNAME = import.meta.env.VITE_COACH_BOT_USERNAME || 'bot_2435';
const ACTIVE_GAME_STORAGE_KEY = 'ai-chess-coach.active-game.v1';
const LEARNING_LOG_STORAGE_KEY = 'ai-chess-coach.learning-log.v2';
const TIME_CONTROL_STORAGE_KEY = 'ai-chess-coach.time-control.v1';

type StoredGame = { gameId: string; username?: string; savedAt: number };
type Player = { name: string; rating?: number; title?: string };
type ClockState = { enabled: boolean; white: number; black: number; increment: number; updatedAt: number };
type PromotionChoice = 'q' | 'r' | 'b' | 'n';
type CoachReviewMode = 'better' | 'threat';
type PendingPromotion = { from: string; to: string; fenBefore: string; basePly: number; choices: PromotionChoice[] };
type PendingMove = { uci: string; basePly: number };
type Winner = 'white' | 'black' | null;
type CoachNote = CoachResult & { gameId: string; savedAt: number; playerColor: 'white' | 'black' };
type ReviewTarget = CoachResult & { playerColor?: 'white' | 'black' };
type StoredLearningSession = { gameId: string; username?: string; updatedAt: number; notes: CoachNote[] };

const LEVELS = [
  { id: 'newcomer', label: 'Newcomer', elo: 500, hint: 'Just learning patterns' },
  { id: 'beginner', label: 'Beginner', elo: 800, hint: 'Sees basic threats' },
  { id: 'developing', label: 'Developing', elo: 1100, hint: 'Good practice opponent' },
  { id: 'club', label: 'Club', elo: 1400, hint: 'Punishes loose moves' },
  { id: 'strong', label: 'Strong', elo: 1700, hint: 'Tactical and steady' },
  { id: 'expert', label: 'Expert', elo: 2000, hint: 'Serious challenge' },
] as const;

const TIME_CONTROLS = [
  { id: 'unlimited', label: 'Unlimited', detail: 'No clock', timeControl: { type: 'unlimited' as const } },
  { id: '30-0', label: '30 min', detail: 'Relaxed', timeControl: { type: 'clock' as const, limitSeconds: 1800, incrementSeconds: 0 } },
  { id: '15-10', label: '15 + 10', detail: 'Thoughtful', timeControl: { type: 'clock' as const, limitSeconds: 900, incrementSeconds: 10 } },
  { id: '10-5', label: '10 + 5', detail: 'Balanced', timeControl: { type: 'clock' as const, limitSeconds: 600, incrementSeconds: 5 } },
  { id: '10-0', label: '10 min', detail: 'Classic', timeControl: { type: 'clock' as const, limitSeconds: 600, incrementSeconds: 0 } },
  { id: '5-3', label: '5 + 3', detail: 'Quick', timeControl: { type: 'clock' as const, limitSeconds: 300, incrementSeconds: 3 } },
  { id: '3-2', label: '3 + 2', detail: 'Fast', timeControl: { type: 'clock' as const, limitSeconds: 180, incrementSeconds: 2 } },
] as const;

type TimeControlId = (typeof TIME_CONTROLS)[number]['id'];
type CoachDetail = 'quick' | 'balanced' | 'deep';

const COACH_DETAIL_STORAGE_KEY =
  'ai-chess-coach.coach-detail.v1';

const COACH_LANGUAGE_STORAGE_KEY =
  'ai-chess-coach.coach-language.v1';

function readStoredGame(): StoredGame | null {
  try {
    const raw = window.localStorage.getItem(ACTIVE_GAME_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredGame>;
    if (!parsed.gameId || typeof parsed.gameId !== 'string') return null;
    return { gameId: parsed.gameId, username: parsed.username, savedAt: Number(parsed.savedAt) || Date.now() };
  } catch {
    return null;
  }
}

function storeActiveGame(gameId: string, username?: string) {
  try {
    window.localStorage.setItem(ACTIVE_GAME_STORAGE_KEY, JSON.stringify({ gameId, username, savedAt: Date.now() } satisfies StoredGame));
  } catch { /* localStorage can be unavailable in private/restricted contexts. */ }
}

function forgetStoredGame() {
  try { window.localStorage.removeItem(ACTIVE_GAME_STORAGE_KEY); } catch { /* no-op */ }
}

function readLearningSessions(): StoredLearningSession[] {
  try {
    const raw = window.localStorage.getItem(LEARNING_LOG_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((session): session is StoredLearningSession => Boolean(
      session && typeof session.gameId === 'string' && Array.isArray(session.notes),
    ));
  } catch {
    return [];
  }
}

function readLearningNotes(gameId: string): CoachNote[] {
  return readLearningSessions().find((session) => session.gameId === gameId)?.notes || [];
}

function storeLearningNotes(gameId: string, username: string | undefined, notes: CoachNote[]) {
  try {
    const existing = readLearningSessions().filter((session) => session.gameId !== gameId);
    const next: StoredLearningSession[] = [
      { gameId, username, updatedAt: Date.now(), notes: notes.slice(0, 16) },
      ...existing,
    ].slice(0, 8);
    window.localStorage.setItem(LEARNING_LOG_STORAGE_KEY, JSON.stringify(next));
  } catch { /* no-op */ }
}

function readPreferredTimeControl(): TimeControlId {
  try {
    const value = window.localStorage.getItem(TIME_CONTROL_STORAGE_KEY) as TimeControlId | null;
    return TIME_CONTROLS.some((item) => item.id === value) ? value! : '10-0';
  } catch {
    return '10-0';
  }
}

function storePreferredTimeControl(value: TimeControlId) {
  try { window.localStorage.setItem(TIME_CONTROL_STORAGE_KEY, value); } catch { /* no-op */ }
}

function readCoachDetail(): CoachDetail {
  try {
    const value = window.localStorage.getItem(COACH_DETAIL_STORAGE_KEY);
    if (value === 'quick' || value === 'balanced' || value === 'deep') {
      return value;
    }
  } catch {
    // no-op
  }
  return 'balanced';
}

function readCoachLanguage(): CoachLanguage {
  try {
    const value = window.localStorage.getItem(
      COACH_LANGUAGE_STORAGE_KEY,
    );

    return value === 'zh-CN'
      ? 'zh-CN'
      : 'en';
  } catch {
    return 'en';
  }
}

function destinations(chess: Chess): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const move of chess.moves({ verbose: true })) {
    const current = result.get(move.from) || [];
    if (!current.includes(move.to)) current.push(move.to);
    result.set(move.from, current);
  }
  return result;
}

function replay(initialFen: string, movesText: string) {
  const chess = initialFen && initialFen !== 'startpos' ? new Chess(initialFen) : new Chess();
  const san: string[] = [];
  const moves = movesText.trim() ? movesText.trim().split(/\s+/) : [];
  for (const uci of moves) {
    const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || 'q' });
    if (move) san.push(move.san);
  }
  const last = moves.at(-1);
  return {
    chess,
    san,
    plyCount: moves.length,
    lastMove: last ? [last.slice(0, 2), last.slice(2, 4)] as [string, string] : undefined,
  };
}

function formatClock(ms: number): string {
  const totalSeconds = Math.ceil(Math.max(0, ms) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function formatTimeControl(clock: any): string {
  if (!clock || typeof clock.initial !== 'number') return 'Unlimited';
  const minutes = Math.round(clock.initial / 60000);
  const increment = Math.round(Number(clock.increment || 0) / 1000);
  return increment ? `${minutes} + ${increment}` : `${minutes} min`;
}

function PlayerBar({ player, clock, active, side }: { player: Player; clock: number | null; active: boolean; side: 'white' | 'black' }) {
  return <div className={`player-bar ${active ? 'active' : ''}`}>
    <div className="player-identity">
      <span className={`color-dot ${side}`} />
      <strong>{player.title ? `${player.title} ` : ''}{player.name}</strong>
      {player.rating ? <span>{player.rating}</span> : null}
    </div>
    <div className={`clock ${clock == null ? 'unlimited' : ''}`} title={clock == null ? 'Unlimited time' : undefined}>
      {clock == null ? <><span className="infinity">∞</span><small>unlimited</small></> : formatClock(clock)}
    </div>
  </div>;
}

function gameEndReason(status: string, winner: Winner, myColor: 'white' | 'black'): string {
  switch (status) {
    case 'mate': return 'Checkmate';
    case 'resign': return winner === myColor ? 'Your opponent resigned' : 'You resigned';
    case 'timeout':
    case 'outoftime': return winner === myColor ? 'Your opponent ran out of time' : 'You ran out of time';
    case 'stalemate': return 'Stalemate';
    case 'draw': return 'Draw agreed';
    case 'insufficientMaterialClaim': return 'Draw by insufficient material';
    case 'aborted': return 'Game aborted';
    case 'noStart': return 'Game did not start';
    case 'cheat': return 'Game ended by Lichess';
    case 'variantEnd': return 'Game ended';
    default: return 'Game finished';
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export default function App() {
  const storedGameAtLoad = useRef<StoredGame | null>(readStoredGame());
  const [token, setToken] = useState<string | null>(getToken());
  const [account, setAccount] = useState<Account | null>(null);
  const [status, setStatus] = useState('Ready');
  const [level, setLevel] = useState<(typeof LEVELS)[number]['id']>('developing');
  const [timeControlId, setTimeControlId] = useState<TimeControlId>(readPreferredTimeControl);
  const [currentTimeControlLabel, setCurrentTimeControlLabel] = useState('10 min');
  const [preferredColor, setPreferredColor] = useState<'random' | 'white' | 'black'>('random');
  const [bot, setBot] = useState<BotRuntimeStatus>({ running: false, connected: false });
  const [startingGame, setStartingGame] = useState(false);
  const [scanningRoom, setScanningRoom] = useState(false);
  const [recoveryChecked, setRecoveryChecked] = useState(false);

  const [gameId, setGameId] = useState<string | null>(storedGameAtLoad.current?.gameId ?? null);
  // SenseRobot mode is intentionally NOT restored from localStorage.
  // A game becomes a SenseRobot game only after this app successfully
  // scans and joins a SenseRobot QR room in the current session.
  const [senseRobotGameId, setSenseRobotGameId] = useState<string | null>(null);
  const gameIdRef = useRef<string | null>(null);
  const [initialFen, setInitialFen] = useState('startpos');
  const [movesText, setMovesText] = useState('');
  const movesTextRef = useRef('');
  const [orientation, setOrientation] = useState<'white' | 'black'>('white');
  const [myColor, setMyColor] = useState<'white' | 'black'>('white');
  const [gameStatus, setGameStatus] = useState(storedGameAtLoad.current?.gameId ? 'recovering' : 'idle');
  const [players, setPlayers] = useState<{ white: Player; black: Player }>({
    white: { name: 'White' }, black: { name: 'Black' },
  });
  const [clock, setClock] = useState<ClockState>({ enabled: true, white: 600000, black: 600000, increment: 0, updatedAt: Date.now() });
  const [now, setNow] = useState(Date.now());
  const [rollbackSignal, setRollbackSignal] = useState(0);
  const [pendingPromotion, setPendingPromotion] = useState<PendingPromotion | null>(null);
  const [moveInFlight, setMoveInFlight] = useState(false);
  const pendingMoveRef = useRef<PendingMove | null>(null);
  const [endGameConfirm, setEndGameConfirm] = useState(false);
  const [winner, setWinner] = useState<Winner>(null);
  const [gameOverOpen, setGameOverOpen] = useState(false);

  const [coachResult, setCoachResult] = useState<CoachResult | null>(null);
  const [coachThinking, setCoachThinking] = useState(false);
  const [coachError, setCoachError] = useState('');
  const [coachNotes, setCoachNotes] = useState<CoachNote[]>([]);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [hintsEnabled, setHintsEnabled] = useState(true);

  const [coachDetail, setCoachDetail] = useState<CoachDetail>(readCoachDetail);
  const [coachLanguage, setCoachLanguage] = useState<CoachLanguage>(readCoachLanguage);
  const [reviewMode, setReviewMode] = useState<CoachReviewMode | null>(null);
  const [reviewTarget, setReviewTarget] = useState<ReviewTarget | null>(null);
  const [historyPly, setHistoryPly] = useState<number | null>(null);
  type CoachJob = {
    fenBefore: string;
    uci: string;
  };

  const coachAbortRef = useRef<AbortController | null>(null);
  const coachQueueRef = useRef<CoachJob[]>([]);
  const coachProcessingRef = useRef(false);
  const observedCoachPlyRef = useRef<number | null>(null);
  const reviewTouchStart = useRef<{ x: number; y: number } | null>(null);
  const [reviewDragX, setReviewDragX] = useState(0);
  const [reviewDragging, setReviewDragging] = useState(false);
  const [reviewNoTransition, setReviewNoTransition] = useState(false);
  const reviewAnimatingRef = useRef(false);

  const position = useMemo(
  () => replay(initialFen, movesText),
  [initialFen, movesText],
);

  const displayPosition = useMemo(() => {
    // null means we are looking at the live/current position.
    if (historyPly == null || historyPly >= position.plyCount) {
      return position;
    }

    const moves = movesText.trim()
      ? movesText.trim().split(/\s+/)
      : [];

    return replay(
      initialFen,
      moves.slice(0, historyPly).join(' '),
    );
  }, [initialFen, movesText, historyPly, position]);

  const turnColor: 'white' | 'black' =
    position.chess.turn() === 'w' ? 'white' : 'black';

  const activeGame =
    gameStatus === 'started' || gameStatus === 'created';

  const isSenseRobotGame =
    Boolean(gameId && senseRobotGameId === gameId);

  const isMyTurn =
    activeGame && myColor === turnColor;

  const canMove =
    !isSenseRobotGame &&
    historyPly == null &&
    isMyTurn &&
    !moveInFlight &&
    !pendingPromotion;
    
  const isCoachGame = players.white.name.toLowerCase() === BOT_USERNAME.toLowerCase()
    || players.black.name.toLowerCase() === BOT_USERNAME.toLowerCase();
  const coachArrows: Arrow[] = useMemo(() => {
    if (!hintsEnabled || !coachResult) return [];
    // A best-move arrow belongs to the position *before* the student's move,
    // while a threat arrow belongs to the position immediately after it. Never
    // draw an arrow on a later live position where it would teach the wrong idea.
    if (position.plyCount === coachResult.ply - 1) {
      return (coachResult.arrows || []).filter((arrow) => arrow.kind === 'best');
    }
    if (position.plyCount === coachResult.ply) {
      return (coachResult.arrows || []).filter((arrow) => arrow.kind === 'danger');
    }
    return [];
  }, [hintsEnabled, coachResult, position.plyCount]);
  const coachHighlights = useMemo(() => {
    if (!hintsEnabled || !coachResult) return [];
    if (position.plyCount === coachResult.ply - 1) return coachResult.highlightsBefore || [];
    if (position.plyCount === coachResult.ply) return coachResult.highlightsAfter || [];
    return [];
  }, [hintsEnabled, coachResult, position.plyCount]);

  const setActiveGameId = useCallback((nextGameId: string) => {
    gameIdRef.current = nextGameId;
    setGameId(nextGameId);
    storeActiveGame(nextGameId, account?.username);
  }, [account?.username]);

  useEffect(() => { gameIdRef.current = gameId; }, [gameId]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    movesTextRef.current = movesText;
  }, [movesText]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        COACH_DETAIL_STORAGE_KEY,
        coachDetail,
      );
    } catch {
      // no-op
    }
  }, [coachDetail]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        COACH_LANGUAGE_STORAGE_KEY,
        coachLanguage,
      );
    } catch {
      // no-op
    }
  }, [coachLanguage]);

  useEffect(() => {
    return () => {
      stopCoachSpeech();
    };
  }, []);

  const displayedClock = useMemo(() => {
    if (!clock.enabled) return { white: null, black: null };
    const elapsed = activeGame ? now - clock.updatedAt : 0;
    return {
      white: turnColor === 'white' && activeGame ? clock.white - elapsed : clock.white,
      black: turnColor === 'black' && activeGame ? clock.black - elapsed : clock.black,
    };
  }, [activeGame, clock, now, turnColor]);

  useEffect(() => {
    storePreferredTimeControl(timeControlId);
  }, [timeControlId]);

  useEffect(() => {
    let disposed = false;
    let removeNativeListener: (() => void) | null = null;

    // Normal browser callback (desktop/web build).
    finishOAuthCallback()
      .then((done) => {
        if (!disposed && done) setToken(getToken());
      })
      .catch((error) => {
        if (!disposed) setStatus(String(error));
      });

    // Native iOS callback delivered through chessbuddy://oauth/callback.
    void listenForNativeOAuth(
      () => {
        if (disposed) return;
        setToken(getToken());
        setStatus('Signed in with Lichess.');
      },
      (error) => {
        if (!disposed) setStatus(error);
      },
    ).then((removeListener) => {
      if (disposed) {
        removeListener();
      } else {
        removeNativeListener = removeListener;
      }
    });

    return () => {
      disposed = true;
      removeNativeListener?.();
    };
  }, []);

  useEffect(() => {
    if (!token) { setAccount(null); return; }
    getAccount(token)
      .then(setAccount)
      .catch((error) => {
        setStatus(`Lichess account error: ${String(error)}`);
        logout();
        setToken(null);
      });
  }, [token]);

  useEffect(() => {
    if (!token || !account) {
      setRecoveryChecked(false);
      return;
    }
    let cancelled = false;
    setRecoveryChecked(false);

    const stored = readStoredGame();
    if (gameIdRef.current) {
      if (stored?.username && stored.username.toLowerCase() !== account.username.toLowerCase()) {
        forgetStoredGame();
        gameIdRef.current = null;
        setGameId(null);
        setGameStatus('idle');
      } else {
        storeActiveGame(gameIdRef.current, account.username);
        setStatus('Reconnecting to your training game…');
        setRecoveryChecked(true);
        return () => { cancelled = true; };
      }
    }

    getPlayingGames(token).then((games) => {
      if (cancelled || gameIdRef.current) return;
      const coachGame = games.find((game) => game.opponent?.username?.toLowerCase() === BOT_USERNAME.toLowerCase());
      if (coachGame?.gameId) {
        setActiveGameId(coachGame.gameId);
        setGameStatus('recovering');
        setStatus('Recovered your active coach game.');
      }
    }).catch((error) => {
      if (!cancelled) setStatus(`Could not check active games yet: ${String(error)}`);
    }).finally(() => {
      if (!cancelled) setRecoveryChecked(true);
    });
    return () => { cancelled = true; };
  }, [token, account, setActiveGameId]);

  useEffect(() => {
    if (!token || !account) return;
    let alive = true;
    const refresh = async () => {
      try {
        const state = await getBotStatus();
        if (alive) setBot(state);
      } catch (error) {
        if (alive) setBot({ running: false, connected: false, error: String(error) });
      }
    };
    void startBot().then((state) => { if (alive) setBot(state); }).catch((error) => {
      if (alive) setBot({ running: false, connected: false, error: String(error) });
    });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [token, account]);

  useEffect(() => {
    if (!token || !account) return;
    const controller = new AbortController();
    void retryingStream(
      (signal) => streamEvents(token, (event: StreamEvent) => {
        if (event.type === 'gameStart' && event.game) {
          const opponent = event.game.opponent?.username?.toLowerCase();
          if (opponent === BOT_USERNAME.toLowerCase()) {
            // A normal Lichess gameStart must stay a normal online game.
            // Preserve SenseRobot mode only when this is the exact game
            // that was activated by a successful QR scan.
            const startedGameId = event.game.id;

            setSenseRobotGameId((current) =>
              current === startedGameId ? current : null
            );
            setActiveGameId(event.game.id);
            setGameStatus('recovering');
            setStatus(`Game started against ${BOT_USERNAME}.`);
          }
        }
        if (event.type === 'gameFinish' && event.game?.id === gameIdRef.current) {
          forgetStoredGame();
          pendingMoveRef.current = null;
          setMoveInFlight(false);
          // The per-game stream carries the authoritative terminal status and
          // winner. Do not overwrite it with a generic "finished" value.
          setStatus('Training game finished. Finalizing your result…');
        }
      }, signal),
      controller.signal,
      () => setStatus('Reconnecting to Lichess…'),
    );
    return () => controller.abort();
  }, [token, account, setActiveGameId]);

  useEffect(() => {
    if (!token || !gameId || !account) return;
    const controller = new AbortController();

    const syncPendingMove = (nextMovesText: string) => {
      const pendingMove = pendingMoveRef.current;
      if (!pendingMove) return;
      const moves = nextMovesText.trim() ? nextMovesText.trim().split(/\s+/) : [];
      if (moves.length <= pendingMove.basePly) return;

      pendingMoveRef.current = null;
      setMoveInFlight(false);
      if (moves[pendingMove.basePly] === pendingMove.uci) {
        setStatus('Move played.');
      } else {
        setRollbackSignal((value) => value + 1);
        setStatus('Board state changed while your move was syncing. Resynced with Lichess.');
      }
    };

    const applyState = (state: any, clockEnabled?: boolean) => {
    const nextMoves = String(state?.moves || '');
    const nextStatus = String(state?.status || 'started');
    const nextWinner: Winner =
      state?.winner === 'white' || state?.winner === 'black'
        ? state.winner
        : null;

    // Keep the synchronous ref in lockstep with the
    // authoritative Lichess stream.
    movesTextRef.current = nextMoves;
    setMovesText(nextMoves);
      setGameStatus(nextStatus);
      if (nextWinner) setWinner(nextWinner);
      syncPendingMove(nextMoves);
      if (nextStatus !== 'started' && nextStatus !== 'created') {
        forgetStoredGame();
        pendingMoveRef.current = null;
        setMoveInFlight(false);
        setEndGameConfirm(false);
        setGameOverOpen(true);
        setStatus(`Training game finished · ${nextStatus}.`);
        controller.abort();
      }
      setClock((previous) => ({
        enabled: clockEnabled ?? previous.enabled,
        white: typeof state?.wtime === 'number' ? state.wtime : previous.white,
        black: typeof state?.btime === 'number' ? state.btime : previous.black,
        increment: typeof state?.winc === 'number' ? state.winc : previous.increment,
        updatedAt: Date.now(),
      }));
    };

    const onGameEvent = (event: any) => {
      if (event.type === 'gameFull') {
        const whiteName = String(event.white?.name || event.white?.id || 'White');
        const blackName = String(event.black?.name || event.black?.id || 'Black');
        const me = account.username.toLowerCase();
        if (whiteName.toLowerCase() !== me && blackName.toLowerCase() !== me) {
          forgetStoredGame();
          gameIdRef.current = null;
          setGameId(null);
          setGameStatus('idle');
          setRecoveryChecked(true);
          setStatus('The saved Lichess game belongs to a different account, so it was not reopened.');
          controller.abort();
          return;
        }
        const color: 'white' | 'black' = whiteName.toLowerCase() === me ? 'white' : 'black';
        setPlayers({
          white: { name: whiteName, rating: event.white?.rating, title: event.white?.title },
          black: { name: blackName, rating: event.black?.rating, title: event.black?.title },
        });
        setMyColor(color);
        setOrientation(color);
        setInitialFen(event.initialFen || 'startpos');
        setCurrentTimeControlLabel(formatTimeControl(event.clock));
        storeActiveGame(gameId, account.username);
        applyState(event.state || {}, Boolean(event.clock));
        setRecoveryChecked(true);
        if ((event.state?.status || 'started') === 'started' || (event.state?.status || 'started') === 'created') {
          setStatus('Training game connected.');
        }
      } else if (event.type === 'gameState') {
        applyState(event);
      }
    };
    void retryingStream(
      (signal) => streamGame(token, gameId, onGameEvent, signal),
      controller.signal,
      () => setStatus('Reconnecting to the game…'),
      (error) => {
        setRecoveryChecked(true);
        if (error instanceof LichessHttpError && error.status === 404) {
          void getPlayingGames(token).then((games) => {
            const found = games.find((game) => game.opponent?.username?.toLowerCase() === BOT_USERNAME.toLowerCase());
            if (found?.gameId && found.gameId !== gameId) {
              setActiveGameId(found.gameId);
              setGameStatus('recovering');
              setStatus('Recovered your current training game.');
              return;
            }
            forgetStoredGame();
            gameIdRef.current = null;
            setGameId(null);
            setGameStatus('idle');
            setStatus('The saved game is no longer active. Ready for a new training game.');
          }).catch((lookupError) => {
            setStatus(`Could not recover the saved game: ${String(lookupError)}`);
          });
          return;
        }
        setStatus(`Game connection stopped: ${String(error)}`);
      },
    );
    return () => controller.abort();
  }, [token, gameId, account, setActiveGameId]);

  useEffect(() => {
    if (!gameId) return;

    let cancelled = false;
    let requestInFlight = false;

    const syncFromBotBackend = async () => {
      if (requestInFlight || cancelled) return;

      requestInFlight = true;

      try {
        const cached = await getCachedGameState(gameId);

        if (!cached || cancelled) {
          return;
        }

        const cachedMoves = String(
          cached.state?.moves || '',
        ).trim();

        const currentMoves =
          movesTextRef.current.trim();

        const cachedMoveList = cachedMoves
          ? cachedMoves.split(/\s+/)
          : [];

        const currentMoveList = currentMoves
          ? currentMoves.split(/\s+/)
          : [];

        // The normal Lichess stream remains the primary source.
        //
        // Only use Render when its cached game has MORE moves
        // than the iPhone currently knows about.
        if (
          cachedMoveList.length >
          currentMoveList.length
        ) {
          movesTextRef.current = cachedMoves;
          setMovesText(cachedMoves);

          if (cached.initialFen) {
            setInitialFen(cached.initialFen);
          }

          const state = cached.state;

          if (
            state.winner === 'white' ||
            state.winner === 'black'
          ) {
            setWinner(state.winner);
          }

          const nextStatus = String(
            state.status || 'started',
          );

          setGameStatus(nextStatus);

          setClock((previous) => ({
            enabled: previous.enabled,
            white:
              typeof state.wtime === 'number'
                ? state.wtime
                : previous.white,
            black:
              typeof state.btime === 'number'
                ? state.btime
                : previous.black,
            increment:
              typeof state.winc === 'number'
                ? state.winc
                : previous.increment,
            updatedAt: Date.now(),
          }));

          // If our own move was waiting for confirmation,
          // the cached state can also confirm it.
          const pendingMove =
            pendingMoveRef.current;

          if (
            pendingMove &&
            cachedMoveList.length >
              pendingMove.basePly
          ) {
            pendingMoveRef.current = null;
            setMoveInFlight(false);
          }

          setStatus(
            'Game resynced automatically.',
          );
        }
      } catch (error) {
        // Do not interrupt the game just because the backup
        // sync temporarily failed. The normal Lichess stream
        // may still be working perfectly.
        console.warn(
          'Backup game sync failed:',
          error,
        );
      } finally {
        requestInFlight = false;
      }
    };

    // Check once immediately.
    void syncFromBotBackend();

    // Then use Render as a lightweight safety net.
    const timer = window.setInterval(
      () => void syncFromBotBackend(),
      1500,
    );

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [gameId]);

  useEffect(() => {
    coachAbortRef.current?.abort();
    coachQueueRef.current = [];
    coachProcessingRef.current = false;
    observedCoachPlyRef.current = null;
    setCoachResult(null);
    setCoachError('');
    setCoachThinking(false);
    setPendingPromotion(null);
    pendingMoveRef.current = null;
    setMoveInFlight(false);
    setEndGameConfirm(false);
    setReviewMode(null);
    setReviewTarget(null);
    setWinner(null);
    setGameOverOpen(false);
    if (gameId) setCoachNotes(readLearningNotes(gameId));
    setRollbackSignal((value) => value + 1);
  }, [gameId]);

  useEffect(() => {
    if (!gameId || !coachNotes.length) return;
    storeLearningNotes(gameId, account?.username, coachNotes);
  }, [gameId, account?.username, coachNotes]);

  function speak(text: string) {
    if (!voiceEnabled) return;

    void speakCoach(
      text,
      coachLanguage,
    );
  }

  const processCoachQueue = useCallback(async () => {
    if (coachProcessingRef.current) return;

    coachProcessingRef.current = true;

    try {
      while (coachQueueRef.current.length > 0) {
        const job = coachQueueRef.current.shift();

        if (!job) continue;

        const controller = new AbortController();
        coachAbortRef.current = controller;

        setCoachThinking(true);
        setCoachError('');

        try {
          const result = await analyzeMove(
            job.fenBefore,
            job.uci,
            coachDetail,
            controller.signal,
            coachLanguage,
          );

          if (!result.shouldCoach) {
            // Give lightweight feedback for normal moves,
            // but do NOT add them to the Learning Log.
            setCoachResult(result);
            speak(result.feedback);
            continue;
          }

          // Always save the mistake even if the player
          // has already played several more moves.
          setCoachNotes((current) => {
            const note: CoachNote = {
              ...result,
              gameId: gameId || '',
              savedAt: Date.now(),
              playerColor: myColor,
            };

            return [
              note,
              ...current.filter((item) => item.ply !== note.ply),
            ].slice(0, 16);
          });

          // Only replace the live coaching card if this is
          // still useful to show.
          setCoachResult(result);

          speak(result.feedback);
        } catch (error) {
          if (!isAbortError(error)) {
            setCoachError(
              `Coach analysis unavailable: ${String(error)}`,
            );
          }
        }
      }
    } finally {
      coachProcessingRef.current = false;
      coachAbortRef.current = null;
      setCoachThinking(false);
    }
  }, [
    coachDetail,
    coachLanguage,
    gameId,
    myColor,
    voiceEnabled,
  ]);


const analyzeStudentMove = useCallback(
  (fenBefore: string, uci: string) => {
    if (!isCoachGame) return;

    coachQueueRef.current.push({
      fenBefore,
      uci,
    });

    void processCoachQueue();
  },
  [isCoachGame, processCoachQueue],
);
  useEffect(() => {
    // Normal phone games use the exact local pre-move FEN captured when the
    // player makes the move. Only SenseRobot games need stream-observed
    // coaching because the move is made on the physical board.
    if (!gameId || !isCoachGame || !isSenseRobotGame) {
      observedCoachPlyRef.current = null;
      return;
    }

    const moves = movesText.trim()
      ? movesText.trim().split(/\s+/)
      : [];

    const currentPly = moves.length;

    // First observation after connecting/reconnecting.
    //
    // Don't suddenly analyze every historical move from
    // a game that was already in progress.
    if (observedCoachPlyRef.current == null) {
      observedCoachPlyRef.current = currentPly;
      return;
    }

    const previousPly = observedCoachPlyRef.current;

    if (currentPly <= previousPly) {
      observedCoachPlyRef.current = currentPly;
      return;
    }

    // Mark these moves as observed before starting analysis
    // so React updates/re-renders cannot analyze them twice.
    observedCoachPlyRef.current = currentPly;

    let latestStudentMoveIndex = -1;

    // Look only at NEW moves.
    //
    // Array index 0 = ply 1 = White
    // Array index 1 = ply 2 = Black
    // etc.
    for (
      let moveIndex = previousPly;
      moveIndex < currentPly;
      moveIndex += 1
    ) {
      const moverColor: 'white' | 'black' =
        moveIndex % 2 === 0
          ? 'white'
          : 'black';

      if (moverColor === myColor) {
        latestStudentMoveIndex = moveIndex;
      }
    }

    // The only new move(s) were made by the bot.
    if (latestStudentMoveIndex < 0) {
      return;
    }

    const uci = moves[latestStudentMoveIndex];

    if (!uci) {
      return;
    }

    // Rebuild the exact board immediately BEFORE
    // the student's move.
    const movesBeforeStudentMove = moves
      .slice(0, latestStudentMoveIndex)
      .join(' ');

    const beforePosition = replay(
      initialFen,
      movesBeforeStudentMove,
    );

    analyzeStudentMove(
      beforePosition.chess.fen(),
      uci,
    );
  }, [
    gameId,
    movesText,
    initialFen,
    myColor,
    isCoachGame,
    isSenseRobotGame,
    analyzeStudentMove,
  ]);

    const submitMove = useCallback(async (
      fenBefore: string,
      basePly: number,
      from: string,
      to: string,
      promotion?: PromotionChoice,
    ) => {
    if (!token || !gameId || !activeGame || pendingMoveRef.current) {
      setRollbackSignal((value) => value + 1);
      return;
    }
    const uci = `${from}${to}${promotion || ''}`;
    setPendingPromotion(null);
    pendingMoveRef.current = { uci, basePly };
    setMoveInFlight(true);
    setStatus('Sending move…');
    try {
      await makeMove(token, gameId, uci);
      // The game stream is authoritative. Keep the board locked until that
      // stream confirms this exact move, so a fast bot reply cannot leave the
      // frontend one ply behind or allow a second move from a stale position.
      if (pendingMoveRef.current?.uci === uci) {
        setStatus('Move accepted — syncing board…');
      }

      // Restore the earlier, more reliable coaching path for normal games:
      // analyze the exact board position that existed when the move was made.
      analyzeStudentMove(fenBefore, uci);
    } catch (error) {
      if (pendingMoveRef.current?.uci === uci) {
        pendingMoveRef.current = null;
        setMoveInFlight(false);
      }
      setRollbackSignal((value) => value + 1);
      setStatus(`Move failed: ${String(error)}`);
    }
  }, [token, gameId, activeGame, analyzeStudentMove]);

    const handleBoardMove = useCallback((from: string, to: string) => {
      if (
        isSenseRobotGame ||
        !token ||
        !gameId ||
        !canMove ||
        !activeGame
      ) {
        setRollbackSignal((value) => value + 1);
        return;
      }

    const fenBefore = position.chess.fen();
    const basePly = position.plyCount;
    const clone = new Chess(fenBefore);
    const legal = clone.moves({ square: from as Square, verbose: true }).filter((move) => move.to === to) as Move[];
    if (!legal.length) {
      setRollbackSignal((value) => value + 1);
      return;
    }
    const promotions = Array.from(new Set(
      legal.map((move) => move.promotion).filter(Boolean) as PromotionChoice[],
    ));
    if (promotions.length) {
      setPendingPromotion({ from, to, fenBefore, basePly, choices: promotions });
      return;
    }
    void submitMove(fenBefore, basePly, from, to);
  }, [isSenseRobotGame, token, gameId, canMove, activeGame, position.chess, position.plyCount, submitMove]);

  async function waitForBotReady(): Promise<BotRuntimeStatus> {
    const deadline = Date.now() + 8000;
    let last: BotRuntimeStatus = bot;
    while (Date.now() < deadline) {
      last = await getBotStatus();
      setBot(last);
      if (last.running && last.connected) return last;
      await new Promise((resolve) => window.setTimeout(resolve, 180));
    }
    throw new Error(last.error || 'Bot could not connect to Lichess.');
  }

  async function changeLevel(nextLevel: (typeof LEVELS)[number]['id']) {
    setLevel(nextLevel);
    try {
      const state = await setBotLevel(nextLevel);
      setBot(state);
      const selected = LEVELS.find((item) => item.id === nextLevel);
      setStatus(`Difficulty: ${selected?.label} (~${selected?.elo}).`);
    } catch (error) {
      setStatus(`Could not change difficulty: ${String(error)}`);
    }
  }


  function changeTimeControl(nextId: TimeControlId) {
    setTimeControlId(nextId);
    const selected = TIME_CONTROLS.find((item) => item.id === nextId);
    if (selected) setStatus(`Time control: ${selected.label} · ${selected.detail}.`);
  }

  async function startCoachGame() {
    if (!token || !account || startingGame || activeGame || gameId || !recoveryChecked) return;

    setStartingGame(true);
    setStatus('Checking for an existing training game…');

    // Normal Play is always a regular Lichess online game.
    // Only the QR scanner is allowed to enable SenseRobot mode.
    setSenseRobotGameId(null);

    try {
      // Refreshes and slow API propagation must never create a second game.
      const existingGames = await getPlayingGames(token);
      const existing = existingGames.find(
        (game) =>
          game.opponent?.username?.toLowerCase() ===
          BOT_USERNAME.toLowerCase(),
      );

      if (existing?.gameId) {
        setActiveGameId(existing.gameId);
        setGameStatus('recovering');
        setStatus('Rejoined your existing training game.');
        return;
      }

      setStatus('Preparing coach bot…');

      const levelState = await setBotLevel(level);
      setBot(levelState);

      let state = levelState;
      if (!state.running) {
        state = await startBot();
      }

      setBot(state);
      await waitForBotReady();

      const selectedTimeControl =
        TIME_CONTROLS.find((item) => item.id === timeControlId) ||
        TIME_CONTROLS[4];

      setCurrentTimeControlLabel(selectedTimeControl.label);
      setStatus(
        `Challenging ${BOT_USERNAME} · ${selectedTimeControl.label}…`,
      );

      const challenge = await challengeBot(token, BOT_USERNAME, {
        timeControl: selectedTimeControl.timeControl,
        color: preferredColor,
      });

      let acceptedGameId: string | null = null;
      let acceptError: unknown = null;

      try {
        const accepted = await acceptBotChallenge(
          challenge.id,
          account.username,
        );
        setBot(accepted);
        acceptedGameId = accepted.gameId || null;
      } catch (error) {
        // A game can already exist even when the bot's gameStart event
        // arrives late. Recover the real Lichess game before giving up.
        acceptError = error;
      }

      if (!acceptedGameId) {
        setStatus('Challenge accepted · connecting to game…');

        // Poll gently for a short period. This prevents the phone from
        // getting stranded on the setup screen while the real game times out.
        const deadline = Date.now() + 9000;

        while (Date.now() < deadline && !acceptedGameId) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, 750),
          );

          try {
            const games = await getPlayingGames(token);
            const found = games.find(
              (game) =>
                game.opponent?.username?.toLowerCase() ===
                BOT_USERNAME.toLowerCase(),
            );

            if (found?.gameId) {
              acceptedGameId = found.gameId;
            }
          } catch {
            // A transient read failure should not abandon a game that
            // may already be starting.
          }
        }
      }

      if (!acceptedGameId) {
        throw (
          acceptError ||
          new Error(
            'The challenge was accepted, but the game did not become visible in time.',
          )
        );
      }

      setActiveGameId(acceptedGameId);
      setGameStatus('recovering');
      setStatus(`Game started against ${BOT_USERNAME}.`);
    } catch (error) {
      setStatus(
        `Could not start game: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    } finally {
      setStartingGame(false);
    }
  }

  async function scanSenseRobotRoom() {
    if (
      scanningRoom ||
      startingGame ||
      activeGame ||
      gameId ||
      !recoveryChecked
    ) {
      return;
    }

    setScanningRoom(true);

    try {
      setStatus('Preparing coach bot…');

      // Always apply the difficulty currently selected
      // in Chess Buddy before joining the SenseRobot room.
      const levelState = await setBotLevel(level);
      setBot(levelState);

      let state = levelState;

      if (!state.running) {
        state = await startBot();
        setBot(state);
      }

      if (!state.connected) {
        state = await waitForBotReady();
        setBot(state);
      }

      setStatus('Scan the SenseRobot room QR code…');

      const joined = await scanSenseRoom();

      setBot(joined);

      if (!joined.gameId) {
        throw new Error(
          'The room was joined, but Lichess did not report a game.'
        );
      }

      setActiveGameId(joined.gameId);

      // This successful QR scan is the one and only activation path
      // for SenseRobot mode.
      setSenseRobotGameId(joined.gameId);

      setGameStatus('recovering');

      setStatus(
        `SenseRobot room joined as ${BOT_USERNAME}.`
      );
    } catch (error) {
      setStatus(
        `Could not join SenseRobot room: ${
          error instanceof Error
            ? error.message
            : String(error)
        }`
      );
    } finally {
      setScanningRoom(false);
    }
  }

  function requestTakeback() {
    if (!token || !gameId) return;
    handleTakeback(token, gameId, true)
      .then(() => setStatus('Takeback requested. The training bot will accept it.'))
      .catch((error) => setStatus(`Takeback failed: ${String(error)}`));
  }

  async function endCurrentGame() {
    if (!token || !gameId || !activeGame || !endGameConfirm) return;
    try {
      setEndGameConfirm(false);
      if (position.plyCount < 2) {
        await abortGame(token, gameId);
        setStatus('Game aborted.');
      } else {
        await resignGame(token, gameId);
        setStatus('Game resigned.');
      }
      forgetStoredGame();
    } catch (error) {
      setStatus(`Could not end game: ${String(error)}`);
    }
  }

  function resetFinishedGame() {
    coachAbortRef.current?.abort();
    coachQueueRef.current = [];
    coachProcessingRef.current = false;

    forgetStoredGame();
    gameIdRef.current = null;
    setGameId(null);

    setSenseRobotGameId(null);

    movesTextRef.current = '';
    setMovesText('');
    setInitialFen('startpos');
    setGameStatus('idle');
    setPlayers({ white: { name: 'White' }, black: { name: 'Black' } });
    setClock({ enabled: true, white: 600000, black: 600000, increment: 0, updatedAt: Date.now() });
    setCoachResult(null);
    setCoachNotes([]);
    setCoachError('');
    setPendingPromotion(null);
    pendingMoveRef.current = null;
    setMoveInFlight(false);
    setEndGameConfirm(false);
    setWinner(null);
    setGameOverOpen(false);
    setReviewMode(null);
    setReviewTarget(null);
    setRollbackSignal((value) => value + 1);
    setStatus('Ready for another training game.');
  }

  if (!token) {
    return <main className="landing">
      <div className="hero-card">
        <span className="eyebrow">AI CHESS COACH</span>
        <h1>Play a bot.<br />Learn every game.</h1>
        <p>Challenge the training bot on Lichess and get immediate, position-specific coaching when a move needs attention.</p>
        <button className="primary" onClick={() => void loginWithLichess()}>Sign in with Lichess</button>
        <p className="fine-print">AI coaching is enabled only in games against the designated training bot.</p>
      </div>
    </main>;
  }

  const topSide = orientation === 'white' ? 'black' : 'white';
  const bottomSide = orientation === 'white' ? 'white' : 'black';
  const coachingMoments = coachNotes.length;
  const blunders = coachNotes.filter((note) => note.classification === 'blunder').length;
  const mistakes = coachNotes.filter((note) => note.classification === 'mistake').length;
  const focusLessons = Array.from(new Set(coachNotes.map((note) => note.lesson).filter(Boolean))).slice(0, 3);
  const botLabel = bot.connected ? 'Coach bot ready' : bot.running ? 'Coach bot connecting' : 'Coach bot offline';
  const selectedLevel = LEVELS.find((item) => item.id === level) || LEVELS[2];
  const selectedTimeControl = TIME_CONTROLS.find((item) => item.id === timeControlId) || TIME_CONTROLS[4];
  const reviewBestUci = reviewTarget?.bestMoveUci || '';
  const reviewReplyUci = reviewTarget?.opponentReplyUci || '';
  const reviewPlayedUci = reviewTarget?.playedMoveUci || '';
  const reviewOrientation = reviewTarget?.playerColor || myColor;
  const terminalGame = Boolean(gameId && !activeGame && gameStatus !== 'recovering' && gameStatus !== 'idle');
  const drawStatus = ['stalemate', 'draw', 'insufficientMaterialClaim'].includes(gameStatus);
  const gameOutcomeTitle = winner
    ? winner === myColor ? 'You won!' : 'Game lost'
    : drawStatus ? 'Draw' : 'Game ended';
  const gameOutcomeClass = winner ? (winner === myColor ? 'win' : 'loss') : drawStatus ? 'draw' : 'ended';
  const gameScore = winner === 'white' ? '1–0' : winner === 'black' ? '0–1' : drawStatus ? '½–½' : '—';
  const gameReason = gameEndReason(gameStatus, winner, myColor);
  const orderedCoachNotes = [...coachNotes].sort((a, b) => a.ply - b.ply);

  const reviewIndex = reviewTarget
    ? orderedCoachNotes.findIndex(
        (note) => note.ply === reviewTarget.ply
      )
    : -1;

  function openReviewAt(index: number) {
    if (!orderedCoachNotes.length) return;

    const normalized =
      (index + orderedCoachNotes.length) % orderedCoachNotes.length;

    setReviewTarget(orderedCoachNotes[normalized]);
  }

  function previousReview() {
    if (!orderedCoachNotes.length) return;

    openReviewAt(
      reviewIndex >= 0
        ? reviewIndex - 1
        : orderedCoachNotes.length - 1
    );
  }

  function nextReview() {
    if (!orderedCoachNotes.length) return;

    openReviewAt(
      reviewIndex >= 0
        ? reviewIndex + 1
        : 0
    );
  }

  function animateReviewChange(direction: 'next' | 'previous') {
    if (reviewAnimatingRef.current) return;

    if (orderedCoachNotes.length < 2) {
      setReviewDragging(false);
      setReviewDragX(0);
      return;
    }

    reviewAnimatingRef.current = true;
    setReviewDragging(false);

    const width = Math.max(window.innerWidth, 400);

    // Swipe left -> current review exits left.
    const outgoing =
      direction === 'next'
        ? -width
        : width;

    // New review enters from opposite side.
    const incoming = -outgoing;

    setReviewDragX(outgoing);

    window.setTimeout(() => {
      if (direction === 'next') {
        nextReview();
      } else {
        previousReview();
      }

      // Instantly move the NEW review to the opposite side.
      setReviewNoTransition(true);
      setReviewDragX(incoming);

      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          // Animate new review into the center.
          setReviewNoTransition(false);
          setReviewDragX(0);

          window.setTimeout(() => {
            reviewAnimatingRef.current = false;
          }, 220);
        });
      });
    }, 180);
  }

  return <div className="app-shell">
    <header>
      <div className="brand-row"><span className="eyebrow">AI CHESS COACH</span><strong>{account?.username || 'Connecting…'}</strong></div>
      <div className="header-actions">
        <span className={`status-dot ${bot.connected ? 'online' : 'offline'}`} />
        <span className="header-status">{status}</span>
        {bot.lastMoveMs != null ? <span className="speed-pill">bot {bot.lastMoveMs} ms</span> : null}
        <button className="ghost" onClick={() => { logout(); setToken(null); }}>Log out</button>
      </div>
    </header>

    <main className="game-layout">
      <section className="play-column">
        <PlayerBar player={players[topSide]} clock={displayedClock[topSide]} active={activeGame && turnColor === topSide} side={topSide} />
        <section className="board-panel">
          <ChessBoard
            fen={displayPosition.chess.fen()}
            orientation={orientation}
            movableColor={canMove ? myColor : undefined}
            destinations={canMove ? destinations(position.chess) : new Map()}
            lastMove={displayPosition.lastMove}
            coachArrows={historyPly == null ? coachArrows : []}
            coachHighlights={historyPly == null ? coachHighlights : []}
            rollbackSignal={rollbackSignal}
            onMove={handleBoardMove}
          />
        </section>
        <PlayerBar player={players[bottomSide]} clock={displayedClock[bottomSide]} active={activeGame && turnColor === bottomSide} side={bottomSide} />
        <div className="under-board">
          <span>
            {gameId ? (
              <span className="under-board-meta">
                <span>Training game</span>
                <span className="bot-level-pill">
                  {selectedLevel.label}
                  <small>~{selectedLevel.elo}</small>
                </span>
                <span>{currentTimeControlLabel}</span>
              </span>
            ) : 'No active game'}
          </span>
          <span>
            {gameId
              ? activeGame
                ? moveInFlight
                  ? 'Syncing your move…'
                  : isMyTurn
                    ? isSenseRobotGame
                      ? 'Your turn · move on SenseRobot'
                      : 'Your turn'
                    : `${players[turnColor].name} is thinking`
                : gameStatus === 'recovering'
                  ? 'Reconnecting to game…'
                  : `${gameOutcomeTitle} · ${gameReason}`
              : recoveryChecked
                ? 'Choose a level and start'
                : 'Checking for an active game…'}
          </span>
        </div>
      </section>

      <aside className="side-panel">
        {!gameId && <section className="card setup-card">
          <div className="section-title"><span>1</span> Training opponent</div>
          <p className="section-copy">Estimated practice strength — start low and move up when games feel comfortable.</p>
          <div className="level-grid">
            {LEVELS.map((item) => <button
              key={item.id}
              className={level === item.id ? 'level active' : 'level'}
              onClick={() => void changeLevel(item.id)}
            >
              <strong>{item.label}</strong>
              <small>~{item.elo} · {item.hint}</small>
            </button>)}
          </div>
          <div className="setup-subtitle">Time control</div>
          <div className="time-control-grid" role="group" aria-label="Choose time control">
            {TIME_CONTROLS.map((item) => <button
              key={item.id}
              className={timeControlId === item.id ? 'time-control active' : 'time-control'}
              onClick={() => changeTimeControl(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </button>)}
          </div>
          <div className="setup-subtitle">Your color</div>
          <div className="color-choice" role="group" aria-label="Choose your color">
            {(['random', 'white', 'black'] as const).map((color) => <button
              key={color}
              className={preferredColor === color ? 'active' : ''}
              onClick={() => setPreferredColor(color)}
            >{color === 'random' ? 'Random color' : `Play ${color}`}</button>)}
          </div>
          <div className="bot-runtime-row">
            <span><i className={`runtime-dot ${bot.connected ? 'on' : ''}`} />{botLabel}</span>
            <small>{bot.error ? 'Check backend setup' : selectedTimeControl.label}</small>
          </div>
          {bot.error ? <div className="inline-error">{bot.error}</div> : null}
          <button className="primary wide" disabled={startingGame || !recoveryChecked} onClick={() => void startCoachGame()}>
            {!recoveryChecked ? 'Checking active game…' : startingGame ? 'Starting…' : `Play ${BOT_USERNAME}`}
          </button>

          <button
            className="ghost wide"
            disabled={
              scanningRoom ||
              startingGame ||
              !recoveryChecked
            }
            onClick={() => void scanSenseRobotRoom()}
          >
            {scanningRoom
              ? 'Scanning…'
              : '▣ Scan SenseRobot Room'}
          </button>
        </section>}

        {gameId && <section className="card game-card">
          <div className="active-game-banner">
            <div>
              <span className="active-game-kicker">CURRENT OPPONENT</span>
              <strong>{selectedLevel.label}</strong>
              <small>Estimated strength ~{selectedLevel.elo}</small>
            </div>
            <div className="active-game-chips">
              <span>{currentTimeControlLabel}</span>
              <span>{isSenseRobotGame ? 'SenseRobot' : 'Phone'}</span>
            </div>
          </div>
          <div className="game-toolbar">
            <button className="icon-button" title="Flip board" onClick={() => setOrientation((value) => value === 'white' ? 'black' : 'white')}>⇅</button>
            <button className="icon-button" title="Request takeback" disabled={!activeGame} onClick={requestTakeback}>↶</button>
            <a className="icon-button" title="Open on Lichess" href={`https://lichess.org/${gameId}`} target="_blank" rel="noreferrer">↗</a>
          </div>
          {terminalGame ? <div className={`game-result-strip ${gameOutcomeClass}`}>
            <div><span>{gameOutcomeTitle}</span><strong>{gameReason}</strong></div>
            <b>{gameScore}</b>
          </div> : null}
          <div className="move-list">
              {position.san.length === 0 ? (
                <span className="muted">Moves will appear here.</span>
              ) : (
                Array.from(
                  { length: Math.ceil(position.san.length / 2) },
                  (_, index) => {
                    const whiteMoveIndex = index * 2;
                    const blackMoveIndex = index * 2 + 1;

                    const whitePly = whiteMoveIndex + 1;
                    const blackPly = blackMoveIndex + 1;

                    const whiteCoachNote = coachNotes.find(
                      (note) => note.ply === whitePly
                    );

                    const blackCoachNote = coachNotes.find(
                      (note) => note.ply === blackPly
                    );

                    const whiteMove = position.san[whiteMoveIndex];
                    const blackMove = position.san[blackMoveIndex];

                    return (
                      <div className="move-row" key={index}>
                        <b>{index + 1}.</b>

                        {whiteMove ? (
                          <button
                            type="button"
                            className={`move-cell ${
                              historyPly === whitePly ? 'active' : ''
                            } ${
                              whiteCoachNote?.classification === 'blunder'
                                ? 'move-blunder'
                                : whiteCoachNote?.classification === 'mistake'
                                  ? 'move-mistake'
                                  : ''
                            }`}
                            onClick={() => {
                              setHistoryPly(
                                whitePly >= position.plyCount
                                  ? null
                                  : whitePly
                              );
                            }}
                          >
                            {whiteMove}
                          </button>
                        ) : (
                          <span />
                        )}

                        {blackMove ? (
                          <button
                            type="button"
                            className={`move-cell ${
                              historyPly === blackPly ? 'active' : ''
                            } ${
                              blackCoachNote?.classification === 'blunder'
                                ? 'move-blunder'
                                : blackCoachNote?.classification === 'mistake'
                                  ? 'move-mistake'
                                  : ''
                            }`}
                            onClick={() => {
                              setHistoryPly(
                                blackPly >= position.plyCount
                                  ? null
                                  : blackPly
                              );
                            }}
                          >
                            {blackMove}
                          </button>
                        ) : (
                          <span />
                        )}
                      </div>
                    );
                  }
                )
              )}
            </div>
          <div className="game-actions">
            <button className="ghost" disabled={!activeGame} onClick={() => setEndGameConfirm(true)}>
              End game…
            </button>
            {!activeGame ? <button className="primary" onClick={resetFinishedGame}>New training game</button> : null}
          </div>
        </section>}

        <section className="card coach-card">
          <div className="section-title">
            <span>2</span>

            {coachLanguage === 'zh-CN'
              ? 'AI 教练'
              : 'Live coach'}
          </div>
          <div className={`coach-bubble ${coachResult?.classification || ''}`}>
            {coachThinking ? <div className="coach-thinking"><span className="spinner" />Analyzing your move…</div> : coachError ? <div className="inline-error">{coachError}</div> : coachResult ? <>
              <div className="coach-heading">
                <strong>{coachResult.title}</strong>
                {coachResult.shouldCoach ? (
                  <span className={`quality-badge ${coachResult.classification}`}>
                    {coachResult.classification}
                  </span>
                ) : null}
              </div>
              <div>{coachResult.feedback}</div>
              {coachResult.question ? (
                <div className="coach-question">
                  <span>
                    {coachLanguage === 'zh-CN'
                      ? '想一想'
                      : 'Ask yourself'}
                  </span>

                  {coachResult.question}
                </div>
              ) : null}
              {coachResult.lesson ? (
              <div className="coach-lesson">
                {coachLanguage === 'zh-CN'
                  ? '记住：'
                  : 'Remember: '}

                {coachResult.lesson}
              </div>
            ) : null}
              {coachResult.shouldCoach ? <button className="coach-review-button" onClick={() => { setReviewTarget(coachResult); setReviewMode('better'); }}>Review this position</button> : null}
            </> : <>
              <strong>Ready to coach</strong>
              <div>After each move, I’ll quickly check it. Bigger mistakes get a concrete explanation, best-move arrow, and the opponent’s threat when it matters.</div>
            </>}
          </div>
          <div className="coach-detail-setting">
            <span>
              {coachLanguage === 'zh-CN'
                ? '教练语言'
                : 'Coach language'}
            </span>

            <div className="coach-detail-options">
              {(
                [
                  ['en', 'English'],
                  ['zh-CN', '中文'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`coach-detail-button ${
                    coachLanguage === value
                      ? 'active'
                      : ''
                  }`}
                  aria-pressed={
                    coachLanguage === value
                  }
                  onClick={() => {
                    stopCoachSpeech();
                    setCoachLanguage(value);
                  }}
                >
                  <span>{label}</span>

                  {coachLanguage === value ? (
                    <span
                      className="coach-detail-check"
                      aria-hidden="true"
                    >
                      ✓
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
          <div className="coach-detail-setting">
            <span>Coach detail</span>

            <div className="coach-detail-options">
              {(
                [
                  ['quick', 'Quick'],
                  ['balanced', 'Balanced'],
                  ['deep', 'Deep'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`coach-detail-button ${
                    coachDetail === value ? 'active' : ''
                  }`}
                  aria-pressed={coachDetail === value}
                  onClick={() => setCoachDetail(value)}
                >
                  <span>{label}</span>
                  {coachDetail === value ? (
                    <span className="coach-detail-check" aria-hidden="true">✓</span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
          <div className="coach-actions">
            <label>
              <input
                type="checkbox"
                checked={voiceEnabled}
                onChange={(event) => {
                  const enabled =
                    event.target.checked;

                  setVoiceEnabled(enabled);

                  if (enabled) {
                    /*
                    * IMPORTANT:
                    * This happens directly inside a user click,
                    * so iOS can unlock audio playback.
                    */
                    void unlockCoachAudio();
                  } else {
                    stopCoachSpeech();
                  }
                }}
              />

              {coachLanguage === 'zh-CN'
                ? ' 语音'
                : ' Voice'}
            </label>
            <label><input type="checkbox" checked={hintsEnabled} onChange={(event) => setHintsEnabled(event.target.checked)} /> Board hints</label>
          </div>
          <div className="hint-legend"><span><i className="legend-line best" />best</span><span><i className="legend-line danger" />threat</span><span><i className="legend-square" />key square</span></div>
        </section>

        {(gameId || coachNotes.length > 0) && <section className="card learning-card">
          <div className="section-title learning-title"><span>3</span><div>Learning log{!gameId && coachNotes.length ? <small>Saved from your last game</small> : null}</div></div>
          {coachNotes.length === 0 ? <p className="muted">Your important coaching moments will collect here so you can review the exact position later.</p> : <div className="lesson-list">
            {orderedCoachNotes.map((note) => <button
              type="button"
              className="lesson-item"
              key={`${note.gameId}-${note.ply}`}
              onClick={() => { setReviewTarget(note); setReviewMode('better'); }}
            >
              <span className={`lesson-dot ${note.classification}`} />
              <div>
                <strong>Move {note.moveNumber} · {note.playedMove} · {note.title}</strong>
                <small>{note.lesson || 'Review the opponent’s forcing replies.'}</small>
              </div>
              <span className="review-chevron">›</span>
            </button>)}
          </div>}
          {!activeGame && coachNotes.length > 0 ? <div className="session-review">
            <strong>Game review</strong>
            <div className="review-stats"><span><b>{coachingMoments}</b> coach moments</span><span><b>{mistakes}</b> mistakes</span><span><b>{blunders}</b> blunders</span></div>
            {focusLessons.length ? <div className="focus-list"><span>Focus next game</span>{focusLessons.map((lesson) => <small key={lesson}>• {lesson}</small>)}</div> : <small className="muted">No major recurring issue found in this game.</small>}
          </div> : null}
        </section>}
      </aside>
    </main>

    {reviewMode && reviewTarget && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Review coached position" onMouseDown={(event) => { if (event.target === event.currentTarget) setReviewMode(null); }}>
      <div
        className="review-modal"
        style={{
          transform: `translate3d(${reviewDragX}px, 0, 0)`,
          transition:
            reviewNoTransition || reviewDragging
              ? 'none'
              : 'transform 180ms cubic-bezier(0.22, 1, 0.36, 1)',
          willChange: 'transform',
        }}
        onTouchStart={(event) => {
          if (reviewAnimatingRef.current) return;

          const touch = event.changedTouches[0];

          reviewTouchStart.current = {
            x: touch.clientX,
            y: touch.clientY,
          };

          setReviewDragging(true);
        }}
        onTouchMove={(event) => {
          if (
            !reviewTouchStart.current ||
            reviewAnimatingRef.current
          ) {
            return;
          }

          const touch = event.changedTouches[0];

          const dx =
            touch.clientX - reviewTouchStart.current.x;

          const dy =
            touch.clientY - reviewTouchStart.current.y;

          // Don't interfere with vertical scrolling.
          if (Math.abs(dy) > Math.abs(dx)) {
            return;
          }

          // Slight resistance makes it feel less stiff.
          setReviewDragX(dx * 0.9);
        }}
        onTouchEnd={(event) => {
          const start = reviewTouchStart.current;
          reviewTouchStart.current = null;

          if (!start || reviewAnimatingRef.current) {
            return;
          }

          const touch = event.changedTouches[0];

          const dx = touch.clientX - start.x;
          const dy = touch.clientY - start.y;

          // Not enough movement -> snap back.
          if (
            Math.abs(dx) < 65 ||
            Math.abs(dx) < Math.abs(dy)
          ) {
            setReviewDragging(false);
            setReviewDragX(0);
            return;
          }

          if (dx < 0) {
            animateReviewChange('next');
          } else {
            animateReviewChange('previous');
          }
        }}
      >
        <div className="review-modal-head">
          <div>
            <span className="eyebrow">COACH REVIEW</span>
            <strong>Move {reviewTarget.moveNumber} · {reviewTarget.playedMove}</strong>
            <small>{reviewTarget.title}</small>
          </div>
          <div className="review-nav">
            <span>
              {reviewIndex >= 0 ? reviewIndex + 1 : 1}
              {' / '}
              {orderedCoachNotes.length}
            </span>

            <button
              className="ghost"
              onClick={() => setReviewMode(null)}
            >
              Close
            </button>
          </div>
        </div>
        <div className="review-tabs">
          <button className={reviewMode === 'better' ? 'active' : ''} onClick={() => setReviewMode('better')}>Before your move</button>
          <button className={reviewMode === 'threat' ? 'active' : ''} onClick={() => setReviewMode('threat')}>After your move</button>
        </div>
        <div className="review-context">
          {reviewMode === 'better' ? 'This is the exact position where you had to choose your move.' : `This is the position immediately after ${reviewTarget.playedMove}.`}
        </div>
        <div className="review-board-wrap">
          <ChessBoard
            fen={reviewMode === 'better' ? reviewTarget.fenBefore : reviewTarget.fenAfter}
            orientation={reviewOrientation}
            movableColor={undefined}
            destinations={new Map()}
            lastMove={reviewMode === 'threat' && reviewPlayedUci.length >= 4 ? [reviewPlayedUci.slice(0, 2), reviewPlayedUci.slice(2, 4)] as [string, string] : undefined}
            coachArrows={reviewMode === 'better' && reviewBestUci.length >= 4
              ? [{ from: reviewBestUci.slice(0, 2), to: reviewBestUci.slice(2, 4), kind: 'best' }]
              : reviewMode === 'threat' && reviewReplyUci.length >= 4
                ? [{ from: reviewReplyUci.slice(0, 2), to: reviewReplyUci.slice(2, 4), kind: 'danger' }]
                : []}
            coachHighlights={reviewMode === 'better'
              ? (reviewTarget.highlightsBefore || [])
              : (reviewTarget.highlightsAfter || [])}
            rollbackSignal={0}
            onMove={() => undefined}
          />
        </div>
        <div className="review-explanation">
          <strong>
            {reviewMode === 'better'
              ? `Better: ${reviewTarget.bestMove}`
              : reviewTarget.opponentReply
                ? `Threat: ${reviewTarget.opponentReply}`
                : 'What changed?'}
          </strong>
          <p>
            {reviewMode === 'better'
              ? `Trace the green arrow and compare it with ${reviewTarget.playedMove}.`
              : reviewTarget.opponentReply
                ? 'The red arrow shows the strongest reply you needed to notice.'
                : 'Look at what changed immediately after your move.'}
          </p>
        </div>

        <div className="review-analysis">
          <div className="review-analysis-head">
            <span>COACH ANALYSIS</span>
            <span className={`quality-badge ${reviewTarget.classification}`}>
              {reviewTarget.classification}
            </span>
          </div>

          <p>{reviewTarget.feedback}</p>

          <div className="review-analysis-moves">
            <span>
              <small>You played</small>
              <strong>{reviewTarget.playedMove}</strong>
            </span>
            <span>
              <small>Better</small>
              <strong>{reviewTarget.bestMove}</strong>
            </span>
            {reviewTarget.opponentReply ? (
              <span>
                <small>Best reply</small>
                <strong>{reviewTarget.opponentReply}</strong>
              </span>
            ) : null}
          </div>

          {reviewTarget.lesson ? (
            <div className="review-analysis-lesson">
              <span>Remember</span>
              {reviewTarget.lesson}
            </div>
          ) : null}

          {reviewTarget.question ? (
            <div className="review-analysis-question">
              <span>Ask yourself</span>
              {reviewTarget.question}
            </div>
          ) : null}
        </div>
      </div>
    </div>}

    {gameOverOpen && terminalGame && <div className="modal-backdrop game-over-backdrop" role="dialog" aria-modal="true" aria-label="Game over">
      <div className={`game-over-modal ${gameOutcomeClass}`}>
        <span className="eyebrow">GAME OVER</span>
        <div className="game-over-score">{gameScore}</div>
        <h2>{gameOutcomeTitle}</h2>
        <p>{gameReason}</p>
        <div className="game-over-summary">
          <span><b>{coachingMoments}</b> learning moments</span>
          <span><b>{mistakes}</b> mistakes</span>
          <span><b>{blunders}</b> blunders</span>
        </div>
        <div className="game-over-actions">
          <button className="ghost" onClick={() => setGameOverOpen(false)}>Keep board open</button>
          <button
            className="ghost"
            disabled={!orderedCoachNotes.length}
            onClick={() => {
              const first = orderedCoachNotes[0];
              if (!first) return;
              setGameOverOpen(false);
              setReviewTarget(first);
              setReviewMode('better');
            }}
          >Review mistakes</button>
          <button className="primary" onClick={resetFinishedGame}>New training game</button>
        </div>
      </div>
    </div>}

    {endGameConfirm && gameId && activeGame && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Confirm end game" onMouseDown={(event) => { if (event.target === event.currentTarget) setEndGameConfirm(false); }}>
      <div className="confirm-modal">
        <span className="eyebrow">END TRAINING GAME</span>
        <strong>{position.plyCount < 2 ? 'Abort this game?' : 'Resign this game?'}</strong>
        <p>Refreshing or closing this page will not end the game. Only this confirmation sends an end-game request to Lichess.</p>
        <div className="confirm-actions">
          <button className="ghost" onClick={() => setEndGameConfirm(false)}>Keep playing</button>
          <button className="danger-button" onClick={() => void endCurrentGame()}>{position.plyCount < 2 ? 'Abort game' : 'Resign game'}</button>
        </div>
      </div>
    </div>}

    {pendingPromotion && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Choose promotion piece">
      <div className="promotion-modal">
        <strong>Promote pawn to</strong>
        <div className="promotion-options">
          {pendingPromotion.choices.map((choice) => <button key={choice} onClick={() => void submitMove(pendingPromotion.fenBefore, pendingPromotion.basePly, pendingPromotion.from, pendingPromotion.to, choice)}>
            {{ q: '♕', r: '♖', b: '♗', n: '♘' }[choice]}
          </button>)}
        </div>
        <button className="ghost" onClick={() => { setPendingPromotion(null); setRollbackSignal((value) => value + 1); }}>Cancel</button>
      </div>
    </div>}
  </div>;
}