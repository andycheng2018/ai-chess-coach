import { registerPlugin } from '@capacitor/core';

export type LocalSettings = {
  model?: string; botUsername?: string; robotTarget?: string; robotFingerprint?: string;
  openaiKeyConfigured?: boolean; botTokenConfigured?: boolean; robotProfileConfigured?: boolean;
  elevenLabsKeyConfigured?: boolean; voiceIdConfigured?: boolean;
};
export type LocalRuntime = { url: string; token: string; standalone: boolean; settings: LocalSettings };
export const standalone = registerPlugin<{
  boot(): Promise<LocalRuntime>;
  configure(values: Record<string, string>): Promise<LocalSettings>;
  publicKey(): Promise<{ publicKey: string }>;
  installRobotKey(options: { password: string; confirmed: boolean }): Promise<{ ok: boolean }>;
}>('StandaloneBackend');
