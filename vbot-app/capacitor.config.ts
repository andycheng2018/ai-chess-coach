import type { CapacitorConfig } from '@capacitor/cli';

/**
 * A separate app identity and launcher entry, so installing it can't replace
 * Chess Buddy (com.andy.chessbuddy) or touch its data. "VBOT Studio" is a working
 * name.
 */
const config: CapacitorConfig = {
  appId: 'com.andy.vbotstudio',
  appName: 'VBOT Studio',
  webDir: 'dist',
};

export default config;
