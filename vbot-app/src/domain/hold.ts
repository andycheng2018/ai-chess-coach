/**
 * Press-and-hold as a chain of short, separate commands. The dog's own safety model has no hold-to-move
 * or dead-man stop (the vendor docs say none is configured), so nothing here streams a velocity. Each link is
 * one finite, already-bounded move; the next link is sent only if the button is STILL held when the previous
 * one has finished cleanly. Releasing stops the chain, so the most a release can overshoot is the one move
 * already in flight. Nothing here contacts a robot.
 */
export const HOLD_MAX_CHUNKS = 12;

export type HoldSent = { commandId: string } | null;
export type HoldEnd = 'released' | 'cap' | 'refused' | 'not-clean';
export type HoldOutcome = { chunks: number; end: HoldEnd; state?: string };

export type HoldDeps = {
  /** Sends exactly one bounded move. Null means it was not accepted. Never retried here. */
  send: () => Promise<HoldSent>;
  /** Resolves with the final state of that one command. */
  settled: (commandId: string) => Promise<string>;
  /** True only while the button is still held AND the page is visible. Checked before every send. */
  holding: () => boolean;
  maxChunks?: number;
};

export async function runHold({ send, settled, holding, maxChunks = HOLD_MAX_CHUNKS }: HoldDeps): Promise<HoldOutcome> {
  let chunks = 0;
  while (chunks < maxChunks && holding()) {
    const sent = await send();
    if (!sent) return { chunks, end: 'refused' };
    chunks += 1;
    const state = await settled(sent.commandId);
    // Anything but a clean completion ends the hold: a refusal, a stop or an unknown outcome is never repeated.
    if (state !== 'completed') return { chunks, end: 'not-clean', state };
  }
  return { chunks, end: holding() ? 'cap' : 'released' };
}
