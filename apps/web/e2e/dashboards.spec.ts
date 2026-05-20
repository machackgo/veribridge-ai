import { expect, test, type Locator, type Page } from "@playwright/test";

async function controlHeight(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box?.height ?? 0;
}

function makeProofEvidenceRouteState() {
  return {
    evidence: [] as Array<Record<string, unknown>>,
  };
}

async function mockProofSubmissionApis(page: Page, state = makeProofEvidenceRouteState()) {
  await page.route("**/api/v1/student/skill-evidence**", async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    const method = route.request().method();

    if (pathname === "/api/v1/student/skill-evidence" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.evidence),
      });
      return;
    }

    if (pathname === "/api/v1/student/skill-evidence" && method === "POST") {
      const body = (await route.request().postDataJSON()) as Record<string, unknown>;
      const id = `evidence-${state.evidence.length + 1}`;
      const row = {
        id,
        user_id: "student-user",
        skill_name: String(body.skill_name ?? ""),
        evidence_type: String(body.evidence_type ?? ""),
        evidence_url: body.evidence_url ?? null,
        repository_url: body.repository_url ?? null,
        file_path: body.file_path ?? null,
        line_start: body.line_start ?? null,
        line_end: body.line_end ?? null,
        evidence_description: body.evidence_description ?? null,
        proof_visibility: body.proof_visibility ?? "public",
        metadata: body.metadata ?? {},
        verification_status: "verified",
        verification_summary: "Proof saved.",
        verifier_version: "mock-v1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      state.evidence = [row, ...state.evidence]
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(row),
      })
      return
    }

    if (pathname.startsWith("/api/v1/student/skill-evidence/") && method === "PUT") {
      const evidenceId = pathname.split("/")[5];
      const body = (await route.request().postDataJSON()) as Record<string, unknown>;
      const index = state.evidence.findIndex((row) => row.id === evidenceId);
      if (index < 0) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "evidence not found" }),
        });
        return;
      }
      const current = state.evidence[index];
      const next = {
        ...current,
        ...body,
        metadata: {
          ...(current.metadata as Record<string, unknown> | undefined),
          ...((body.metadata as Record<string, unknown> | undefined) ?? {}),
        },
        updated_at: new Date().toISOString(),
      };
      state.evidence[index] = next;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(next),
      });
      return;
    }

    if (pathname.endsWith("/website-verification-guide") && method === "POST") {
      const body = (await route.request().postDataJSON()) as Record<string, unknown>
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "guide-1",
          user_id: "student-user",
          skill_evidence_id: pathname.split("/")[5],
          project_overview: body.project_overview ?? null,
          feature_to_verify: body.feature_to_verify ?? "",
          verification_steps: body.verification_steps ?? [],
          sample_inputs: body.sample_inputs ?? null,
          expected_output: body.expected_output ?? "",
          login_required: Boolean(body.login_required),
          login_notes: body.login_notes ?? null,
          access_notes: body.access_notes ?? null,
          known_limitations: body.known_limitations ?? null,
          additional_notes: body.additional_notes ?? null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
      return
    }

    if (pathname.endsWith("/website-verification-plan") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "plan-1",
          user_id: "student-user",
          skill_evidence_id: pathname.split("/")[5],
          website_url: state.evidence[0]?.evidence_url ?? "https://student-app.example.com",
          feature_to_verify: "route risk analysis",
          plan_status: "ready",
          normalized_test_steps: ["Open the site", "Run the main action"],
          expected_output: "A risk score card appears.",
          sample_inputs: null,
          inferred_action_candidates: [],
          validation_warnings: [],
          agent_notes: "Ready",
          requires_login: false,
          can_attempt_automated_execution: true,
          planner_version: "website-plan-v1",
          created_at: new Date().toISOString(),
        }),
      })
      return
    }

    if (pathname.endsWith("/website-verification-runs") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "static-run-1",
          evidence_id: pathname.split("/")[5],
          plan_id: "plan-1",
          user_id: "student-user",
          execution_status: "static_verified",
          executor_version: "mock-static-v1",
          execution_summary: "Static checks passed.",
          checks_attempted: 2,
          checks_passed: 2,
          checks_failed: 0,
          checks_needing_review: 0,
          inspected_url: "https://student-app.example.com",
          inspected_title: "Student App",
          inspected_meta_description: null,
          inspected_headings: ["Boston Accident Risk Rerouting"],
          inspected_visible_text_excerpt: "Risk Score: High",
          raw_executor_notes: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          checks: [],
        }),
      })
      return
    }

    if (pathname.endsWith("/website-browser-verification-runs") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "browser-run-1",
          evidence_id: pathname.split("/")[5],
          plan_id: "plan-1",
          user_id: "student-user",
          browser_execution_status: "browser_verified",
          executor_version: "mock-browser-v1",
          execution_summary: "Browser flow passed.",
          inspected_url: "https://student-app.example.com",
          final_url: "https://student-app.example.com/results",
          page_title: "Student App",
          screenshot_storage_path: null,
          html_snapshot_storage_path: null,
          safe_text_snapshot: "Risk Score: High. Safer route available.",
          steps_attempted: 3,
          steps_passed: 3,
          steps_failed: 0,
          steps_skipped: 0,
          steps_needing_review: 0,
          browser_metadata: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          steps: [],
        }),
      })
      return
    }

    if (pathname.endsWith("/website-semantic-verification-results") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "semantic-run-1",
          evidence_id: pathname.split("/")[5],
          plan_id: "plan-1",
          static_run_id: "static-run-1",
          browser_run_id: "browser-run-1",
          user_id: "student-user",
          semantic_status: "verified",
          confidence_score: 0.92,
          evaluator_version: "website-semantic-evaluator-mock-v1",
          evaluator_provider: "deterministic_mock",
          recruiter_facing_summary: "Verified.",
          evidence_summary: "Matched.",
          limitations: "Visible behavior only.",
          recommended_next_action: "No further action required.",
          semantic_similarity: {
            available: true,
            score: 0.92,
            label: "strong_semantic_match",
            model: "sentence-transformers/all-MiniLM-L6-v2",
            method: "sentence_transformers_cosine_similarity",
          },
          source_snapshot: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
      return
    }

    if (pathname.endsWith("/github-semantic-verification-results") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "github-semantic-1",
          evidence_id: pathname.split("/")[5],
          user_id: "student-user",
          semantic_status: "verified",
          confidence_score: 0.96,
          evaluator_version: "github-claim-code-semantic-v1",
          evaluator_provider: "local_deterministic_embedding",
          recruiter_facing_summary: "Verified.",
          evidence_summary: "Matched.",
          limitations: "Visible code only.",
          recommended_next_action: "No further action required.",
          strongest_matching_segment_start: 20,
          strongest_matching_segment_end: 32,
          strongest_matching_segment_summary: "Trains the model.",
          matched_segments: [],
          source_snapshot: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
      return
    }

    if (pathname.endsWith("/github-recruiter-proof-reports") && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "github-report-1",
          evidence_id: pathname.split("/")[5],
          github_semantic_result_id: "github-semantic-1",
          user_id: "student-user",
          report_status: "verified",
          confidence_score: 0.96,
          report_version: "github-recruiter-proof-report-v1",
          student_claim: "Built and evaluated a model.",
          headline: "Selected GitHub code supports the student’s claim.",
          recruiter_summary: "VeriBridge found that the selected code supports the student’s claim.",
          evidence_summary: "Training and evaluation logic detected.",
          limitations: "Visible code only.",
          recommended_next_action: "No further action required.",
          confirmed_capabilities: [],
          missing_capabilities: [],
          supporting_line_ranges: [],
          report_snapshot: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      })
      return
    }

    if (pathname.endsWith("/evidence-access-links") && method === "POST") {
      const evidenceId = pathname.split("/")[5]
      const evidence = state.evidence.find((row) => row.id === evidenceId)
      const links =
        evidence?.evidence_type === "deployed website"
          ? [
              {
                id: "website-link-1",
                evidence_id: evidenceId,
                source_report_type: "website_semantic_verification_result",
                source_report_id: "semantic-run-1",
                access_type: "live_website",
                label: "Open Live Website",
                url: String(evidence?.evidence_url ?? "https://student-app.example.com"),
                source_type: "website",
                file_path: null,
                line_start: null,
                line_end: null,
                availability_status: "available",
                notes: null,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ]
          : [
              {
                id: "github-link-1",
                evidence_id: evidenceId,
                source_report_type: "github_recruiter_proof_report",
                source_report_id: "github-report-1",
                access_type: "github_exact_lines",
                label: "View Exact Code Lines",
                url: "https://github.com/maya/proof-app/blob/main/app/main.py#L20-L32",
                source_type: "github",
                file_path: "app/main.py",
                line_start: 20,
                line_end: 32,
                availability_status: "available",
                notes: null,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ]
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results: links }),
      })
      return
    }

    await route.continue()
  })
}

