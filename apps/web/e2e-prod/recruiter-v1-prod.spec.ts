import { test, expect, chromium, devices } from "@playwright/test";
import * as fs from "fs";

// Recruiter V1 production verification — entry flow, prototype removal,
// workspace redesign — against veribridgeai.com. Uses the same pre-minted
// throwaway QA recruiter sessions as recruiter-connection-prod.spec.ts.

const SCRATCH =
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/aea5d64b-2d85-4a7a-a6b3-837ae0a78bfc/scratchpad";
const BASE = "https://veribridgeai.com";
const SLUG = "ZwC_0l8HutI";
const FAKE = ["Maya Reyes", "Jordan Kim", "Arjun Singh", "Stripe Early Talent"];

type QaUser = {
  email: string;
  id: string;
  access_token: string;
  cookie_name: string;
  cookie_chunks: string[];
};

const sessions: { users: QaUser[] } = JSON.parse(
  fs.readFileSync(`${SCRATCH}/qa_sessions.json`, "utf8"),
);
const [recA] = sessions.users;

function cookiesFor(user: QaUser) {
  return user.cookie_chunks.length === 1
    ? [
        {
          name: user.cookie_name,
          value: user.cookie_chunks[0],
          domain: "veribridgeai.com",
          path: "/",
          secure: true,
        },
      ]
    : user.cookie_chunks.map((v, i) => ({
        name: `${user.cookie_name}.${i}`,
        value: v,
        domain: "veribridgeai.com",
        path: "/",
        secure: true,
      }));
}

async function expectNoFakeContent(page: import("@playwright/test").Page) {
  const text = await page.locator("body").innerText();
  for (const f of FAKE) expect(text, `prototype content "${f}" leaked`).not.toContain(f);
}

test.describe("Recruiter V1 — production entry + routing", () => {
  test("homepage Recruiters nav goes to the real entry page (no prototype)", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const link = page.locator('a[href="/recruiters"]').first();
    await expect(link).toBeAttached({ timeout: 30_000 });
    await page.goto(`${BASE}/recruiters`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("recruiters-hero")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { level: 1, name: /Recruiter Workspace/i })).toBeVisible();
    await expect(page.getByTestId("recruiters-signin-link")).toHaveAttribute(
      "href",
      "/login?next=%2Frecruiters%2Fworkspace",
    );
    await expectNoFakeContent(page);
    await page.screenshot({ path: `${SCRATCH}/shots/prod-1-entry-mobile.png`, fullPage: true });
  });

  test("old /recruiter prototype routes redirect to the real flow", async ({ page }) => {
    await page.goto(`${BASE}/recruiter`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(`${BASE}/recruiters`);
    await expectNoFakeContent(page);

    await page.goto(`${BASE}/recruiter/candidates`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/login\?next=%2Frecruiters%2Fworkspace|\/recruiters\/workspace/);
    await expectNoFakeContent(page);
  });

  test("signed-in recruiter: /recruiters redirects to real workspace with the saved candidate", async () => {
    const browser = await chromium.launch();
    // Desktop context — the workspace must be verified at desktop width too.
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addCookies(cookiesFor(recA));
    const page = await ctx.newPage();

    // Ensure the QA recruiter has the candidate saved (idempotent).
    const res = await fetch("https://veribridge-api.onrender.com/api/v1/recruiter/connections", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${recA.access_token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ passport_slug: SLUG, source: "qr_scan" }),
    });
    expect(res.status, "idempotent save").toBeLessThan(300);

    await page.goto(`${BASE}/recruiters`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(`${BASE}/recruiters/workspace`, { timeout: 30_000 });

    await expect(page.getByTestId("workspace-candidate-card").first()).toBeVisible({
      timeout: 30_000,
    });
    const meta = await page.getByTestId("workspace-candidate-meta").first().innerText();
    expect(meta).toMatch(/Saved .*·/);
    await expectNoFakeContent(page);
    await page.screenshot({ path: `${SCRATCH}/shots/prod-2-workspace-desktop.png`, fullPage: true });

    // Open Passport → same candidate, Saved ✓ persists.
    const openHref = await page
      .getByTestId("workspace-candidate-open")
      .first()
      .getAttribute("href");
    expect(openHref).toBe(`/p/${SLUG}`);
    await page.goto(`${BASE}${openHref}`, { waitUntil: "domcontentloaded" });
    // The status probe deliberately falls back to the idle CTA on a transient
    // network failure (no retry loop in the component) — one reload is a fair
    // recovery before declaring the persisted Saved state broken.
    try {
      await expect(page.getByTestId("save-candidate-saved")).toBeVisible({ timeout: 30_000 });
    } catch {
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByTestId("save-candidate-saved")).toBeVisible({ timeout: 45_000 });
    }

    // Mobile viewport of the same real workspace (same API, same data).
    const mob = await browser.newContext({ ...devices["iPhone 13"] });
    await mob.addCookies(cookiesFor(recA));
    const mpage = await mob.newPage();
    await mpage.goto(`${BASE}/recruiters/workspace`, { waitUntil: "domcontentloaded" });
    await expect(mpage.getByTestId("workspace-candidate-card").first()).toBeVisible({
      timeout: 30_000,
    });
    const overflow = await mpage.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "mobile horizontal overflow px").toBeLessThanOrEqual(1);
    await mpage.screenshot({ path: `${SCRATCH}/shots/prod-3-workspace-mobile.png`, fullPage: true });

    await mob.close();
    await ctx.close();
    await browser.close();
  });
});
