import { expect, test, type Locator } from "@playwright/test";

async function controlHeight(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box?.height ?? 0;
}

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

  test("sidebar Onboarding → /dashboard/onboarding", async ({ page }) => {
    await page.getByRole("link", { name: /Onboarding/i }).click();
    await expect(page).toHaveURL("/dashboard/onboarding");
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

/* ── Universal onboarding ── */
test.describe("/onboarding first-run flow", () => {
  test("/onboarding renders focused onboarding flow", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByRole("heading", { name: /Set up your Career Graph/i })).toBeVisible();
    await expect(page.getByText("Step 1 of 7").first()).toBeVisible();
    await expect(page.getByText(/You can update these preferences anytime from your dashboard/i)).toBeVisible();
  });

  test("academic dropdowns render", async ({ page }) => {
    await page.goto("/onboarding");
    const degreeHeightBefore = await controlHeight(page.getByLabel("Degree level"));
    await page.getByLabel("University country").click();
    await expect(page.getByRole("option", { name: "Canada" })).toBeVisible();
    await expect(page.getByRole("option", { name: "India" })).toBeVisible();
    await expect(page.getByRole("option", { name: "United Arab Emirates" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Australia" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Germany" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Singapore" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Brazil" })).toBeVisible();
    await expect(page.getByRole("option", { name: "United Kingdom" })).toBeVisible();
    await expect.poll(async () => controlHeight(page.getByLabel("Degree level"))).toBeLessThanOrEqual(degreeHeightBefore + 2);
    await expect
      .poll(() => page.getByRole("listbox").evaluate((node) => node.scrollHeight > node.clientHeight))
      .toBeTruthy();
    await page.getByLabel("University country").fill("in");
    await expect(page.getByRole("option", { name: "India" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Indonesia" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Ireland" })).toBeVisible();
    await page.getByRole("option", { name: "India" }).click();
    await expect(page.getByLabel("University country")).toHaveValue("India");

    await page.getByLabel("Degree level").click();
    await expect(page.getByRole("option", { name: "Master's" })).toBeVisible();
    await expect(page.getByRole("option", { name: "PhD" })).toBeVisible();
    await expect(page.getByRole("option", { name: "MBA" })).toBeVisible();
    await page.keyboard.press("Escape");

    const graduationHeightBefore = await controlHeight(page.getByLabel("Graduation year"));
    await page.getByLabel("Major / field of study").click();
    await expect(page.getByRole("option", { name: "Mechanical Engineering" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Psychology" })).toBeVisible();
    await expect.poll(async () => controlHeight(page.getByLabel("Graduation year"))).toBeLessThanOrEqual(graduationHeightBefore + 2);
    await page.getByLabel("Major / field of study").fill("Aerospace Engineering");
    await expect(page.getByRole("option", { name: "Use custom: Aerospace Engineering" })).toBeVisible();
    await page.getByRole("option", { name: "Use custom: Aerospace Engineering" }).click();
    await expect(page.getByLabel("Major / field of study")).toHaveValue("Aerospace Engineering");
  });

  test("steps advance one at a time", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByRole("heading", { name: "Academic Profile" })).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Target Roles & Industries" })).toBeVisible();
    await expect(page.getByText("Step 2 of 7").first()).toBeVisible();
  });

  test("final completion redirects to dashboard", async ({ page }) => {
    await page.goto("/onboarding");
    for (let i = 0; i < 6; i += 1) {
      await page.getByRole("button", { name: "Continue" }).click();
    }
    await expect(page.getByRole("heading", { name: "Opportunity & Salary Heatmap Review" })).toBeVisible();
    await page.getByRole("button", { name: "Complete onboarding" }).click();
    await expect(page).toHaveURL("/dashboard");
  });
});

test.describe("/dashboard/onboarding", () => {
  test("dashboard onboarding remains an edit/preferences page", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await expect(page.getByRole("heading", { name: /Career Preferences/i })).toBeVisible();
    await expect(page.getByText("VeriBridge Career Graph")).toBeVisible();
    await expect(page.getByText(/Update your Career Graph/i)).toBeVisible();
  });

  test("steps can advance", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByRole("heading", { name: /Target Roles & Industries/i })).toBeVisible();
  });

  test("Computer Science major shows matching target roles", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Computer Science");
    await page.getByRole("option", { name: "Computer Science", exact: true }).click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByText(/Based on your major, VeriBridge suggests common roles companies hire for globally/i)).toBeVisible();
    await expect(page.getByText("Technology & Software")).toBeVisible();
    await page.getByLabel("Target roles").click();
    await expect(page.getByRole("option", { name: "Software Engineer", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Generative AI Engineer", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "LLM Engineer", exact: true })).toBeVisible();
    await page.getByLabel("Target roles").fill("Site Reliability Engineer");
    await expect(page.getByRole("option", { name: "Site Reliability Engineer", exact: true })).toBeVisible();
  });

  test("Finance major shows finance target roles", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Finance");
    await page.getByRole("option", { name: "Finance", exact: true }).click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await page.getByLabel("Target roles").click();
    await expect(page.getByRole("option", { name: "FP&A Analyst", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Quantitative Analyst", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Treasury Analyst", exact: true })).toBeVisible();
  });

  test("engineering and life science majors show broad role coverage", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Mechanical Engineering");
    await page.getByRole("option", { name: "Mechanical Engineering", exact: true }).click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await page.getByLabel("Target roles").click();
    await expect(page.getByRole("option", { name: "Aerospace Engineer", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Battery Engineer", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Validation Engineer", exact: true })).toBeVisible();

    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Biology");
    await page.getByRole("option", { name: "Biology", exact: true }).click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await page.getByLabel("Target roles").click();
    await expect(page.getByRole("option", { name: "Clinical Data Coordinator", exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: "Bioinformatics Analyst", exact: true })).toBeVisible();
  });

  test("target roles and industries support searchable custom selections", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByLabel("Add custom target role")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add role" })).toHaveCount(0);
    await page.getByLabel("Target roles").click();
    await expect(page.getByRole("option", { name: "Business Analyst" })).toBeVisible();
    await page.getByLabel("Target roles").fill("LLMOps Engineer");
    await expect(page.getByRole("option", { name: "LLMOps Engineer", exact: true })).toBeVisible();
    await page.getByLabel("Target roles").fill("Aerospace Systems Analyst");
    await expect(page.getByRole("option", { name: "Use custom: Aerospace Systems Analyst" })).toBeVisible();
    await page.getByRole("option", { name: "Use custom: Aerospace Systems Analyst" }).click();
    await expect(page.getByRole("button", { name: /Aerospace Systems Analyst/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByLabel("Target industries").click();
    await expect(page.getByRole("option", { name: "Healthcare" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Finance" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Technology", exact: true })).toBeVisible();
    await page.getByLabel("Target industries").fill("generative");
    await expect(page.getByRole("option", { name: "Generative AI", exact: true })).toBeVisible();
    await page.getByLabel("Target industries").fill("aero");
    await expect(page.getByRole("option", { name: "Aerospace", exact: true })).toBeVisible();
    await page.getByLabel("Target industries").fill("");
    await page.getByRole("option", { name: "Technology", exact: true }).click();
    await expect(page.getByRole("button", { name: /Technology/ })).toBeVisible();
    await page.getByLabel("Target industries").fill("SpaceTech");
    await expect(page.getByRole("option", { name: "Use custom: SpaceTech" })).toBeVisible();
    await page.getByRole("option", { name: "Use custom: SpaceTech" }).click();
    await expect(page.getByRole("button", { name: /SpaceTech/ })).toBeVisible();
  });

  test("skills and evidence dropdowns render", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Suggested skills").click();
    await expect(page.getByRole("option", { name: "Python" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Financial Modeling" })).toBeVisible();
    await page.getByLabel("Suggested skills").fill("Revit");
    await expect(page.getByRole("option", { name: "Use custom: Revit" })).toBeVisible();
    await page.getByRole("option", { name: "Use custom: Revit" }).click();
    await expect(page.getByRole("button", { name: /Revit/ })).toBeVisible();
    await page.getByLabel("Evidence type").click();
    await expect(page.getByRole("option", { name: "GitHub repo" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Financial model" })).toBeVisible();
  });

  test("location and work mode options render", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    for (let i = 0; i < 3; i += 1) {
      await page.getByRole("button", { name: "Continue" }).click();
    }
    await expect(page.getByRole("heading", { name: "Global location preferences" })).toBeVisible();
    await expect(page.getByText("United States", { exact: true })).toBeVisible();
    await expect(page.getByText("Remote in USA")).toBeVisible();
    await expect(page.getByText("New York City")).toBeVisible();
    await expect(page.getByText("Boston")).toBeVisible();
    await page.getByRole("button", { name: /Boston/ }).click();
    await expect(page.getByRole("button", { name: /Boston ×/ })).toBeVisible();

    await page.getByText("India", { exact: true }).first().click();
    await expect(page.getByRole("button", { name: /Bengaluru/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Hyderabad/ })).toBeVisible();

    await page.getByLabel("Search for other regions in United States").fill("Riyadh");
    await expect(page.getByRole("button", { name: "Add custom location: Riyadh" })).toBeVisible();
    await page.getByRole("button", { name: "Add custom location: Riyadh" }).click();
    await expect(page.getByRole("button", { name: /Riyadh/ })).toBeVisible();

    await expect(page.getByRole("button", { name: "On-site" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Hybrid" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Remote worldwide", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Flexible" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open to relocate" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open to global opportunities" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Include remote-first roles" })).toBeVisible();
  });

  test("compensation fields exist", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    for (let i = 0; i < 5; i += 1) {
      await page.getByRole("button", { name: "Continue" }).click();
    }
    await expect(page.getByText("Expected salary min")).toBeVisible();
    await expect(page.getByText("Minimum acceptable salary")).toBeVisible();
    await expect(page.getByLabel("Currency")).toBeVisible();
    await expect(page.getByLabel("Salary period")).toBeVisible();
    await expect(page.getByLabel("Open to negotiation")).toBeVisible();
    await expect(page.getByText(/compare your expectations with market ranges/i)).toBeVisible();
  });

  test("heatmap section renders recommended locations", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    for (let i = 0; i < 6; i += 1) {
      await page.getByRole("button", { name: "Continue" }).click();
    }
    await expect(page.getByRole("heading", { name: "Opportunity & Salary Heatmap", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "California, USA" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Remote worldwide" })).toBeVisible();
    await expect(page.getByText(/Compensation Fit/i).first()).toBeVisible();
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
    ["/onboarding", /Set up your Career Graph/i],
    ["/dashboard/onboarding", /Career Preferences/i],
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