async function mockOnboardingProofBuilderOffline(page: Page) {
  await page.route("**/api/v1/student/skill-evidence**", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "offline demo mode" }),
      })
      return
    }
    await route.continue()
  })
}

async function mockRecruiterRealProofApis(page: Page) {
  const realEvidenceRows: Array<Record<string, unknown>> = [
    {
      id: "boston-github-evidence",
      user_id: "student-user",
      skill_name: "Machine Learning",
      evidence_type: "github repository",
      repository_url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
      file_path: "api.py",
      line_start: 19,
      line_end: 23,
      evidence_description: "I built and evaluated a Decision Tree classification model for route risk prediction.",
      proof_visibility: "public",
      metadata: {
        proof_kind: "github_code",
        evidence_title: "Boston Smart Accident Risk and Rerouting System",
        submission_source: "student_profile_proof_modal",
        branch_ref: "main",
        proof_verification_reconciliation: {
          available: true,
          displayStatus: "supported_with_review",
          confidenceBand: "medium",
          shortDisplayLabel: "Supported with review",
          studentFacingMessage: "Relevant evidence was found, but some claim details still benefit from review.",
          recruiterFacingMessage: "Relevant evidence was found, but some claim details still benefit from review.",
          reviewRecommended: true,
          notes: "Supportive but cautious Boston proof calibration result.",
          technicalStatuses: {
            baseEvidenceStatus: "verified",
            semanticStatus: "needs_human_review",
          },
        },
      },
      verification_status: "verified",
      verification_summary: "Model training and evaluation logic detected.",
      verifier_version: "mock-v1",
      created_at: "2026-05-19T00:00:00.000Z",
      updated_at: "2026-05-19T00:00:00.000Z",
    },
    {
      id: "boston-website-evidence",
      user_id: "student-user",
      skill_name: "Web Applications",
      evidence_type: "deployed website",
      evidence_url: "https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app",
      evidence_description: "After the user enters a source and destination, the website analyzes route risk and shows a safer rerouting recommendation.",
      proof_visibility: "public",
      metadata: {
        proof_kind: "website_live_demo",
        evidence_title: "Boston Smart Accident Risk and Rerouting System",
        submission_source: "student_profile_proof_modal",
        proof_verification_reconciliation: {
          available: true,
          displayStatus: "supported_with_review",
          confidenceBand: "medium",
          shortDisplayLabel: "Supported with review",
          studentFacingMessage: "Relevant evidence was found, but some claim details still benefit from review.",
          recruiterFacingMessage: "Relevant evidence was found, but some claim details still benefit from review.",
          reviewRecommended: true,
          notes: "Supportive but cautious Boston proof calibration result.",
          technicalStatuses: {
            baseEvidenceStatus: "verified",
            semanticStatus: "needs_human_review",
          },
        },
      },
      verification_status: "verified",
      verification_summary: "Website flow matched the claimed route-risk feature.",
      verifier_version: "mock-v1",
      created_at: "2026-05-19T00:01:00.000Z",
      updated_at: "2026-05-19T00:01:00.000Z",
    },
    {
      id: "decision-tree-github-evidence",
      user_id: "student-user",
      skill_name: "Machine Learning",
      evidence_type: "github repository",
      repository_url: "https://github.com/maya/decision-tree-project",
      file_path: "Tree.py",
      line_start: 20,
      line_end: 61,
      evidence_description: "I built and evaluated a Decision Tree classification model.",
      proof_visibility: "public",
      metadata: {
        proof_kind: "github_code",
        evidence_title: "Decision Tree Classification Model",
        submission_source: "student_profile_proof_modal",
      },
      verification_status: "verified",
      verification_summary: "Python usage likely found ✅",
      verifier_version: "mock-v1",
      created_at: "2026-05-18T00:00:00.000Z",
      updated_at: "2026-05-18T00:00:00.000Z",
    },
    {
      id: "route-risk-website-evidence",
      user_id: "student-user",
      skill_name: "Web Applications",
      evidence_type: "deployed website",
      evidence_url: "https://route-risk-demo.example.com",
      evidence_description: "Public deployed proof only.",
      proof_visibility: "public",
      metadata: {
        proof_kind: "website_live_demo",
        evidence_title: "Route Risk Demo Deployment",
        submission_source: "student_profile_proof_modal",
      },
      verification_status: "verified",
      verification_summary: "Website flow matched the claimed route-risk feature.",
      verifier_version: "mock-v1",
      created_at: "2026-05-17T00:00:00.000Z",
      updated_at: "2026-05-17T00:00:00.000Z",
    },
  ]

  await page.route("**/api/v1/student/skill-evidence**", async (route) => {
    const url = new URL(route.request().url())
    const { pathname } = url
    const method = route.request().method()

    if (pathname === "/api/v1/student/skill-evidence" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(realEvidenceRows),
      })
      return
    }

    if (pathname.endsWith("/evidence-access-links/latest") && method === "GET") {
      const evidenceId = pathname.split("/")[5]
      const isGithub = evidenceId.includes("github")
      const isBoston = evidenceId.includes("boston")
      const results =
        isGithub && isBoston
          ? [
              {
                id: "boston-github-link",
                evidence_id: evidenceId,
                source_report_type: "github_recruiter_proof_report",
                source_report_id: "boston-github-report",
                access_type: "github_exact_lines",
                label: "View Code Lines 19–23",
                url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud/blob/main/api.py#L19-L23",
                source_type: "github",
                file_path: "api.py",
                line_start: 19,
                line_end: 23,
                availability_status: "available",
                notes: "Boston code lines from the recruiter proof report.",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ]
          : isGithub
            ? [
                {
                  id: "decision-tree-link",
                  evidence_id: evidenceId,
                  source_report_type: "github_recruiter_proof_report",
                  source_report_id: "decision-tree-report",
                  access_type: "github_exact_lines",
                  label: "View Exact Code Lines",
                  url: "https://github.com/maya/decision-tree-project/blob/main/Tree.py#L20-L61",
                  source_type: "github",
                  file_path: "Tree.py",
                  line_start: 20,
                  line_end: 61,
                  availability_status: "available",
                  notes: "Decision Tree code lines from the recruiter proof report.",
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                },
              ]
            : isBoston
              ? [
                  {
                    id: "boston-website-link",
                    evidence_id: evidenceId,
                    source_report_type: "website_semantic_verification_result",
                    source_report_id: "boston-website-report",
                    access_type: "live_website",
                    label: "Open Live Website",
                    url: "https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app",
                    source_type: "website",
                    file_path: null,
                    line_start: null,
                    line_end: null,
                    availability_status: "available",
                    notes: "Boston public deployed proof from the semantic verification report.",
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                  },
                ]
              : [
                  {
                    id: "route-risk-live-link",
                    evidence_id: evidenceId,
                    source_report_type: "website_semantic_verification_result",
                    source_report_id: "route-risk-report",
                    access_type: "live_website",
                    label: "Open Live Website",
                    url: "https://route-risk-demo.example.com",
                    source_type: "website",
                    file_path: null,
                    line_start: null,
                    line_end: null,
                    availability_status: "available",
                    notes: "Public deployed proof inspected through the semantic verification report.",
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                  },
                ]

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ results }),
      })
      return
    }

    await route.continue()
  })
}

