import { parseSenseRoomUrl, type SenseRoom, type CachedGameState } from './botControl';
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


const ROOM_DRAFT_KEY = 'chess_buddy_pending_room_invitation';
const ROOM_DRAFT_TTL_MS = 30 * 60 * 1000;

/** Only a public invitation ID/color survives OAuth; never store tokens or private seats. */
export function saveRoomJoinDraft(raw: string, storage?: Pick<Storage, 'setItem'>, now = Date.now()): boolean {
  try {
    const room = raw.trim() ? roomJoinPreview(raw) : null;
    const url = room ? `https://lichess.org/game/${room.challengeId}?color=${room.color}` : '';
    (storage ?? localStorage).setItem(ROOM_DRAFT_KEY, JSON.stringify({ url, savedAt: now }));
    return true;
  } catch { return false; }
}

export function readRoomJoinDraft(storage?: Pick<Storage, 'getItem'>, now = Date.now()): string | null {
  try {
    const value = JSON.parse((storage ?? localStorage).getItem(ROOM_DRAFT_KEY) || 'null');
    if (!value || typeof value.url !== 'string' || typeof value.savedAt !== 'number'
      || !Number.isFinite(value.savedAt) || value.savedAt > now || now - value.savedAt > ROOM_DRAFT_TTL_MS) return null;
    if (value.url) roomJoinPreview(value.url);
    return value.url;
  } catch { return null; }
}

export function clearRoomJoinDraft(storage?: Pick<Storage, 'removeItem'>): void {
  try { (storage ?? localStorage).removeItem(ROOM_DRAFT_KEY); } catch { /* Joining remains available without storage. */ }
}


/** A bot-side cache cannot grant the signed-in user a player seat. Never accept
 * an already-created game again when their account API did not confirm it. */
export function requireUnjoinedRoom(room: SenseRoom, cached: CachedGameState | null, username: string): void {
  if (!cached || cached.gameId !== room.challengeId) return;
  const status = cached.state?.status;
  if (!status) return;
  if (!['created', 'started'].includes(status)) {
    throw new Error(`Room ${room.challengeId} has already finished. Create a new invitation on SenseRobot.`);
  }
  throw new Error(`The coach bot has already joined room ${room.challengeId}, but Lichess did not confirm its player seat for ${username}. Sign in with the same player account shown on SenseRobot, then reopen this link. Do not accept the invitation again.`);
}
