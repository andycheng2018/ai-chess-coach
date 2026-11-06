import { Capacitor, registerPlugin } from '@capacitor/core';
import type { BackendCall } from './nativeFetch';

interface StudioBackendPlugin {
  call: BackendCall;
  pairing(): Promise<{ fingerprint: string }>;
  pair(request: { target: string; fingerprint: string; password: string; confirmed: boolean }): Promise<{ fingerprint: string }>;
}

/** True inside the Android app. In a browser the app uses the computer's local controller. */
export const isNativeApp = Capacitor.isNativePlatform();
export const studioBackend = registerPlugin<StudioBackendPlugin>('StudioBackend');
