import { test, expect, type Page, type Browser } from "@playwright/test";
import * as fs from "fs";

// Recruiter Pipeline + Interview Workspace V4 — LOCAL rig verification
// (docker e2e-supabase :54321 + local API :8000 + web :3000).
//
// Journey (audit §PIPELINE UX / §INTERVIEW UX): create brief → brief-scoped
// search → add ONE candidate → compare tab shows a CALM empty state (V3
// defect fix) → stage walk saved→reviewing→shortlisted→contacted→interview
// with live stage-bar counts + reload persistence → Interview Workspace
// (deterministic checklist w/ proof deep links + honest gap language,
// grounded questions, autosaved notes, checklist marks, decision strip) →
// cross-role stage independence → recruiter isolation smoke → zero console
// errors / zero 5xx.
//
// CONTRACT TESTIDS this spec depends on (V4_ARCHITECTURE_AUDIT.md — the
// integration pass must reconcile these against the real frontend):
//   brief-stage-bar, brief-stage-pill-{status}, brief-stage-section-{status}
//   brief-candidate-stage-select   (accessible <select>, option VALUES are
//                                   the raw status keys, e.g. "reviewing")
//   brief-candidate-interview-link, brief-comparison-empty
//   interview-workspace, interview-summary, interview-coverage
//   interview-checklist, interview-checklist-row
//   interview-mark-verified        (toggle reflects selection via
//                                   aria-pressed="true")
//   interview-questions, interview-generate-questions, interview-question-card
//   interview-notes, interview-prep-notes, interview-notes-input,
//   interview-notes-status         (shows /Saved/ after autosave)
//   interview-decision             (contains an explicit "Hired" button)
//   search-residual-terms          (honest "Not understood" line, V3 defect 2)
// Plus existing V3 testids (brief-create-form, brief-tab-*, brief-search-*,
// brief-candidate-card, requirement-chip, search-input/submit/interpretation).
//
// Rig ground truth assumed (same corpus as the V3 local suite): ≥2 published
// candidates with Python+FastAPI evidence and NO NLP evidence anywhere
// (recruiter-search-v15-local.spec.ts asserts q="NLP" → empty), so an
// "NLP required" brief yields proven Python/FastAPI rows AND a guaranteed
// "No published evidence" gap row in the interview checklist.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/490bf054-308f-41f9-95b8-d657b80a7c6b/scratchpad";
const BASE = "http://localhost:3000";

type Session = { email: string; user_id: string; access_token: string; refresh_token: string };
const qa: { rec3: Session; rec1?: Session; rec2?: Session; cookie_name: string } = JSON.parse(
  fs.readFileSync(`${SCRATCH}/qa_rig_sessions.json`, "utf8"),
);

const STAGE_WALK = ["reviewing", "shortlisted", "contacted", "interview"] as const;

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
let candidateName = "";
let interviewUrl = "";

