export type PhysicalWitness = { gameId: string; username: string; moves: string[] };
export const senseMoveLine = (text: string): string[] => text.trim().split(/\s+/).filter(Boolean);

export function canConfirmPhysicalExchange(moves: string, playerColor: 'white' | 'black'): boolean {
  return senseMoveLine(moves).length >= (playerColor === 'white' ? 2 : 3);
}

/** A person's witness stays tied to the exact game/account/played branch. */
export function physicalWitnessMatches(witness: PhysicalWitness | null, gameId: string, username: string, moves: string): boolean {
  if (!witness || witness.gameId !== gameId || witness.username.toLowerCase() !== username.toLowerCase() || !witness.moves.length) return false;
  const current = senseMoveLine(moves);
  return current.length >= witness.moves.length && witness.moves.every((move, index) => move === current[index]);
}
