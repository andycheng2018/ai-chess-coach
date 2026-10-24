export type PendingMoveAttempt = {
  uci: string;
  basePly: number;
  /** The authoritative move list immediately before this move was submitted. */
  movesBefore: readonly string[];
};

export type PendingMoveReconciliation =
  | { outcome: 'waiting' }
  | { outcome: 'confirmed'; observedUci: string }
  | { outcome: 'rollback'; reason: 'rewind' | 'divergence' | 'invalid-base-ply' };

const DEFINITIVE_MOVE_FAILURE_STATUSES = new Set([400, 401, 403, 404, 409, 410, 422, 429]);

/** Resolve a failed move request without letting an old request affect a newer move. */
export function resolveMoveFailure(
  pending: PendingMoveAttempt | null,
  attempt: PendingMoveAttempt,
  status?: number,
): 'ignore' | 'rollback' | 'wait' {
  if (pending !== attempt) return 'ignore';
  return status != null && DEFINITIVE_MOVE_FAILURE_STATUSES.has(status)
    ? 'rollback'
    : 'wait';
}

/**
 * Compare a pending move with a newly received authoritative move list.
 * An unchanged prefix means the server has not confirmed or rejected the
 * request yet, so callers should keep the board locked and wait for another
 * snapshot.
 */
export function reconcilePendingMove(
  pending: PendingMoveAttempt,
  authoritativeMoves: readonly string[],
): PendingMoveReconciliation {
  if (
    !Number.isInteger(pending.basePly) ||
    pending.basePly < 0 ||
    pending.movesBefore.length !== pending.basePly
  ) {
    return { outcome: 'rollback', reason: 'invalid-base-ply' };
  }

  const normalize = (move: string) => move.trim().toLowerCase();
  const before = pending.movesBefore.map(normalize);
  const current = authoritativeMoves.map(normalize);
  const sharedLength = Math.min(before.length, current.length);

  for (let index = 0; index < sharedLength; index += 1) {
    if (before[index] !== current[index]) {
      return { outcome: 'rollback', reason: 'divergence' };
    }
  }

  if (current.length < before.length) {
    return { outcome: 'rollback', reason: 'rewind' };
  }

  // The pre-submit position is still current. The request may be in flight,
  // or its accepted move may not have reached this stream snapshot yet.
  if (current.length === pending.basePly) {
    return { outcome: 'waiting' };
  }

  const observedUci = current[pending.basePly];
  if (observedUci === normalize(pending.uci)) {
    return { outcome: 'confirmed', observedUci };
  }

  return { outcome: 'rollback', reason: 'divergence' };
}
