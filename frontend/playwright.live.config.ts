import { defineConfig, devices } from '@playwright/test';

// E2E against the REAL backend (no mock): starts the FastAPI server on a fresh test project and Vite in live mode.
// Run from frontend/ after `. ..\tools\env.ps1` (Windows) or `. ../tools/env.sh` (macOS / Linux):
//   npx playwright test -c playwright.live.config.ts
const UI_PORT = Number(process.env.T2S_LIVE_UI_PORT ?? 5198);
const API_PORT = Number(process.env.T2S_LIVE_API_PORT ?? 8775);
const SERVER_ARGS = `--project e2e_live --fresh --islands 2 --validators 1 --port ${API_PORT}`;
const API_COMMAND =
  process.platform === 'win32'
    ? `cmd /c "call ..\\tools\\env.cmd && cd ..\\backend && uv run python run_server.py ${SERVER_ARGS}"`
    : `bash -c ". ../tools/env.sh && cd ../backend && uv run --frozen python run_server.py ${SERVER_ARGS}"`;

export default defineConfig({
  testDir: 'tests/e2e-live',
  timeout: 180_000,
  expect: { timeout: 90_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${UI_PORT}`,
    viewport: { width: 1600, height: 900 },
    trace: 'retain-on-failure',
    launchOptions: {
      args: ['--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'],
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 900 } } }],
  webServer: [
    {
      command: API_COMMAND,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: `npx vite --port ${UI_PORT} --strictPort`,
      url: `http://localhost:${UI_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_MOCK: '0', T2S_BACKEND: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
