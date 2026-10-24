import { useCallback, useEffect, useRef, useState } from 'react';
import { vbotNeedsDetach, vbotManagedSession, vbotRequest, type VbotStatus } from './vbotDemo';

export type CompanionContext = {
  gameId: string | null; playerColor: 'white' | 'black';
  resolved: boolean; ended: boolean; canArm: boolean;
};

export function useVbotCompanion(context: CompanionContext) {
  const [status, setStatus] = useState<VbotStatus | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const [actionError, setActionError] = useState('');
  const [pending, setPending] = useState(false);
  const current = useRef(context);
  current.current = context;
  const mounted = useRef(false);
  const revision = useRef(0);
  const inFlight = useRef(false);
  const detaching = useRef(false);
  const managed = useRef<{ gameId: string; generation: number } | null>(null);

  const refresh = useCallback(async () => {
    const request = ++revision.current;
    try {
      const next = await vbotRequest('status');
      if (!mounted.current || revision.current !== request) return;
      setStatus(next); setConnectionError('');
    } catch {
      if (mounted.current && revision.current === request) setConnectionError('VBOT controller is unavailable. Chess can continue; check the local coach server.');
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => { if (!inFlight.current) void refresh(); }, 2000);
    return () => { mounted.current = false; revision.current++; window.clearInterval(timer); };
  }, [refresh]);

  const perform = useCallback(async (path: 'check' | 'connect' | 'disarm', payload: object) => {
    if (inFlight.current) return;
    inFlight.current = true; revision.current++;
    setPending(true); setActionError('');
    const originGame = current.current.gameId;
    try {
      let next = await vbotRequest(path, payload);
      // A game can finish/change during a slow connection request. Disarm only
      // that exact session, never a newer session armed from another tab.
      if (path === 'connect' && (current.current.gameId !== originGame || !current.current.canArm)) {
        next = await vbotRequest('disarm', { gameId: next.gameId, generation: next.generation });
      }
      if (mounted.current) { setStatus(next); setConnectionError(''); }
    } catch (error) {
      if (mounted.current) setActionError(error instanceof Error ? error.message : 'VBOT request failed.');
    } finally {
      inFlight.current = false;
      if (mounted.current) { setPending(false); void refresh(); }
    }
  }, [refresh]);

  useEffect(() => {
    if (!status) return;
    const session = vbotManagedSession(status, managed.current, context.gameId);
    managed.current = session;
    if (!session || !vbotNeedsDetach(status, context) || inFlight.current || detaching.current) return;
    detaching.current = true;
    void perform('disarm', session)
      .finally(() => { detaching.current = false; });
  }, [status, context.gameId, context.resolved, context.ended, perform]);

  return {
    status, pending, offline: Boolean(connectionError), error: actionError || connectionError,
    check: (target: string) => perform('check', { target }),
    connect: (mode: 'live' | 'rehearsal', target: string, confirmed: boolean) => {
      const c = current.current;
      if (!c.canArm || !c.gameId) return Promise.resolve();
      return perform('connect', { gameId: c.gameId, playerColor: c.playerColor, mode, target,
        preset: 'actions/ROCKYOU.json', applicationVersion: status?.verification?.applicationVersion || 'unknown',
        confirmSafeWorkspace: confirmed, confirmHandsetStop: confirmed });
    },
    off: () => status ? perform('disarm', { gameId: status.gameId, generation: status.generation }) : Promise.resolve(),
  };
}

export type VbotCompanionControl = ReturnType<typeof useVbotCompanion>;
