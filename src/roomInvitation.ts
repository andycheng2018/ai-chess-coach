import { roomJoinPreview } from './roomJoin';

/** Keep only the public invitation ID and explicit color; never open a scanned URL. */
export function normalizeRoomInvitation(raw: string): string {
  const room = roomJoinPreview(raw);
  const url = new URL(raw.trim());
  if (url.username || url.password || url.port || url.hash || url.searchParams.getAll('color').length !== 1) {
    throw new Error('Use the original Lichess room invitation with one explicit bot color.');
  }
  return `https://lichess.org/game/${room.challengeId}?color=${room.color}`;
}
