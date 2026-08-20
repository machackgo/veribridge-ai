import { test, expect, chromium, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter V5 — Talent Pools + Saved Searches — PRODUCTION verification
// against veribridgeai.com. @post-deploy: run ONLY after migration 070 +
// API + web are live.
//
// Corpus ground truth (2026-08-20): exactly ONE discoverable candidate —
// slug ZwC_0l8HutI with Python + FastAPI evidence — so "Python and FastAPI"
// yields exactly one EXACT match. Throwaway QA recruiters (v5a/v5b) minted
// for this run; every row they create is deleted post-suite (deep cleanup
// script). NO candidate-side data is ever created or modified.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-recruiter-v5/9ffc6ef1-9e52-4ce8-b287-95cc1b1fe0c7/scratchpad";
const BASE = "https://veribridgeai.com";
const API = "https://veribridge-api.onrender.com";
const CANDIDATE_SLUG = "ZwC_0l8HutI";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec1: Session; rec2: Session; cookie_name: string } = JSON.parse(
  fs.readFileSync(`${SCRATCH}/qa_prod_sessions.json`, "utf8"),
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
  const chunks: { name: string; value: string; domain: string; path: string; secure: boolean }[] = [];
  if (value.length <= MAX) {
    return [{ name: qa.cookie_name, value, domain: "veribridgeai.com", path: "/", secure: true }];
  }
  for (let i = 0; i * MAX < value.length; i++) {
    chunks.push({
      name: `${qa.cookie_name}.${i}`,
      value: value.slice(i * MAX, (i + 1) * MAX),
      domain: "veribridgeai.com",
      path: "/",
      secure: true,
    });
  }
  return chunks;
}

async function recruiterPage(
  s: Session,
  viewport: { width: number; height: number } = { width: 1440, height: 900 },
): Promise<{ browser: Browser; page: Page }> {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport });
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return { browser, page };
}

