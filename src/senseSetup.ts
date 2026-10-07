export const SENSE_SETUP_KEY = 'ai-chess-coach.senserobot-setup.v1';

export type SenseSetupDraft = {
  open: boolean;
  networkReady: boolean;
  linkedUsername: string;
  joinedUsername: string;
  joinedGameId: string;
  level: string;
};

const emptyDraft: SenseSetupDraft = {
  open: false, networkReady: false, linkedUsername: '',
  joinedUsername: '', joinedGameId: '', level: 'developing',
};

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
