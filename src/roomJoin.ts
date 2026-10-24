import { parseSenseRoomUrl, type SenseRoom } from './botControl';
import type { PlayingGame } from './lichess';
import { requireSenseTrainingGame } from './senseRecovery';

export function roomJoinPreview(raw: string) {
  const path = (() => { try { return new URL(raw.trim()).pathname; } catch { return ''; } })();
  if (/^\/(?:game\/)?[A-Za-z0-9]{8}\/(?:white|black)\/?$/.test(path)) {
    throw new Error('This is a game-viewing link. Create a room on SenseRobot and paste its invitation with ?color=white or ?color=black.');
  }
  const room = parseSenseRoomUrl(raw);
  return { ...room, playerColor: room.color === 'white' ? 'black' as const : 'white' as const };
}

export function requireExactJoinedRoom(expected: string, actual: string | null | undefined): string {
  if (!actual || actual !== expected) throw new Error('The bot did not confirm this exact room. Keep the current game open and check the room before retrying.');
  return actual;
}

/** Recover only the supplied room; another active bot game is never a substitute. */
export function recoverJoinedRoom(room: SenseRoom, botUsername: string, games: readonly PlayingGame[]): string | null {
  if (!games.some(game => game.gameId === room.challengeId)) return null;
  const game = requireSenseTrainingGame(room.challengeId, botUsername, games);
  if (game.color !== (room.color === 'white' ? 'black' : 'white')) {
    throw new Error('The room link names the wrong bot color for this joined game. Check the original invitation.');
  }
  return game.gameId;
}
