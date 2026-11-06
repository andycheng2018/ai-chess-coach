import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CATALOG, mergeDeviceFaces, type CatalogEntry } from './domain/catalog';
import { isTerminal, makeEnvelope, type CommandReceipt, type DeviceSnapshot } from './domain/commands';
import { copyShow, findShow, importShow, loadLibrary, reviseShow, saveLibrary, upsertShow, type KeyValueStore, type LibraryState } from './domain/library';
import { admitScore, cueFromEntry, makeScore, parseScore, type Score } from './domain/score';
import { CloudTransport } from './transport/cloud';
import { FakeTransport, type FakeFault } from './transport/fake';
import { LocalFaceTransport } from './transport/localFace';
import { isNativeApp, studioBackend } from './transport/native';
import { NATIVE_CONTROLLER_DOWN, nativeFetcher } from './transport/nativeFetch';
import { emptySnapshot, type DeviceTransport, type MotionConfirmation, type TransportKind } from './transport/types';

const NO_CONFIRMATION: MotionConfirmation = { onsite: false, standing: false, clear: false };

const SETTINGS_KEY = 'vbot-studio.settings.v1';

/** Storage can throw in private windows, so the app still runs without it. */
function browserStore(): KeyValueStore {
  const memory = new Map<string, string>();
  return {
    getItem(key) { try { return window.localStorage.getItem(key); } catch { return memory.get(key) ?? null; } },
    setItem(key, value) { try { window.localStorage.setItem(key, value); } catch { memory.set(key, value); } },
  };
}

function readSettings(store: KeyValueStore): { kind: TransportKind; target: string } {
  try {
    const data = JSON.parse(store.getItem(SETTINGS_KEY) ?? '{}');
    const kind: TransportKind = data.kind === 'local-face' || data.kind === 'cloud' ? data.kind : 'fake';
    return { kind, target: typeof data.target === 'string' ? data.target : '' };
  } catch { return { kind: 'fake', target: '' }; }
}

function createTransport(kind: TransportKind, store: KeyValueStore): DeviceTransport {
  if (kind === 'local-face') {
    return isNativeApp
      ? new LocalFaceTransport({ fetcher: nativeFetcher(request => studioBackend.call(request)), downMessage: NATIVE_CONTROLLER_DOWN })
      : new LocalFaceTransport();
  }
  if (kind === 'cloud') return new CloudTransport();
  return new FakeTransport({ store });
}

