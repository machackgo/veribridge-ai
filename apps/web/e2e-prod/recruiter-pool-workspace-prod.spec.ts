import { test, expect, chromium, type Page } from "@playwright/test";
import * as fs from "fs";

/**
 * Recruiter Talent Pool WORKSPACE (V6) — PRODUCTION verification against
 * veribridgeai.com. Throwaway QA recruiter sessions minted for this run
 * (users + pools + tags deleted afterwards).
 *
 * Corpus ground truth in production: exactly ONE discoverable candidate —
 * Mohammed Mubashir Uddin Faraz (ZwC_0l8HutI) with Machine Learning /
 * FastAPI / Python evidence and no NLP evidence. That is enough to prove
 * every workspace behaviour EXCEPT a multi-candidate matrix, and the
 * one-candidate case is asserted as an honest refusal (comparison needs
 * 2–5) rather than skipped.
 *
 * Requires ${QA_SCRATCH}/qa_prod_pool_sessions.json:
 *   { rec1: {email,user_id,access_token,refresh_token},
 *     rec2: {...}, cookie_name: "sb-<ref>-auth-token" }
 */

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/48d1f5f3-10e2-4efc-b5e9-7573056a23e4/scratchpad";
const BASE = "https://veribridgeai.com";
const API = "https://veribridge-api.onrender.com";
const CANDIDATE_SLUG = "ZwC_0l8HutI";

type Session = {
  email: string;
  user_id: string;
  access_token: string;
  refresh_token: string;
};
const qa: { rec1: Session; rec2: Session; cookie_name: string } = JSON.parse(
  fs.readFileSync(`${SCRATCH}/qa_prod_pool_sessions.json`, "utf8"),
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
    return [{ name: qa.cookie_name, value, domain: "veribridgeai.com", path: "/", secure: true }];
  }
  const chunks = [];
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

let poolUrl = "";
let poolId = "";

