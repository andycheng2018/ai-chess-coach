import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.andy.chessbuddy',
  appName: 'Chess Buddy',
  webDir: 'dist',
  android: { adjustMarginsForEdgeToEdge: 'auto', allowMixedContent: true },
};

export default config;
