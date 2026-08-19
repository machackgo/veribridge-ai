import { test, expect, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter Hiring Briefs V3 — LOCAL rig verification
// (docker e2e-supabase :54321 + local API :8000 + web :3000).
//
// Journey: create a brief from role text → find candidates with the brief's
// stored requirements → build the role-scoped pool → shortlist + private
// note → live evidence comparison matrix → prove status is ROLE-SCOPED
// (same candidate merely Saved in a second brief).

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/490bf054-308f-41f9-95b8-d657b80a7c6b/scratchpad";
const BASE = "http://localhost:3000";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec3: Session; cookie_name: string } = JSON.parse(
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

async function recruiterPage(browser: Browser, s: Session) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return page;
}

let brief1Url = "";
let brief2Url = "";
let shortlistedName = "";

test.describe("Recruiter Hiring Briefs V3 — local rig", () => {
  test("create a brief from role text; deterministic requirement chips", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-create-form")).toBeVisible({ timeout: 45_000 });
    // Hydration guard: the list region only renders client-side; once it
    // shows, React owns the form and fill() cannot be reset by hydration.
    await expect(
      page.getByTestId("briefs-empty").or(page.getByTestId("brief-card").first()),
    ).toBeVisible({ timeout: 45_000 });

    await page
      .getByTestId("brief-create-role-text")
      .fill("Entry-level engineer. Python and FastAPI are required. React is preferred.");
    await page.getByTestId("brief-create-submit").click();

    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 45_000 });
    brief1Url = page.url();
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 45_000 });
    const chips = page.getByTestId("requirement-chip");
    await expect(chips.filter({ hasText: "Python" })).toBeVisible();
    await expect(chips.filter({ hasText: "FastAPI" })).toBeVisible();
    await expect(chips.filter({ hasText: "React" })).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-local/b1-brief-created.png`, fullPage: true });
    await page.context().close();
  });

  test("find candidates with the brief's stored plan; add two to the role", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 30_000 });
    const results = page.getByTestId("brief-search-result");
    expect(await results.count()).toBeGreaterThanOrEqual(2);

    shortlistedName = (await results.first().locator("h3").innerText()).trim();

    // Add the top two results to this role.
    await page.getByTestId("brief-search-add").first().click();
    await expect(page.getByTestId("brief-search-in-brief").first()).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("brief-search-add").first().click();
    await expect(page.getByTestId("brief-search-in-brief").nth(1)).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/b2-brief-search.png`, fullPage: true });
    await page.context().close();
  });

  test("role pool: live evaluation, role-scoped shortlist + private note", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-candidate-card").first()).toBeVisible({ timeout: 45_000 });
    expect(await page.getByTestId("brief-candidate-card").count()).toBe(2);

    // Live, transparent evaluation — counts, never a score.
    await expect(page.getByTestId("brief-candidate-evaluation").first()).toContainText(
      /of \d+ required proven/,
    );

    const card = page
      .getByTestId("brief-candidate-card")
      .filter({ hasText: shortlistedName })
      .first();
    // V4 pipeline: stage moves happen through the accessible stage select
    // (the V3 status pills were replaced by the 9-stage <select>), and the
    // card moves into its stage section — re-scope through the section so
    // an identically-named sibling card can never be matched instead.
    await card.getByTestId("brief-candidate-stage-select").selectOption("shortlisted");
    const shortlistedCard = page
      .getByTestId("brief-stage-section-shortlisted")
      .getByTestId("brief-candidate-card")
      .first();
    await expect(shortlistedCard.getByTestId("brief-candidate-status-badge")).toContainText(
      "Shortlisted",
      { timeout: 30_000 },
    );

    await shortlistedCard.getByTestId("brief-candidate-note-toggle").click();
    await shortlistedCard.getByTestId("brief-candidate-note-input").fill("Strong for this role — verified FastAPI evidence.");
    await shortlistedCard.getByTestId("brief-candidate-note-save").click();
    await expect(shortlistedCard.getByTestId("brief-candidate-note")).toContainText("Strong for this role", {
      timeout: 30_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shots-local/b3-pool-shortlist.png`, fullPage: true });
    await page.context().close();
  });

  test("comparison: live evidence matrix, closed cell states, no scores", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("brief-tab-compare").click();
    const matrix = page.getByTestId("comparison-matrix");
    await expect(matrix).toBeVisible({ timeout: 45_000 });

    // Both pool candidates evaluate live from published evidence.
    expect(await page.getByTestId("comparison-column-name").count()).toBe(2);
    expect(await page.getByTestId("matrix-cell-proven").count()).toBeGreaterThanOrEqual(1);

    // Proven cells deep-link to the public skill report.
    const proofHref = await page.getByTestId("matrix-cell-proof-link").first().getAttribute("href");
    expect(proofHref).toMatch(/^\/p\/.+\/skills\/.+/);

    // Role-scoped status travels into the matrix header; transparent counts only.
    await expect(matrix).toContainText("Shortlisted");
    await expect(matrix).toContainText(/of \d+ required proven/);
    expect((await matrix.innerText()).includes("%")).toBe(false);
    await page.screenshot({ path: `${SCRATCH}/shots-local/b4-comparison.png`, fullPage: true });
    await page.context().close();
  });

  test("status is ROLE-SCOPED: same candidate is merely Saved in a second brief", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-create-form")).toBeVisible({ timeout: 45_000 });
    // Hydration guard: the list region only renders client-side; once it
    // shows, React owns the form and fill() cannot be reset by hydration.
    await expect(
      page.getByTestId("briefs-empty").or(page.getByTestId("brief-card").first()),
    ).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("brief-create-role-text").fill("Python required.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 45_000 });
    brief2Url = page.url();
    expect(brief2Url).not.toBe(brief1Url);

    // Add the SAME candidate (shortlisted in brief 1) to brief 2 via search.
    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 30_000 });
    const targetResult = page
      .getByTestId("brief-search-result")
      .filter({ hasText: shortlistedName })
      .first();
    await targetResult.getByTestId("brief-search-add").click();
    // Freshly added to THIS brief: role-scoped status is Saved, not the
    // other brief's Shortlisted.
    await expect(targetResult.getByTestId("brief-search-in-brief")).toContainText("In role", {
      timeout: 30_000,
    });
    await expect(targetResult.getByTestId("brief-search-in-brief")).not.toContainText("Shortlisted");

    await page.getByTestId("brief-tab-candidates").click();
    // V4 pipeline sections make the role-scoped stage explicit: the fresh
    // add sits in the Saved section of THIS brief.
    const card2 = page
      .getByTestId("brief-stage-section-saved")
      .getByTestId("brief-candidate-card")
      .filter({ hasText: shortlistedName })
      .first();
    await expect(card2.getByTestId("brief-candidate-status-badge")).toContainText("Saved", {
      timeout: 45_000,
    });

    // Brief 1 still shows Shortlisted — no global status anywhere.
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    const card1 = page
      .getByTestId("brief-stage-section-shortlisted")
      .getByTestId("brief-candidate-card")
      .filter({ hasText: shortlistedName })
      .first();
    await expect(card1.getByTestId("brief-candidate-status-badge")).toContainText("Shortlisted", {
      timeout: 45_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shots-local/b5-role-scoped.png`, fullPage: true });
    await page.context().close();
  });

  test("briefs list carries role-scoped counts; navs link the surfaces", async ({ browser }) => {
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-card").first()).toBeVisible({ timeout: 45_000 });
    expect(await page.getByTestId("brief-card").count()).toBe(2);
    await expect(page.getByText("1 shortlisted")).toBeVisible();
    await expect(page.getByText("2 candidates")).toBeVisible();

    await page.screenshot({ path: `${SCRATCH}/shots-local/b6-briefs-list.png`, fullPage: true });

    // Workspace and search navs both reach Hiring Briefs. Wait for each
    // page's hydration-dependent content before interacting further —
    // screenshots/actions on a pre-hydration page corrupt the style attr
    // Playwright rewrites for caret hiding and fail React hydration.
    await page.goto(`${BASE}/recruiters/workspace`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("workspace-empty")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("workspace-nav-briefs")).toBeVisible();
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("search-nav-briefs")).toBeVisible();
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
