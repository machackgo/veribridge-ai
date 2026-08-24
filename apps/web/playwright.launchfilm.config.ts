import { defineConfig, devices } from "@playwright/test";

/**
 * Launch-film QA config — desktop + tablet + phone against a local production
 * server (`npm run start -- -p 3111`), on an isolated port so it never
 * collides with another worktree's dev server.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["launch-film.spec.ts"],
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  reporter: [["line"]],
  use: {
    baseURL: "http://localhost:3111",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "tablet", use: { ...devices["iPad Mini landscape"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
