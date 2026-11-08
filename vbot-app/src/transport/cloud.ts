/**
 * Controls the dog through the hosted server. It speaks the same protocol as the
 * local controller, so a lost submit is still "unknown" and is never resent.
 * Hold-to-drive is deliberately absent: a tunnel's delay is wrong for it.
 */
import type { CommandEnvelope, CommandReceipt, DeviceSnapshot } from '../domain/commands';
import { cloudFetcher, type CloudPairing } from './cloudPairing';
import { LocalFaceTransport } from './localFace';
import { emptySnapshot, noCapabilities, type ConnectOptions, type DeviceTransport } from './types';

export const CLOUD_NOT_PAIRED = 'Pair Studio with the cloud server first.';
const CLOUD_DOWN = 'Couldn’t reach the cloud server, or it refused this key. Check the Internet connection and the pairing key.';

export class CloudTransport implements DeviceTransport {
  readonly kind = 'cloud' as const;
  readonly simulated = false;
  private readonly inner: LocalFaceTransport | null;
  private readonly unpaired: DeviceSnapshot = { ...emptySnapshot(CLOUD_NOT_PAIRED), connection: 'unavailable', capabilities: noCapabilities(CLOUD_NOT_PAIRED) };

  constructor(pairing: CloudPairing | null, request?: typeof fetch) {
    this.inner = pairing ? new LocalFaceTransport({ fetcher: cloudFetcher(pairing, request), base: `${pairing.url}/api/vbot/studio`, downMessage: CLOUD_DOWN }) : null;
  }

  async connect(options: ConnectOptions) { return this.inner ? this.inner.connect(options) : this.unpaired; }
  async disconnect() { return this.inner ? this.inner.disconnect() : this.unpaired; }
  async status() { return this.inner ? this.inner.status() : this.unpaired; }
  async submit(envelope: CommandEnvelope): Promise<CommandReceipt> {
    if (this.inner) return this.inner.submit(envelope);
    return { commandId: envelope.commandId, state: 'rejected', duplicate: false, code: 'backend_unavailable', reason: CLOUD_NOT_PAIRED };
  }
  async cancelFutureCues(commandId: string) { return this.inner ? this.inner.cancelFutureCues(commandId) : this.unpaired; }
  subscribe(listener: (snapshot: DeviceSnapshot) => void) { return this.inner ? this.inner.subscribe(listener) : () => {}; }
  dispose() { this.inner?.dispose(); }
}
