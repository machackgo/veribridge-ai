import { test, expect, chromium, devices, type Page } from "@playwright/test";
import * as fs from "fs";

// Recruiter Search Intelligence V1.5 — PRODUCTION verification against
// veribridgeai.com. Uses throwaway QA recruiter sessions minted for this run
// (deleted after). Corpus ground truth (2026-08-18, post-cleanup): exactly ONE
// discoverable candidate — Mohammed (ZwC_0l8HutI) with Python / FastAPI /
// Machine Learning / API Development evidence, NO NLP evidence, no live site.

const SCRATCH =
  process.env.QA_SCRATCH ??
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/0bd171a1-f6dc-47a8-9e49-72e5dbbb6767/scratchpad";
const BASE = "https://veribridgeai.com";
const API = "https://veribridge-api.onrender.com";
const FAKE = ["Maya Reyes", "Jordan Kim", "Arjun Singh", "Stripe Early Talent", "Maya Chen"];
// QA/demo identities that must NEVER appear in recruiter discovery again.
const QA_IDENTITIES = [
  "QA Student One-Forty-Eight",
  "QA-PROOF-TO-BEAM-E2E",
  "Isolation Test",
];
const QA_SLUGS = ["zrvnaFzbdFI", "dDb2X-Gekdc", "p9j9-_vGzCc"];

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
  if (value.length <= MAX) {
    return [{ name: qa.cookie_name, value, domain: "veribridgeai.com", path: "/", secure: true }];
  }
  const chunks: { name: string; value: string; domain: string; path: string; secure: boolean }[] = [];
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

async function newRecruiterPage(s: Session, viewport?: { width: number; height: number }) {
  const browser = await chromium.launch();
  const context = await browser.newContext(
    viewport ? { viewport } : { viewport: { width: 1440, height: 900 } },
  );
  await context.addCookies(cookiesFor(s));
  const page = await context.newPage();
  watch(page);
  return { browser, page };
}

async function expectCleanContent(page: Page) {
  const text = await page.locator("body").innerText();
  for (const f of FAKE) expect(text, `fake/demo content "${f}" leaked`).not.toContain(f);
  for (const q of QA_IDENTITIES) expect(text, `QA identity "${q}" leaked`).not.toContain(q);
  expect(text).not.toMatch(/\d+\s*%/);
}

