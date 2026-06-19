import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
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
