/**
 * Extension discovery + install/recovery UX — local browser E2E.
 *
 * Covers the journey a new student takes to find and install the Website Proof
 * Recorder, and the state distinctions VeriBridge must get right afterwards.
 *
 * MANUAL CHECKPOINT (cannot be automated): actually clicking "Add to Chrome"
 * on the Chrome Web Store. Google blocks automated installation, so this suite
 * asserts the link *destination* is the official listing and simulates the
 * post-install world by injecting a recorder bridge that answers the extension
 * protocol's ping exactly as the real content script does. Everything before
 * and after that single click is covered here.
 *
 * Run: npx playwright test --config playwright.extension.config.ts
 */

import { expect, test, type Page } from "@playwright/test"

const OFFICIAL_LISTING =
  "https://chromewebstore.google.com/detail/veribridge-website-proof/gdogdgnaioldjldljniffcmkcdpdjlme"

/** Schema/build the app currently requires (packages/shared contract). */
const SCHEMA_VERSION = 1
const CURRENT_BUILD = "1.0.1"

/**
 * Impersonates the extension's content-script bridge. This is the same
 * synchronous PING → PONG exchange `probeRecorderExtension()` relies on, so
 * "detected" here is produced by the real detection path — not a UI stub.
 */
async function installRecorderBridge(
  page: Page,
  opts: { buildVersion?: string; contextValid?: boolean } = {},
) {
  const buildVersion = opts.buildVersion ?? CURRENT_BUILD
  const contextValid = opts.contextValid ?? true
  await page.evaluate(
    ({ buildVersion, contextValid, schemaVersion }) => {
      const w = window as unknown as { __vbBridge?: (e: MessageEvent) => void }
      if (w.__vbBridge) window.removeEventListener("message", w.__vbBridge)
      const handler = (event: MessageEvent) => {
        const data = event.data as { source?: string; type?: string; payload?: { request_id?: string } }
        if (data?.source !== "veribridge-app") return
        if (data.type !== "VERIBRIDGE_RECORDER_BRIDGE_PING") return
        window.postMessage(
          {
            source: "veribridge-extension",
            type: "VERIBRIDGE_RECORDER_BRIDGE_PONG",
            payload: {
              request_id: String(data.payload?.request_id ?? ""),
              schema_version: schemaVersion,
              build_version: buildVersion,
              context_valid: contextValid,
              bridge_trusted: true,
            },
          },
          window.location.origin,
        )
      }
      w.__vbBridge = handler
      window.addEventListener("message", handler)
    },
    { buildVersion, contextValid, schemaVersion: SCHEMA_VERSION },
  )
}

/** Injects the bridge for every future navigation (a truly installed browser). */
async function installRecorderBridgeForAllPages(page: Page, buildVersion = CURRENT_BUILD) {
  await page.addInitScript(
    ({ buildVersion, schemaVersion }) => {
      window.addEventListener("message", (event: MessageEvent) => {
        const data = event.data as { source?: string; type?: string; payload?: { request_id?: string } }
        if (data?.source !== "veribridge-app") return
        if (data.type !== "VERIBRIDGE_RECORDER_BRIDGE_PING") return
        window.postMessage(
          {
            source: "veribridge-extension",
            type: "VERIBRIDGE_RECORDER_BRIDGE_PONG",
            payload: {
              request_id: String(data.payload?.request_id ?? ""),
              schema_version: schemaVersion,
              build_version: buildVersion,
              context_valid: true,
              bridge_trusted: true,
            },
          },
          window.location.origin,
        )
      })
    },
    { buildVersion, schemaVersion: SCHEMA_VERSION },
  )
}

/**
 * Empty-but-successful API responses: the dashboard renders a fresh student
 * (no projects/proofs) rather than an error state.
 */
async function mockFreshStudentApis(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
    if (url.pathname.includes("/work-passport")) return json({ is_published: false, public_path: null })
    if (url.pathname.includes("/skill-gaps")) return json({ projects: [], total_gap_count: 0 })
    return json([])
  })
}

/** Captured events from the discovery telemetry channel. */
async function captureTelemetry(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __vbEvents?: unknown[] }
    w.__vbEvents = []
    window.addEventListener("veribridge:recorder-extension-event", (event: Event) => {
      w.__vbEvents!.push((event as CustomEvent).detail)
    })
  })
}