async function mockRecruiterDemoProofFallback(page: Page) {
  await page.route("**/api/v1/student/skill-evidence**", async (route) => {
    const url = new URL(route.request().url())
    const { pathname } = url
    const method = route.request().method()

    if (pathname === "/api/v1/student/skill-evidence" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      })
      return
    }

    await route.continue()
  })
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
    await expect(page.getByRole("link", { name: /Visa Fit/i })).toHaveAttribute("href", "/dashboard/visa-fit");
  });

  test("sidebar Onboarding → /dashboard/onboarding", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Onboarding/i })).toHaveAttribute("href", "/dashboard/onboarding");
  });

  test("sidebar Profile & Proof → /dashboard/profile", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Profile/i })).toHaveAttribute("href", "/dashboard/profile");
  });

  test("sidebar Job Matches → /dashboard/jobs", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Job Matches/i })).toHaveAttribute("href", "/dashboard/jobs");
  });

  test("sidebar Applications → /dashboard/applications", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Applications/i })).toHaveAttribute("href", "/dashboard/applications");
  });

  test("sidebar Skill Gaps → /dashboard/skill-gaps", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Skill Gaps/i })).toHaveAttribute("href", "/dashboard/skill-gaps");
  });

  test("sidebar Mock Interview → /dashboard/mock-interview", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Mock Interview/i })).toHaveAttribute("href", "/dashboard/mock-interview");
  });

  test("sidebar Settings → /dashboard/settings", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Settings/i })).toHaveAttribute("href", "/dashboard/settings");
  });

  test("sidebar Privacy → /dashboard/privacy", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Privacy/i })).toHaveAttribute("href", "/dashboard/privacy");
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
    await expect(page.getByLabel("University country")).toHaveValue("");
    await expect(page.getByRole("button", { name: "Degree level" })).toContainText("Select an option");
    const degreeHeightBefore = await controlHeight(page.getByRole("button", { name: "Degree level" }));
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

  test("starts with no preselected roles, industries, skills, or proof evidence", async ({ page }) => {
    await page.goto("/dashboard/onboarding");
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByText("No target roles selected yet. Add the roles you want to apply for.")).toBeVisible();
    await expect(page.getByText("No target industries selected yet. Add the industries you are interested in.")).toBeVisible();
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByText("No skills added yet. Start with your strongest technical, AI, data, cloud, or project skills.")).toBeVisible();
    await expect(page.getByText("No proof evidence added yet. Attach proof such as GitHub, LinkedIn, certificates, reports, demos, or dashboards.")).toBeVisible();
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

  test("skills proof builder renders and verifies proof evidence", async ({ page }) => {
    await mockOnboardingProofBuilderOffline(page);
    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Artificial Intelligence");
    await page.getByRole("option", { name: "Artificial Intelligence", exact: true }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Skills & Proof Evidence" })).toBeVisible();
    await expect(page.getByText(/Add skills you want recruiters to trust/i)).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: "Proof Evidence Builder" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Public link" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload file" })).toBeVisible();
    await page.getByLabel("Suggested skills").click();
    await expect(page.getByRole("option", { name: "Python" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Machine Learning" })).toBeVisible();
    await expect(page.getByRole("option", { name: "RAG" })).toBeVisible();
    await expect(page.getByRole("option", { name: "LLMs" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Financial Modeling" })).toHaveCount(0);
    await page.getByRole("option", { name: "Python" }).click();
    await page.getByLabel("Suggested skills").click();
    await page.getByRole("option", { name: "Machine Learning" }).click();
    await expect(page.getByRole("button", { name: /Python ×/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Machine Learning ×/ })).toBeVisible();
    await page.getByLabel("Add a skill").fill("AWS");
    await page.getByRole("button", { name: "Add skill to inventory" }).click();
    await expect(page.getByRole("button", { name: /AWS ×/ })).toBeVisible();
    await expect(page.getByText(/3 skills in inventory/i).first()).toBeVisible();
    await page.getByLabel("Add a skill").fill("RAG");
    await page.getByRole("button", { name: "Add skill to inventory" }).click();
    await expect(page.getByRole("button", { name: /RAG ×/ })).toBeVisible();
    await expect(page.getByText(/4 skills in inventory/i).first()).toBeVisible();
    await page.getByRole("button", { name: /RAG ×/ }).click();
    await expect(page.getByRole("button", { name: /RAG ×/ })).toHaveCount(0);
    await expect(page.getByText(/3 skills in inventory/i).first()).toBeVisible();

    const proofSkillField = page.getByRole("textbox", { name: "Skill", exact: true });
    await proofSkillField.click();
    await expect(page.getByRole("option", { name: "Python" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Machine Learning" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Financial Modeling" })).toHaveCount(0);
    await page.getByRole("option", { name: "Python" }).click();
    await expect(page.getByText(/Good Python proof can include/i)).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Skill", exact: true })).toHaveValue("Python");
    await page.getByLabel("Evidence source type").click();
    await expect(page.getByRole("option", { name: "GitHub file", exact: true })).toBeVisible();
    await page.getByRole("option", { name: "GitHub file", exact: true }).click();
    await expect(page.getByLabel("Repository URL / Evidence URL")).toBeVisible();
    await expect(page.getByLabel("File path")).toBeVisible();
    await expect(page.getByLabel("Start line")).toBeVisible();
    await expect(page.getByLabel("End line")).toBeVisible();
    await expect(page.getByLabel("Evidence description", { exact: true })).toHaveCount(1);
    await page.getByLabel("Repository URL / Evidence URL").fill("https://github.com/user/project");
    await page.getByLabel("File path").fill("app/main.py");
    await page.getByLabel("Start line").fill("20");
    await page.getByLabel("End line").fill("95");
    await page.getByLabel("Evidence description", { exact: true }).fill("Built FastAPI prediction endpoint using Python.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText("Skill: Python")).toBeVisible();
    await expect(page.getByText("Evidence source: GitHub file")).toBeVisible();
    await expect(page.getByText("Repository URL: https://github.com/user/project")).toBeVisible();
    await expect(page.getByText("File path: app/main.py")).toBeVisible();
    await expect(page.getByText("Lines: 20–95")).toBeVisible();
    await expect(page.getByTestId("proof-evidence-card").filter({ hasText: "File path: app/main.py" })).toContainText("Verification:");
    await expect(page.getByText(/1 proof items added/i).first()).toBeVisible();

    await proofSkillField.click();
    await page.getByRole("option", { name: "Machine Learning", exact: true }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "GitHub file", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://github.com/user/ml-project");
    await page.getByLabel("File path").fill("Tree.py");
    await page.getByLabel("Evidence description", { exact: true }).fill("Used a decision tree Machine Learning model.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    const machineLearningFileCard = page.getByTestId("proof-evidence-card").filter({ hasText: "File path: Tree.py" });
    await expect(machineLearningFileCard).toContainText("Skill: Machine Learning");
    await expect(machineLearningFileCard).toContainText("File path: Tree.py");
    await expect(machineLearningFileCard).toContainText(/Machine Learning evidence likely found/i);
    await expect(machineLearningFileCard).toContainText(/Python\/Notebook file and ML keywords detected/i);

    await proofSkillField.click();
    await page.getByRole("option", { name: "Python", exact: true }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Presentation deck", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://example.com/presentation.pdf");
    await page.getByLabel("File path").fill("presentation.pdf");
    await page.getByLabel("Evidence description", { exact: true }).fill("Presentation deck for a class project.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText(/Skill usage not found in the provided file path/i)).toBeVisible();

    await page.getByLabel("Add a skill").fill("RAG");
    await page.getByRole("button", { name: "Add skill to inventory" }).click();
    await proofSkillField.click();
    await page.getByRole("option", { name: "RAG", exact: true }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "GitHub file", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://github.com/user/rag-project");
    await page.getByLabel("File path").fill("rag_pipeline.py");
    await page.getByLabel("Evidence description", { exact: true }).fill("Built embeddings and retrieval for a RAG pipeline.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText("Skill: RAG")).toBeVisible();
    await expect(page.getByText("File path: rag_pipeline.py")).toBeVisible();
    await expect(page.getByText(/AI\/LLM evidence likely found/i)).toBeVisible();

    await proofSkillField.click();
    await page.getByRole("option", { name: "AWS", exact: true }).click();
    await expect(page.getByText(/Good AWS proof can include/i)).toBeVisible();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Deployed app", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://cloud.example.com");
    await page.getByLabel("File path").fill("infra/main.tf");
    await page.getByLabel("Evidence description", { exact: true }).fill("Deployed an app on AWS with Terraform.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    const awsEvidenceCard = page.getByTestId("proof-evidence-card").filter({ hasText: "Skill: AWS" }).filter({ hasText: "Evidence source: Deployed app" });
    await expect(awsEvidenceCard).toBeVisible();
    await expect(awsEvidenceCard).toContainText("Verification: Pending review");

    await proofSkillField.click();
    await page.getByRole("option", { name: "Machine Learning", exact: true }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Certificate", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://credential.example.com/cert");
    await page.getByLabel("Evidence description", { exact: true }).fill("Completed a machine learning certificate.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    const certificateCard = page.getByTestId("proof-evidence-card").filter({ hasText: "Evidence source: Certificate" });
    await expect(certificateCard).toContainText("Skill: Machine Learning");
    await expect(certificateCard).toContainText("Evidence source: Certificate");
    await expect(certificateCard).toContainText("Verification: Pending review");

    await proofSkillField.click();
    await page.getByRole("option", { name: "AWS", exact: true }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "LinkedIn post", exact: true }).click();
    await page.getByLabel("Repository URL / Evidence URL").fill("https://www.linkedin.com/posts/example");
    await page.getByLabel("Evidence description", { exact: true }).fill("LinkedIn post about a cloud deployment project.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    const linkedInCard = page.getByTestId("proof-evidence-card").filter({ hasText: "Evidence source: LinkedIn post" });
    await expect(linkedInCard).toContainText("Skill: AWS");
    await expect(linkedInCard).toContainText("Evidence source: LinkedIn post");
    await expect(linkedInCard).toContainText("Repository URL: https://www.linkedin.com/posts/example");
  });

  test("upload file evidence flow supports report image and video uploads", async ({ page }) => {
    await mockOnboardingProofBuilderOffline(page);
    await page.goto("/dashboard/onboarding");
    await page.getByLabel("Major / field of study").fill("Artificial Intelligence");
    await page.getByRole("option", { name: "Artificial Intelligence", exact: true }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Suggested skills").click();
    await page.getByRole("option", { name: "Python", exact: true }).click();
    await page.getByLabel("Add a skill").fill("AWS");
    await page.getByRole("button", { name: "Add skill to inventory" }).click();

    const proofSkillField = page.getByRole("textbox", { name: "Skill", exact: true });
    await proofSkillField.click();
    await page.getByRole("option", { name: "AWS", exact: true }).click();

    await page.getByRole("button", { name: "Upload file" }).click();
    await expect(page.getByLabel("Upload evidence file")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Recruiter visibility" })).toHaveAttribute("aria-checked", "false");

    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Lab report", exact: true }).click();
    await expect(page.getByLabel("Evidence description", { exact: true })).toHaveCount(1);
    await expect(page.getByLabel("Start line")).toHaveCount(0);
    await expect(page.getByLabel("End line")).toHaveCount(0);
    await expect(page.getByLabel("Live demo URL")).toHaveCount(0);
    await expect(page.getByLabel("Repository URL", { exact: true })).toHaveCount(0);
    await page.getByLabel("Upload evidence file").setInputFiles({
      name: "report.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4\n%demo pdf"),
    });
    await page.getByLabel("Evidence title").fill("Quarterly report");
    await page.getByLabel("Related project/repository URL (optional)").fill("https://github.com/user/report");
    await expect(page.getByLabel("Evidence description", { exact: true })).toHaveCount(1);
    await page.getByLabel("Evidence description", { exact: true }).fill("Quarterly report proving project delivery.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText("Uploaded file: report.pdf")).toBeVisible();
    await expect(page.getByText("File type: application/pdf")).toBeVisible();
    await expect(page.getByText("Evidence description: Quarterly report proving project delivery.")).toBeVisible();
    await expect(page.getByText("Visibility: Private")).toBeVisible();
    await expect(page.getByTestId("proof-evidence-card").filter({ hasText: "Uploaded file: report.pdf" })).toContainText("Verification:");

    await proofSkillField.click();
    await page.getByRole("option", { name: "AWS", exact: true }).click();
    await page.getByRole("button", { name: "Upload file" }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Design portfolio", exact: true }).click();
    await expect(page.getByLabel("Start line")).toHaveCount(0);
    await expect(page.getByLabel("Live demo URL")).toHaveCount(0);
    await page.getByRole("switch", { name: "Recruiter visibility" }).click();
    await page.getByRole("switch", { name: "Require my approval before each recruiter can view this evidence" }).click();
    await page.getByLabel("Upload evidence file").setInputFiles({
      name: "architecture.png",
      mimeType: "image/png",
      buffer: Buffer.from("png-demo"),
    });
    await page.getByLabel("Evidence description", { exact: true }).fill("Architecture diagram proving system design.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText("Uploaded file: architecture.png")).toBeVisible();
    await expect(page.getByText("File type: image/png")).toBeVisible();
    await expect(page.getByText("Visibility: Approval required for recruiters")).toBeVisible();
    await page.getByRole("button", { name: "Show evidence" }).last().click();
    await expect(page.getByAltText("architecture.png")).toBeVisible();
    await expect(page.getByText(/Request access to view this evidence/i)).toHaveCount(0);

    await proofSkillField.click();
    await page.getByRole("option", { name: "AWS", exact: true }).click();
    await page.getByRole("button", { name: "Upload file" }).click();
    await page.getByLabel("Evidence source type").click();
    await page.getByRole("option", { name: "Demo video", exact: true }).click();
    await expect(page.getByLabel("Evidence description", { exact: true })).toHaveCount(1);
    await expect(page.getByLabel("Live demo URL")).toHaveCount(0);
    await expect(page.getByLabel("Repository URL", { exact: true })).toHaveCount(0);
    await page.getByLabel("Upload evidence file").setInputFiles({
      name: "demo.mp4",
      mimeType: "video/mp4",
      buffer: Buffer.from("mp4-demo"),
    });
    await page.getByLabel("Evidence description", { exact: true }).fill("Recorded demo presentation video.");
    await page.getByRole("button", { name: "Add proof evidence" }).click();
    await expect(page.getByText("Uploaded file: demo.mp4")).toBeVisible();
    await expect(page.getByText("File type: video/mp4")).toBeVisible();
    await expect(page.getByText("Visibility: Approval required for recruiters")).toBeVisible();
    await page.getByRole("button", { name: "Show evidence" }).last().click();
    await expect(page.locator("video").last()).toBeVisible();
    await expect(page.getByText(/Request access to view this evidence/i)).toHaveCount(0);
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
    await expect(page.getByRole("textbox", { name: "Currency", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Salary period" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open to negotiation" })).toBeVisible();
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
    await expect(page.getByRole("link", { name: /Job Posts/i })).toHaveAttribute("href", "/recruiter/company");
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
    await expect(page.getByRole("link", { name: /Readiness/i })).toHaveAttribute("href", "/university/analytics");
  });

  test("sidebar /university/skill-gaps link works", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Skill gaps/i })).toHaveAttribute("href", "/university/skill-gaps");
  });

  test("sidebar /university/outcomes link works", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Outcomes/i })).toHaveAttribute("href", "/university/outcomes");
  });

  test("sidebar /university/employers link works", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Employer/i })).toHaveAttribute("href", "/university/employers");
  });

  test("sidebar /university/privacy link works", async ({ page }) => {
    await expect(page.getByRole("link", { name: /Privacy/i })).toHaveAttribute("href", "/university/privacy");
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

test.describe("Dashboard empty states", () => {
  test("profile proof starts empty", async ({ page }) => {
    await mockProofSubmissionApis(page);
    await page.goto("/dashboard/profile");
    await expect(page.getByText("Verified skills · none added yet")).toBeVisible();
    await expect(page.getByText("Proof evidence · none added yet")).toBeVisible();
    await expect(page.getByText(/No skills have been added to this profile yet/i)).toBeVisible();
    await expect(page.getByText(/No proof evidence has been attached yet/i)).toBeVisible();
  });

  test("settings target roles and compensation start empty", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await expect(page.getByText(/No target roles selected yet/i)).toBeVisible();
    await expect(page.getByText(/No salary preference set yet/i)).toBeVisible();
    await expect(page.getByPlaceholder("Add your major in onboarding")).toBeVisible();
    await expect(page.getByPlaceholder("Add location preferences in onboarding")).toBeVisible();
  });
});

test.describe.serial("Student proof submission modal", () => {
  test.beforeEach(async ({ page }) => {
    await mockProofSubmissionApis(page);
    await page.goto("/dashboard/profile");
  });

  test("opens GitHub and website tabs", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await expect(page.getByTestId("proof-submission-modal")).toBeVisible();
    await expect(page.getByTestId("proof-tab-github")).toHaveAttribute("aria-selected", "true");

    await page.getByTestId("proof-tab-website").click();
    await expect(page.getByTestId("proof-tab-website")).toHaveAttribute("aria-selected", "true");
  });

  test("blocks invalid GitHub line range", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await page.getByRole("tab", { name: "GitHub Code" }).click();
    await page.getByLabel("Skill you want to prove").fill("Machine Learning");
    await page.getByLabel("What does this code prove?").fill("This code trains and evaluates a machine learning model.")
    await page.getByLabel("GitHub repository URL").fill("https://github.com/maya/proof-app")
    await page.getByLabel("File path inside the repo").fill("app/main.py")
    await page.getByLabel("Start line").fill("32")
    await page.getByLabel("End line").fill("20")
    await page.getByTestId("proof-submit-action").click()
    await expect(page.locator('[role="alert"]').filter({ hasText: "End line must be the same as or greater than the start line." })).toBeVisible()
  });

  test("blocks website feature descriptions under the word minimum", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await page.getByRole("tab", { name: "Live Website" }).click();
    await page.getByLabel("Skill you want to prove").fill("Product Design");
    await page.getByLabel("Live website URL").fill("https://student-app.example.com")
    await page.getByLabel("Feature to verify").fill("Shows safer route.")
    await page.getByRole("textbox", { name: "Expected output" }).fill("A risk score card appears on screen.")
    await page.getByLabel("Verification steps").fill("Open the deployed site\nRun the main action")
    await page.getByTestId("proof-submit-action").click()
    await expect(page.locator('[role="alert"]').filter({ hasText: "Feature description must contain at least 20 words." })).toBeVisible()
  });

  test("blocks website expected output descriptions under the word minimum", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await page.getByRole("tab", { name: "Live Website" }).click();
    await page.getByLabel("Skill you want to prove").fill("Product Design");
    await page.getByLabel("Live website URL").fill("https://student-app.example.com")
    await page.getByLabel("Feature to verify").fill(
      "After the user enters a source and destination, the website analyzes route risk for the trip and displays a safer rerouting recommendation on the results screen."
    )
    await page.getByRole("textbox", { name: "Expected output" }).fill("A result appears.")
    await page.getByLabel("Verification steps").fill("Open the deployed site\nRun the main action")
    await page.getByTestId("proof-submit-action").click()
    await expect(page.locator('[role="alert"]').filter({ hasText: "Expected output must contain at least 8 words." })).toBeVisible()
  });

  test("submits GitHub proof successfully", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await page.getByRole("tab", { name: "GitHub Code" }).click();
    await page.getByLabel("Skill you want to prove").fill("Machine Learning");
    await page.getByLabel("Project or evidence title").fill("Decision Tree Stroke Project");
    await page.getByLabel("What does this code prove?").fill("I built and evaluated a Decision Tree classification model for stroke prediction.")
    await page.getByLabel("GitHub repository URL").fill("https://github.com/maya/proof-app")
    await page.getByLabel("File path inside the repo").fill("app/main.py")
    await page.getByLabel("Start line").fill("20")
    await page.getByLabel("End line").fill("61")
    await page.getByTestId("proof-submit-action").click()
    await expect(page.getByRole("heading", { name: "GitHub proof submitted successfully." })).toBeVisible()
    await expect(page.getByText("Claim verification: Evidence accepted.")).toBeVisible()
    await page.getByRole("button", { name: "Done" }).click()
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toBeVisible()
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toContainText("Machine Learning")
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toContainText("Evidence accepted")
  });

  test("submits website proof successfully", async ({ page }) => {
    await page.getByTestId("open-proof-submission-modal").click();
    await page.getByRole("tab", { name: "Live Website" }).click();
    await page.getByLabel("Skill you want to prove").fill("Web Applications");
    await page.getByLabel("Project or evidence title").fill("Boston Accident Risk Rerouting");
    await page.getByLabel("Live website URL").fill("https://student-app.example.com")
    await page.getByLabel("Feature to verify").fill(
      "After the user enters a source and destination, the website analyzes route risk for the trip and displays a safer rerouting recommendation."
    )
    await page.getByRole("textbox", { name: "Expected output" }).fill("A risk score card and safer route recommendation appear on the results section.")
    await page.getByLabel("Verification steps").fill("Open the deployed site\nEnter route inputs\nTrigger the analysis action")
    await page.getByTestId("proof-submit-action").click()
    await expect(page.getByRole("heading", { name: "Website proof submitted successfully." })).toBeVisible()
    await expect(page.getByText("Claim verification: Evidence accepted.")).toBeVisible()
    await page.getByRole("button", { name: "Done" }).click()
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toBeVisible()
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toContainText("Web Applications")
    await expect(page.getByTestId("student-proof-evidence-evidence-1")).toContainText("Evidence accepted")
  });
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

/* ── Recruiter verified skill search (Phase J1 + J2) ── */

async function mockRecruiterCandidateSearch(
  page: Page,
  results: Array<Record<string, unknown>> = [],
) {
  await page.route("**/api/v1/recruiter/candidates/search**", async (route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get("query") ?? "";
    const filtered = results.filter((r) => {
      const skills = r.matched_skill_names as string[];
      return skills.some((s) => s.toLowerCase().includes(query.toLowerCase()));
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query,
        results: filtered,
        result_count: filtered.length,
      }),
    });
  });
}