async function api(
  s: Session,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; json: any }> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${s.access_token}`,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let parsed: any = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  return { status: res.status, json: parsed };
}

const POOL_NAME = `V5 Prod QA Pool ${Date.now()}`;
const SEARCH_NAME = "V5 Prod QA — Python + FastAPI watch";
let poolUrl = "";
let poolId = "";
let savedSearchUrl = "";
let savedSearchId = "";
let candidateName = "";

test.describe("@post-deploy Recruiter V5 — production", () => {
  test("workspace nav carries Talent Pools + Saved Searches", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/workspace`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("workspace-nav-pools")).toHaveAttribute(
      "href",
      "/recruiters/pools",
      { timeout: 60_000 },
    );
    await expect(page.getByTestId("workspace-nav-savedsearches")).toHaveAttribute(
      "href",
      "/recruiters/saved-searches",
    );
    await browser.close();
  });

  test("create a Talent Pool; rename inline", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/pools`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pools-create-form")).toBeVisible({ timeout: 60_000 });
    await expect(
      page.getByTestId("pools-empty").or(page.getByTestId("pool-card").first()),
    ).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("pools-create-name").fill(POOL_NAME);
    await page.getByTestId("pools-create-submit").click();
    await page.waitForURL(/\/recruiters\/pools\/[0-9a-f-]{36}/, { timeout: 60_000 });
    poolUrl = page.url();
    poolId = poolUrl.split("/").pop()!;
    await expect(page.getByTestId("pool-title")).toHaveText(POOL_NAME, { timeout: 60_000 });
    await expect(page.getByTestId("pool-candidates-empty")).toBeVisible();

    await page.getByTestId("pool-rename").click();
    await page.getByTestId("pool-rename-input").fill(`${POOL_NAME}!`);
    await page.getByTestId("pool-rename-save").click();
    await expect(page.getByTestId("pool-title")).toHaveText(`${POOL_NAME}!`, { timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v5p-1-pool.png`, fullPage: true });
    await browser.close();
  });

  test("add the exact search match to the pool; live evidence context", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-input")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();
    const exactCard = page.locator('[data-match-type="exact"]').first();
    await expect(exactCard).toBeVisible({ timeout: 60_000 });
    candidateName = (await exactCard.locator("h3").first().innerText()).trim();

    await exactCard.getByTestId("add-to-pool").click();
    const option = exactCard.getByTestId("add-to-pool-option").filter({ hasText: POOL_NAME });
    await expect(option).toBeVisible({ timeout: 30_000 });
    await option.click();
    await expect(exactCard.getByText("Added ✓")).toBeVisible({ timeout: 30_000 });

    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await expect(card.getByTestId("pool-candidate-name")).toHaveText(candidateName);
    await expect(card.getByTestId("pool-candidate-source")).toContainText("Search");
    await expect(card.getByTestId("pool-candidate-evidence")).toContainText("skills");
    await expect(card.getByTestId("pool-candidate-open")).toHaveAttribute(
      "href",
      `/p/${CANDIDATE_SLUG}`,
    );
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v5p-2-pool-candidate.png`, fullPage: true });
    await browser.close();
  });

  test("membership is idempotent (API re-add reports already_in_pool)", async () => {
    const res = await api(qa.rec1, "POST", `/api/v1/recruiter/pools/${poolId}/candidates`, {
      candidate_slugs: [CANDIDATE_SLUG],
      source: "search",
    });
    expect(res.status).toBe(200);
    expect(res.json.added).toBe(0);
    expect(res.json.already_in_pool).toBe(1);
  });

  test("private pool note", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await card.getByTestId("pool-candidate-note-toggle").click();
    await card.getByTestId("pool-candidate-note-input").fill("V5 prod QA note — delete me");
    await card.getByTestId("pool-candidate-note-save").click();
    await expect(card.getByTestId("pool-candidate-note")).toContainText(
      "V5 prod QA note — delete me",
      { timeout: 30_000 },
    );
    await browser.close();
  });

  test("save the search; structured intent preserved on the saved search", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("search-input").fill("Python and FastAPI");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-save-search")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("search-save-search").click();
    await expect(page.getByTestId("search-save-panel")).toBeVisible();
    // Prefilled from the structured interpretation — proves the parser ran.
    expect(await page.getByTestId("search-save-name").inputValue()).toContain("Python");
    await page.getByTestId("search-save-name").fill(SEARCH_NAME);
    await page.getByTestId("search-save-submit").click();
    const success = page.getByTestId("search-save-success");
    await expect(success).toBeVisible({ timeout: 60_000 });
    await success.getByRole("link").click();
    await page.waitForURL(/\/recruiters\/saved-searches\/[0-9a-f-]{36}/, { timeout: 60_000 });
    savedSearchUrl = page.url();
    savedSearchId = savedSearchUrl.split("/").pop()!;
    await browser.close();
  });

  test("saved-search detail: evidence-aware exact match, View Proof, honest baseline", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("savedsearch-title")).toHaveText(SEARCH_NAME, {
      timeout: 60_000,
    });
    await expect(page.getByTestId("savedsearch-section-exact")).toContainText("Exact matches (1)");
    const exact = page.locator('[data-match-type="exact"]').first();
    await expect(exact).toBeVisible();
    await expect(exact.getByTestId("savedsearch-result-counts")).toContainText(
      "Satisfies all 2 required requirements",
    );
    // Evidence-grounded requirement rows with the View Proof drawer.
    const viewProof = exact.getByTestId("requirement-view-proof").first();
    await expect(viewProof).toBeVisible();
    await viewProof.click();
    await expect(exact.getByTestId("requirement-proof-drawer")).toBeVisible({ timeout: 30_000 });
    // Baseline honesty: nothing is "new" at creation; no scores anywhere.
    await expect(page.getByTestId("savedsearch-badge-new")).toHaveCount(0);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/\d+\s*%/);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v5p-3-saved-search.png`, fullPage: true });
    await browser.close();
  });

  test("discovery bookkeeping: re-evaluation never fakes 'new'", async () => {
    // Two consecutive detail loads re-evaluate live; the unchanged corpus
    // must keep new/updated at zero (last_change never bumps w/o change).
    const first = await api(qa.rec1, "GET", `/api/v1/recruiter/saved-searches/${savedSearchId}`);
    expect(first.status).toBe(200);
    const second = await api(qa.rec1, "GET", `/api/v1/recruiter/saved-searches/${savedSearchId}`);
    expect(second.status).toBe(200);
    expect(second.json.saved_search.tracking).toBe(true);
    expect(second.json.saved_search.match_count).toBe(1);
    expect(second.json.saved_search.new_count).toBe(0);
    expect(second.json.saved_search.updated_count).toBe(0);
    const annotations = second.json.annotations ?? {};
    for (const a of Object.values(annotations) as any[]) {
      expect(a.is_new).toBe(false);
      expect(a.evidence_updated).toBe(false);
    }
  });

  test("add to Hiring Brief from the saved-search result card", async () => {
    test.setTimeout(180_000);
    // A QA brief to add into (deleted in cleanup).
    const brief = await api(qa.rec1, "POST", "/api/v1/recruiter/briefs", {
      title: "V5 Prod QA Brief",
      role_text: "Python and FastAPI are required.",
    });
    expect(brief.status).toBe(200);
    const briefId = brief.json.brief.id;

    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    const exact = page.locator('[data-match-type="exact"]').first();
    await expect(exact).toBeVisible({ timeout: 60_000 });
    await exact.getByTestId("add-to-brief").click();
    const option = exact.getByTestId("add-to-brief-option").filter({ hasText: "V5 Prod QA Brief" });
    await expect(option).toBeVisible({ timeout: 30_000 });
    await option.click();
    await expect(exact.getByText("Added ✓")).toBeVisible({ timeout: 30_000 });
    await browser.close();

    const poolAdd = await api(qa.rec1, "GET", `/api/v1/recruiter/briefs/${briefId}/candidates`);
    expect(poolAdd.status).toBe(200);
    expect(poolAdd.json.total).toBe(1);
  });

  test("add to pool from the saved-search card uses source saved_search", async () => {
    // Second pool via API, add through the UI picker from the saved search.
    const created = await api(qa.rec1, "POST", "/api/v1/recruiter/pools", {
      name: "V5 Prod QA Pool B",
    });
    expect(created.status).toBe(200);
    const poolBId = created.json.pool.id;

    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    const exact = page.locator('[data-match-type="exact"]').first();
    await expect(exact).toBeVisible({ timeout: 60_000 });
    await exact.getByTestId("add-to-pool").click();
    const option = exact.getByTestId("add-to-pool-option").filter({ hasText: "V5 Prod QA Pool B" });
    await expect(option).toBeVisible({ timeout: 30_000 });
    await option.click();
    await expect(exact.getByText("Added ✓")).toBeVisible({ timeout: 30_000 });
    await browser.close();

    const detail = await api(qa.rec1, "GET", `/api/v1/recruiter/pools/${poolBId}`);
    expect(detail.status).toBe(200);
    expect(detail.json.candidates[0].source).toBe("saved_search");
  });

  test("pause shows the honest banner; resume restores tracking", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/saved-searches`, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("savedsearch-card").filter({ hasText: SEARCH_NAME });
    await expect(card).toBeVisible({ timeout: 60_000 });
    await card.getByTestId("savedsearch-pause").click();
    await expect(card.getByTestId("savedsearch-resume")).toBeVisible({ timeout: 30_000 });
    await page.goto(savedSearchUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("savedsearch-paused-banner")).toContainText(
      "Paused — not tracking new candidates",
      { timeout: 60_000 },
    );
    await page.goto(`${BASE}/recruiters/saved-searches`, { waitUntil: "domcontentloaded" });
    const card2 = page.getByTestId("savedsearch-card").filter({ hasText: SEARCH_NAME });
    await card2.getByTestId("savedsearch-resume").click();
    await expect(card2.getByTestId("savedsearch-pause")).toBeVisible({ timeout: 30_000 });
    await browser.close();
  });

  test("recruiter isolation: rec2 sees nothing of rec1's V5 data", async () => {
    const pools = await api(qa.rec2, "GET", "/api/v1/recruiter/pools");
    expect(pools.status).toBe(200);
    expect(pools.json.total).toBe(0);
    const searches = await api(qa.rec2, "GET", "/api/v1/recruiter/saved-searches");
    expect(searches.status).toBe(200);
    expect(searches.json.total).toBe(0);
    for (const path of [
      `/api/v1/recruiter/pools/${poolId}`,
      `/api/v1/recruiter/saved-searches/${savedSearchId}`,
    ]) {
      const res = await api(qa.rec2, "GET", path);
      expect(res.status, path).toBe(404);
    }
    const hijack = await api(qa.rec2, "PATCH", `/api/v1/recruiter/pools/${poolId}`, {
      name: "hijacked",
    });
    expect(hijack.status).toBe(404);
    // Anonymous requests fail closed.
    const anon = await fetch(`${API}/api/v1/recruiter/pools`);
    expect(anon.status).toBe(401);
  });

  test("no recruiter-private V5 metadata on the public passport", async () => {
    const res = await fetch(`${BASE}/p/${CANDIDATE_SLUG}`);
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).not.toContain(POOL_NAME);
    expect(html).not.toContain(SEARCH_NAME);
    expect(html).not.toContain("V5 prod QA note");
    expect(html).not.toContain("V5 Prod QA Brief");
    expect(html.toLowerCase()).not.toContain("talent pool");
    expect(html.toLowerCase()).not.toContain("saved search");
  });

  test("remove candidate from the pool", async () => {
    const { browser, page } = await recruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await card.getByTestId("pool-candidate-remove").click();
    await expect(page.getByTestId("pool-candidates-empty")).toBeVisible({ timeout: 30_000 });
    await browser.close();
  });

  test("iPhone 13: pools + saved-search detail without horizontal overflow", async () => {
    const { browser, page } = await recruiterPage(qa.rec1, { width: 390, height: 844 });
    for (const target of [`${BASE}/recruiters/pools`, savedSearchUrl]) {
      await page.goto(target, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2000);
      const overflow = await page.evaluate(
        () => document.scrollingElement!.scrollWidth - document.scrollingElement!.clientWidth,
      );
      expect(overflow, `overflow on ${target}`).toBeLessThanOrEqual(2);
    }
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v5p-4-iphone.png`, fullPage: true });
    await browser.close();
  });

  test("zero console errors / zero 5xx across the V5 journey", async () => {
    const material = consoleErrors.filter(
      (e) => !/favicon|manifest|Download the React DevTools/i.test(e),
    );
    expect(serverErrors, `5xx seen: ${serverErrors.join(", ")}`).toHaveLength(0);
    expect(material, `console errors: ${material.join(" | ")}`).toHaveLength(0);
  });
});
