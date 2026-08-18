import { expect, test } from "@playwright/test";

/* ── Landing page v2 (Keystone brand) — navigation ── */
test.describe("Landing page — navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("page has correct title", async ({ page }) => {
    await expect(page).toHaveTitle(/VeriBridge/i);
  });

  test("hero heading is visible", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      /Prove them/i,
    );
  });

  test("navbar logo links to /", async ({ page }) => {
    const logo = page.getByRole("link", { name: /VeriBridge home/i });
    await expect(logo).toHaveAttribute("href", "/");
  });

  test("navbar For Recruiters → #recruiters section", async ({ page }) => {
    const link = page
      .getByRole("navigation", { name: "Main" })
      .getByRole("link", { name: "For Recruiters" });
    if (!(await link.isVisible())) {
      test.skip(true, "nav links are collapsed on small viewports");
    }
    await link.click();
    await expect(page).toHaveURL("/#recruiters");
  });

  test("navbar Sign in → /login", async ({ page }) => {
    const signIn = page.getByRole("link", { name: /^Sign in$/i });
    if (!(await signIn.isVisible())) {
      test.skip(true, "Sign in is collapsed on small viewports (CTA covers login)");
    }
    await signIn.click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("navbar Create Work Passport → /login", async ({ page }) => {
    await page
      .getByRole("banner")
      .getByRole("link", { name: /Create Work Passport/i })
      .click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("hero candidate CTA → /login", async ({ page }) => {
    await page
      .getByRole("link", { name: /Create your Work Passport/i })
      .click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("hero recruiter CTA → /recruiters", async ({ page }) => {
    await page
      .getByRole("link", { name: /Explore recruiter search/i })
      .first()
      .click();
    await expect(page).toHaveURL("/recruiters");
  });

  test("footer links are the live routes only", async ({ page }) => {
    const footer = page.getByRole("contentinfo");
    await expect(
      footer.getByRole("link", { name: "For Recruiters" }),
    ).toHaveAttribute("href", "/recruiters");
    await expect(
      footer.getByRole("link", { name: "Website Proof Recorder" }),
    ).toHaveAttribute("href", "/extension");
    await expect(
      footer.getByRole("link", { name: "Privacy" }),
    ).toHaveAttribute("href", "/privacy");
  });

  test("no links into removed prototype or unshipped surfaces", async ({
    page,
  }) => {
    const hrefs = await page
      .locator("a[href]")
      .evaluateAll((els) => els.map((el) => el.getAttribute("href")));
    for (const href of hrefs) {
      expect(href, `unexpected link ${href}`).not.toMatch(
        /^\/(recruiter\/|university|dashboard\/(jobs|visa-fit|mock-interview))/,
      );
    }
  });

  test("primary buttons have visible text", async ({ page }) => {
    const primaryBtns = page.locator(".lv-btn-primary");
    const count = await primaryBtns.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const text = await primaryBtns.nth(i).textContent();
      expect(text?.trim().length).toBeGreaterThan(0);
    }
  });
});

/* ── Honest-claims guardrails ── */
test.describe("Landing page — claim honesty", () => {
  test("never promises scores, rankings, or guaranteed verification", async ({
    page,
  }) => {
    await page.goto("/");
    const body = (await page.locator("body").innerText()).toLowerCase();
    expect(body).not.toContain("100% verified");
    expect(body).not.toContain("fraud-proof");
    expect(body).not.toContain("guaranteed skills");
    expect(body).not.toContain("match score");
    expect(body).not.toMatch(/\d+% (match|fit)/);
  });
});
