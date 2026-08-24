import { defineConfig, devices } from "@playwright/test";

/** Production smoke config for the launch film — desktop, tablet (WebKit), phone. */
export default defineConfig({
  testDir: "./e2e-prod",
  testMatch: ["launch-film-prod.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 180_000,
  reporter: [["line"]],
  use: {
    baseURL: "https://veribridgeai.com",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "tablet-safari", use: { ...devices["iPad Mini landscape"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