async function mockRecruiterCandidateDetail(
  page: Page,
  detailByUserId: Record<string, Record<string, unknown>> = {},
) {
  await page.route("**/api/v1/recruiter/candidates/*/detail", async (route) => {
    const segments = new URL(route.request().url()).pathname.split("/");
    const userId = segments[segments.length - 2] ?? "";
    const detail = detailByUserId[userId];
    if (!detail) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Candidate not found." }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(detail),
    });
  });
}

const MOCK_CANDIDATE: Record<string, unknown> = {
  user_id: "user-ml-01",
  display_name: "Mohammed Mubashir Uddin Faraz",
  school_name: "WPI",
  degree: "MS AI",
  major: "Artificial Intelligence",
  matched_skill_names: ["Machine Learning"],
  evidence_count: 2,
  accepted_evidence_count: 2,
  has_github_proof: true,
  has_website_proof: true,
  strongest_project_title: "Boston Smart Accident Risk and Rerouting System",
  proof_status_label: "Evidence Accepted",
};

test.describe("Recruiter verified skill search — Phase J1", () => {
  test("search bar is editable and search button exists", async ({ page }) => {
    await mockRecruiterCandidateSearch(page);
    await page.goto("/recruiter");
    const input = page.getByTestId("recruiter-search-input");
    await expect(input).toBeVisible();
    await expect(input).not.toHaveAttribute("readOnly");
    await expect(page.getByTestId("recruiter-search-submit")).toBeVisible();
  });

  test("submitting a query shows real proof-backed candidate cards", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("recruiter-search-results")).toBeVisible();
    // name and status appear in both card and auto-selected detail panel — check first occurrence
    await expect(page.getByText("Mohammed Mubashir Uddin Faraz").first()).toBeVisible();
    await expect(page.getByText("Evidence Accepted").first()).toBeVisible();
    await expect(page.getByText("Machine Learning").first()).toBeVisible();
  });

  test("entering a query with Enter key triggers search", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("recruiter-search-results")).toBeVisible();
    await expect(page.getByText("Mohammed Mubashir Uddin Faraz").first()).toBeVisible();
  });

  test("candidate card shows GitHub and live site proof badges", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByText("⌥ GitHub")).toBeVisible();
    await expect(page.getByText("▤ Live site")).toBeVisible();
  });

  test("candidate card shows strongest project title", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    // title appears in card + auto-selected detail panel
    await expect(page.getByText("Boston Smart Accident Risk and Rerouting System").first()).toBeVisible();
  });

  test("clicking a search result shows the detail panel", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    // 404 for detail → error state still shows proof overview and fallback skills
    await mockRecruiterCandidateDetail(page, {});
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await page.getByTestId(`search-result-card-${MOCK_CANDIDATE.user_id}`).click();
    // Proof overview stats are always rendered regardless of detail fetch state
    await expect(page.getByTestId("detail-proof-overview")).toBeVisible();
  });

  test("no-results state renders cleanly", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, []);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("COBOL");
    await page.getByTestId("recruiter-search-submit").click();
    // testid is the most precise locator; text appears in both heading and count label
    await expect(page.getByTestId("recruiter-search-empty")).toBeVisible();
    await expect(page.getByTestId("recruiter-search-empty")).toContainText("No candidates found");
  });

  test("clear button resets to default demo state", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("recruiter-search-results")).toBeVisible();
    await page.getByTestId("recruiter-search-clear").click();
    await expect(page.getByTestId("recruiter-search-results")).toHaveCount(0);
  });

  test("result count label shows number of matches", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByText(/1 proof-backed candidate found/i)).toBeVisible();
  });
});