export function useStudio() {
  const store = useMemo(browserStore, []);
  const [library, setLibrary] = useState<LibraryState>(() => loadLibrary(store));
  const [settings, setSettings] = useState(() => readSettings(store));
  const [snapshot, setSnapshot] = useState<DeviceSnapshot>(() => emptySnapshot());
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null);
  const [connecting, setConnecting] = useState(false);
  // Held in memory only: a stored confirmation could outlive the onsite checks it stands for.
  const [motionConfirm, setMotionConfirm] = useState<MotionConfirmation>(NO_CONFIRMATION);
  const [sending, setSending] = useState(false);
  const [fault, setFaultState] = useState<FakeFault>('none');
  const [storageOk, setStorageOk] = useState(true);
  const transport = useRef<DeviceTransport | null>(null);
  const sendLock = useRef(false);

  useEffect(() => { setStorageOk(saveLibrary(store, library)); }, [library, store]);
  useEffect(() => { store.setItem(SETTINGS_KEY, JSON.stringify(settings)); }, [settings, store]);

  // Switching adapters only reads status. Nothing connects or runs by itself.
  useEffect(() => {
    const next = createTransport(settings.kind, store);
    transport.current = next;
    setFaultState('none');
    setReceipt(null);
    setSnapshot(emptySnapshot());
    const unsubscribe = next.subscribe(setSnapshot);
    void next.status().then(current => { if (transport.current === next) setSnapshot(current); });
    return () => { unsubscribe(); next.dispose(); transport.current = null; };
  }, [settings.kind, store]);

  const catalog: CatalogEntry[] = useMemo(() => mergeDeviceFaces(CATALOG, snapshot.supportedFaces), [snapshot.supportedFaces]);
  const running = snapshot.run !== null && !isTerminal(snapshot.run.state);

  const connect = useCallback(async () => {
    if (!transport.current) return;
    setConnecting(true);
    const motion = motionConfirm.onsite && motionConfirm.standing && motionConfirm.clear ? motionConfirm : undefined;
    try { setSnapshot(await transport.current.connect({ target: settings.target, ...(motion ? { motion } : {}) })); }
    finally { setConnecting(false); setMotionConfirm(NO_CONFIRMATION); }
  }, [settings.target, motionConfirm]);

  const disconnect = useCallback(async () => {
    setMotionConfirm(NO_CONFIRMATION);
    if (transport.current) setSnapshot(await transport.current.disconnect());
  }, []);

  /** One deliberate press sends one single-use command. It is never retried. */
  const startShow = useCallback(async (score: Score) => {
    const active = transport.current;
    if (!active || sendLock.current) return null;
    sendLock.current = true;
    setSending(true);
    try {
      const current = await active.status();
      const envelope = makeEnvelope(score, current, Date.now());
      const result = await active.submit(envelope);
      setReceipt(result);
      setSnapshot(await active.status());
      return result;
    } catch (error) {
      setReceipt({ commandId: '', state: 'rejected', duplicate: false, reason: error instanceof Error ? error.message : 'The show could not be sent.' });
      return null;
    } finally {
      sendLock.current = false;
      setSending(false);
    }
  }, []);

  const tryEntry = useCallback((entry: CatalogEntry) => {
    const cue = cueFromEntry(entry);
    if (!cue) return Promise.resolve(null);
    return startShow(makeScore(`Try: ${entry.label}`, Date.now(), [cue]));
  }, [startShow]);

  const stopFuture = useCallback(async () => {
    if (transport.current && snapshot.run) setSnapshot(await transport.current.cancelFutureCues(snapshot.run.commandId));
  }, [snapshot.run]);

  const setFault = useCallback((value: FakeFault) => {
    setFaultState(value);
    if (transport.current instanceof FakeTransport) transport.current.setFault(value);
  }, []);

  // --- library -------------------------------------------------------------
  const select = useCallback((id: string | null) => setLibrary(state => ({ ...state, selectedId: id })), []);

  const createShow = useCallback(() => {
    const show = makeScore('Untitled show', Date.now());
    setLibrary(state => ({ ...upsertShow(state, show), selectedId: show.id }));
    return show;
  }, []);

  const addShow = useCallback((show: Score) => {
    setLibrary(state => ({ ...upsertShow(state, show), selectedId: show.id }));
  }, []);

  /** Every edit must pass validation. Canned shows can't change. */
  const editShow = useCallback((show: Score, change: Parameters<typeof reviseShow>[1]): string | null => {
    if (show.origin !== 'custom') return 'Built-in shows are read-only. Make a copy to change one.';
    const next = reviseShow(show, change, Date.now());
    const parsed = parseScore(next);
    if (!parsed.ok) return parsed.errors[0] ?? 'That change is not valid.';
    setLibrary(state => upsertShow(state, parsed.score));
    return null;
  }, []);

  const saveAs = useCallback((show: Score, title: string) => {
    const copy = copyShow(show, title, Date.now());
    setLibrary(state => ({ ...upsertShow(state, copy), selectedId: copy.id }));
  }, []);

  const removeShow = useCallback((show: Score) => {
    setLibrary(state => ({
      ...state, shows: state.shows.filter(item => item.id !== show.id),
      selectedId: state.selectedId === show.id ? null : state.selectedId,
    }));
  }, []);

  const importText = useCallback((text: string) => {
    const result = importShow(text, Date.now());
    if (result.ok) addShow(result.show);
    return result;
  }, [addShow]);

  const toggleFavorite = useCallback((id: string) => {
    setLibrary(state => {
      const favorites = new Set(state.favorites);
      if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
      return { ...state, favorites };
    });
  }, []);

  const selected = findShow(library, library.selectedId);
  const setKind = useCallback((kind: TransportKind) => setSettings(state => ({ ...state, kind })), []);
  const setTarget = useCallback((target: string) => setSettings(state => ({ ...state, target })), []);

  return {
    library, selected, settings, snapshot, receipt, catalog, connecting, sending, running, fault, storageOk, motionConfirm, setMotionConfirm,
    simulated: settings.kind === 'fake',
    connect, disconnect, startShow, tryEntry, stopFuture, setFault, setKind, setTarget,
    select, createShow, editShow, saveAs, removeShow, importText, toggleFavorite,
    admission: (score: Pick<Score, 'cues'>) => admitScore(score, snapshot.capabilities),
  };
}

export type Studio = ReturnType<typeof useStudio>;
