import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { StandaloneRuntime } from './components/StandaloneRuntime';
import './styles.css';

const App = lazy(() => import('./App'));

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <StandaloneRuntime><Suspense fallback={<p>Opening Chess Buddy…</p>}><App /></Suspense></StandaloneRuntime>
  </React.StrictMode>,
);
