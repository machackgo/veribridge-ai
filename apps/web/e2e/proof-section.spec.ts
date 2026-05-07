import { expect, test } from "@playwright/test";

test.describe("Proof-of-Skill section — interactive skill tabs", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // Scroll to the proof section so it's in view
    await page.locator("#proof").scrollIntoViewIfNeeded();
  });

  test("Docker tab is selected by default", async ({ page }) => {
    const dockerTab = page.getByRole("tab", { name: /Docker/i });
    await expect(dockerTab).toHaveAttribute("aria-selected", "true");
  });

  test("Clicking React tab updates evidence panel", async ({ page }) => {
    const reactTab = page.getByRole("tab", { name: /React/i });
    await reactTab.click();
    await expect(reactTab).toHaveAttribute("aria-selected", "true");

    const panel = page.getByRole("tabpanel");
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("heading", { level: 3 })).toContainText("React");
  });

  test("Clicking Distributed Systems tab updates evidence panel", async ({ page }) => {
    const tab = page.getByRole("tab", { name: /Distributed Systems/i });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");

    const panel = page.getByRole("tabpanel");
    await expect(panel.getByRole("heading", { level: 3 })).toContainText("Distributed Systems");
  });

  test("Clicking Machine Learning tab shows pending state", async ({ page }) => {
    const tab = page.getByRole("tab", { name: /Machine Learning/i });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");

    const panel = page.getByRole("tabpanel");
    await expect(panel.getByRole("heading", { level: 3 })).toContainText("Machine Learning");
    // ML is pending — check the specific status badge, not any text node
    await expect(panel.getByTestId("skill-status-badge")).toHaveText("Pending");
  });

  test("Clicking SQL & Postgres tab updates evidence panel", async ({ page }) => {
    const tab = page.getByRole("tab", { name: /SQL/i });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");

    const panel = page.getByRole("tabpanel");
    await expect(panel.getByRole("heading", { level: 3 })).toContainText("SQL");
  });

  test("All 5 skill tabs are present and clickable", async ({ page }) => {
    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveCount(5);
    for (let i = 0; i < 5; i++) {
      const tab = tabs.nth(i);
      await expect(tab).toBeVisible();
      await expect(tab).toBeEnabled();
    }
  });

  test("Evidence cards are rendered as clickable links", async ({ page }) => {
    // Default Docker tab — evidence cards should be <a> or Next.js <Link>
    const evCards = page.locator(".cp-ev-card");
    const count = await evCards.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const card = evCards.nth(i);
      // Each card should be either an anchor or have a parent anchor
      const tagName = await card.evaluate((el) => el.tagName.toLowerCase());
      expect(["a"]).toContain(tagName);
    }
  });

  test("GitHub Repo evidence card opens external link", async ({ page }) => {
    const githubCard = page.locator(".cp-ev-card").filter({ hasText: "GitHub Repo" }).first();
    const href = await githubCard.getAttribute("href");
    // Should be an external link (https://)
    expect(href).toMatch(/^https?:\/\//);
    const target = await githubCard.getAttribute("target");
    expect(target).toBe("_blank");
  });

  test("Coursework evidence card links to /dashboard/profile", async ({ page }) => {
    const courseworkCard = page.locator(".cp-ev-card").filter({ hasText: "Coursework" }).first();
    const href = await courseworkCard.getAttribute("href");
    expect(href).toBe("/dashboard/profile");
  });

  test("switching tabs changes evidence count in panel heading", async ({ page }) => {
    // Docker: 4 sources
    let panel = page.getByRole("tabpanel");
    await expect(panel.locator("text=4 evidence sources")).toBeVisible();

    // Click SQL → 2 sources
    await page.getByRole("tab", { name: /SQL/i }).click();
    panel = page.getByRole("tabpanel");
    await expect(panel.locator("text=2 evidence source")).toBeVisible();
  });
});
