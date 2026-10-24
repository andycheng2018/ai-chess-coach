import { Chess } from 'chess.js';

type PlayerColor = 'white' | 'black';
export type CoachStreamSnapshot = {
  gameId: string;
  account: string;
  playerColor: PlayerColor;
  initialFen: string;
  moves: readonly string[];
  status: string;
  /** gameFull establishes a baseline, including after a reconnect. */
  resync?: boolean;
};
export type CoachStreamCursor = Omit<CoachStreamSnapshot, 'resync'>;
export type ConfirmedCoachMove = { fenBefore: string; uci: string; moves: string[] };

/** Observe only the primary Lichess stream, independently of the input device.
 * Initial history, reconnect snapshots, rewinds and alternate lines never replay
 * old coaching or robot reactions. A batched update coaches its newest player move.
 */
export function observeCoachStream(previous: CoachStreamCursor | null, snapshot: CoachStreamSnapshot): {
  cursor: CoachStreamCursor | null; move: ConfirmedCoachMove | null; invalidated: boolean;
} {
  const cursor: CoachStreamCursor = { ...snapshot, moves: [...snapshot.moves] };
  const sameIdentity = previous && previous.gameId === snapshot.gameId
    && previous.account === snapshot.account && previous.playerColor === snapshot.playerColor
    && previous.initialFen === snapshot.initialFen;
  const extendsLine = sameIdentity && previous.moves.length <= snapshot.moves.length
    && previous.moves.every((move, index) => move === snapshot.moves[index]);
  if (!snapshot.gameId || !snapshot.account || snapshot.resync || !sameIdentity || !extendsLine
    || !['started', 'created'].includes(snapshot.status)) {
    return { cursor, move: null, invalidated: true };
  }
  if (previous.moves.length === snapshot.moves.length) {
    return { cursor, move: null, invalidated: false };
  }

  try {
    const board = snapshot.initialFen && snapshot.initialFen !== 'startpos'
      ? new Chess(snapshot.initialFen) : new Chess();
    let latest: ConfirmedCoachMove | null = null;
    for (let index = 0; index < snapshot.moves.length; index += 1) {
      const uci = snapshot.moves[index];
      const mover: PlayerColor = board.turn() === 'w' ? 'white' : 'black';
      const fenBefore = board.fen();
      board.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      if (index >= previous.moves.length && mover === snapshot.playerColor) {
        latest = { fenBefore, uci, moves: snapshot.moves.slice(0, index + 1) };
      }
    }
    return { cursor, move: latest, invalidated: false };
  } catch {
    // An invalid stream position must never produce an engine/robot request.
    return { cursor: null, move: null, invalidated: true };
  }
}
