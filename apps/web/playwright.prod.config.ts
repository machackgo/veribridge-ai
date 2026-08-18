import { defineConfig, devices } from "@playwright/test";

// Production verification config — runs specs in e2e-prod against the live
// deployment. No local webServer. Not part of the regular e2e suite.
export default defineConfig({
  testDir: "./e2e-prod",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"]],
  timeout: 120_000,
  use: {
    baseURL: "https://veribridgeai.com",
    trace: "off",
    screenshot: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["iPhone 13"] } }],
});