async function telemetry(page: Page): Promise<Array<{ name: string; surface: string }>> {
  return await page.evaluate(
    () => (window as unknown as { __vbEvents: Array<{ name: string; surface: string }> }).__vbEvents,
  )
}

test.describe("CASE A/G — dashboard discovery for a student without the extension", () => {
  test("dashboard surfaces the recorder with a direct install CTA to the official listing", async ({ page }) => {
    await captureTelemetry(page)
    await mockFreshStudentApis(page)
    await page.goto("/student")

    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toBeVisible()
    await expect(card).toContainText("Website Proof Recorder")
    // WHY / WHAT the student needs to understand.
    await expect(card).toContainText("Website Proof evidence")

    // Detection resolves to "absent" — no extension in this browser.
    await expect(card).toHaveAttribute("data-recorder-status", "absent", { timeout: 15_000 })
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toHaveText("Not installed")

    // CASE G — the dashboard link opens the official Chrome Web Store listing.
    const install = page.getByTestId("dashboard-recorder-install-link")
    await expect(install).toHaveAttribute("href", OFFICIAL_LISTING)
    await expect(install).toHaveAttribute("target", "_blank")
    await expect(install).toHaveAttribute("rel", "noopener noreferrer")

    // Keyboard reachable with a visible focus ring.
    await install.focus()
    await expect(install).toBeFocused()

    await page.screenshot({ path: "test-results/shots/01-dashboard-not-installed.png", fullPage: false })
    await card.screenshot({ path: "test-results/shots/01b-dashboard-card-not-installed.png" })

    // Telemetry (no PII) fires on click, without faking detection.
    await install.click({ modifiers: ["Meta"] }).catch(() => undefined)
    const events = await telemetry(page)
    expect(events.some((e) => e.name === "extension_install_clicked" && e.surface === "dashboard")).toBe(true)
    // Clicking through must NOT flip the card to detected.
    await expect(card).toHaveAttribute("data-recorder-status", "absent")
  })
})

test.describe("CASE B — dashboard with the extension installed", () => {
  test("detected state replaces the install CTA with a Website Proof entry point", async ({ page }) => {
    await installRecorderBridgeForAllPages(page)
    await mockFreshStudentApis(page)
    await page.goto("/student")

    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "detected", { timeout: 15_000 })
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toContainText("Recorder detected")
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toContainText(`v${CURRENT_BUILD}`)

    // An installed extension is never told to install.
    await expect(page.getByTestId("dashboard-recorder-install-link")).toHaveCount(0)
    await expect(page.getByTestId("dashboard-recorder-open-website-proof")).toHaveAttribute(
      "href",
      "/student/proofs/website",
    )
    // Store listing remains available as a secondary "view" link.
    await expect(page.getByTestId("dashboard-recorder-store-link")).toHaveAttribute("href", OFFICIAL_LISTING)

    await page.screenshot({ path: "test-results/shots/02-dashboard-detected.png", fullPage: false })
    await card.screenshot({ path: "test-results/shots/02b-dashboard-card-detected.png" })
  })
})

test.describe("CASE A/H — Website Proof install gate", () => {
  test("missing extension blocks with a direct install CTA to the official listing", async ({ page }) => {
    await captureTelemetry(page)
    await mockFreshStudentApis(page)
    await page.goto("/student/proofs/website")

    const gate = page.getByTestId("recorder-install-gate")
    await expect(gate).toBeVisible({ timeout: 20_000 })
    await expect(gate).toContainText("Install the VeriBridge Recorder to continue")
    // Permission transparency before install.
    await expect(gate).toContainText("Screen recording you start")

    // CASE H — same official listing as the dashboard.
    const install = page.getByTestId("recorder-gate-install-link")
    await expect(install).toHaveAttribute("href", OFFICIAL_LISTING)
    await expect(install).toHaveAttribute("rel", "noopener noreferrer")
    // Explicit post-install recovery affordance.
    await expect(page.getByTestId("recorder-gate-recheck")).toBeVisible()

    await page.screenshot({ path: "test-results/shots/03-website-proof-install-gate.png", fullPage: false })
    await gate.screenshot({ path: "test-results/shots/03b-website-proof-gate.png" })
  })
})

