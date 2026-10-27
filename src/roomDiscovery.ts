import type { RoomChallenge, PlayingGame } from './lichess';
export type DiscoveredRoom = { id: string; url: string | null; playerColor?: 'white' | 'black'; botColor?: 'white' | 'black'; timeControl: string; blockedReason?: string };
const identity = (user: { id?: string; name?: string } | null | undefined) => (user?.id || user?.name || '').trim().toLowerCase();

/** Never infer a seat from array order or random/finalColor. Fixed color is the challenger's seat. */
export function discoverRooms(challenges: readonly RoomChallenge[], username: string, botUsername: string): DiscoveredRoom[] {
  const seen = new Set<string>();
  return challenges.filter(c => typeof c?.id === 'string' && /^[A-Za-z0-9]{8}$/.test(c.id) && !seen.has(c.id) && Boolean(seen.add(c.id))).map(c => {
    let blockedReason: string | undefined;
    if (c.status !== 'created') blockedReason = 'Invitation is no longer open.';
    else if (!username || identity(c.challenger) !== username.trim().toLowerCase()) blockedReason = 'Creator account could not be verified.';
    else if (c.rated !== false) blockedReason = 'Only explicitly unrated rooms can be joined here.';
    else if (c.variant?.key !== 'standard') blockedReason = 'Only standard chess rooms are supported.';
    else if (c.destUser && identity(c.destUser) !== botUsername.trim().toLowerCase()) blockedReason = 'This invitation is addressed to another player.';
    else if (c.open?.userIds && (c.open.userIds.length !== 2 || !c.open.userIds.map(id => id.toLowerCase()).includes(botUsername.trim().toLowerCase()) || !c.open.userIds.map(id => id.toLowerCase()).includes(username.trim().toLowerCase()))) blockedReason = 'This room is restricted to different players.';
    else if (c.color !== 'white' && c.color !== 'black') blockedReason = 'Player color is not fixed. Use the original invitation instead.';
    const playerColor = c.color === 'white' || c.color === 'black' ? c.color : undefined;
    const botColor = playerColor === 'white' ? 'black' : playerColor === 'black' ? 'white' : undefined;
    const timeControl = c.timeControl?.type === 'unlimited' ? 'Unlimited' : c.timeControl?.show || c.timeControl?.type || 'Unknown time control';
    return { id: c.id, playerColor, botColor, timeControl, blockedReason,
      url: !blockedReason && botColor ? `https://lichess.org/game/${c.id}?color=${botColor}` : null };
  });
}

/** Auto mode is one-shot and must ignore rooms that existed when it was enabled. */
export function nextAutomaticRoom(rooms: readonly DiscoveredRoom[], baseline: ReadonlySet<string>, attempted: ReadonlySet<string>): DiscoveredRoom | null {
  const eligible = rooms.filter(r => r.url && !baseline.has(r.id) && !attempted.has(r.id));
  return eligible.length === 1 ? eligible[0] : null;
}

/** Already joined account games are a separate list, never automatic join candidates. */
export function discoverJoinedRooms(games: readonly PlayingGame[], botUsername: string): DiscoveredRoom[] {
  const seen = new Set<string>();
  return games.filter(game => /^[A-Za-z0-9]{8}$/.test(game.gameId) && !seen.has(game.gameId)
    && (game.color === 'white' || game.color === 'black')
    && (game.opponent?.id || game.opponent?.username || '').trim().toLowerCase() === botUsername.trim().toLowerCase()
    && Boolean(seen.add(game.gameId))).map(game => {
      const botColor = game.color === 'white' ? 'black' : 'white';
      return { id: game.gameId, playerColor: game.color, botColor,
        timeControl: game.speed || 'Active game', url: `https://lichess.org/game/${game.gameId}?color=${botColor}` };
    });
}
