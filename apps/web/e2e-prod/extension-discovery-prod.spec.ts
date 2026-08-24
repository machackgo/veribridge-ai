import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import * as fs from "fs";

/**
 * Extension discovery/install UX — PRODUCTION verification (veribridgeai.com).
 *
 * Guards the regression where the install CTA silently vanished in production:
 * the store URL was env-driven and unset on Vercel, so every install surface
 * rendered "release under review" instead of a link to the published listing.
 *
 * Detection is NOT faked. STATE A runs in a browser with no extension at all —
 * the real probe genuinely fails. STATE B installs the real content-script
 * bridge protocol (PING → PONG), the same exchange the shipped extension
 * answers; Google blocks automated "Add to Chrome", so the bridge stands in
 * for the extension while the app's detection path runs for real.
 */

const SCRATCH = process.env.QA_SCRATCH;
const BASE = "https://veribridgeai.com";
const OFFICIAL_LISTING =
  "https://chromewebstore.google.com/detail/veribridge-website-proof/gdogdgnaioldjldljniffcmkcdpdjlme";
const SCHEMA_VERSION = 1;

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };

// Needs a throwaway student session minted for the run. Skip rather than throw
// at import time, so this spec cannot break a whole-directory prod run.
const FIXTURE = SCRATCH ? `${SCRATCH}/qa_ext_session.json` : "";
const hasFixture = Boolean(FIXTURE) && fs.existsSync(FIXTURE);
test.skip(!hasFixture, "requires a minted QA student session at $QA_SCRATCH/qa_ext_session.json");

const qa: { student: Session; cookie_name: string } = hasFixture
  ? JSON.parse(fs.readFileSync(FIXTURE, "utf8"))
  : { student: { email: "", user_id: "", access_token: "", refresh_token: "" }, cookie_name: "" };

function cookiesFor(s: Session) {
  const value =
    "base64-" +
    Buffer.from(
      JSON.stringify({
        access_token: s.access_token,
        refresh_token: s.refresh_token,
        expires_in: 3600,
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        token_type: "bearer",
        user: { id: s.user_id, email: s.email },
      }),
    ).toString("base64");
  const CHUNK = 3180;
  if (value.length <= CHUNK) {
    return [{ name: qa.cookie_name, value, domain: "veribridgeai.com", path: "/", secure: true }];
  }
  const out = [];
  for (let i = 0; i * CHUNK < value.length; i++) {
    out.push({
      name: `${qa.cookie_name}.${i}`,
      value: value.slice(i * CHUNK, (i + 1) * CHUNK),
      domain: "veribridgeai.com",
      path: "/",
      secure: true,
    });
  }
  return out;
}

async function auth(context: BrowserContext) {
  await context.addCookies(cookiesFor(qa.student));
}

/** The real extension bridge protocol — same PING/PONG the content script answers. */
async function installBridge(page: Page, buildVersion = "1.0.1") {
  await page.addInitScript(
    ({ buildVersion, schemaVersion }) => {
      window.addEventListener("message", (event: MessageEvent) => {
        const data = event.data as { source?: string; type?: string; payload?: { request_id?: string } };
        if (data?.source !== "veribridge-app") return;
        if (data.type !== "VERIBRIDGE_RECORDER_BRIDGE_PING") return;
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
        );
      });
    },
    { buildVersion, schemaVersion: SCHEMA_VERSION },
  );
}

test.describe("PROD STATE A — no extension installed", () => {
  test("Website Proof explains the requirement and links to the real listing", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();
    await page.goto(`${BASE}/student/proofs/website`, { waitUntil: "domcontentloaded" });

    const gate = page.getByTestId("recorder-install-gate");
    await expect(gate).toBeVisible({ timeout: 30_000 });
    await expect(gate).toContainText("Install the VeriBridge Recorder to continue");

    // THE REGRESSION: this degraded box must not exist while the listing is live.
    await expect(page.getByTestId("recorder-gate-pending-release")).toHaveCount(0);

    const install = page.getByTestId("recorder-gate-install-link");
    await expect(install).toBeVisible();
    await expect(install).toHaveAttribute("href", OFFICIAL_LISTING);
    await expect(install).toHaveAttribute("target", "_blank");
    await expect(page.getByTestId("recorder-gate-recheck")).toBeVisible();

    await page.screenshot({ path: "test-results/prod/A-website-proof-not-installed.png" });
    await context.close();
  });

  test("dashboard surfaces the recorder as not installed", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();
    await page.goto(`${BASE}/student`, { waitUntil: "domcontentloaded" });

    const card = page.getByTestId("dashboard-recorder-extension-card");
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card).toHaveAttribute("data-recorder-status", "absent", { timeout: 30_000 });
    await expect(page.getByTestId("dashboard-recorder-install-link")).toHaveAttribute("href", OFFICIAL_LISTING);

    await page.screenshot({ path: "test-results/prod/A-dashboard-not-installed.png" });
    await context.close();
  });

  test("State A survives direct nav, reload and back/forward", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();

    await page.goto(`${BASE}/student/proofs/website`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("recorder-install-gate")).toBeVisible({ timeout: 30_000 });

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("recorder-install-gate")).toBeVisible({ timeout: 30_000 });

    await page.goto(`${BASE}/student`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("dashboard-recorder-extension-card")).toBeVisible({ timeout: 30_000 });
    await page.goBack({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("recorder-install-gate")).toBeVisible({ timeout: 30_000 });
    await page.goForward({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("dashboard-recorder-extension-card")).toBeVisible({ timeout: 30_000 });

    await context.close();
  });
});

