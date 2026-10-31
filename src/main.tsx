import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { installTabletTransport } from './nativeBackend';
import { TabletConnection } from './components/TabletConnection';
import './styles.css';

installTabletTransport();
const App = lazy(() => import('./App'));

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <TabletConnection><Suspense fallback={<p>Opening Chess Buddy…</p>}><App /></Suspense></TabletConnection>
  </React.StrictMode>,
);
