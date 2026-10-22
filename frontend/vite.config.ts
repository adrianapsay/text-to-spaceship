/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend: FastAPI on 127.0.0.1:8765 (docs/api-contract.md). The dev server proxies /api and /ws to it.
// MOCK mode: VITE_MOCK=1 forces the in-browser mock; VITE_MOCK=0 forces the live backend; unset (dev) means
// "probe /api/health at start-up and fall back to the mock if the backend does not answer".
const BACKEND = process.env.T2S_BACKEND ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
      '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true, changeOrigin: false },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
      '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true, changeOrigin: false },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    chunkSizeWarningLimit: 4000,
  },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/unit/setup.ts'],
    css: false,
    testTimeout: 30000,
  },
});
