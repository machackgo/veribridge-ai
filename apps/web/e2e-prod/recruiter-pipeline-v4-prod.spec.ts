import { test, expect, chromium, type Page } from "@playwright/test";
import * as fs from "fs";

// Recruiter Pipeline + Interview Workspace V4 — PRODUCTION verification
// against veribridgeai.com. @post-deploy: the orchestrator runs this ONLY
// after migration 069 + API + web are live (run with
// `--grep @post-deploy`); it will 404 on the interview routes before then.
//
// Throwaway QA recruiter session minted for this run (user + briefs +
// events deleted after; brief deletion cascades interview/marks/activity
// rows via 069 FKs — deep cleanup runs post-suite). Corpus ground truth
// (2026-08-19): exactly ONE discoverable candidate — Mohammed Mubashir
// Uddin Faraz (ZwC_0l8HutI) with Python + FastAPI evidence and NO NLP
// evidence, so an "NLP required" brief guarantees both a proven checklist
// row (proof deep link) and an honest gap row. Production runs with no
// LLM provider: generated questions must be the deterministic set with
// honest provenance.
//
// CONTRACT TESTIDS (V4_ARCHITECTURE_AUDIT.md; reconcile at integration):
//   brief-stage-bar, brief-stage-pill-{status}, brief-stage-section-{status},
//   brief-candidate-stage-select (option values = raw status keys),
//   brief-candidate-interview-link, brief-comparison-empty,
//   interview-workspace, interview-summary, interview-coverage,
//   interview-checklist, interview-checklist-row,
//   interview-questions, interview-generate-questions, interview-question-card,
//   interview-notes, interview-prep-notes, interview-notes-input,
//   interview-notes-status (/Saved/), interview-decision ("Hired" button),
//   search-residual-terms — plus the existing V3 brief/search testids.

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

let briefUrl = "";
let interviewUrl = "";

