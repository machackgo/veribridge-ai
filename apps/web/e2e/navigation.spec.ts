import { expect, test } from "@playwright/test";

/* ── Landing page navigation ── */
test.describe("Landing page — navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("page has correct title", async ({ page }) => {
    await expect(page).toHaveTitle(/VeriBridge AI/i);
  });

  test("hero heading is visible", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("navbar logo links to /", async ({ page }) => {
    await page.goto("/dashboard");
    const logo = page.getByRole("link", { name: /VeriBridge/i }).first();
    await logo.click();
    await expect(page).toHaveURL("/");
  });

  test("navbar Students link → /dashboard", async ({ page }) => {
    await page.getByRole("link", { name: "Students" }).first().click();
    await expect(page).toHaveURL("/dashboard");
  });

  test("navbar Recruiters link → /recruiters", async ({ page }) => {
    await page.getByRole("link", { name: "Recruiters" }).first().click();
    await expect(page).toHaveURL("/recruiters");
  });

  test("navbar Universities link → /university", async ({ page }) => {
    await page.getByRole("link", { name: "Universities" }).first().click();
    await expect(page).toHaveURL("/university");
  });

  test("navbar Sign in → /login", async ({ page }) => {
    await page.getByRole("link", { name: /Sign in/i }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("hero Start Building Profile → /login", async ({ page }) => {
    const heroCta = page
      .locator(".cp-hero-ctas")
      .getByRole("link", { name: /Start Building Profile/i });
    await heroCta.click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("hero View Platform → #platform (stays on /)", async ({ page }) => {
    const viewPlatform = page.getByRole("link", { name: /View Platform/i });
    await viewPlatform.click();
    await expect(page).toHaveURL("/#platform");
  });

  test("CTA card Start Building Profile → /login", async ({ page }) => {
    const ctaLink = page
      .locator(".cp-cta-card")
      .getByRole("link", { name: /Start Building Profile/i });
    await ctaLink.click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("no black button has zero-contrast text", async ({ page }) => {
    // Check that primary buttons have visible (non-zero-width) text
    const primaryBtns = page.locator(".cp-btn-primary");
    const count = await primaryBtns.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const btn = primaryBtns.nth(i);
      await expect(btn).toBeVisible();
      const text = await btn.textContent();
      expect(text?.trim().length).toBeGreaterThan(0);
    }
  });
});

/* ── Three-sided platform cards ── */
test.describe("Landing page — platform cards", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("Students preview card links to /dashboard", async ({ page }) => {
    const link = page.getByRole("link", { name: /Preview the students dashboard/i });
    await link.click();
    await expect(page).toHaveURL("/dashboard");
  });

  test("Recruiters preview card links to /recruiters", async ({ page }) => {
    const link = page.getByRole("link", { name: /Preview the recruiters dashboard/i });
    await link.click();
    await expect(page).toHaveURL("/recruiters");
  });

  test("Universities preview card links to /university", async ({ page }) => {
    const link = page.getByRole("link", { name: /Preview the universities dashboard/i });
    await link.click();
    await expect(page).toHaveURL("/university");
  });
});

/* ── Visa intelligence section ── */
test.describe("Landing page — visa section", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("Check Visa Fit → /dashboard/visa-fit", async ({ page }) => {
    const btn = page.getByRole("link", { name: /Check Visa Fit/i });
    await btn.click();
    await expect(page).toHaveURL("/dashboard/visa-fit");
  });

  test("View compatible jobs → /dashboard/jobs", async ({ page }) => {
    const btn = page.getByRole("link", { name: /View compatible jobs/i });
    await btn.click();
    await expect(page).toHaveURL("/dashboard/jobs");
  });

  test("Learn privacy controls → /dashboard/privacy", async ({ page }) => {
    const btn = page.getByRole("link", { name: /Learn privacy controls/i });
    await btn.click();
    await expect(page).toHaveURL("/dashboard/privacy");
  });

  test("Visa job rows link to /dashboard/jobs", async ({ page }) => {
    const row = page.locator(".cp-visa-job-row").first();
    await row.click();
    await expect(page).toHaveURL("/dashboard/jobs");
  });
});
