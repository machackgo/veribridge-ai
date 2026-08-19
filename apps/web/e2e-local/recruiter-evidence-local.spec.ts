import { test, expect, devices, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter Evidence Discovery V1.6 — LOCAL rig verification
// (docker e2e-supabase :54321 + local API :8000 + web :3000).
//
// Rig ground truth (rebuilt index): 5 published candidates; Python evidence
// on several (GitHub Proof among sources); FastAPI evidence ONLY on
// rdQygsI3lok and ONLY via Document Proof + VBR Report (no GitHub proof for
// FastAPI); NO candidate has NLP evidence.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/e52d8d20-2420-4d65-b7dc-a59d237c9c98/scratchpad";
const BASE = "http://localhost:3000";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec1: Session; rec2: Session; cookie_name: string } = JSON.parse(
  fs.readFileSync(`${SCRATCH}/qa_rig_sessions.json`, "utf8"),
);

const consoleErrors: string[] = [];
const serverErrors: string[] = [];

function watch(page: Page) {
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("response", (res) => {
    if (res.status() >= 500) serverErrors.push(`${res.status()} ${res.url()}`);
  });
}

function cookiesFor(s: Session) {
  const session = {
    access_token: s.access_token,
    refresh_token: s.refresh_token,
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: { id: s.user_id, email: s.email, aud: "authenticated", role: "authenticated" },
  };
  const value = "base64-" + Buffer.from(JSON.stringify(session)).toString("base64url");
  const MAX = 3180;
  if (value.length <= MAX) {
    return [{ name: qa.cookie_name, value, domain: "localhost", path: "/" }];
  }
  const chunks: { name: string; value: string; domain: string; path: string }[] = [];
  for (let i = 0; i * MAX < value.length; i++) {
    chunks.push({
      name: `${qa.cookie_name}.${i}`,
      value: value.slice(i * MAX, (i + 1) * MAX),
      domain: "localhost",
      path: "/",
    });
  }
  return chunks;
}

async function recruiterPage(
  browser: Browser,
  s: Session,
  viewport?: { width: number; height: number },
) {
  const context = await browser.newContext(
    viewport ? { viewport } : { viewport: { width: 1440, height: 900 } },
  );
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return page;
}

async function searchFor(page: Page, query: string) {
  await page.getByTestId("search-input").fill(query);
  await page.getByTestId("search-submit").click();
}

