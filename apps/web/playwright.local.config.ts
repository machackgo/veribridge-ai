import { defineConfig } from "@playwright/test";

// Local-rig E2E (docker e2e-supabase + local API :8000 + web :3000).
// Session fixtures are minted per-run into the session scratchpad.
export default defineConfig({
  testDir: "./e2e-local",
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: { headless: true, screenshot: "only-on-failure" },
});