test.describe("Recruiter Pipeline V4 — production @post-deploy", () => {
  test("create brief; brief-scoped search; add the ONE evidenced candidate", async () => {
    test.setTimeout(180_000);
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
      .fill("Python and FastAPI are required. NLP is required.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 60_000 });
    briefUrl = page.url();

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 60_000 });
    const result = page.getByTestId("brief-search-result").first();
    await expect(result).toContainText("Mohammed");
    await result.getByTestId("brief-search-add").click();
    await expect(result.getByTestId("brief-search-in-brief")).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-01-brief.png`, fullPage: true });
    await browser.close();
  });

  test("compare tab with 1 candidate: calm empty state (V3 defect fixed in prod)", async () => {
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(briefUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("brief-tab-compare").click();
    await expect(page.getByTestId("brief-comparison-empty")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("brief-comparison-empty")).toContainText(/at least 2/i);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("Something went wrong");
    expect(bodyText).not.toContain("too_few_candidates");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-02-compare-empty.png`, fullPage: true });
    await browser.close();
  });

  test("stage walk to interview via the pipeline; counts + reload persistence", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(briefUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("brief-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("brief-stage-bar")).toBeVisible();
    await expect(page.getByTestId("brief-stage-pill-saved")).toContainText("1");

    // Stage moves render optimistically — await each PATCH response before
    // moving on so a navigation never aborts an in-flight request (an abort
    // logs "Failed to fetch" even though the server processed it).
    const select = card.getByTestId("brief-candidate-stage-select");
    const patchDone = () =>
      page.waitForResponse(
        (res) => res.url().includes("/candidates/") && res.request().method() === "PATCH",
        { timeout: 60_000 },
      );
    let patch = patchDone();
    await select.selectOption("reviewing");
    await patch;
    await expect(page.getByTestId("brief-stage-pill-reviewing")).toContainText("1", {
      timeout: 60_000,
    });
    patch = patchDone();
    await select.selectOption("interview");
    await patch;
    await expect(page.getByTestId("brief-stage-pill-interview")).toContainText("1", {
      timeout: 60_000,
    });
    await expect(page.getByTestId("brief-stage-section-interview")).toContainText("Mohammed");

    await page.reload({ waitUntil: "domcontentloaded" });
    const cardAfter = page.getByTestId("brief-candidate-card").first();
    await expect(cardAfter).toBeVisible({ timeout: 60_000 });
    await expect(cardAfter.getByTestId("brief-candidate-stage-select")).toHaveValue("interview");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-03-stage-walk.png`, fullPage: true });
    await browser.close();
  });

  test("interview workspace: checklist truth, proof deep link, honest gap, deterministic questions", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(briefUrl, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("brief-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await card.getByTestId("brief-candidate-interview-link").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}\/interview\//, { timeout: 60_000 });
    interviewUrl = page.url();

    const workspace = page.getByTestId("interview-workspace");
    await expect(workspace).toBeVisible({ timeout: 60_000 });
    await expect(workspace).toContainText("Mohammed");
    await expect(page.getByTestId("interview-summary")).toBeVisible();

    // Deterministic checklist: proven rows deep-link to the REAL public
    // skill report of the known prod candidate; the NLP gap row uses the
    // honest language contract.
    const checklist = page.getByTestId("interview-checklist");
    await expect(checklist).toBeVisible();
    const proofLink = checklist.locator('a[href^="/p/"]').first();
    await expect(proofLink).toBeVisible();
    expect(await proofLink.getAttribute("href")).toMatch(
      new RegExp(`^/p/${CANDIDATE_SLUG}/skills/.+`),
    );
    await expect(
      page.getByTestId("interview-checklist-row").filter({ hasText: "No published" }).first(),
    ).toBeVisible();

    await expect(page.getByTestId("interview-coverage")).toContainText(/of \d+/);

    // Questions: prod has no LLM provider — the deterministic set must
    // appear with honest provenance, still grounded per requirement.
    await page.getByTestId("interview-generate-questions").click();
    const cards = page.getByTestId("interview-question-card");
    await expect(cards.first()).toBeVisible({ timeout: 60_000 });
    await expect(cards.first()).toContainText(/Evidence-backed|Gap to verify/);
    await expect(page.getByTestId("interview-questions")).toContainText(/advisory only/i);

    const text = await workspace.innerText();
    expect(text.includes("%")).toBe(false);
    expect(text).not.toContain("doesn't know");
    expect(text).not.toContain("does not know");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-04-interview.png`, fullPage: true });
    await browser.close();
  });

  test("notes autosave persists; decision Hired lands the candidate in Hired", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-workspace")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("interview-notes")).toBeVisible();

    await page.getByTestId("interview-prep-notes").fill("V4 prod QA prep note.");
    await page.getByTestId("interview-prep-notes").blur();
    await page.getByTestId("interview-notes-input").fill("V4 prod QA interview note.");
    await page.getByTestId("interview-notes-input").blur();
    await expect(page.getByTestId("interview-notes-status")).toContainText(/Saved/, {
      timeout: 60_000,
    });

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-workspace")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("interview-prep-notes")).toHaveValue("V4 prod QA prep note.", {
      timeout: 60_000,
    });
    await expect(page.getByTestId("interview-notes-input")).toHaveValue(
      "V4 prod QA interview note.",
    );

    const decision = page.getByTestId("interview-decision");
    // The Hired badge is optimistic — await the stage PATCH response before
    // navigating away so the navigation never aborts the in-flight request.
    const hiredPatch = page.waitForResponse(
      (res) => res.url().includes("/candidates/") && res.request().method() === "PATCH",
      { timeout: 60_000 },
    );
    await decision.getByRole("button", { name: /hired/i }).click();
    await hiredPatch;
    await expect(decision).toContainText(/hired/i, { timeout: 60_000 });

    await page.goto(briefUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-stage-bar")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("brief-stage-pill-hired")).toContainText("1");
    await expect(page.getByTestId("brief-stage-section-hired")).toContainText("Mohammed");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-05-hired.png`, fullPage: true });
    await browser.close();
  });

  test("search surface: honest residual terms; 'in MA' understood as Massachusetts", async () => {
    test.setTimeout(120_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 60_000 });

    await page.getByTestId("search-input").fill("AI engineer in MA with flurbomatic Python");
    await page.getByTestId("search-submit").click();
    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 60_000 });
    await expect(interp).toContainText("Massachusetts");

    const residual = page.getByTestId("search-residual-terms");
    await expect(residual).toBeVisible();
    await expect(residual).toContainText(/not understood/i);
    await expect(residual).toContainText("flurbomatic");
    expect((await residual.innerText()).toLowerCase()).not.toMatch(/\bma\b/);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/v4p-06-residual.png`, fullPage: true });
    await browser.close();
  });

  test("cleanup: delete the QA brief via UI (interview data cascades)", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
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
    const material = consoleErrors.filter(
      (e) => !/favicon|manifest|Download the React DevTools/i.test(e),
    );
    expect(serverErrors, `5xx seen: ${serverErrors.join(", ")}`).toHaveLength(0);
    expect(material, `console errors: ${material.join(" | ")}`).toHaveLength(0);
  });
});