test.describe("CASE C — extension installed while the Website Proof page is already open", () => {
  test("returning to the tab detects the recorder without a reload or re-login", async ({ page }) => {
    await mockFreshStudentApis(page)
    await page.goto("/student/proofs/website")

    const gate = page.getByTestId("recorder-install-gate")
    await expect(gate).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-gate-install-link")).toBeVisible()

    // The student installs the extension in the other tab. Chrome injects the
    // content script into already-open tabs — simulated here — and VeriBridge
    // is NOT reloaded.
    const urlBefore = page.url()
    await installRecorderBridge(page)
    // Returning to the tab is the trigger (no aggressive polling required).
    await page.evaluate(() => window.dispatchEvent(new Event("focus")))

    await expect(page.getByTestId("recorder-detected-banner")).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-gate-continue")).toBeVisible()
    // Same page, same session — no navigation, no logout.
    expect(page.url()).toBe(urlBefore)

    await page.screenshot({ path: "test-results/shots/04-website-proof-detected-after-install.png" })
    await gate.screenshot({ path: "test-results/shots/04b-gate-detected-after-install.png" })
  })

  test("the dashboard card also recovers on tab focus", async ({ page }) => {
    await mockFreshStudentApis(page)
    await page.goto("/student")
    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "absent", { timeout: 15_000 })

    await installRecorderBridge(page)
    await page.evaluate(() => window.dispatchEvent(new Event("focus")))

    await expect(card).toHaveAttribute("data-recorder-status", "detected", { timeout: 15_000 })
    await expect(page.getByTestId("dashboard-recorder-open-website-proof")).toBeVisible()
  })
})

test.describe("CASE B — Website Proof pre-start state reflects a detected recorder", () => {
  test("shows readiness instead of an install prompt", async ({ page }) => {
    await installRecorderBridgeForAllPages(page)
    await mockFreshStudentApis(page)
    await page.goto("/student/proofs/website")

    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-ready-badge")).toContainText("ready to record")
    // The install gate must NOT be shown to a student who has the extension.
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0)

    await page.screenshot({ path: "test-results/shots/05-website-proof-ready.png", fullPage: false })
    await page.getByTestId("recorder-ready-badge").screenshot({
      path: "test-results/shots/05b-recorder-ready-badge.png",
    })
  })
})

test.describe("CASE F — outdated / disabled-then-reloaded extension", () => {
  test("an outdated build is offered an update, never a first-time install", async ({ page }) => {
    await installRecorderBridgeForAllPages(page, "0.2.1")
    await mockFreshStudentApis(page)
    await page.goto("/student")

    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "outdated", { timeout: 15_000 })
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toHaveText("Update required")
    await expect(page.getByTestId("dashboard-recorder-install-link")).toContainText("Update in Chrome Web Store")
    await expect(card).toContainText("Detected v0.2.1")

    await card.screenshot({ path: "test-results/shots/06-dashboard-outdated.png" })
  })

  test("an orphaned bridge (extension reloaded/disabled) asks for a refresh, not an install", async ({ page }) => {
    await mockFreshStudentApis(page)
    await page.goto("/student")
    await installRecorderBridge(page, { contextValid: false })
    await page.evaluate(() => window.dispatchEvent(new Event("focus")))

    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "reload_needed", { timeout: 15_000 })
    await expect(page.getByTestId("dashboard-recorder-refresh")).toBeVisible()
    await expect(page.getByTestId("dashboard-recorder-install-link")).toHaveCount(0)

    await card.screenshot({ path: "test-results/shots/07-dashboard-reload-needed.png" })
  })
})

test.describe("CASE I — unsupported / mobile browser", () => {
  test("makes no 'ready to record' claim and states the Chrome requirement", async ({ browser }) => {
    const context = await browser.newContext({
      userAgent:
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    })
    const page = await context.newPage()
    await mockFreshStudentApis(page)
    await page.goto("/student")

    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "unsupported")
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toHaveText("Chrome required")
    await expect(card).toContainText("requires desktop Google Chrome")
    await expect(card).not.toContainText("ready to record")
    // No "check again" on a browser that can never answer the bridge.
    await expect(page.getByTestId("dashboard-recorder-recheck")).toHaveCount(0)

    // Mobile layout: the card must fit the viewport without horizontal
    // overflow. Scoped to the card rather than the document, so unrelated
    // dev-only overlays can't make this assertion lie either way.
    const fits = await card.evaluate((el) => {
      const rect = el.getBoundingClientRect()
      return {
        overflowRight: Math.round(rect.right - document.documentElement.clientWidth),
        scrollOverflow: el.scrollWidth - el.clientWidth,
      }
    })
    expect(fits.overflowRight).toBeLessThanOrEqual(0)
    expect(fits.scrollOverflow).toBeLessThanOrEqual(0)

    await page.screenshot({ path: "test-results/shots/08-mobile-unsupported.png", fullPage: false })
    await context.close()
  })
})

