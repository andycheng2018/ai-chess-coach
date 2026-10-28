export type BackupSnapshotInput = {
  primaryConnected: boolean;
  branchChanged?: boolean;
  gameId: string;
  cachedGameId: string;
  updatedAt: number;
  now: number;
  currentMoves: readonly string[];
  cachedMoves: readonly string[];
};

/** Detects a rewind or a move-line divergence; equal lines and extensions are stable. */
export function moveLineChanged(previous: readonly string[], next: readonly string[]): boolean {
  if (next.length < previous.length) return true;
  return previous.some((move, index) => next[index] !== move);
}

/** Decide whether a secondary cached snapshot may advance the local board. */
export function shouldApplyBackupSnapshot(input: BackupSnapshotInput): boolean {
  if (input.primaryConnected) return false;
  if (input.branchChanged) return false;
  if (!input.gameId || !input.cachedGameId || input.cachedGameId !== input.gameId) return false;

  const age = input.now - input.updatedAt;
  if (!Number.isFinite(age) || age < 0 || age > 30_000) return false;
  if (input.cachedMoves.length <= input.currentMoves.length) return false;

  return input.currentMoves.every(
    (move, index) => input.cachedMoves[index] === move,
  );
}