/* ── Recruiter candidate detail — Phase J2 ── */

const MOCK_CANDIDATE_DETAIL: Record<string, unknown> = {
  candidate_id: "user-ml-01",
  display_name: "Mohammed Mubashir Uddin Faraz",
  school_name: "WPI",
  degree: "MS AI",
  major: "Artificial Intelligence",
  proof_overview: {
    total_evidence_count: 2,
    accepted_evidence_count: 2,
    github_proof_count: 1,
    website_proof_count: 1,
    strongest_display_status: "Evidence Accepted",
  },
  verified_or_supported_skills: [
    { skill_name: "Machine Learning", evidence_count: 2, strongest_status_label: "Evidence Accepted" },
  ],
  proof_projects: [
    {
      project_title: "Boston Smart Accident Risk and Rerouting System",
      status_label: "Evidence Accepted",
      status_code: "verified",
      has_github_proof: true,
      has_website_proof: true,
      recruiter_summary: "Model training and evaluation logic detected.",
      associated_skill_labels: ["Machine Learning"],
      evidence_access_links: [
        {
          id: "link-github-1",
          label: "View Exact Code Lines",
          url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud/blob/main/api.py#L19-L23",
          access_type: "github_exact_lines",
          source_type: "github",
          file_path: "api.py",
          line_start: 19,
          line_end: 23,
          availability_status: "available",
        },
        {
          id: "link-website-1",
          label: "Open Live Website",
          url: "https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app",
          access_type: "live_website",
          source_type: "website",
          file_path: null,
          line_start: null,
          line_end: null,
          availability_status: "available",
        },
      ],
    },
  ],
};

