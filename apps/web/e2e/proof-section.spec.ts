import { expect, test } from "@playwright/test";

/* ── Landing v2 — interactive product demonstrations ── */

test.describe("Work Passport demo", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("passport-demo").scrollIntoViewIfNeeded();
  });

  test("renders the fixture passport with skills and projects", async ({
    page,
  }) => {
    const demo = page.getByTestId("passport-demo");
    await expect(demo.getByText("Verified Work Passport")).toBeVisible();
    await expect(
      demo.getByRole("listitem").filter({ hasText: "Machine Learning" }),
    ).toBeVisible();
    await expect(demo.getByText("sign-language-translator")).toBeVisible();
  });

  test("skill without evidence is labeled claimed only", async ({ page }) => {
    const nlp = page
      .getByTestId("passport-demo")
      .getByRole("listitem")
      .filter({ hasText: "NLP" });
    await expect(nlp).toContainText("claimed only");
  });

  test("selecting a skill dims unrelated projects", async ({ page }) => {
    const demo = page.getByTestId("passport-demo");
    // Focus (keyboard path) is deterministic under entry animations,
    // and doubles as an a11y check for the hover interaction.
    await demo
      .getByRole("listitem")
      .filter({ hasText: "Machine Learning" })
      .focus();
    const events = demo
      .locator(".lv-passport-project")
      .filter({ hasText: "campus-events-api" });
    await expect(events).toHaveAttribute("data-dim", "true");
  });
});

test.describe("Recruiter search demo", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("recruiter-demo").scrollIntoViewIfNeeded();
  });

  test("plays through to a candidate result with requirement states", async ({
    page,
  }) => {
    const demo = page.getByTestId("recruiter-demo");
    await expect(demo.getByText("Maya Chen")).toBeVisible({ timeout: 15000 });
    await expect(
      demo.getByRole("listitem").filter({ hasText: "Python" }),
    ).toContainText("Published evidence");
    await expect(
      demo.getByRole("listitem").filter({ hasText: "NLP" }),
    ).toContainText("No published evidence");
  });

  test("View Proof expands the evidence panel", async ({ page }) => {
    const demo = page.getByTestId("recruiter-demo");
    const viewProof = demo.getByRole("button", { name: "View Proof" });
    await viewProof.click({ timeout: 15000 });
    await expect(demo.getByText("Recorded defense · 12 min")).toBeVisible();
    await expect(
      demo.getByRole("button", { name: "Hide proof" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  test("Save Candidate toggles saved state", async ({ page }) => {
    const demo = page.getByTestId("recruiter-demo");
    const save = demo.getByRole("button", { name: "Save Candidate" });
    await save.click({ timeout: 15000 });
    await expect(demo.getByRole("button", { name: /Saved/ })).toBeVisible();
  });

  test("demo never shows scores or percentages", async ({ page }) => {
    const demo = page.getByTestId("recruiter-demo");
    await expect(demo.getByText("Maya Chen")).toBeVisible({ timeout: 15000 });
    const text = await demo.innerText();
    expect(text).not.toMatch(/\d+%/);
  });
});
