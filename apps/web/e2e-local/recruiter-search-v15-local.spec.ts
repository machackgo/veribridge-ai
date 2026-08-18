import { test, expect, chromium, devices, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter Search Intelligence V1.5 — LOCAL rig verification
// (docker e2e-supabase :54321 + local API :8000 + web :3000).

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/0bd171a1-f6dc-47a8-9e49-72e5dbbb6767/scratchpad";
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
  const chunks: { name: string; value: string; domain: string; path: string }[] = [];
  if (value.length <= MAX) {
    return [{ name: qa.cookie_name, value, domain: "localhost", path: "/" }];
  }
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
  init?: (page: Page) => Promise<void>,
) {
  const context = await browser.newContext(
    viewport ? { viewport } : { viewport: { width: 1440, height: 900 } },
  );
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  if (init) await init(page);
  return page;
}

test.describe("Recruiter Search V1.5 — local rig", () => {
  test("browse: population renders, no interpretation panel, examples shown", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    expect(await page.getByTestId("search-result-card").count()).toBeGreaterThanOrEqual(4);
    await expect(page.getByTestId("search-interpretation")).toHaveCount(0);
    await expect(page.getByTestId("search-examples")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-local/1-browse.png`, fullPage: true });
    await page.context().close();
  });

  test("structured AND query: exact vs close sections with requirement checklists", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();

    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 30_000 });
    await expect(interp).toContainText("Understood as:");
    await expect(interp).toContainText("Python");
    await expect(interp).toContainText("FastAPI");

    // Exactly one rig candidate has FastAPI evidence → 1 exact; the
    // Python+React candidates are close with FastAPI explicitly missing.
    await expect(page.getByTestId("search-section-exact")).toContainText("Exact matches (1)");
    await expect(page.getByTestId("search-section-close")).toBeVisible();
    const closeCard = page.locator('[data-match-type="close"]').first();
    await expect(closeCard.getByTestId("search-result-requirements")).toContainText(
      "No published FastAPI evidence",
    );
    const exactCard = page.locator('[data-match-type="exact"]').first();
    await expect(exactCard.getByTestId("search-result-requirements")).toContainText("FastAPI");
    await expect(page.getByTestId("search-result-count")).toContainText("1 exact match");
    await page.screenshot({ path: `${SCRATCH}/shots-local/2-exact-close.png`, fullPage: true });
    await page.context().close();
  });

  test("NLP requirement is independent: no NLP evidence in rig → honest zero", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-input").fill("NLP");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-empty")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/3-nlp-zero.png`, fullPage: true });
    await page.context().close();
  });

  test("natural language + evidence expectation classifies correctly", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page
      .getByTestId("search-input")
      .fill("Find me a candidate with FastAPI who has deployed a live site");
    await page.getByTestId("search-submit").click();
    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 30_000 });
    await expect(interp).toContainText("FastAPI");
    await expect(interp).toContainText("Live deployed project");
    // The FastAPI candidate has no live site → close, with the gap stated.
    const closeCard = page.locator('[data-match-type="close"]').first();
    await expect(closeCard.getByTestId("search-result-requirements")).toContainText(
      /No published live deployed project/i,
    );
    await page.screenshot({ path: `${SCRATCH}/shots-local/4-nl-evidence.png`, fullPage: true });
    await page.context().close();
  });

  test("voice search: mic → listening → transcript → auto search (mocked SpeechRecognition)", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addCookies(cookiesFor(qa.rec1));
    // Deterministic fake SpeechRecognition: emits a final transcript shortly
    // after start(). Real-microphone audio requires the manual test pass.
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
            const result = Object.assign([{ transcript: "python and fastapi" }], {
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

    await expect(page.getByTestId("search-mic")).toBeVisible();
    await page.getByTestId("search-mic").click();
    await expect(page.getByTestId("search-listening")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-local/5-listening.png` });

    // Transcript lands visibly in the editable box, then searches itself.
    await expect(page.getByTestId("search-input")).toHaveValue("python and fastapi", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("search-result-count")).toContainText("exact match", {
      timeout: 30_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shots-local/6-voice-results.png`, fullPage: true });
    await context.close();
  });

  test("journey: search → open passport → save → workspace", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec2);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-input").fill("Python");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 30_000 });

    const firstCard = page.getByTestId("search-result-card").first();
    const href = await firstCard.getByTestId("search-result-open").getAttribute("href");
    const [passportPage] = await Promise.all([
      page.context().waitForEvent("page"),
      firstCard.getByTestId("search-result-open").click(),
    ]);
    await passportPage.waitForLoadState("domcontentloaded");
    await expect(passportPage.locator("body")).toContainText(/Work Passport/i, { timeout: 45_000 });
    await passportPage.close();

    await firstCard.getByTestId("search-result-save").click();
    await expect(firstCard.getByTestId("search-result-saved")).toBeVisible({ timeout: 30_000 });

    await page.getByTestId("search-nav-workspace").click();
    await page.waitForURL(/\/recruiters\/workspace/);
    await expect(page.getByTestId("workspace-candidate-card").first()).toBeVisible({ timeout: 45_000 });
    const meta = (await page.getByTestId("workspace-candidate-meta").allInnerTexts()).join(" ");
    expect(meta).toContain("Search");
    expect(href).toBeTruthy();
    await page.screenshot({ path: `${SCRATCH}/shots-local/7-workspace.png`, fullPage: true });
    await page.context().close();
  });

  test("mobile iPhone 13: sections + mic usable, no horizontal overflow", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1, devices["iPhone 13"].viewport);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("search-section-close")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SCRATCH}/shots-local/8-mobile.png`, fullPage: true });
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