test.describe("Recruiter candidate detail — Phase J2", () => {
  test("search results still appear as in J1", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("recruiter-search-results")).toBeVisible();
    await expect(page.getByText("Mohammed Mubashir Uddin Faraz").first()).toBeVisible();
  });

  test("first result auto-select triggers detail fetch and renders overview", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    // Auto-select fires detail fetch; wait for overview stats to populate
    await expect(page.getByTestId("detail-proof-overview")).toBeVisible();
    // After detail loads, overview values come from real detail response
    await expect(page.getByTestId("detail-proof-overview")).toContainText("2");
  });

  test("clicking a different result updates the detail panel", async ({ page }) => {
    const secondCandidate: Record<string, unknown> = {
      user_id: "user-ml-02",
      display_name: "Alice Nguyen",
      school_name: "MIT",
      degree: "BS",
      major: "Computer Science",
      matched_skill_names: ["Machine Learning"],
      evidence_count: 1,
      accepted_evidence_count: 1,
      has_github_proof: true,
      has_website_proof: false,
      strongest_project_title: "Alice ML Project",
      proof_status_label: "Evidence Accepted",
    };
    const secondDetail: Record<string, unknown> = {
      candidate_id: "user-ml-02",
      display_name: "Alice Nguyen",
      school_name: "MIT",
      degree: "BS",
      major: "Computer Science",
      proof_overview: { total_evidence_count: 1, accepted_evidence_count: 1, github_proof_count: 1, website_proof_count: 0, strongest_display_status: "Evidence Accepted" },
      verified_or_supported_skills: [{ skill_name: "Machine Learning", evidence_count: 1, strongest_status_label: "Evidence Accepted" }],
      proof_projects: [],
    };
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE, secondCandidate]);
    await mockRecruiterCandidateDetail(page, {
      "user-ml-01": MOCK_CANDIDATE_DETAIL,
      "user-ml-02": secondDetail,
    });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    // Click the second candidate card
    await page.getByTestId("search-result-card-user-ml-02").click();
    // Detail panel header should update to Alice's name
    await expect(page.getByText("Alice Nguyen").first()).toBeVisible();
  });

  test("detail panel shows proof overview counts from real detail response", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("detail-proof-overview")).toBeVisible();
    // The overview grid should render stat labels from real detail
    await expect(page.getByTestId("detail-proof-overview")).toContainText("Total evidence");
    await expect(page.getByTestId("detail-proof-overview")).toContainText("Accepted");
  });

  test("detail panel shows project title from real detail response", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("detail-proof-projects")).toBeVisible();
    // Scope to the detail projects section to avoid strict-mode conflict with the search card
    await expect(
      page.getByTestId("detail-proof-projects").getByText("Boston Smart Accident Risk and Rerouting System")
    ).toBeVisible();
  });

  test("detail panel renders GitHub exact-line action from detail response", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("detail-proof-projects")).toBeVisible();
    const githubLink = page.locator(
      'a[href="https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud/blob/main/api.py#L19-L23"]'
    ).first();
    await expect(githubLink).toBeVisible();
    await expect(githubLink).toHaveAttribute("target", "_blank");
    await expect(githubLink).toHaveAttribute("rel", /noopener/);
  });

  test("detail panel renders website open action from detail response", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    await mockRecruiterCandidateDetail(page, { "user-ml-01": MOCK_CANDIDATE_DETAIL });
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("detail-proof-projects")).toBeVisible();
    const websiteLink = page.locator(
      'a[href="https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app"]'
    ).first();
    await expect(websiteLink).toBeVisible();
    await expect(websiteLink).toHaveAttribute("target", "_blank");
  });

  test("detail fetch failure shows clean UI message", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, [MOCK_CANDIDATE]);
    // Return 404 for detail to simulate failure
    await mockRecruiterCandidateDetail(page, {});
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("Machine Learning");
    await page.getByTestId("recruiter-search-submit").click();
    // Error message should appear in the panel
    await expect(page.getByTestId("detail-error-message")).toBeVisible();
    await expect(page.getByTestId("detail-error-message")).toContainText("Could not load full proof detail");
  });

  test("J1 no-results behavior still passes", async ({ page }) => {
    await mockRecruiterCandidateSearch(page, []);
    await page.goto("/recruiter");
    await page.getByTestId("recruiter-search-input").fill("COBOL");
    await page.getByTestId("recruiter-search-submit").click();
    await expect(page.getByTestId("recruiter-search-empty")).toBeVisible();
    await expect(page.getByTestId("recruiter-search-empty")).toContainText("No candidates found");
  });
});

