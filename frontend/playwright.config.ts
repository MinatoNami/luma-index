import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests for the one part of this app that unit tests cannot reach.
 *
 * The reader renders PDF pages onto canvases, and PDF.js drives that with
 * `requestAnimationFrame`. happy-dom has no layout and no rAF worth the name,
 * so every reader bug in this project's history — a canvas leak, a blank page
 * after using the arrows, a toolbar that painted its own contents while
 * collapsed — was found by a person looking at a browser. This suite is that
 * person, made repeatable.
 *
 * It runs against the development stack from inside the compose network, where
 * `caddy` is a hostname Django already allows, so nothing has to be
 * reconfigured to be testable. See scripts/e2e.sh.
 */
export default defineConfig({
  testDir: './e2e',
  // The reader has to fetch and parse a real PDF before anything is true.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['github']] : [['list']],
  use: {
    baseURL: process.env.LUMA_E2E_BASE_URL ?? 'http://caddy:8080',
    trace: 'retain-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
