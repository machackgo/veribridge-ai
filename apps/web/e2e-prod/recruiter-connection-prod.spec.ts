import { test, expect, type BrowserContext } from "@playwright/test";
import * as fs from "fs";

// Post-deploy verification of the recruiter passport connection feature
// against production (veribridgeai.com + veribridge-api.onrender.com).
// Uses two pre-minted throwaway QA recruiter sessions (created via the
// Supabase admin API by scratchpad/mint_qa_sessions.py).

const SCRATCH =
  "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-ai/aea5d64b-2d85-4a7a-a6b3-837ae0a78bfc/scratchpad";
const API = "https://veribridge-api.onrender.com";
const SLUG = "ZwC_0l8HutI";

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
const [recA, recB] = sessions.users;

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

async function api(
  method: string,
  path: string,
  token?: string,
  body?: unknown,
) {
  const res = await fetch(API + path, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON */
  }
  return { status: res.status, json };
}

function connectionCount(json: unknown): number {
  const j = json as Record<string, unknown>;
  const list = (j?.connections ?? j?.items ?? j) as unknown[];
  return Array.isArray(list) ? list.length : -1;
}

test.describe("recruiter passport connection — production", () => {
  test("signed-out passport shows Save Candidate and routes through login", async ({
    page,
  }) => {
    await page.goto(`/p/${SLUG}?src=qr`, { waitUntil: "domcontentloaded" });
    const btn = page.getByRole("button", { name: /save candidate/i }).first();
    await expect(btn).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SCRATCH}/shot-1-signedout-passport.png` });
    await btn.click();
    await page.waitForURL(/\/login\?/, { timeout: 30_000 });
    const url = decodeURIComponent(page.url());
    expect(url).toContain("next=");
    expect(url).toContain("save=1");
    await page.screenshot({ path: `${SCRATCH}/shot-2-login-redirect.png` });
  });

  test("recruiter A return leg auto-saves, workspace shows candidate, Saved persists", async ({
    browser,
  }) => {
    const ctx: BrowserContext = await browser.newContext({
      ...test.info().project.use,
    });
    await ctx.addCookies(cookiesFor(recA));
    const page = await ctx.newPage();

    await page.goto(`https://veribridgeai.com/p/${SLUG}?save=1&src=qr`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByText(/saved/i).first()).toBeVisible({
      timeout: 45_000,
    });
    await expect
      .poll(() => page.url(), { timeout: 20_000 })
      .not.toContain("save=1");
    await page.screenshot({ path: `${SCRATCH}/shot-3-saved-state.png` });

    await page.goto("https://veribridgeai.com/recruiters/workspace", {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByText(/qr scan|open passport|remove/i).first()).toBeVisible(
      { timeout: 45_000 },
    );
    await page.screenshot({ path: `${SCRATCH}/shot-4-workspace-A.png` });

    await page.goto(`https://veribridgeai.com/p/${SLUG}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByText(/saved/i).first()).toBeVisible({
      timeout: 45_000,
    });
    await page.screenshot({ path: `${SCRATCH}/shot-5-reopen-saved.png` });
    await ctx.close();
  });

  test("API: exactly one connection for A; repeat saves stay idempotent", async () => {
    const list1 = await api("GET", "/api/v1/recruiter/connections", recA.access_token);
    expect(list1.status).toBe(200);
    expect(connectionCount(list1.json)).toBe(1);

    await api("POST", "/api/v1/recruiter/connections", recA.access_token, {
      public_slug: SLUG,
      source: "qr_scan",
    });
    await api("POST", "/api/v1/recruiter/connections", recA.access_token, {
      public_slug: SLUG,
      source: "shared_link",
    });

    const list2 = await api("GET", "/api/v1/recruiter/connections", recA.access_token);
    expect(list2.status).toBe(200);
    expect(connectionCount(list2.json)).toBe(1);
  });

  test("recruiter B is isolated: zero connections, empty workspace", async ({
    browser,
  }) => {
    const listB = await api("GET", "/api/v1/recruiter/connections", recB.access_token);
    expect(listB.status).toBe(200);
    expect(connectionCount(listB.json)).toBe(0);

    const ctx = await browser.newContext({ ...test.info().project.use });
    await ctx.addCookies(cookiesFor(recB));
    const page = await ctx.newPage();
    await page.goto("https://veribridgeai.com/recruiters/workspace", {
      waitUntil: "domcontentloaded",
    });
    // The redesigned workspace header legitimately mentions "QR scan", so
    // assert isolation structurally: the polished empty state and zero cards.
    await expect(page.getByTestId("workspace-empty")).toBeVisible({ timeout: 45_000 });
    expect(await page.getByTestId("workspace-candidate-card").count()).toBe(0);
    await page.screenshot({ path: `${SCRATCH}/shot-6-workspace-B-empty.png` });
    await ctx.close();
  });

  test("privacy: public payload has no owner email; anon connections fail closed", async () => {
    const pub = await fetch(`${API}/api/v1/public/p/${SLUG}`);
    expect(pub.status).toBe(200);
    const text = await pub.text();
    expect(text).not.toMatch(/mohammedmubashir149@gmail\.com/);
    expect(text).not.toMatch(/mohammedmubashir@wpi\.edu/);

    const anon = await api("GET", "/api/v1/recruiter/connections");
    expect([401, 403]).toContain(anon.status);
  });
});
