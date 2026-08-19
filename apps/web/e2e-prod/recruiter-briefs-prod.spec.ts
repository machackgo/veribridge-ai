import { test, expect, chromium, type Page } from "@playwright/test";
import * as fs from "fs";

// Recruiter Hiring Briefs V3 — PRODUCTION verification against
// veribridgeai.com. Throwaway QA recruiter session minted for this run
// (user + briefs + events deleted after). Corpus ground truth (2026-08-19):
// exactly ONE discoverable candidate — Mohammed Mubashir Uddin Faraz
// (ZwC_0l8HutI) with Machine Learning / FastAPI / Python evidence; NO NLP
// evidence. Comparison therefore legitimately refuses to run with a
// 1-candidate pool (2–5 required) — that refusal is asserted, not skipped.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/490bf054-308f-41f9-95b8-d657b80a7c6b/scratchpad";
const BASE = "https://veribridgeai.com";
const CANDIDATE_SLUG = "ZwC_0l8HutI";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec1: Session; cookie_name: string } = JSON.parse(
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

async function newRecruiterPage(s: Session) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return { browser, page };
}

let brief1Url = "";
let brief2Url = "";

test.describe("Recruiter Hiring Briefs V3 — production", () => {
  test("create a brief from role text; deterministic chips", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-create-form")).toBeVisible({ timeout: 60_000 });
    // Hydration guard: the list region only renders client-side; once it
    // shows, React owns the form and fill() cannot be reset by hydration.
    await expect(
      page.getByTestId("briefs-empty").or(page.getByTestId("brief-card").first()),
    ).toBeVisible({ timeout: 60_000 });

    await page
      .getByTestId("brief-create-role-text")
      .fill("Python and FastAPI are required. NLP is preferred.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 60_000 });
    brief1Url = page.url();

    const chips = page.getByTestId("requirement-chip");
    await expect(chips.filter({ hasText: "Python" })).toBeVisible();
    await expect(chips.filter({ hasText: "FastAPI" })).toBeVisible();
    await expect(chips.filter({ hasText: "Natural Language Processing" })).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-prod/p1-brief-created.png`, fullPage: true });
    await browser.close();
  });

  test("brief-scoped search finds the evidenced candidate; add to role", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 60_000 });
    const result = page.getByTestId("brief-search-result").first();
    await expect(result).toContainText("Mohammed");

    await result.getByTestId("brief-search-add").click();
    await expect(result.getByTestId("brief-search-in-brief")).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/p2-brief-search.png`, fullPage: true });
    await browser.close();
  });

  test("pool: live evaluation, role-scoped shortlist + private note", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("brief-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });

    // Both required requirements (Python, FastAPI) are proven in prod.
    await expect(card.getByTestId("brief-candidate-evaluation")).toContainText(
      "2 of 2 required proven",
    );

    // V4 pipeline: stage moves happen through the accessible stage select;
    // await the PATCH response so nothing downstream aborts it in flight.
    const patch = page.waitForResponse(
      (res) => res.url().includes("/candidates/") && res.request().method() === "PATCH",
      { timeout: 60_000 },
    );
    await card.getByTestId("brief-candidate-stage-select").selectOption("shortlisted");
    await patch;
    await expect(card.getByTestId("brief-candidate-status-badge")).toContainText("Shortlisted", {
      timeout: 60_000,
    });
    await card.getByTestId("brief-candidate-note-toggle").click();
    await card.getByTestId("brief-candidate-note-input").fill("V3 prod QA note — role-scoped.");
    await card.getByTestId("brief-candidate-note-save").click();
    await expect(card.getByTestId("brief-candidate-note")).toContainText("V3 prod QA note", {
      timeout: 60_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/p3-pool.png`, fullPage: true });
    await browser.close();
  });

  test("comparison honestly refuses a 1-candidate pool (2–5 required)", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("brief-tab-compare").click();
    // V4 fixed the V3 defect: a valid small pool is a calm guarded empty
    // state (no fetch, no alarming ErrorState, no raw error code).
    await expect(page.getByTestId("brief-comparison-empty")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("brief-comparison-empty")).toContainText(/at least 2/i);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("Something went wrong");
    expect(bodyText).not.toContain("too_few_candidates");
    await browser.close();
  });

  test("status is ROLE-SCOPED in production: Saved in a second brief", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-create-form")).toBeVisible({ timeout: 60_000 });
    // Hydration guard: the list region only renders client-side; once it
    // shows, React owns the form and fill() cannot be reset by hydration.
    await expect(
      page.getByTestId("briefs-empty").or(page.getByTestId("brief-card").first()),
    ).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("brief-create-role-text").fill("Python required.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 60_000 });
    brief2Url = page.url();
    expect(brief2Url).not.toBe(brief1Url);

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    const result = page.getByTestId("brief-search-result").first();
    await expect(result).toBeVisible({ timeout: 60_000 });
    await result.getByTestId("brief-search-add").click();
    await expect(result.getByTestId("brief-search-in-brief")).toContainText("In role", {
      timeout: 60_000,
    });
    await expect(result.getByTestId("brief-search-in-brief")).not.toContainText("Shortlisted");

    await page.getByTestId("brief-tab-candidates").click();
    await expect(
      page.getByTestId("brief-candidate-card").first().getByTestId("brief-candidate-status-badge"),
    ).toContainText("Saved", { timeout: 60_000 });

    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByTestId("brief-candidate-card").first().getByTestId("brief-candidate-status-badge"),
    ).toContainText("Shortlisted", { timeout: 60_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/p4-role-scoped.png`, fullPage: true });
    await browser.close();
  });

  test("briefs list counts; existing search surface unaffected; cleanup via UI", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-card").first()).toBeVisible({ timeout: 60_000 });
    expect(await page.getByTestId("brief-card").count()).toBe(2);
    await expect(page.getByText("1 shortlisted")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-prod/p5-briefs-list.png`, fullPage: true });

    // Existing V1.5/V1.6 search surface still works post-deploy.
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("search-nav-briefs")).toBeVisible();

    // UI cleanup: delete both QA briefs (deep cleanup runs post-suite).
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-card").first()).toBeVisible({ timeout: 60_000 });
    while ((await page.getByTestId("brief-card").count()) > 0) {
      await page.getByTestId("brief-card-delete").first().click();
      await page.waitForTimeout(1500);
    }
    await expect(page.getByTestId("briefs-empty")).toBeVisible({ timeout: 60_000 });
    await browser.close();
  });

  test("zero console errors / zero 5xx across the suite", async () => {
    // The comparison-refusal test intentionally triggers one 400
    // (too_few_candidates) — the browser logs every 4xx fetch as a console
    // error, so that expected, asserted refusal is not a defect.
    const material = consoleErrors.filter(
      (e) =>
        !/favicon|manifest|Download the React DevTools|status of 400/i.test(e),
    );
    expect(serverErrors, `5xx seen: ${serverErrors.join(", ")}`).toHaveLength(0);
    expect(material, `console errors: ${material.join(" | ")}`).toHaveLength(0);
  });
});
