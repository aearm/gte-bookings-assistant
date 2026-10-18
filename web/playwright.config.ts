// End-to-end tests of the React app against the real FastAPI server and the real cubes.
// Claude's answers are replayed from e2e/cassette.json (E2E_RECORD=1 records them once, which costs).
// The server runs on port 8620 with a throwaway data folder (never the app's real data).
import { defineConfig, devices } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const PORT = 8620
const dataDir = path.join(os.tmpdir(), 'bookings-assistant-e2e')
const python = path.resolve(__dirname, '..', '.venv', 'Scripts', 'python.exe')

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 60_000 },
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `"${python}" e2e/prepare.py && "${python}" ../start_api.py`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 300_000,
    reuseExistingServer: false,
    stdout: 'pipe',
    env: {
      API_PORT: String(PORT),
      APP_DATA_DIR: dataDir,
      APP_DASHBOARDS_FILE: path.join(dataDir, 'dashboards.json'),
      CLAUDE_CASSETTE: path.resolve(__dirname, 'e2e', 'cassette.json'),
      CLAUDE_CASSETTE_MODE: process.env.E2E_RECORD ? 'record' : 'replay',
      APP_BUILTIN_DASHBOARDS: '0', // prepare.py puts them after the test dashboard instead
      OPENBLAS_NUM_THREADS: '1',
    },
  },
})
