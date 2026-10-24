/** Public game link only: never encode a token or a private player URL. */
export function gameQrLink(gameId: string, color: 'white' | 'black'): string {
  if (gameId.length !== 8 || !/^[A-Za-z0-9]{8}$/.test(gameId) || !['white', 'black'].includes(color)) {
    throw new Error('A current game and an explicit player color are required.');
  }
  // Documented public watcher route; orientation is distinct from claiming a seat.
  return `https://lichess.org/${gameId}/${color}`;
}