test.describe("Recruiter Search V1.5 — production", () => {
  test("anonymous: /recruiters/search requires login; search API 401s", async ({ page }) => {
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/login\?next=%2Frecruiters%2Fsearch/);
    const res = await page.request.get(`${API}/api/v1/recruiter/search?q=python`);
    expect(res.status()).toBe(401);
  });

  test("identity cleanliness: one Mohammed, zero QA identities, voice control present", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    // Exactly one discoverable candidate; the duplicate + QA rows are gone.
    const names = await page.getByTestId("search-result-name").allInnerTexts();
    const mohammeds = names.filter((n) => n.includes("Mohammed Mubashir"));
    expect(mohammeds, "duplicate Mohammed identities").toHaveLength(1);
    await expectCleanContent(page);

    // The mic renders in real Chrome (webkitSpeechRecognition available).
    await expect(page.getByTestId("search-mic")).toBeVisible();
    await page.screenshot({ path: `${SCRATCH}/shots-prod/1-browse.png`, fullPage: true });

    // The three cleaned QA passports are no longer published (404).
    for (const slug of QA_SLUGS) {
      const res = await page.request.get(`${API}/api/v1/public/p/${slug}`);
      expect(res.status(), `QA slug ${slug} should be unpublished`).toBe(404);
    }
    await browser.close();
  });

  test("NLP is independent: bare NLP → honest zero; ML+NLP → close with missing NLP", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    // Bare NLP: no published NLP evidence exists → honest zero, never an
    // ML candidate presented as NLP-qualified.
    await page.getByTestId("search-input").fill("NLP");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-empty")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/2-nlp-zero.png`, fullPage: true });

    // ML + NLP: the ML candidate appears ONLY as a close match with the
    // missing NLP requirement stated explicitly.
    await page.getByTestId("search-input").fill("I want a candidate with machine learning and NLP experience");
    await page.getByTestId("search-submit").click();
    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 30_000 });
    await expect(interp).toContainText("Machine Learning");
    await expect(interp).toContainText("Natural Language Processing");
    await expect(page.getByTestId("search-section-close")).toBeVisible();
    const closeCard = page.locator('[data-match-type="close"]').first();
    await expect(closeCard.getByTestId("search-result-requirements")).toContainText(
      "No published Natural Language Processing evidence",
    );
    expect(await page.locator('[data-match-type="exact"]').count()).toBe(0);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/3-ml-nlp-close.png`, fullPage: true });
    await browser.close();
  });

  test("multi-skill AND enforces every requirement; NL role query parses", async () => {
    test.setTimeout(180_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    // All three requirements evidenced → exact.
    await page.getByTestId("search-input").fill("Python FastAPI API development");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    const exactCard = page.locator('[data-match-type="exact"]').first();
    await expect(exactCard).toBeVisible({ timeout: 30_000 });
    const reqs = exactCard.getByTestId("search-result-requirements");
    await expect(reqs).toContainText("Python");
    await expect(reqs).toContainText("FastAPI");
    await expect(reqs).toContainText("API Development");
    await page.screenshot({ path: `${SCRATCH}/shots-prod/4-and-exact.png`, fullPage: true });

    // Natural-language role + seniority + skills + missing requirement.
    await page
      .getByTestId("search-input")
      .fill("Find me an entry-level AI engineer with Python, FastAPI and NLP experience");
    await page.getByTestId("search-submit").click();
    const interp = page.getByTestId("search-interpretation");
    await expect(interp).toBeVisible({ timeout: 30_000 });
    await expect(interp).toContainText("Role: AI Engineer");
    await expect(interp).toContainText("Python");
    await expect(interp).toContainText("FastAPI");
    await expect(interp).toContainText("Natural Language Processing");
    const closeCard = page.locator('[data-match-type="close"]').first();
    await expect(closeCard.getByTestId("search-result-requirements")).toContainText(
      "Role: AI Engineer",
    );
    await expect(closeCard.getByTestId("search-result-requirements")).toContainText(
      "No published Natural Language Processing evidence",
    );
    await page.screenshot({ path: `${SCRATCH}/shots-prod/5-nl-role.png`, fullPage: true });
    await browser.close();
  });

  test("voice: mocked transcript → visible editable text → auto search (real audio = manual pass)", async () => {
    test.setTimeout(120_000);
    const browser = await chromium.launch();
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
            const result = Object.assign([{ transcript: "python and fastapi" }], { isFinal: true });
            this.onresult?.({ resultIndex: 0, results: [result] });
            setTimeout(() => this.onend?.(), 150);
          }, 250);
        }
        stop() { this.onend?.(); }
        abort() {}
      }
      (window as unknown as Record<string, unknown>).SpeechRecognition = FakeRecognition;
    });
    const page = await context.newPage();
    watch(page);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-mic").click();
    await expect(page.getByTestId("search-listening")).toBeVisible();
    await expect(page.getByTestId("search-input")).toHaveValue("python and fastapi", { timeout: 10_000 });
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shots-prod/6-voice.png`, fullPage: true });
    await browser.close();
  });

  test("journey: search → open passport → save → workspace → persistence", async () => {
    test.setTimeout(240_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-input").fill("python");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 30_000 });

    const firstCard = page.getByTestId("search-result-card").first();
    const href = await firstCard.getByTestId("search-result-open").getAttribute("href");
    const slug = href!.replace("/p/", "");
    const [passportPage] = await Promise.all([
      page.context().waitForEvent("page"),
      firstCard.getByTestId("search-result-open").click(),
    ]);
    await passportPage.waitForLoadState("domcontentloaded");
    await expect(passportPage.locator("body")).toContainText(/Work Passport/i, { timeout: 45_000 });
    await passportPage.screenshot({ path: `${SCRATCH}/shots-prod/7-passport.png`, fullPage: true });
    await passportPage.close();

    await firstCard.getByTestId("search-result-save").click();
    await expect(firstCard.getByTestId("search-result-saved")).toBeVisible({ timeout: 30_000 });

    await page.getByTestId("search-nav-workspace").click();
    await page.waitForURL(/\/recruiters\/workspace/);
    await expect(page.getByTestId("workspace-candidate-card").first()).toBeVisible({ timeout: 45_000 });
    const meta = (await page.getByTestId("workspace-candidate-meta").allInnerTexts()).join(" ");
    expect(meta).toContain("Search");
    await expectCleanContent(page);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/8-workspace.png`, fullPage: true });

    // Idempotency at the API level: repeat saves, still 1 row.
    for (let i = 0; i < 2; i++) {
      const res = await page.request.post(`${API}/api/v1/recruiter/connections`, {
        headers: { Authorization: `Bearer ${qa.rec1.access_token}` },
        data: { passport_slug: slug, source: "search" },
      });
      expect(res.ok()).toBeTruthy();
      expect((await res.json()).already_saved).toBe(true);
    }
    const list = await page.request.get(`${API}/api/v1/recruiter/connections`, {
      headers: { Authorization: `Bearer ${qa.rec1.access_token}` },
    });
    const body = await list.json();
    const forSlug = body.connections.filter(
      (c: { candidate: { public_slug: string | null } }) => c.candidate.public_slug === slug,
    );
    expect(forSlug).toHaveLength(1);

    // Saved mark persists after a fresh reload.
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("search-result-saved").first()).toBeVisible({ timeout: 30_000 });
    await browser.close();
  });

  test("zero results, clear, evidence filter, isolation", async () => {
    test.setTimeout(120_000);
    const { browser, page } = await newRecruiterPage(qa.rec1);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });

    await page.getByTestId("search-input").fill("zzz-nonexistent-technology");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-empty")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("search-clear").click();
    await expect(page.getByTestId("search-result-card").first()).toBeVisible({ timeout: 30_000 });

    await page.getByTestId("search-filter-github").click();
    await expect(
      page.getByTestId("search-result-count").or(page.getByTestId("search-empty")),
    ).toBeVisible({ timeout: 30_000 });
    await browser.close();

    // Isolation: rec2 sees an empty workspace and no saved marks.
    const { browser: b2, page: p2 } = await newRecruiterPage(qa.rec2);
    await p2.goto(`${BASE}/recruiters/workspace`, { waitUntil: "domcontentloaded" });
    await expect(p2.getByTestId("workspace-empty")).toBeVisible({ timeout: 45_000 });
    await p2.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(p2.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await expect(p2.getByTestId("search-result-saved")).toHaveCount(0);
    await b2.close();
  });

  test("mobile iPhone 13: structured search + sections + mic, no overflow", async () => {
    test.setTimeout(120_000);
    const { browser, page } = await newRecruiterPage(qa.rec1, devices["iPhone 13"].viewport);
    await page.goto(`${BASE}/recruiters/search`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("search-result-count")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("search-input").fill("machine learning and NLP");
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("search-section-close")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SCRATCH}/shots-prod/9-mobile.png`, fullPage: true });
    await browser.close();
  });

  test("regression: anonymous public passport + QR save flow still works", async () => {
    test.setTimeout(120_000);
    const browser = await chromium.launch();
    const page = await (await browser.newContext()).newPage();
    watch(page);
    await page.goto(`${BASE}/p/ZwC_0l8HutI?src=qr`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(/Work Passport/i, { timeout: 45_000 });
    await expect(page.getByTestId("save-candidate-button")).toBeVisible({ timeout: 30_000 });
    await browser.close();

    const { browser: b2, page: p2 } = await newRecruiterPage(qa.rec2);
    await p2.goto(`${BASE}/p/ZwC_0l8HutI?src=qr`, { waitUntil: "domcontentloaded" });
    await expect(p2.getByTestId("save-candidate-button")).toBeVisible({ timeout: 45_000 });
    await p2.getByTestId("save-candidate-button").click();
    await expect(p2.getByTestId("save-candidate-saved")).toBeVisible({ timeout: 30_000 });
    const list = await p2.request.get(`${API}/api/v1/recruiter/connections`, {
      headers: { Authorization: `Bearer ${qa.rec2.access_token}` },
    });
    const body = await list.json();
    expect(body.connections).toHaveLength(1);
    expect(body.connections[0].source).toBe("qr_scan");
    await b2.close();
  });

  test("zero material console errors / zero 5xx across the suite", async () => {
    const material = consoleErrors.filter(
      (e) => !/favicon|manifest|Download the React DevTools/i.test(e),
    );
    expect(serverErrors, `5xx seen: ${serverErrors.join(", ")}`).toHaveLength(0);
    expect(material, `console errors: ${material.join(" | ")}`).toHaveLength(0);
  });
});