test.describe("PROD STATE B — extension detected", () => {
  test("Website Proof confirms readiness and drops the install prompt", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();
    await installBridge(page);
    await page.goto(`${BASE}/student/proofs/website`, { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0);

    // The existing proof workflow is exposed, not gated away.
    const body = page.locator("body");
    await expect(body).toContainText("Privacy Guard");
    await expect(body).toContainText("Website URL");

    await page.screenshot({ path: "test-results/prod/B-website-proof-detected.png" });
    await context.close();
  });

  test("dashboard shows detected and offers Website Proof instead of install", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();
    await installBridge(page);
    await page.goto(`${BASE}/student`, { waitUntil: "domcontentloaded" });

    const card = page.getByTestId("dashboard-recorder-extension-card");
    await expect(card).toHaveAttribute("data-recorder-status", "detected", { timeout: 30_000 });
    await expect(page.getByTestId("dashboard-recorder-install-link")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-recorder-open-website-proof")).toHaveAttribute(
      "href",
      "/student/proofs/website",
    );

    await page.screenshot({ path: "test-results/prod/B-dashboard-detected.png" });
    await context.close();
  });

  test("returning from the Chrome Web Store detects without a reload", async ({ browser }) => {
    const context = await browser.newContext();
    await auth(context);
    const page = await context.newPage();

    // Arrive with no extension: the gate is up.
    await page.goto(`${BASE}/student/proofs/website`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("recorder-install-gate")).toBeVisible({ timeout: 30_000 });
    const urlBefore = page.url();

    // Student opens the store in another tab, installs, and comes back. The
    // content script injects into already-open tabs — simulate exactly that,
    // then restore focus/visibility to this tab. No reload, no re-login.
    const store = await context.newPage();
    await store.goto("about:blank");
    await page.evaluate(({ schemaVersion }) => {
      window.addEventListener("message", (event: MessageEvent) => {
        const data = event.data as { source?: string; type?: string; payload?: { request_id?: string } };
        if (data?.source !== "veribridge-app") return;
        if (data.type !== "VERIBRIDGE_RECORDER_BRIDGE_PING") return;
        window.postMessage(
          {
            source: "veribridge-extension",
            type: "VERIBRIDGE_RECORDER_BRIDGE_PONG",
            payload: {
              request_id: String(data.payload?.request_id ?? ""),
              schema_version: schemaVersion,
              build_version: "1.0.1",
              context_valid: true,
              bridge_trusted: true,
            },
          },
          window.location.origin,
        );
      });
    }, { schemaVersion: SCHEMA_VERSION });
    await store.close();
    // Returning to the tab is the trigger — the same signal a real tab switch
    // raises. No reload, no re-login.
    await page.bringToFront();
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));

    // The gate recognises the recorder in place and offers to continue the
    // SAME session, rather than telling an installed student to install.
    await expect(page.getByTestId("recorder-detected-banner")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("recorder-gate-continue")).toBeVisible();
    await expect(page.getByTestId("recorder-gate-install-link")).toHaveCount(0);
    expect(page.url()).toBe(urlBefore);

    await page.screenshot({ path: "test-results/prod/B-detected-after-return.png" });

    // Continuing lands in State B: readiness confirmed, workflow exposed.
    await page.getByTestId("recorder-gate-continue").click();
    await expect(page.getByTestId("recorder-ready-badge")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("recorder-install-gate")).toHaveCount(0);
    await expect(page.locator("body")).toContainText("Privacy Guard");

    await page.screenshot({ path: "test-results/prod/B-continued-into-workflow.png" });
    await context.close();
  });
});
