import { defineConfig, devices } from '@playwright/test';

// The acceptance tests live in tests/e2e. The webServer builds the app and
// serves the production bundle so page.goto('/') hits the real built output
// (ADR-7 prod path), keeping the e2e honest about the Vite build.
export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: true,
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
