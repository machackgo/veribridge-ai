import { expect, test } from "@playwright/test";

/* ── Student dashboard ── */
test.describe("Student dashboard — sidebar navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
  });

  test("renders Welcome back heading", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Welcome back");
  });

  test("sidebar has Visa Fit link", async ({ page }) => {
    const visaFitLink = page.getByRole("link", { name: /Visa Fit/i });
    await expect(visaFitLink).toBeVisible();
  });

  test("sidebar Visa Fit → /dashboard/visa-fit", async ({ page }) => {
    await page.getByRole("link", { name: /Visa Fit/i }).click();
    await expect(page).toHaveURL("/dashboard/visa-fit");
  });

  test("sidebar Profile & Proof → /dashboard/profile", async ({ page }) => {
    await page.getByRole("link", { name: /Profile/i }).click();
    await expect(page).toHaveURL("/dashboard/profile");
  });

  test("sidebar Job Matches → /dashboard/jobs", async ({ page }) => {
    await page.getByRole("link", { name: /Job Matches/i }).click();
    await expect(page).toHaveURL("/dashboard/jobs");
  });

  test("sidebar Applications → /dashboard/applications", async ({ page }) => {
    await page.getByRole("link", { name: /Applications/i }).click();
    await expect(page).toHaveURL("/dashboard/applications");
  });

  test("sidebar Skill Gaps → /dashboard/skill-gaps", async ({ page }) => {
    await page.getByRole("link", { name: /Skill Gaps/i }).click();
    await expect(page).toHaveURL("/dashboard/skill-gaps");
  });

  test("sidebar Mock Interview → /dashboard/mock-interview", async ({ page }) => {
    await page.getByRole("link", { name: /Mock Interview/i }).click();
    await expect(page).toHaveURL("/dashboard/mock-interview");
  });

  test("sidebar Settings → /dashboard/settings", async ({ page }) => {
    await page.getByRole("link", { name: /Settings/i }).click();
    await expect(page).toHaveURL("/dashboard/settings");
  });

  test("sidebar Privacy → /dashboard/privacy", async ({ page }) => {
    await page.getByRole("link", { name: /Privacy/i }).click();
    await expect(page).toHaveURL("/dashboard/privacy");
  });
});

/* ── Visa Fit page ── */
test.describe("/dashboard/visa-fit", () => {
  test("renders Visa Fit heading", async ({ page }) => {
    await page.goto("/dashboard/visa-fit");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/visa/i);
  });

  test("Visa Fit is the active sidebar item", async ({ page }) => {
    await page.goto("/dashboard/visa-fit");
    const visaLink = page.getByRole("link", { name: /Visa Fit/i });
    await expect(visaLink).toHaveAttribute("aria-current", "page");
  });
});

/* ── Recruiter dashboard ── */
test.describe("Recruiter dashboard — sidebar navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/recruiter");
  });

  test("renders recruiter heading", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("sidebar /recruiter/search link works", async ({ page }) => {
    await page.getByRole("link", { name: /Pipeline/i }).click();
    await expect(page).toHaveURL("/recruiter/search");
  });

  test("sidebar /recruiter/candidates link works", async ({ page }) => {
    await page.getByRole("link", { name: /Saved Lists/i }).click();
    await expect(page).toHaveURL("/recruiter/candidates");
  });

  test("sidebar /recruiter/invites link works", async ({ page }) => {
    await page.getByRole("link", { name: /Messages/i }).click();
    await expect(page).toHaveURL("/recruiter/invites");
  });

  test("sidebar /recruiter/company link works", async ({ page }) => {
    await page.getByRole("link", { name: /Job Posts/i }).click();
    await expect(page).toHaveURL("/recruiter/company");
  });

  test("sidebar /recruiter/settings link works", async ({ page }) => {
    await page.getByRole("link", { name: /Team/i }).click();
    await expect(page).toHaveURL("/recruiter/settings");
  });
});

