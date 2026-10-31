import { registerPlugin } from '@capacitor/core';

export type LocalSettings = {
  model?: string; botUsername?: string; robotTarget?: string; robotFingerprint?: string;
  openaiKeyConfigured?: boolean; botTokenConfigured?: boolean; robotProfileConfigured?: boolean;
  elevenLabsKeyConfigured?: boolean; voiceIdConfigured?: boolean;
};
export type LocalRuntime = { url: string; token: string; standalone: boolean; settings: LocalSettings };
export type AndroidUpdate = {
  available: boolean; currentCode: number; currentVersion: string;
  versionCode?: number; versionName?: string; downloadUrl?: string; releaseUrl?: string;
};
export const standalone = registerPlugin<{
  checkForUpdate(): Promise<AndroidUpdate>;
  prepareUpdate(): Promise<void>;
  boot(): Promise<LocalRuntime>;
  configure(values: Record<string, string>): Promise<LocalSettings>;
  publicKey(): Promise<{ publicKey: string }>;
  installRobotKey(options: { password: string; confirmed: boolean }): Promise<{ ok: boolean }>;
}>('StandaloneBackend');
