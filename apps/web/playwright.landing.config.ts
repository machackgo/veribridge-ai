import { defineConfig, devices } from "@playwright/test";

/**
 * Landing-page QA config — isolated port so it never collides with another
 * worktree's dev server on :3000 (see stale-dev-servers gotcha).
 * Expects a production server already running: `npm run start -- -p 3111`.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["navigation.spec.ts", "proof-section.spec.ts"],
  fullyParallel: true,
  reporter: [["line"]],
  use: {
    baseURL: "http://localhost:3111",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "iphone-13", use: { ...devices["iPhone 13"] } },
  ],
});
