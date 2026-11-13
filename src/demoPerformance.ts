import { vbotRequest } from './vbotDemo';
import type { VbotCompanionControl } from './useVbotCompanion';

export type DemoHostCheck = { target: string; space: boolean; stop: boolean; checkedAt: number };
export const HOST_CHECK_MS = 15 * 60 * 1000;
export function hostCheckValid(check: DemoHostCheck, target: string, now = Date.now()) {
  return Boolean(target && check.target === target && check.space && check.stop
    && now >= check.checkedAt && now - check.checkedAt < HOST_CHECK_MS);
}

/** A visitor click, independent of account/game state. Never automatically retries. */
export function createDemoStarter() {
  let inFlight = false;
  return async (check: DemoHostCheck, getControl: () => VbotCompanionControl) => {
    if (inFlight) throw new Error('The demo is already starting.');
    const assertPrepared = () => {
      const c = getControl();
      if (!hostCheckValid(check, c.status?.target || '')) throw new Error('Ask the demo host to confirm clear space and the handset Stop below.');
      if (c.pending || c.offline || c.status?.armed || c.status?.busy) throw new Error('Wait for the current robot session to finish or turn reactions off first.');
      return c;
    };
    assertPrepared();
    inFlight = true;
    try {
      const preview = await vbotRequest('performance/preview', { target: check.target, dances: 2, pace: 'flow' });
      if (!preview.performancePreview?.allRehearsed || preview.performancePreview.target !== check.target) {
        throw new Error('The dog needs its verified rehearsal profile before this show can start.');
      }
      const control = assertPrepared();
      const result = await control.startPerformance({ target: check.target, dances: 2, pace: 'flow',
        requestId: crypto.randomUUID().replaceAll('-', ''), confirmSafeWorkspace: check.space, confirmHandsetStop: check.stop });
      if (!result?.armed || result.sessionKind !== 'performance') {
        throw new Error('The performance did not confirm a start. Inspect Dog stage before trying again.');
      }
      return result;
    } finally { inFlight = false; }
  };
}

export type DemoWelcomeState =
  | { kind: 'ready' | 'needs-host' }
  | { kind: 'no-dog' | 'offline' | 'robot-busy'; message: string };

/** What the visitor welcome can offer right now. Without a reachable dog the
 * Start button is replaced, so visitors never face a big button that cannot work. */
export function demoWelcomeState(input: { target: string; offline: boolean; armed: boolean; busy: boolean; prepared: boolean }): DemoWelcomeState {
  if (input.offline) return { kind: 'offline', message: 'The robot dog controller isn’t reachable right now, so the dog show is off. Chess still works.' };
  if (!input.target) return { kind: 'no-dog', message: 'No robot dog is connected to this device, so the dog show is off. Chess still works.' };
  if (input.armed || input.busy) return { kind: 'robot-busy', message: 'The dog is busy with another session. Turn its reactions off before starting the show.' };
  return { kind: input.prepared ? 'ready' : 'needs-host' };
}
