/**
 * Placeholder for the cloud adapter. No hosting, API or auth contract has been
 * supplied, so this explains what's missing instead of pretending to work.
 * Never add device or cloud administrator secrets to frontend code or the APK.
 */
import type { CommandEnvelope, CommandReceipt, DeviceSnapshot } from '../domain/commands';
import { emptySnapshot, noCapabilities, type DeviceTransport } from './types';

export const CLOUD_MISSING = 'Cloud control isn’t built yet. It needs the backend API, authentication model and device-pairing contract.';

export class CloudTransport implements DeviceTransport {
  readonly kind = 'cloud' as const;
  readonly simulated = false;
  private readonly snapshot: DeviceSnapshot = {
    ...emptySnapshot(CLOUD_MISSING), connection: 'unavailable', capabilities: noCapabilities(CLOUD_MISSING),
  };
  async connect() { return this.snapshot; }
  async disconnect() { return this.snapshot; }
  async status() { return this.snapshot; }
  async submit(envelope: CommandEnvelope): Promise<CommandReceipt> {
    return { commandId: envelope.commandId, state: 'rejected', duplicate: false, code: 'backend_unavailable', reason: CLOUD_MISSING };
  }
  async cancelFutureCues() { return this.snapshot; }
  subscribe() { return () => {}; }
  dispose() {}
}
