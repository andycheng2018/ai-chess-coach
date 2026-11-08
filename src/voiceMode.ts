export type VoiceState = 'off' | 'connecting' | 'listening' | 'thinking' | 'error';
export type VoiceTurn = { id: string; at: number; heard: string; rejected: boolean; understood: string; clarifying: boolean; reply: string; spoken: boolean | null; error?: string };
export type VoiceStatus = { available: boolean; reason?: string; enabled: boolean; state: VoiceState; message?: string; chatRestored?: boolean | null; turns: VoiceTurn[] };

export const VOICE_STATE_TEXT: Record<VoiceState, string> = {
  off: 'Off. The dog’s built-in assistant is answering.', connecting: 'Connecting to the dog…',
  listening: 'Say the wake word, then talk.', thinking: 'Qwen is thinking…', error: 'Something went wrong.',
};
