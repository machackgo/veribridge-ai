import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e-prod",
  testMatch: /student-workflows-prod\.spec\.ts/,
  timeout: 120_000,
  retries: 1,
  workers: 1,
  reporter: [["list"]],
  use: { headless: true, screenshot: "only-on-failure", ...devices["Desktop Chrome"] },
})
