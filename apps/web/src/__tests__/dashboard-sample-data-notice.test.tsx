/**
 * Regression: no authenticated dashboard route may present illustrative
 * sample content as the signed-in user's own data without saying so.
 *
 * Production audit 2026-07-21 found eight such routes (fabricated skill gaps
 * "In 68% of saved jobs / Your readiness 42%", another person's name and
 * "verified" .edu address, asserted F-1/OPT status, and privacy toggles that
 * only set local state). If a route is later wired to real per-user data,
 * remove it from MOCK_BACKED_ROUTES in the same change that does the wiring.
 */
import { describe, expect, it } from "vitest"
import { readFileSync, existsSync } from "node:fs"
import { join } from "node:path"

const APP_DIR = join(__dirname, "..", "app", "dashboard")

// Routes whose body still renders illustrative placeholder content.
const MOCK_BACKED_ROUTES = [
  "skill-gaps",
  "profile",
  "visa-fit",
  "jobs",
  "applications",
  "mock-interview",
  "settings",
  "privacy",
] as const

// Routes whose visible controls do not change any real sharing/exposure state.
const INERT_CONTROL_ROUTES = ["visa-fit", "settings", "privacy"] as const

describe("dashboard sample-data honesty", () => {
  it.each(MOCK_BACKED_ROUTES)("%s renders the sample-data notice", (route) => {
    const file = join(APP_DIR, route, "page.tsx")
    expect(existsSync(file), `${route}/page.tsx should exist`).toBe(true)
    const src = readFileSync(file, "utf8")
    expect(src).toContain("SampleDataNotice")
  })

  it.each(INERT_CONTROL_ROUTES)("%s declares its controls are not connected", (route) => {
    const src = readFileSync(join(APP_DIR, route, "page.tsx"), "utf8")
    expect(src).toMatch(/controlsInert/)
  })

  it("the notice states plainly that the data is not the user's", () => {
    const src = readFileSync(
      join(__dirname, "..", "..", "components", "dashboard", "SampleDataNotice.tsx"),
      "utf8",
    )
    expect(src).toContain("this is not your data")
    expect(src).toMatch(/not derived from your proofs/i)
    expect(src).toContain("The controls on this page are not connected")
  })

  it("mock data never reaches the real proof pipeline routes", () => {
    // The proof -> passport -> report pipeline must never import mock data.
    const pipelineFiles = [
      join(__dirname, "..", "app", "student", "vbr", "page.tsx"),
      join(__dirname, "..", "app", "student", "vbr", "passport", "page.tsx"),
      join(__dirname, "..", "app", "student", "proofs", "github", "page.tsx"),
      join(__dirname, "..", "app", "student", "proofs", "website", "page.tsx"),
      join(__dirname, "..", "app", "student", "proofs", "documents", "page.tsx"),
      join(__dirname, "..", "app", "student", "proofs", "project-defense", "page.tsx"),
    ]
    for (const file of pipelineFiles) {
      if (!existsSync(file)) continue
      const src = readFileSync(file, "utf8")
      expect(src, `${file} must not import data/mock`).not.toMatch(/data\/mock/)
    }
  })
})
