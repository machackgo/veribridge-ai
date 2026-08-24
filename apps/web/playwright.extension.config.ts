import { defineConfig, devices } from "@playwright/test"

// Extension discovery/install UX E2E. Runs against a local demo-mode dev
// server on an alternate port (3111) so it never collides with another
// worktree's :3000 server.
export default defineConfig({
  testDir: "./e2e-local",
  testMatch: /extension-install-discovery-local\.spec\.ts/,
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.VB_WEB_BASE_URL ?? "http://localhost:3111",
    headless: true,
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
})
