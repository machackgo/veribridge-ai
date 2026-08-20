import { test, expect, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter V5 — Talent Pools + Saved Searches + evidence-aware discovery.
// LOCAL rig verification (docker e2e-supabase :54321 + API :8000 + web :3000).
//
// Journey: shared 5-item nav → create a Talent Pool → add a search result
// to it (evidence context stays live) → save the search from the search
// page → saved-search detail (exact section, requirement rows, honest
// annotations machinery) → pause/resume → private pool note → deleting the
// saved search never touches the pool → iPhone-13 layout sanity.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-recruiter-v5/9ffc6ef1-9e52-4ce8-b287-95cc1b1fe0c7/scratchpad";
const BASE = "http://localhost:3000";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec1: Session; cookie_name: string } = JSON.parse(
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
  viewport: { width: number; height: number } = { width: 1440, height: 900 },
) {
  const context = await browser.newContext({ viewport });
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return page;
}

const POOL_NAME = `V5 QA Pool ${Date.now()}`;
let poolUrl = "";
let savedSearchUrl = "";
let addedCandidateName = "";

test.describe("Recruiter V5 — Talent Pools + Saved Searches (local rig)", () => {
  test("shared nav carries all five sections on the workspace", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/workspace`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("workspace-nav-search")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("workspace-nav-briefs")).toBeVisible();
    await expect(page.getByTestId("workspace-nav-pools")).toHaveAttribute(
      "href",
      "/recruiters/pools",
    );
    await expect(page.getByTestId("workspace-nav-savedsearches")).toHaveAttribute(
      "href",
      "/recruiters/saved-searches",
    );
    await page.context().close();
  });

  test("create a Talent Pool; empty state; inline rename", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/pools`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pools-create-form")).toBeVisible({ timeout: 45_000 });
    // Hydration guard: wait for the client-rendered list region.
    await expect(
      page.getByTestId("pools-empty").or(page.getByTestId("pool-card").first()),
    ).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("pools-create-name").fill(POOL_NAME);
    await page.getByTestId("pools-create-description").fill("V5 acceptance pool");
    await page.getByTestId("pools-create-submit").click();

    await page.waitForURL(/\/recruiters\/pools\/[0-9a-f-]{36}/, { timeout: 45_000 });
    poolUrl = page.url();
    await expect(page.getByTestId("pool-title")).toHaveText(POOL_NAME, { timeout: 45_000 });
    await expect(page.getByTestId("pool-candidates-empty")).toBeVisible();

    await page.getByTestId("pool-rename").click();
    await page.getByTestId("pool-rename-input").fill(`${POOL_NAME} (renamed)`);
    await page.getByTestId("pool-rename-save").click();
    await expect(page.getByTestId("pool-title")).toHaveText(`${POOL_NAME} (renamed)`, {
      timeout: 30_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-1-pool-created.png`, fullPage: true });
    await page.context().close();
  });

  test("add a search result to the pool; live evidence context in the pool", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-input")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-section-exact")).toBeVisible({ timeout: 30_000 });

    const exactCard = page.locator('[data-match-type="exact"]').first();
    addedCandidateName = (await exactCard.locator("h3").first().innerText()).trim();

    await exactCard.getByTestId("add-to-pool").click();
    const option = exactCard
      .getByTestId("add-to-pool-option")
      .filter({ hasText: POOL_NAME });
    await expect(option).toBeVisible({ timeout: 30_000 });
    await option.click();
    await expect(exactCard.getByText("Added ✓")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-2-added-to-pool.png`, fullPage: true });

    // The pool now shows the candidate with LIVE evidence context.
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 45_000 });
    await expect(card.getByTestId("pool-candidate-name")).toHaveText(addedCandidateName);
    await expect(card.getByTestId("pool-candidate-source")).toContainText("Search");
    await expect(card.getByTestId("pool-candidate-evidence")).toContainText("skills");
    await expect(card.getByTestId("pool-candidate-open")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-3-pool-candidate.png`, fullPage: true });
    await page.context().close();
  });

  test("private pool note (recruiter-only)", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 45_000 });
    await card.getByTestId("pool-candidate-note-toggle").click();
    await card.getByTestId("pool-candidate-note-input").fill("V5 QA — strong FastAPI evidence");
    await card.getByTestId("pool-candidate-note-save").click();
    await expect(card.getByTestId("pool-candidate-note")).toContainText(
      "V5 QA — strong FastAPI evidence",
      { timeout: 30_000 },
    );
    await page.context().close();
  });

  test("save the search from the search page (honest tracked summary)", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-save-search")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("search-save-search").click();

    await expect(page.getByTestId("search-save-panel")).toBeVisible();
    const prefilled = await page.getByTestId("search-save-name").inputValue();
    expect(prefilled.length).toBeGreaterThan(0);
    await page.getByTestId("search-save-name").fill("V5 QA — Python + FastAPI watch");
    await page.getByTestId("search-save-submit").click();

    const success = page.getByTestId("search-save-success");
    await expect(success).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-4-search-saved.png`, fullPage: true });
    await success.getByRole("link").click();
    await page.waitForURL(/\/recruiters\/saved-searches\/[0-9a-f-]{36}/, { timeout: 45_000 });
    savedSearchUrl = page.url();
    await page.context().close();
  });

  test("saved-search detail: exact section, requirement rows, no scores", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("savedsearch-title")).toHaveText(
      "V5 QA — Python + FastAPI watch",
      { timeout: 45_000 },
    );
    await expect(page.getByTestId("savedsearch-section-exact")).toContainText("Exact matches");
    const exact = page.locator('[data-match-type="exact"]').first();
    await expect(exact).toBeVisible({ timeout: 30_000 });
    await expect(exact.getByTestId("savedsearch-result-counts")).toContainText(
      "Satisfies all",
    );
    // Baseline honesty: at creation nothing is "new".
    await expect(page.getByTestId("savedsearch-badge-new")).toHaveCount(0);
    // Language invariant: no percentages anywhere on the page.
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/\d+\s*%/);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-5-saved-search-detail.png`, fullPage: true });
    await page.context().close();
  });

  test("list shows the saved search; pause → paused banner; resume", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/saved-searches`, { waitUntil: "domcontentloaded" });
    const card = page
      .getByTestId("savedsearch-card")
      .filter({ hasText: "V5 QA — Python + FastAPI watch" });
    await expect(card).toBeVisible({ timeout: 45_000 });
    await expect(card).toContainText("Checked");

    await card.getByTestId("savedsearch-pause").click();
    await expect(card.getByTestId("savedsearch-resume")).toBeVisible({ timeout: 30_000 });

    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("savedsearch-paused-banner")).toContainText(
      "Paused — not tracking new candidates",
      { timeout: 45_000 },
    );

    await page.goto(`${BASE}/recruiters/saved-searches`, { waitUntil: "domcontentloaded" });
    const card2 = page
      .getByTestId("savedsearch-card")
      .filter({ hasText: "V5 QA — Python + FastAPI watch" });
    await card2.getByTestId("savedsearch-resume").click();
    await expect(card2.getByTestId("savedsearch-pause")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-6-saved-search-list.png`, fullPage: true });
    await page.context().close();
  });

  test("deleting the saved search never touches the pool", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1);
    await page.goto(`${BASE}/recruiters/saved-searches`, { waitUntil: "domcontentloaded" });
    const card = page
      .getByTestId("savedsearch-card")
      .filter({ hasText: "V5 QA — Python + FastAPI watch" });
    await expect(card).toBeVisible({ timeout: 45_000 });
    await card.getByTestId("savedsearch-delete").click();
    await expect(page.getByTestId("savedsearch-delete-confirm")).toContainText(
      "never removes candidates, Talent Pools, or Hiring Briefs",
    );
    await card.getByTestId("savedsearch-delete").click();
    await expect(card).toHaveCount(0, { timeout: 30_000 });

    // The pool and its candidate are intact.
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const poolCard = page.getByTestId("pool-candidate-card").first();
    await expect(poolCard).toBeVisible({ timeout: 45_000 });
    await expect(poolCard.getByTestId("pool-candidate-name")).toHaveText(addedCandidateName);
    await page.context().close();
  });

  test("iPhone 13: pools + saved searches render without horizontal overflow", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec1, { width: 390, height: 844 });
    for (const path of ["/recruiters/pools", poolUrl, "/recruiters/saved-searches"]) {
      const target = path.startsWith("http") ? path : `${BASE}${path}`;
      await page.goto(target, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);
      const overflow = await page.evaluate(
        () => document.scrollingElement!.scrollWidth - document.scrollingElement!.clientWidth,
      );
      expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(2);
    }
    await page.screenshot({ path: `${SCRATCH}/shots-local/v5-7-iphone-pool.png`, fullPage: true });
    await page.context().close();
  });

  test("no console errors, no 5xx across the journey", async () => {
    const realConsoleErrors = consoleErrors.filter(
      (e) => !e.includes("Download the React DevTools"),
    );
    expect(serverErrors, serverErrors.join("\n")).toHaveLength(0);
    expect(realConsoleErrors, realConsoleErrors.join("\n")).toHaveLength(0);
  });
});
