import { test, expect, chromium, devices } from "@playwright/test";

// Claim-Attribution Integrity — PRODUCTION verification against veribridgeai.com.
//
// Trust rule under test: PROJECT EVIDENCE != CANDIDATE OWNERSHIP. Every public
// VBR report must state the candidate↔project relationship explicitly, and must
// never carry subject-ambiguous ownership wording ("<skill> was implemented and
// demonstrated in <project>") or the retired "Authorship explanation" tier.
//
// Unauthenticated public surfaces only — no QA session minting required.
// Tokens are the live published project-report tokens as of 2026-08-24; a
// rotated/unpublished token surfaces as a skipped case, never a false pass.

const BASE = "https://veribridgeai.com";
const API = "https://veribridge-api.onrender.com";

type Case = {
  name: string;
  token: string;
  expectState: "unknown" | "claimed_contributor" | "denied_by_candidate" | "conflicted" | "verified_author" | "verified_contributor";
  expectLabel: string;
};

const CASES: Case[] = [
  {
    name: "MULTIUSER-149-MARKDOWN-STUDIO",
    token: "3jrLOblpz4p3hu3p8oznklP4bQlzgEj9",
    expectState: "claimed_contributor",
    expectLabel: "Contribution claimed (unverified)",
  },
  {
    name: "Boston Smart Accident Risk Rerouting",
    token: "ZF5rU20TbxlW8JdNwuKulwwwBJ9ZQHUQ",
    expectState: "unknown",
    expectLabel: "Contribution not established",
  },
  {
    name: "VeriBridge",
    token: "m6s2lUVkDKYG3U-vM9evqh_FhEd47o_7",
    expectState: "unknown",
    expectLabel: "Contribution not established",
  },
];

// Wording that must never reach a recruiter surface: it reads as a claim about
// the CANDIDATE while being derived from PROJECT-level artifact evidence.
const FORBIDDEN = ["was implemented and demonstrated", "authorship explanation"];

test("public report API carries an explicit candidate-attribution block", async ({ request }) => {
  let checked = 0;
  for (const c of CASES) {
    const resp = await request.get(`${API}/api/v1/public/vbr/reports/${c.token}`);
    if (resp.status() === 404) continue; // unpublished / passport made private
    expect(resp.status(), `${c.name} API status`).toBe(200);
    const body = await resp.json();

    const att = body.candidate_attribution;
    expect(att, `${c.name} candidate_attribution present`).toBeTruthy();
    expect(att.state, `${c.name} ownership state`).toBe(c.expectState);
    expect(att.label).toBe(c.expectLabel);
    expect(String(att.candidate_claim_text).length).toBeGreaterThan(0);

    // A non-attributed candidate can never carry implementation wording.
    if (["unknown", "denied_by_candidate", "conflicted"].includes(att.state)) {
      expect(att.candidate_claim_text.toLowerCase()).not.toContain("the candidate personally implemented");
      expect(att.candidate_claim_text.toLowerCase()).not.toContain("the candidate contributed to this implementation");
    }

    // Project-scoped claim sentences only.
    const blob = JSON.stringify(body).toLowerCase();
    for (const bad of FORBIDDEN) {
      expect(blob, `${c.name} must not contain "${bad}"`).not.toContain(bad);
    }
    checked += 1;
  }
  expect(checked, "at least one published report was verified").toBeGreaterThan(0);
});

test("public report page renders the candidate-relationship block, no ambiguous wording", async () => {
  const browser = await chromium.launch();
  const consoleErrors: string[] = [];
  let rendered = 0;

  try {
    for (const c of CASES) {
      const ctx = await browser.newContext({ ...devices["Desktop Chrome"] });
      const page = await ctx.newPage();
      page.on("console", (m) => {
        if (m.type() === "error") consoleErrors.push(`${c.name}: ${m.text()}`);
      });

      // NOTE: never `networkidle` here — the public report fires a view beacon
      // that keeps the network busy, so networkidle never settles.
      const resp = await page.goto(`${BASE}/vbr/report/${c.token}`, {
        waitUntil: "domcontentloaded",
      });
      if (!resp || resp.status() >= 400) {
        await ctx.close();
        continue;
      }

      const banner = page.getByTestId("candidate-attribution").first();
      await expect(banner, `${c.name} attribution banner visible`).toBeVisible({ timeout: 20_000 });
      await expect(banner).toHaveAttribute("data-attribution-state", c.expectState);
      await expect(banner.getByText(c.expectLabel, { exact: false })).toBeVisible();

      const bodyText = (await page.locator("body").innerText()).toLowerCase();
      for (const bad of FORBIDDEN) {
        expect(bodyText, `${c.name} rendered page must not contain "${bad}"`).not.toContain(bad);
      }

      // iPhone-13: the new block must not introduce horizontal overflow.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${c.name} iPhone-13 horizontal overflow`).toBeLessThanOrEqual(1);

      rendered += 1;
      await ctx.close();
    }
  } finally {
    await browser.close();
  }

  expect(rendered, "at least one published report page was rendered").toBeGreaterThan(0);
  expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
});
