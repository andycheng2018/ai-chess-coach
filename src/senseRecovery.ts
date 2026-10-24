import type { PlayingGame } from './lichess';

/** The account API, not a supplied LAN address, verifies a recoverable game. */
export function requireSenseTrainingGame(
  gameId: string,
  botUsername: string,
  games: readonly PlayingGame[],
): PlayingGame {
  if (!/^[A-Za-z0-9]{8}$/.test(gameId) || !botUsername.trim()) {
    throw new Error('Choose a verified training game before switching input.');
  }
  const game = games.find(item => item?.gameId === gameId &&
    typeof item.opponent?.username === 'string' &&
    item.opponent.username.toLowerCase() === botUsername.trim().toLowerCase());
  if (!game) {
    throw new Error('Lichess did not confirm this active game against your training bot. Reconnect the game before trying again.');
  }
  return game;
}