test.describe("Recruiter evidence preview", () => {
  test("respects uploaded evidence visibility settings", async ({ page }) => {
    await mockRecruiterDemoProofFallback(page);
    await page.goto("/recruiter");

    await page.getByTestId("evidence-toggle-0").click();
    await expect(page.getByText("Visibility: Private")).toBeVisible();
    await expect(page.getByText(/Evidence exists, but the student has not shared this private file/i)).toBeVisible();

    await page.getByTestId("evidence-toggle-4").click();
    await expect(page.getByText("Visibility: Shared with recruiters")).toBeVisible();
    await expect(page.getByText("Uploaded file: docker-certificate.png")).toBeVisible();
    await expect(page.getByText("File type: image/png")).toBeVisible();

    await page.getByTestId("evidence-toggle-5").click();
    await expect(page.getByText("Visibility: Approval required")).toBeVisible();
    await expect(page.getByText(/Request access to view this evidence/i)).toBeVisible();
  });

  test("shows real Boston project evidence access actions", async ({ page }) => {
    await mockRecruiterRealProofApis(page);
    await page.goto("/recruiter");

    await expect(page.getByText("Real proof bundles loaded from backend submissions.")).toBeVisible();

    await expect(page.getByText("Boston Smart Accident Risk and Rerouting System")).toBeVisible();
    await expect(page.getByText("Supported with review")).toBeVisible();

    const githubLine20 = page.locator('a[href="https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud/blob/main/api.py#L19-L23"]');
    await expect(githubLine20).toBeVisible();
    await expect(githubLine20).toHaveAttribute("target", "_blank");
    await expect(githubLine20).toHaveAttribute("rel", /noopener/);
    await expect(page.getByRole("link", { name: /View Code Lines 19–23/i })).toBeVisible();

    const websiteLink = page.locator('a[href="https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app"]');
    await expect(websiteLink).toBeVisible();
    await expect(websiteLink).toHaveAttribute("target", "_blank");
    await expect(websiteLink).toHaveAttribute("rel", /noopener/);
    await expect(page.getByText("student-app.example.com")).toHaveCount(0);
    await expect(page.getByText(/404/i)).toHaveCount(0);
  });

  test("shows combined project evidence actions for GitHub and website proof", async ({ page }) => {
    await mockRecruiterRealProofApis(page);
    await page.goto("/recruiter");

    await expect(page.getByText("Boston Smart Accident Risk and Rerouting System")).toBeVisible();
    await expect(
      page.locator('a[href="https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud/blob/main/api.py#L19-L23"]')
    ).toBeVisible();
    await expect(page.locator('a[href="https://boston-accident-risk-api-qzr2qvsfqa-uc.a.run.app"]')).toBeVisible();

    await expect(page.locator('a[href="https://github.com/maya/decision-tree-project/blob/main/Tree.py#L20-L61"]')).toBeVisible();
    await expect(page.getByText("Decision Tree Classification Model")).toBeVisible();
    await expect(page.locator('a[href="https://github.com/maya/decision-tree-project/blob/main/Tree.py#L20-L61"]')).toBeVisible();
    await expect(page.getByText("Route Risk Demo Deployment")).toBeVisible();
    await expect(page.locator('a[href="https://route-risk-demo.example.com"]')).toBeVisible();
  });
});
