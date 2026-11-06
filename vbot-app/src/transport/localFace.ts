/**
 * Live, face-only adapter for the local controller (server/vbot_app_server.py).
 * Polling only reads status. A lost submit is reported as unknown and is never
 * resent: the controller and the dog keep their own deduplication records.
 */
import type { CommandEnvelope, CommandReceipt, DeviceSnapshot } from '../domain/commands';
import { emptySnapshot, noCapabilities, type ConnectOptions, type DeviceTransport } from './types';

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

const CONTROLLER_DOWN = 'The local controller isn’t running. Start it with `npm run vbot:controller`, then connect again.';
const CONTROL_TIMEOUT_MS = 30000;
const STATUS_TIMEOUT_MS = 4000;
const POLL_MS = 1200;

export class LocalFaceTransport implements DeviceTransport {
  readonly kind = 'local-face' as const;
  readonly simulated = false;
  private readonly listeners = new Set<(snapshot: DeviceSnapshot) => void>();
  private readonly fetcher: FetchLike;
  private readonly base: string;
  private readonly downMessage: string;
  private timer: ReturnType<typeof setInterval> | null = null;
  private last: DeviceSnapshot = emptySnapshot();

  constructor(options: { fetcher?: FetchLike; base?: string; downMessage?: string } = {}) {
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
    this.base = options.base ?? '/api/app';
    this.downMessage = options.downMessage ?? CONTROLLER_DOWN;
  }

  private async post(path: string, body: object): Promise<Response> {
    return this.fetcher(`${this.base}/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(CONTROL_TIMEOUT_MS),
    });
  }

  private accept(snapshot: DeviceSnapshot): DeviceSnapshot {
    this.last = snapshot;
    for (const listener of this.listeners) listener(snapshot);
    return snapshot;
  }

  private unreachable(): DeviceSnapshot {
    const detail = this.downMessage;
    return this.accept({ ...this.last, connection: 'unavailable', detail, capabilities: noCapabilities(detail) });
  }

  async status(): Promise<DeviceSnapshot> {
    try {
      const response = await this.fetcher(`${this.base}/status`, { signal: AbortSignal.timeout(STATUS_TIMEOUT_MS) });
      if (!response.ok) return this.unreachable();
      return this.accept(await response.json());
    } catch { return this.unreachable(); }
  }

  async connect(options: ConnectOptions): Promise<DeviceSnapshot> {
    try {
      const response = await this.post('connect', { target: options.target ?? '' });
      if (!response.ok) return this.unreachable();
      return this.accept(await response.json());
    } catch { return this.unreachable(); }
  }

  async disconnect(): Promise<DeviceSnapshot> {
    try {
      const response = await this.post('disconnect', {});
      if (!response.ok) return this.unreachable();
      return this.accept(await response.json());
    } catch { return this.unreachable(); }
  }

  /** Exactly one POST. Without a readable reply the outcome is unknown, not failed. */
  async submit(envelope: CommandEnvelope): Promise<CommandReceipt> {
    const unknown = (): CommandReceipt => ({
      commandId: envelope.commandId, state: 'unknown', duplicate: false,
      reason: 'The controller’s answer never arrived, so this show may or may not have started. It won’t be resent. Check Stage for the current status.',
    });
    let response: Response;
    try { response = await this.post('submit', envelope); } catch { return unknown(); }
    try {
      const receipt = await response.json() as CommandReceipt;
      return receipt?.commandId === envelope.commandId ? receipt : unknown();
    } catch { return unknown(); }
  }

  async cancelFutureCues(commandId: string): Promise<DeviceSnapshot> {
    try {
      const response = await this.post('cancel', { commandId });
      if (!response.ok) throw new Error('refused');
      return this.accept(await response.json());
    } catch {
      const detail = 'The stop request didn’t reach the controller, so future cues may still run. Use the onsite handset Stop if the dog is moving, and check the controller.';
      return this.accept({ ...this.last, connection: 'unavailable', detail, capabilities: noCapabilities(detail) });
    }
  }

  subscribe(listener: (snapshot: DeviceSnapshot) => void) {
    this.listeners.add(listener);
    if (!this.timer) this.timer = setInterval(() => { void this.status(); }, POLL_MS);
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size && this.timer) { clearInterval(this.timer); this.timer = null; }
    };
  }

  dispose() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.listeners.clear();
  }
}