test.describe("Recruiter Evidence Discovery — local rig", () => {
  test("evidence intent: 'show me proof of python' opens proof cards, not candidate cards", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    await searchFor(page, "show me proof of python");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("interpretation-intent")).toContainText("Evidence search");
    await expect(page.getByTestId("search-result-card")).toHaveCount(0);
    expect(await page.getByTestId("evidence-group-card").count()).toBeGreaterThanOrEqual(3);
    const firstItem = page.getByTestId("evidence-item").first();
    await expect(firstItem).toContainText("Python");
    await expect(page.getByTestId("evidence-view-full").first()).toHaveAttribute(
      "href",
      /\/p\/.+\/skills\/python/,
    );
    await page.screenshot({ path: `${SCRATCH}/shots-local/e1-proof-python.png`, fullPage: true });
    await page.context().close();
  });

  test("View full evidence opens the real public skill evidence page", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "show me document proof of fastapi");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    const link = page.getByTestId("evidence-view-full").first();
    await expect(link).toHaveAttribute("href", "/p/rdQygsI3lok/skills/fastapi");
    const [proofPage] = await Promise.all([
      page.context().waitForEvent("page"),
      link.click(),
    ]);
    await proofPage.waitForLoadState("domcontentloaded");
    await expect(proofPage.locator("body")).toContainText(/FastAPI/i, { timeout: 45_000 });
    await proofPage.screenshot({ path: `${SCRATCH}/shots-local/e2-skill-evidence-page.png`, fullPage: true });
    await proofPage.close();
    await page.screenshot({ path: `${SCRATCH}/shots-local/e2b-fastapi-doc-proof.png`, fullPage: true });
    await page.context().close();
  });

  test("evidence-type filter is honest: no GitHub proof of FastAPI → explicit zero, no substitution", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "show me GitHub proof of FastAPI");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("evidence-item")).toHaveCount(0);
    const unmatched = page.getByTestId("evidence-unmatched");
    await expect(unmatched).toBeVisible();
    await expect(unmatched).toContainText("FastAPI: no published proof");
    await expect(unmatched).toContainText(/no other evidence type was substituted/i);
    await page.screenshot({ path: `${SCRATCH}/shots-local/e3-honest-zero-github.png`, fullPage: true });
    await page.context().close();
  });

  test("no published NLP evidence → explicit zero, never fake proof", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "show me NLP proof");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("evidence-item")).toHaveCount(0);
    await expect(page.getByTestId("evidence-unmatched")).toContainText(
      "Natural Language Processing: no published proof",
    );
    // Any related hint must be explicitly labeled as NOT proof.
    const related = page.getByTestId("evidence-related");
    if ((await related.count()) > 0) {
      await expect(related.first()).toContainText(/not .* proof/i);
    }
    await page.screenshot({ path: `${SCRATCH}/shots-local/e4-nlp-zero.png`, fullPage: true });
    await page.context().close();
  });

  test("filter chips gate evidence retrieval (project defense chip → zero for python)", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "show me proof of fastapi");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    expect(await page.getByTestId("evidence-item").count()).toBeGreaterThanOrEqual(1);
    // Toggle the Project defense chip — FastAPI has only Document Proof.
    await page.getByTestId("search-filter-project_defense").click();
    await expect(page.getByTestId("evidence-unmatched")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("evidence-item")).toHaveCount(0);
    await page.screenshot({ path: `${SCRATCH}/shots-local/e5-chip-gates-proof.png`, fullPage: true });
    await page.context().close();
  });

  test("project intent: 'which project proves fastapi' anchors proof to the project", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "which project proves fastapi");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("interpretation-intent")).toContainText("Project proof search");
    const item = page.getByTestId("evidence-item").first();
    await expect(item).toContainText("FastAPI");
    await expect(item.getByTestId("evidence-open-project")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-local/e6-project-proof.png`, fullPage: true });
    await page.context().close();
  });

  test("View proof drawer on a verified requirement row + Save Candidate from proof card", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec2);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    // Candidate search first: requirement rows carry View proof.
    await searchFor(page, "Python and FastAPI");
    await expect(page.getByTestId("search-section-exact")).toBeVisible({ timeout: 30_000 });
    const exactCard = page.locator('[data-match-type="exact"]').first();
    const viewProof = exactCard.getByTestId("requirement-view-proof").first();
    await expect(viewProof).toBeVisible();
    await viewProof.click();
    const drawer = exactCard.getByTestId("requirement-proof-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("evidence-item").first()).toBeVisible({ timeout: 30_000 });
    await expect(drawer.getByTestId("evidence-view-full").first()).toHaveAttribute(
      "href",
      /\/p\/.+\/skills\/.+/,
    );
    await page.screenshot({ path: `${SCRATCH}/shots-local/e7-view-proof-drawer.png`, fullPage: true });

    // Now the proof-card journey: evidence search → open passport → save.
    await searchFor(page, "show me proof of fastapi");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    const group = page.getByTestId("evidence-group-card").first();
    const [passportPage] = await Promise.all([
      page.context().waitForEvent("page"),
      group.getByTestId("evidence-open-passport").click(),
    ]);
    await passportPage.waitForLoadState("domcontentloaded");
    await expect(passportPage.locator("body")).toContainText(/Work Passport/i, { timeout: 45_000 });
    await passportPage.close();
    const saveButton = group.getByTestId("search-result-save");
    if ((await saveButton.count()) > 0) {
      await saveButton.click();
      await expect(group.getByTestId("search-result-saved")).toBeVisible({ timeout: 30_000 });
    } else {
      await expect(group.getByTestId("search-result-saved")).toBeVisible();
    }
    await page.screenshot({ path: `${SCRATCH}/shots-local/e8-evidence-save.png`, fullPage: true });
    await page.context().close();
  });

  test("voice evidence query flows through the same speech pipeline (mocked)", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addCookies(cookiesFor(qa.rec1));
    await context.addInitScript(() => {
      class FakeRecognition {
        lang = "";
        continuous = false;
        interimResults = false;
        maxAlternatives = 1;
        onresult: ((e: unknown) => void) | null = null;
        onerror: ((e: unknown) => void) | null = null;
        onend: (() => void) | null = null;
        start() {
          setTimeout(() => {
            const result = Object.assign([{ transcript: "show me proof of python" }], {
              isFinal: true,
            });
            this.onresult?.({ resultIndex: 0, results: [result] });
            setTimeout(() => this.onend?.(), 150);
          }, 250);
        }
        stop() {
          this.onend?.();
        }
        abort() {}
      }
      (window as unknown as Record<string, unknown>).SpeechRecognition = FakeRecognition;
    });
    const page = await context.newPage();
    watch(page);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-mic").click();
    await expect(page.getByTestId("search-input")).toHaveValue("show me proof of python", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("interpretation-intent")).toContainText("Evidence search");
    await page.screenshot({ path: `${SCRATCH}/shots-local/e9-voice-evidence.png`, fullPage: true });
    await context.close();
  });

  test("mobile iPhone 13: proof cards usable, no horizontal overflow", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1, devices["iPhone 13"].viewport);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await searchFor(page, "show me proof of python");
    await expect(page.getByTestId("evidence-results")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("evidence-item").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SCRATCH}/shots-local/e10-mobile-evidence.png`, fullPage: true });
    await page.context().close();
  });

  test("zero console errors / zero 5xx across the suite", async () => {
    const material = consoleErrors.filter(
      (e) => !/favicon|manifest|Download the React DevTools/i.test(e),
    );
    expect(serverErrors, `5xx seen: ${serverErrors.join(", ")}`).toHaveLength(0);
    expect(material, `console errors: ${material.join(" | ")}`).toHaveLength(0);
  });
});
