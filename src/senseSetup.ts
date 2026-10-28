export const SENSE_SETUP_KEY = 'ai-chess-coach.senserobot-setup.v1';

export type SenseSetupDraft = {
  open: boolean;
  networkReady: boolean;
  linkedUsername: string;
  joinedUsername: string;
  joinedGameId: string;
  deviceIp: string;
  deviceMac: string;
  level: string;
};

const emptyDraft: SenseSetupDraft = {
  open: false, networkReady: false, linkedUsername: '',
  joinedUsername: '', joinedGameId: '', level: 'developing',
  deviceIp: '', deviceMac: '',
};

export function isPrivateIPv4(value: string): boolean {
  const parts = value.split('.');
  if (parts.length !== 4 || parts.some(part => !/^\d{1,3}$/.test(part))) return false;
  const octets = parts.map(Number);
  if (octets.some(octet => octet < 0 || octet > 255)) return false;
  const [a, b] = octets;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

export function normalizeMacAddress(value: string): string | null {
  if (!/^(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}|[0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})$/.test(value)) return null;
  const compact = value.replace(/[:-]/g, '');
  if (!/^[0-9a-fA-F]{12}$/.test(compact)) return null;
  return compact.toUpperCase().match(/.{2}/g)!.join(':');
}

export function isNormalizedMacAddress(value: string): boolean {
  return /^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$/.test(value);
}

export function readSenseSetup(): SenseSetupDraft {
  try {
    const value = JSON.parse(localStorage.getItem(SENSE_SETUP_KEY) || '{}');
    if (!value || typeof value !== 'object') return { ...emptyDraft };
    return {
      open: value.open === true,
      networkReady: value.networkReady === true,
      linkedUsername: typeof value.linkedUsername === 'string' ? value.linkedUsername : '',
      joinedUsername: typeof value.joinedUsername === 'string' ? value.joinedUsername : '',
      joinedGameId: typeof value.joinedGameId === 'string' && /^[a-zA-Z0-9]{8}$/.test(value.joinedGameId)
        ? value.joinedGameId : '',
      deviceIp: typeof value.deviceIp === 'string' && isPrivateIPv4(value.deviceIp) ? value.deviceIp : '',
      deviceMac: typeof value.deviceMac === 'string' ? normalizeMacAddress(value.deviceMac) || '' : '',
      level: typeof value.level === 'string' ? value.level : emptyDraft.level,
    };
  } catch {
    return { ...emptyDraft };
  }
}

export function saveSenseSetup(draft: SenseSetupDraft): boolean {
  try {
    localStorage.setItem(SENSE_SETUP_KEY, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function isRememberedSenseGame(draft: SenseSetupDraft, gameId: string, username: string): boolean {
  return Boolean(gameId && username && draft.joinedGameId === gameId
    && draft.joinedUsername.toLowerCase() === username.toLowerCase());
}

export type SenseSetupStep = 'network' | 'account' | 'room' | 'connected';

export function senseSetupStep(draft: SenseSetupDraft, username: string | null, verified: boolean): SenseSetupStep {
  if (!draft.networkReady) return 'network';
  if (!username || draft.linkedUsername.toLowerCase() !== username.toLowerCase()) return 'account';
  return verified ? 'connected' : 'room';
}