test.describe("Recruiter Pipeline V4 — local rig", () => {
  test("create brief → brief-scoped search → add ONE candidate", async ({ browser }) => {
    test.setTimeout(120_000);
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
      .fill("Entry-level engineer. Python, FastAPI and NLP are required. React is preferred.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 45_000 });
    brief1Url = page.url();

    const chips = page.getByTestId("requirement-chip");
    await expect(chips.filter({ hasText: "Python" })).toBeVisible({ timeout: 45_000 });
    await expect(chips.filter({ hasText: "Natural Language Processing" })).toBeVisible();

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 30_000 });
    const results = page.getByTestId("brief-search-result");
    expect(await results.count()).toBeGreaterThanOrEqual(1);
    candidateName = (await results.first().locator("h3").innerText()).trim();

    // Exactly ONE candidate in the pool — the compare tab must stay calm.
    await page.getByTestId("brief-search-add").first().click();
    await expect(page.getByTestId("brief-search-in-brief").first()).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-01-brief-search.png`, fullPage: true });
    await page.context().close();
  });

  test("compare tab with 1 candidate: calm empty state, never 'Something went wrong'", async ({
    browser,
  }) => {
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-title")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("brief-tab-compare").click();
    // V3 defect 1 fixed: a guarded, calm empty state — no fetch, no
    // alarming ErrorState, no raw error code.
    await expect(page.getByTestId("brief-comparison-empty")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("brief-comparison-empty")).toContainText(/at least 2/i);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("Something went wrong");
    expect(bodyText).not.toContain("too_few_candidates");
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-02-compare-empty.png`, fullPage: true });
    await page.context().close();
  });

  test("stage walk saved→reviewing→shortlisted→contacted→interview; stage bar counts; reload persists", async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("brief-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 45_000 });

    // Pipeline chrome: stage bar with a pill per stage; fresh add = saved.
    await expect(page.getByTestId("brief-stage-bar")).toBeVisible();
    await expect(page.getByTestId("brief-stage-pill-saved")).toContainText("1");
    await expect(page.getByTestId("brief-stage-section-saved")).toContainText(candidateName);

    const select = card.getByTestId("brief-candidate-stage-select");
    await expect(select).toBeVisible();
    for (const stage of STAGE_WALK) {
      await select.selectOption(stage);
      // Live counts: the walked-to stage owns the candidate, saved is empty.
      await expect(page.getByTestId(`brief-stage-pill-${stage}`)).toContainText("1", {
        timeout: 30_000,
      });
      await expect(page.getByTestId(`brief-stage-section-${stage}`)).toContainText(candidateName, {
        timeout: 30_000,
      });
      await expect(page.getByTestId("brief-stage-pill-saved")).toContainText("0");
    }

    // Reload: role-scoped stage persisted server-side.
    await page.reload({ waitUntil: "domcontentloaded" });
    const cardAfter = page.getByTestId("brief-candidate-card").first();
    await expect(cardAfter).toBeVisible({ timeout: 45_000 });
    await expect(cardAfter.getByTestId("brief-candidate-stage-select")).toHaveValue("interview");
    await expect(page.getByTestId("brief-stage-pill-interview")).toContainText("1");
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-03-stage-walk.png`, fullPage: true });
    await page.context().close();
  });

  test("interview workspace: deterministic checklist, proof links, honest gap language, no %", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    const card = page.getByTestId("brief-candidate-card").first();
    await expect(card).toBeVisible({ timeout: 45_000 });

    await card.getByTestId("brief-candidate-interview-link").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}\/interview\//, { timeout: 45_000 });
    interviewUrl = page.url();

    const workspace = page.getByTestId("interview-workspace");
    await expect(workspace).toBeVisible({ timeout: 45_000 });
    await expect(workspace).toContainText(candidateName);
    await expect(page.getByTestId("interview-summary")).toBeVisible();

    // Deterministic verification checklist (works with AI down).
    const checklist = page.getByTestId("interview-checklist");
    await expect(checklist).toBeVisible();
    expect(await page.getByTestId("interview-checklist-row").count()).toBeGreaterThanOrEqual(2);

    // Proven row: published evidence with a View proof deep link.
    const proofLink = checklist.locator('a[href^="/p/"]').first();
    await expect(proofLink).toBeVisible();
    expect(await proofLink.getAttribute("href")).toMatch(/^\/p\/.+\/skills\/.+/);

    // Gap row (NLP): honest language contract — absence of evidence, never
    // a judgment about the person.
    const gapRow = page
      .getByTestId("interview-checklist-row")
      .filter({ hasText: "No published" })
      .first();
    await expect(gapRow).toBeVisible();
    const workspaceText = await workspace.innerText();
    expect(workspaceText).not.toContain("doesn't know");
    expect(workspaceText).not.toContain("does not know");

    // Transparent coverage line — deterministic counts, never a %.
    await expect(page.getByTestId("interview-coverage")).toContainText(/of \d+/);
    expect((await page.getByTestId("interview-coverage").innerText()).includes("%")).toBe(false);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-04-interview-checklist.png`, fullPage: true });
    await page.context().close();
  });

  test("generate questions: grounded cards, provenance line, zero % anywhere", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-workspace")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("interview-generate-questions").click();
    const cards = page.getByTestId("interview-question-card");
    await expect(cards.first()).toBeVisible({ timeout: 45_000 });
    expect(await cards.count()).toBeGreaterThanOrEqual(1);

    // Every card is grounded in a checklist requirement (kind badge +
    // grounding footer); the questions block carries honest provenance.
    await expect(cards.first()).toContainText(/Evidence-backed|Gap to verify/);
    await expect(page.getByTestId("interview-questions")).toContainText(/advisory only/i);

    // No scores, no percentages — anywhere in the workspace.
    const text = await page.getByTestId("interview-workspace").innerText();
    expect(text.includes("%")).toBe(false);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-05-questions.png`, fullPage: true });
    await page.context().close();
  });

  test("prep + interview notes autosave; reload persists", async ({ browser }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-workspace")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("interview-notes")).toBeVisible();

    await page.getByTestId("interview-prep-notes").fill("Prep: verify NLP depth (no published evidence).");
    await page.getByTestId("interview-prep-notes").blur();
    await page.getByTestId("interview-notes-input").fill("Interview: walked through the FastAPI proof together.");
    await page.getByTestId("interview-notes-input").blur();
    await expect(page.getByTestId("interview-notes-status")).toContainText(/Saved/, {
      timeout: 30_000,
    });

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-workspace")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("interview-prep-notes")).toHaveValue(
      "Prep: verify NLP depth (no published evidence).",
      { timeout: 30_000 },
    );
    await expect(page.getByTestId("interview-notes-input")).toHaveValue(
      "Interview: walked through the FastAPI proof together.",
    );
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-06-notes.png`, fullPage: true });
    await page.context().close();
  });

  test("mark a topic Verified in interview; reload persists (recruiter-private)", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-checklist")).toBeVisible({ timeout: 45_000 });

    const mark = page.getByTestId("interview-mark-verified").first();
    await mark.click();
    await expect(mark).toHaveAttribute("aria-pressed", "true", { timeout: 30_000 });

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interview-checklist")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("interview-mark-verified").first()).toHaveAttribute(
      "aria-pressed",
      "true",
      { timeout: 30_000 },
    );
    await page.context().close();
  });

  test("decision strip: Hired → back on the brief the candidate sits in Hired", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    const decision = page.getByTestId("interview-decision");
    await expect(decision).toBeVisible({ timeout: 45_000 });

    await decision.getByRole("button", { name: /hired/i }).click();
    // The strip reflects the new role-scoped stage.
    await expect(decision).toContainText(/hired/i, { timeout: 30_000 });

    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-stage-bar")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("brief-stage-pill-hired")).toContainText("1");
    await expect(page.getByTestId("brief-stage-section-hired")).toContainText(candidateName);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-07-hired.png`, fullPage: true });
    await page.context().close();
  });

  test("cross-role independence: same candidate is reviewing in brief B, hired in brief A", async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(`${BASE}/recruiters/briefs`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-create-form")).toBeVisible({ timeout: 45_000 });
    await expect(
      page.getByTestId("briefs-empty").or(page.getByTestId("brief-card").first()),
    ).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("brief-create-role-text").fill("Python required.");
    await page.getByTestId("brief-create-submit").click();
    await page.waitForURL(/\/recruiters\/briefs\/[0-9a-f-]{36}/, { timeout: 45_000 });
    brief2Url = page.url();
    expect(brief2Url).not.toBe(brief1Url);

    await page.getByTestId("brief-tab-search").click();
    await page.getByTestId("brief-search-submit").click();
    await expect(page.getByTestId("brief-search-totals")).toBeVisible({ timeout: 30_000 });
    const target = page
      .getByTestId("brief-search-result")
      .filter({ hasText: candidateName })
      .first();
    await target.getByTestId("brief-search-add").click();
    await expect(target.getByTestId("brief-search-in-brief")).toBeVisible({ timeout: 30_000 });

    await page.getByTestId("brief-tab-candidates").click();
    const cardB = page
      .getByTestId("brief-candidate-card")
      .filter({ hasText: candidateName })
      .first();
    await expect(cardB).toBeVisible({ timeout: 45_000 });
    // Fresh add in THIS role: saved, not brief A's hired.
    await expect(cardB.getByTestId("brief-candidate-stage-select")).toHaveValue("saved");
    await cardB.getByTestId("brief-candidate-stage-select").selectOption("reviewing");
    await expect(page.getByTestId("brief-stage-pill-reviewing")).toContainText("1", {
      timeout: 30_000,
    });

    // Brief A is untouched: still hired. Zero global status.
    await page.goto(brief1Url, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("brief-stage-bar")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("brief-stage-pill-hired")).toContainText("1");
    await expect(page.getByTestId("brief-stage-section-hired")).toContainText(candidateName);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-08-cross-role.png`, fullPage: true });
    await page.context().close();
  });

  test("search surface renders honest residual terms; location aliases understood", async ({
    browser,
  }) => {
    // V3 defect 2 (residual_terms never rendered) + WP3 location work:
    // "in MA" must resolve to Massachusetts while a gibberish term is
    // surfaced as not-understood — never silently used, never guessed.
    test.setTimeout(120_000);
    const page = await recruiterPage(browser, qa.rec3);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("search-input").fill("AI engineer in MA with flurbomatic Python");
    await page.getByTestId("search-submit").click();
    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 30_000 });
    await expect(interp).toContainText("Massachusetts");

    const residual = page.getByTestId("search-residual-terms");
    await expect(residual).toBeVisible();
    await expect(residual).toContainText(/not understood/i);
    await expect(residual).toContainText("flurbomatic");
    // The state abbreviation was UNDERSTOOD as a location, not residual.
    expect((await residual.innerText()).toLowerCase()).not.toMatch(/\bma\b/);
    await page.screenshot({ path: `${SCRATCH}/shots-local/v4-09-residual.png`, fullPage: true });
    await page.context().close();
  });

  test("recruiter isolation smoke: another recruiter cannot open the interview workspace", async ({
    browser,
  }) => {
    const other = qa.rec1 ?? qa.rec2;
    test.skip(!other, "no second recruiter session (rec1/rec2) in qa_rig_sessions.json");
    test.setTimeout(120_000);
    // Deliberately unwatched page: the EXPECTED outcome here is a 404 from
    // the workspace API (foreign == missing), which the browser logs as a
    // failed-resource console error — that is the pass condition, not noise
    // for the zero-console-errors sweep. 5xx are still asserted via the
    // absence of a rendered workspace below.
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addCookies(cookiesFor(other as Session));
    const page = await context.newPage();
    page.on("response", (res) => {
      if (res.status() >= 500) serverErrors.push(`${res.status()} ${res.url()}`);
    });
    await page.goto(interviewUrl, { waitUntil: "domcontentloaded" });
    // Foreign == missing: the workspace must never render for recruiter B —
    // a not-found state or a redirect away are both acceptable.
    await page.waitForTimeout(5_000);
    await expect(page.getByTestId("interview-workspace")).toHaveCount(0);
    const body = (await page.locator("body").innerText()).toLowerCase();
    const redirectedAway = !page.url().startsWith(interviewUrl);
    expect(
      redirectedAway || /not found|couldn.t find|doesn.t exist|404|sign in/i.test(body),
      `recruiter B saw: url=${page.url()}`,
    ).toBe(true);
    expect(body).not.toContain(candidateName.toLowerCase());
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