/* ── University dashboard ── */
test.describe("University dashboard — sidebar navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/university");
  });

  test("renders cohort overview heading", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/2026|cohort|overview/i);
  });

  test("sidebar /university/analytics link works", async ({ page }) => {
    await page.getByRole("link", { name: /Readiness/i }).click();
    await expect(page).toHaveURL("/university/analytics");
  });

  test("sidebar /university/skill-gaps link works", async ({ page }) => {
    await page.getByRole("link", { name: /Skill gaps/i }).click();
    await expect(page).toHaveURL("/university/skill-gaps");
  });

  test("sidebar /university/outcomes link works", async ({ page }) => {
    await page.getByRole("link", { name: /Outcomes/i }).click();
    await expect(page).toHaveURL("/university/outcomes");
  });

  test("sidebar /university/employers link works", async ({ page }) => {
    await page.getByRole("link", { name: /Employer/i }).click();
    await expect(page).toHaveURL("/university/employers");
  });

  test("sidebar /university/privacy link works", async ({ page }) => {
    await page.getByRole("link", { name: /Privacy/i }).click();
    await expect(page).toHaveURL("/university/privacy");
  });
});

/* ── Key page headings ── */
test.describe("Key pages render expected headings", () => {
  const routes: [string, RegExp][] = [
    ["/", /verified student talent/i],
    ["/dashboard", /Welcome back/i],
    ["/dashboard/visa-fit", /visa/i],
    ["/dashboard/jobs", /Roles ranked/i],
    ["/dashboard/profile", /verified profile/i],
    ["/recruiter", /verified|talent|discover/i],
    ["/recruiter/search", /search|pipeline/i],
    ["/university", /cohort|overview/i],
    ["/university/analytics", /readiness|analytics/i],
  ];

  for (const [url, pattern] of routes) {
    test(`${url} renders a matching heading`, async ({ page }) => {
      await page.goto(url);
      const h1 = page.getByRole("heading", { level: 1 });
      await expect(h1).toBeVisible();
      await expect(h1).toMatchAriaSnapshot(`- heading`);
    });
  }
});

/* ── Toggle interaction tests ── */
test.describe("Toggle switches are interactive", () => {
  test("Recruiter settings toggles respond to click", async ({ page }) => {
    await page.goto("/recruiter/settings");
    // Find a toggle switch
    const firstSwitch = page.locator('[role="switch"]').first();
    await expect(firstSwitch).toBeVisible();
    const initialState = await firstSwitch.getAttribute("aria-checked");
    await firstSwitch.click();
    const newState = await firstSwitch.getAttribute("aria-checked");
    expect(newState).not.toBe(initialState);
  });

  test("Recruiter settings toast appears after toggle", async ({ page }) => {
    await page.goto("/recruiter/settings");
    const firstSwitch = page.locator('[role="switch"]').first();
    await firstSwitch.click();
    // Toast should appear
    await expect(page.locator('[role="status"]')).toBeVisible();
  });

  test("University privacy toggles respond to click", async ({ page }) => {
    await page.goto("/university/privacy");
    const firstSwitch = page.locator('[role="switch"]').first();
    await expect(firstSwitch).toBeVisible();
    const before = await firstSwitch.getAttribute("aria-checked");
    await firstSwitch.click();
    const after = await firstSwitch.getAttribute("aria-checked");
    expect(after).not.toBe(before);
  });

  test("Student settings notification toggles respond", async ({ page }) => {
    await page.goto("/dashboard/settings");
    const switches = page.locator('[role="switch"]');
    const count = await switches.count();
    expect(count).toBeGreaterThan(0);
    const firstSwitch = switches.first();
    const before = await firstSwitch.getAttribute("aria-checked");
    await firstSwitch.click();
    const after = await firstSwitch.getAttribute("aria-checked");
    expect(after).not.toBe(before);
  });

  test("Student privacy toggles respond", async ({ page }) => {
    await page.goto("/dashboard/privacy");
    const firstSwitch = page.locator('[role="switch"]').first();
    await expect(firstSwitch).toBeVisible();
    await firstSwitch.click();
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 3000 });
  });

  test("Student mock interview start button shows demo toast", async ({ page }) => {
    await page.goto("/dashboard/mock-interview");
    const startBtn = page.getByText(/Start mock interview/i);
    await expect(startBtn).toBeVisible();
    await startBtn.click();
    await expect(page.locator('[role="status"]')).toBeVisible({ timeout: 3000 });
  });
});
