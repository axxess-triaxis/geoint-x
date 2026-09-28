import { defineConfig, devices } from '@playwright/test'

// E2E runs against a dedicated backend instance with a throwaway state directory,
// serving the production build (run `npm run build` first). Real demo-pack data.
const PORT = 8010

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 60_000 },
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `uv run --directory ../backend python -c "from geointx.api.app import main; main()"`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: { PORT: String(PORT), GEOINTX_VAR_DIR: '../var-e2e', GEMINI_API_KEY: '', GEOINTX_GEMINI_API_KEY: '' },
  },
})