test.describe("Recruiter Talent Pool workspace V6 — production", () => {
  test("create a pool and reach its workspace", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/pools`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pools-create-name")).toBeVisible({ timeout: 60_000 });
    // Hydration guard: the list region renders client-side.
    await expect(
      page.getByTestId("pools-empty").or(page.getByTestId("pool-card").first()),
    ).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("pools-create-name").fill("V6 prod QA — Fall 2026 AI / ML");
    await page.getByTestId("pools-create-submit").click();
    await page.waitForURL(/\/recruiters\/pools\/[0-9a-f-]{36}/, { timeout: 60_000 });
    poolUrl = page.url();
    poolId = poolUrl.split("/pools/")[1].split("?")[0];

    await expect(page.getByTestId("pool-title")).toContainText("V6 prod QA");
    await expect(page.getByTestId("pool-candidates-empty")).toBeVisible({ timeout: 60_000 });
    // The empty state must offer a real next action, not just prose.
    await expect(page.getByTestId("pool-empty-saved")).toHaveAttribute(
      "href",
      "/recruiters/workspace",
    );
    await expect(page.getByTestId("pool-empty-search")).toHaveAttribute(
      "href",
      "/recruiters/search",
    );
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v6-1-pool-empty.png`, fullPage: true });
    await browser.close();
  });

  test("add the discoverable candidate; membership survives a reload", async () => {
    const res = await fetch(`${API}/api/v1/recruiter/pools/${poolId}/candidates`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${qa.rec1.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ candidate_slugs: [CANDIDATE_SLUG], source: "qr_scan" }),
    });
    expect(res.status, await res.text()).toBe(200);
    expect((await res.json()).added).toBe(1);

    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await expect(card.getByTestId("pool-candidate-name")).toContainText("Mohammed");
    // LIVE evidence context, not a snapshot.
    await expect(card.getByTestId("pool-candidate-evidence")).toBeVisible();
    await expect(card.getByTestId("pool-candidate-status")).toContainText("Review");

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card").first()).toBeVisible({ timeout: 60_000 });
    await browser.close();
  });

  test("idempotent re-add: no duplicate membership", async () => {
    const res = await fetch(`${API}/api/v1/recruiter/pools/${poolId}/candidates`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${qa.rec1.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ candidate_slugs: [CANDIDATE_SLUG] }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.added).toBe(0);
    expect(body.already_in_pool).toBe(1);

    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card")).toHaveCount(1, { timeout: 60_000 });
    await browser.close();
  });

  test("evidence filter is grounded, and its reasoning is inspectable", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card").first()).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("pool-filter-input").fill("Show candidates with FastAPI");
    await page.getByTestId("pool-filter-submit").click();
    await page.waitForURL(/[?&]q=/, { timeout: 60_000 });

    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    // WHY they matched, linking into the evidence itself.
    const match = card.getByTestId("pool-candidate-match");
    await expect(match).toBeVisible();
    await expect(match).toContainText("Matched on published evidence");
    await expect(page.getByTestId("pool-filter-understood")).toContainText("FastAPI");

    const proofLink = match.getByTestId("pool-match-proof-link").first();
    await expect(proofLink).toHaveAttribute(
      "href",
      new RegExp(`/p/${CANDIDATE_SLUG}/skills/`),
    );
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v6-2-filter.png`, fullPage: true });
    await browser.close();
  });

  test("a filter with no evidence behind it returns an honest empty state", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${poolUrl}?q=${encodeURIComponent("Rust systems programming")}`, {
      waitUntil: "domcontentloaded",
    });
    const empty = page.getByTestId("pool-filter-empty");
    await expect(empty).toBeVisible({ timeout: 60_000 });
    await expect(empty).toContainText("judgement about anyone");
    // Never an evaluative verdict about a person.
    const text = (await empty.innerText()).toLowerCase();
    expect(text).not.toContain("weak");
    expect(text).not.toContain("poor");
    expect(text).not.toContain("unqualified");
    await browser.close();
  });

  test("filter state survives reload and browser back/forward", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card").first()).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("pool-filter-input").fill("FastAPI");
    await page.getByTestId("pool-filter-submit").click();
    await page.waitForURL(/[?&]q=FastAPI/, { timeout: 60_000 });

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-filter-input")).toHaveValue("FastAPI", {
      timeout: 60_000,
    });

    await page.goBack({ waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(new RegExp(`/pools/${poolId}$`), { timeout: 60_000 });
    await page.goForward({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-filter-input")).toHaveValue("FastAPI", {
      timeout: 60_000,
    });
    await browser.close();
  });

  test("workflow status, private note and tags persist across reload", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });

    const statusPatch = page.waitForResponse(
      (r) => r.url().includes("/candidates/") && r.request().method() === "PATCH",
      { timeout: 60_000 },
    );
    await card.getByTestId("pool-candidate-status-select").selectOption("shortlisted");
    await statusPatch;
    await expect(card.getByTestId("pool-candidate-status")).toContainText("Shortlisted");

    await card.getByTestId("pool-candidate-note-toggle").click();
    const notePatch = page.waitForResponse(
      (r) => r.url().includes("/candidates/") && r.request().method() === "PATCH",
      { timeout: 60_000 },
    );
    await card
      .getByTestId("pool-candidate-note-input")
      .fill("V6 prod QA — private note, pool-scoped.");
    await card.getByTestId("pool-candidate-note-save").click();
    await notePatch;

    await card.getByTestId("pool-candidate-tags-toggle").click();
    const tagPatch = page.waitForResponse(
      (r) => r.url().includes("/candidates/") && r.request().method() === "PATCH",
      { timeout: 60_000 },
    );
    await card.getByTestId("pool-candidate-tag-input").fill("Career Fair");
    await card.getByTestId("pool-candidate-tag-add").click();
    await tagPatch;

    await page.reload({ waitUntil: "domcontentloaded" });
    const reloaded = page.getByTestId("pool-candidate-card").first();
    await expect(reloaded.getByTestId("pool-candidate-status")).toContainText("Shortlisted", {
      timeout: 60_000,
    });
    await expect(reloaded.getByTestId("pool-candidate-note")).toContainText("private note");
    await expect(reloaded.getByTestId("pool-candidate-tags")).toContainText("Career Fair");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v6-3-workflow.png`, fullPage: true });
    await browser.close();
  });

  test("recruiter metadata filters work against real stored data", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${poolUrl}?status=shortlisted`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card")).toHaveCount(1, { timeout: 60_000 });

    await page.goto(`${poolUrl}?status=pass`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-filter-empty")).toBeVisible({ timeout: 60_000 });

    await page.goto(`${poolUrl}?tags=${encodeURIComponent("Career Fair")}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByTestId("pool-candidate-card")).toHaveCount(1, { timeout: 60_000 });
    await browser.close();
  });

  test("comparison honestly refuses a one-candidate pool", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("pool-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });

    await card.getByTestId("pool-candidate-select").check();
    await page.waitForURL(/[?&]selected=/, { timeout: 60_000 });
    // One selected candidate is not comparable — the control stays disabled
    // rather than producing a single-column "comparison".
    await expect(page.getByTestId("pool-compare")).toBeDisabled();
    await expect(page.getByTestId("pool-compare-bar")).toContainText("1 selected");

    // …and the deep link says why instead of erroring.
    await page.goto(`${BASE}/recruiters/pools/${poolId}/compare?ids=${qa.rec1.user_id}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByTestId("comparison-too-few")).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v6-4-compare-refusal.png`, fullPage: true });
    await browser.close();
  });

  test("comparison API refuses candidates outside the pool", async () => {
    const res = await fetch(`${API}/api/v1/recruiter/pools/${poolId}/comparison`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${qa.rec1.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        student_user_ids: [qa.rec1.user_id, "00000000-0000-4000-8000-000000000999"],
      }),
    });
    expect(res.status).toBe(400);
    expect((await res.json()).detail.code).toBe("candidate_not_found");
  });

  test("recruiter isolation: every verb refuses recruiter 2", async () => {
    const auth = {
      Authorization: `Bearer ${qa.rec2.access_token}`,
      "Content-Type": "application/json",
    };
    const attempts: [string, string, unknown?][] = [
      ["GET", `/api/v1/recruiter/pools/${poolId}`],
      ["GET", `/api/v1/recruiter/pools/${poolId}/filter`],
      ["PATCH", `/api/v1/recruiter/pools/${poolId}`, { name: "hijacked" }],
      ["DELETE", `/api/v1/recruiter/pools/${poolId}`],
      ["POST", `/api/v1/recruiter/pools/${poolId}/candidates`, { candidate_slugs: [CANDIDATE_SLUG] }],
      ["POST", `/api/v1/recruiter/pools/${poolId}/comparison`, { student_user_ids: ["a", "b"] }],
    ];
    for (const [method, path, body] of attempts) {
      const res = await fetch(`${API}${path}`, {
        method,
        headers: auth,
        body: body ? JSON.stringify(body) : undefined,
      });
      expect(res.status, `${method} ${path}`).toBe(404);
    }

    // Recruiter 2 sees none of recruiter 1's private tag vocabulary.
    const tags = await fetch(`${API}/api/v1/recruiter/pools/tags`, { headers: auth });
    expect(tags.status).toBe(200);
    expect((await tags.json()).tags).toEqual([]);

    // Recruiter 1's pool is untouched.
    const mine = await fetch(`${API}/api/v1/recruiter/pools/${poolId}`, {
      headers: { Authorization: `Bearer ${qa.rec1.access_token}` },
    });
    expect(mine.status).toBe(200);
    const body = await mine.json();
    expect(body.pool.name).toContain("V6 prod QA");
    expect(body.total).toBe(1);
  });

  test("unauthenticated access is refused", async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/login/, { timeout: 60_000 });
    await browser.close();

    const res = await fetch(`${API}/api/v1/recruiter/pools/${poolId}`);
    expect(res.status).toBe(401);
  });

  test("malformed ids are not found rather than a server error", async () => {
    const headers = { Authorization: `Bearer ${qa.rec1.access_token}` };
    for (const path of [
      "/api/v1/recruiter/pools/not-a-uuid",
      "/api/v1/recruiter/pools/not-a-uuid/filter",
    ]) {
      const res = await fetch(`${API}${path}`, { headers });
      expect(res.status, path).toBe(404);
    }
  });

  test("mobile viewport stays usable and never scrolls horizontally", async () => {
    const browser = await chromium.launch();
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.addCookies(cookiesFor(qa.rec1));
    const page = await context.newPage();
    watch(page);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-candidate-card").first()).toBeVisible({ timeout: 60_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v6-5-mobile.png`, fullPage: true });
    await browser.close();
  });

  test("deleting the pool leaves the candidate and the tag vocabulary alone", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(poolUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("pool-delete")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("pool-delete").click();
    await expect(page.getByTestId("pool-delete-confirm")).toBeVisible();
    await page.getByTestId("pool-delete").click();
    await page.waitForURL(/\/recruiters\/pools$/, { timeout: 60_000 });
    await browser.close();

    // The candidate's public passport is untouched by any of this.
    const passport = await fetch(`${API}/api/v1/public/p/${CANDIDATE_SLUG}`);
    expect(passport.status).toBe(200);

    // Tags are recruiter-scoped, so they outlive the pool.
    const tags = await fetch(`${API}/api/v1/recruiter/pools/tags`, {
      headers: { Authorization: `Bearer ${qa.rec1.access_token}` },
    });
    expect((await tags.json()).tags.length).toBeGreaterThan(0);
  });

  test("no unexplained console or server errors across the run", async () => {
    const ignorable = (m: string) =>
      m.includes("favicon") || m.includes("Download the React DevTools");
    expect(consoleErrors.filter((m) => !ignorable(m))).toEqual([]);
    expect(serverErrors).toEqual([]);
  });
});
