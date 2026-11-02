import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: dirname(fileURLToPath(import.meta.url)),
  // Relative asset paths so the same build works in a browser and a Capacitor WebView.
  base: './',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5180,
    strictPort: true,
    proxy: { '/api/app': { target: 'http://127.0.0.1:8791', changeOrigin: true } },
  },
});
