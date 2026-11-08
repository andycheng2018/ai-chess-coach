import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { Capacitor } from '@capacitor/core';
import { StandaloneRuntime } from './components/StandaloneRuntime';
import { installTabletTransport } from './nativeBackend';
import './styles.css';

// On a computer, a saved Chess Buddy server (paired at #pair-server) is used for every
// backend call. Android decides this in StandaloneRuntime. Must run before App loads.
if (Capacitor.getPlatform() !== 'android') installTabletTransport();

const App = lazy(() => import('./App'));

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <StandaloneRuntime><Suspense fallback={<p>Opening Chess Buddy…</p>}><App /></Suspense></StandaloneRuntime>
  </React.StrictMode>,
);
