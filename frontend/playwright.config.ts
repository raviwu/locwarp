import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  // CI flake insurance: retry twice on CI (0 locally so a real local failure
  // surfaces immediately); keep a trace from the first retry so a CI-only
  // failure is debuggable from the uploaded HTML report artifact.
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['line']] : 'line',
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    // Build first (uses NODE_ENV=production; fast serving via preview).
    // 'vite preview' serves the pre-built dist/ at port 4173 so page loads
    // are instant — no per-request module transform that can time out.
    command: 'npx vite build --logLevel error && npx vite preview --port 4173',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