test.describe("PART 7 — accessibility of the discovery surfaces", () => {
  test("card is a labelled region with real controls and no icon-only CTA", async ({ page }) => {
    await mockFreshStudentApis(page)
    await page.goto("/student")
    const card = page.getByTestId("dashboard-recorder-extension-card")
    await expect(card).toHaveAttribute("data-recorder-status", "absent", { timeout: 15_000 })

    // Status is announced, not only colour-coded.
    await expect(page.getByTestId("dashboard-recorder-status-chip")).toHaveAttribute("aria-live", "polite")
    // Heading is real text.
    await expect(card.getByRole("heading", { name: "Website Proof Recorder" })).toBeVisible()
    // External CTA carries an accessible name that says it leaves the app.
    await expect(page.getByTestId("dashboard-recorder-install-link")).toHaveAttribute(
      "aria-label",
      /opens the Chrome Web Store in a new tab/,
    )
    // Recheck is a genuine button, keyboard-operable.
    const recheck = page.getByTestId("dashboard-recorder-recheck")
    await expect(recheck).toHaveRole("button")
    await recheck.focus()
    await expect(recheck).toBeFocused()
  })
})

test.describe("PART 8 — navigation durability of the discovery states", () => {
  // The regression that lost this UX was invisible on a first page load, so
  // the states must survive every way a student actually reaches the page:
  // typing the URL, reloading, and using the browser's history buttons.

  test("State A survives direct navigation, reload, and back/forward", async ({ page }) => {
    await mockFreshStudentApis(page)

    // Direct navigation — no dashboard hop first.
    await page.goto("/student/proofs/website")
    const gate = page.getByTestId("recorder-install-gate")
    await expect(gate).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-gate-install-link")).toHaveAttribute("href", OFFICIAL_LISTING)
    // The degraded "release under review" box must never appear now that the
    // listing is published — that box IS the regression this suite guards.
    await expect(page.getByTestId("recorder-gate-pending-release")).toHaveCount(0)

    // Reload.
    await page.reload()
    await expect(gate).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-gate-install-link")).toHaveAttribute("href", OFFICIAL_LISTING)

    // Navigate away, then come back with the browser Back button.
    await page.goto("/student")
    await expect(page.getByTestId("dashboard-recorder-extension-card")).toBeVisible({ timeout: 20_000 })
    await page.goBack()
    await expect(gate).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-gate-install-link")).toHaveAttribute("href", OFFICIAL_LISTING)

    // Forward to the dashboard again — its card re-detects too.
    await page.goForward()
    await expect(page.getByTestId("dashboard-recorder-extension-card")).toHaveAttribute(
      "data-recorder-status",
      "absent",
      { timeout: 20_000 },
    )
  })

  test("State B survives direct navigation, reload, and back/forward", async ({ page }) => {
    await installRecorderBridgeForAllPages(page)
    await mockFreshStudentApis(page)

    await page.goto("/student/proofs/website")
    // Detected: readiness confirmed, and no install prompt anywhere.
    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0)

    await page.reload()
    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0)

    await page.goto("/student")
    await expect(page.getByTestId("dashboard-recorder-extension-card")).toHaveAttribute(
      "data-recorder-status",
      "detected",
      { timeout: 20_000 },
    )
    await page.goBack()
    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0)
  })

  test("the proof configuration form stays intact in both states", async ({ page }) => {
    // The restoration must not gate away the existing Website Proof workflow.
    await mockFreshStudentApis(page)
    await page.goto("/student/proofs/website")
    await expect(page.getByTestId("recorder-install-gate")).toBeVisible({ timeout: 20_000 })

    const body = page.locator("body")
    // Privacy Guard, project relationship, URLs, skills, objective all remain
    // reachable while the install gate is on screen.
    await expect(body).toContainText("Privacy Guard")
    await expect(body).toContainText("Website URL")
    await expect(body).toContainText("GitHub")
    await expect(body).toContainText(/Skills/i)
    await expect(body).toContainText(/objective/i)
  })
})
