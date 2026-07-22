/**
 * Skill Gaps page — real evidence-derived surface.
 *
 * The page previously rendered fabricated demo content from data/mock.ts
 * ("Kubernetes 68%", fake jobs/readiness) under a SampleDataNotice. It is now
 * backed by GET /api/v1/student/skill-gaps. Covered here:
 *   1. loading state
 *   2. error state with retry
 *   3. empty state (no projects)
 *   4. per-project insufficient-evidence state (honest fallback, no items)
 *   5. real data render: statuses, why, evidence basis, links, next actions
 *   6. guard: the page no longer imports mock data or the sample-data notice
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const apiMocks = vi.hoisted(() => ({
  getSkillGapsOverview: vi.fn(),
}))

vi.mock("@/lib/skill-gaps-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/skill-gaps-api")>()),
  getSkillGapsOverview: apiMocks.getSkillGapsOverview,
}))

import SkillGapsPage from "../app/dashboard/skill-gaps/page"
import type {
  ProjectSkillGapReport,
  SkillGapsOverviewResponse,
} from "@/lib/skill-gaps-api"
import { evidenceBasisHref } from "@/lib/skill-gaps-api"

function assessedProject(
  overrides: Partial<ProjectSkillGapReport> = {},
): ProjectSkillGapReport {
  return {
    project_id: "project-1",
    project_title: "Analytics Project",
    assessment_state: "assessed",
    insufficient_evidence_note: null,
    claimed_skills: ["Web Analytics", "Data Visualization"],
    demonstrated_skills: [],
    gap_items: [
      {
        skill_name: "Web Analytics",
        skill_key: "web analytics",
        status: "missing_evidence",
        status_label: "Missing evidence",
        why: "A completed website workflow analysis attempted this skill at runtime and listed it as not demonstrated.",
        evidence_basis: [
          {
            kind: "website_analysis",
            reference_id: "analysis-1",
            proof_type: "website",
            proof_id: "session-1",
            citation_type: "website_workflow",
            link_status: null,
            evidence_quality: null,
            detail: "The completed website workflow analysis attempted this skill at runtime and lists it as not demonstrated.",
            limitations: [],
          },
        ],
        recommended_action: "Record a website workflow that visibly demonstrates Web Analytics in action.",
        claim_id: null,
      },
      {
        skill_name: "Data Visualization",
        skill_key: "data visualization",
        status: "partially_demonstrated",
        status_label: "Partially demonstrated",
        why: "Counted evidence supports this skill, but only at supporting quality — no primary (direct) citation has been counted.",
        evidence_basis: [
          {
            kind: "claim_link",
            reference_id: "link-1",
            proof_type: "document",
            proof_id: "doc-1",
            citation_type: "document_block",
            link_status: "counted",
            evidence_quality: "supporting",
            detail: "The document cites this skill at an exact page/section/block locator.",
            limitations: [],
          },
        ],
        recommended_action: "Add a proof with a direct, primary citation for Data Visualization.",
        claim_id: "claim-dv",
      },
    ],
    summary: {
      total_claimed: 2,
      demonstrated: 0,
      partially_demonstrated: 1,
      insufficient_evidence: 0,
      missing_evidence: 1,
      not_assessed: 0,
    },
    ...overrides,
  }
}

function overview(
  projects: ProjectSkillGapReport[],
): SkillGapsOverviewResponse {
  return {
    projects,
    total_gap_count: projects.reduce((n, p) => n + p.gap_items.length, 0),
    generated_at: "2026-07-22T00:00:00+00:00",
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("Skill Gaps page states", () => {
  it("shows a loading state while fetching", () => {
    apiMocks.getSkillGapsOverview.mockReturnValue(new Promise(() => undefined))
    render(<SkillGapsPage />)
    expect(screen.getByText(/Loading your evidence/i)).toBeInTheDocument()
  })

  it("shows an error state with a retry that refetches", async () => {
    apiMocks.getSkillGapsOverview
      .mockRejectedValueOnce(new Error("Failed to load skill gaps (HTTP 500)."))
      .mockResolvedValueOnce(overview([]))
    render(<SkillGapsPage />)
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 500")
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() =>
      expect(screen.getByText(/No projects yet/i)).toBeInTheDocument(),
    )
    expect(apiMocks.getSkillGapsOverview).toHaveBeenCalledTimes(2)
  })

  it("shows an honest empty state when the user has no projects", async () => {
    apiMocks.getSkillGapsOverview.mockResolvedValue(overview([]))
    render(<SkillGapsPage />)
    expect(await screen.findByText(/No projects yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Go to Student Dashboard/i)).toBeInTheDocument()
  })

  it("shows the insufficient-evidence fallback without fabricating items", async () => {
    apiMocks.getSkillGapsOverview.mockResolvedValue(
      overview([
        assessedProject({
          assessment_state: "insufficient_evidence",
          insufficient_evidence_note:
            "Not enough evidence to assess skill gaps for this project. Claim the skills this project demonstrates and attach proofs (document, GitHub, or a recorded website workflow) to enable an honest assessment.",
          gap_items: [],
          claimed_skills: [],
          summary: {
            total_claimed: 0,
            demonstrated: 0,
            partially_demonstrated: 0,
            insufficient_evidence: 0,
            missing_evidence: 0,
            not_assessed: 0,
          },
        }),
      ]),
    )
    render(<SkillGapsPage />)
    expect(
      await screen.findByText("Not enough evidence to assess"),
    ).toBeInTheDocument()
    expect(screen.queryAllByTestId("skill-gap-item")).toHaveLength(0)
  })

  it("renders real gap items with status, why, basis, links and next action", async () => {
    apiMocks.getSkillGapsOverview.mockResolvedValue(overview([assessedProject()]))
    render(<SkillGapsPage />)

    expect(await screen.findByText("Web Analytics")).toBeInTheDocument()
    expect(screen.getByText("Missing evidence")).toBeInTheDocument()
    expect(screen.getByText("Partially demonstrated")).toBeInTheDocument()
    expect(
      screen.getByText(/attempted this skill at runtime and listed it as not demonstrated/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/no primary \(direct\) citation has been counted/i),
    ).toBeInTheDocument()
    // Evidence basis details + link to the underlying evidence surface.
    expect(
      screen.getByText(/exact page\/section\/block locator/i),
    ).toBeInTheDocument()
    const evidenceLinks = screen.getAllByRole("link", { name: /View evidence/i })
    expect(
      evidenceLinks.some(
        (a) => a.getAttribute("href") === "/student/proofs/website?session=session-1",
      ),
    ).toBe(true)
    // Recommended next proof actions.
    expect(screen.getByText(/Record a website workflow/i)).toBeInTheDocument()
    // Summary line + project report link.
    expect(screen.getByText(/2 claimed/)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /Open project report/i }),
    ).toHaveAttribute("href", "/student/vbr/projects/project-1/report")
  })

  it("switches between projects", async () => {
    apiMocks.getSkillGapsOverview.mockResolvedValue(
      overview([
        assessedProject(),
        assessedProject({
          project_id: "project-2",
          project_title: "Second Project",
          gap_items: [],
          demonstrated_skills: ["React"],
          summary: {
            total_claimed: 1,
            demonstrated: 1,
            partially_demonstrated: 0,
            insufficient_evidence: 0,
            missing_evidence: 0,
            not_assessed: 0,
          },
        }),
      ]),
    )
    render(<SkillGapsPage />)
    await screen.findByText("Web Analytics")
    fireEvent.click(screen.getByRole("button", { name: /Second Project/ }))
    expect(
      await screen.findByText(/every assessed skill on this project is demonstrated/i),
    ).toBeInTheDocument()
    expect(screen.getByText("React")).toBeInTheDocument()
  })
})

describe("evidenceBasisHref", () => {
  it("routes website analyses to the session replay surface", () => {
    expect(
      evidenceBasisHref({
        kind: "website_analysis",
        reference_id: "a",
        proof_type: "website",
        proof_id: "s-1",
        citation_type: "website_workflow",
        link_status: null,
        evidence_quality: null,
        detail: "",
        limitations: [],
      }),
    ).toBe("/student/proofs/website?session=s-1")
  })

  it("routes claim links to their proof surfaces and unknown kinds to nothing", () => {
    expect(
      evidenceBasisHref({
        kind: "claim_link",
        reference_id: "l",
        proof_type: "document",
        proof_id: "d-1",
        citation_type: "document_block",
        link_status: "counted",
        evidence_quality: "supporting",
        detail: "",
        limitations: [],
      }),
    ).toBe("/student/proofs/documents")
    expect(
      evidenceBasisHref({
        kind: "claimed_skill",
        reference_id: "",
        proof_type: null,
        proof_id: null,
        citation_type: null,
        link_status: null,
        evidence_quality: null,
        detail: "",
        limitations: [],
      }),
    ).toBeNull()
  })
})

describe("fabricated demo content is gone from this surface", () => {
  it("the page module imports neither data/mock nor the sample-data notice", () => {
    const source = readFileSync(
      join(__dirname, "../app/dashboard/skill-gaps/page.tsx"),
      "utf8",
    )
    expect(source).not.toMatch(/data\/mock/)
    expect(source).not.toMatch(/SampleDataNotice/)
    expect(source).not.toMatch(/StudentSkillGaps/)
  })

  it("renders no fabricated market/readiness claims", async () => {
    apiMocks.getSkillGapsOverview.mockResolvedValue(overview([assessedProject()]))
    render(<SkillGapsPage />)
    await screen.findByText("Web Analytics")
    // Anchors of the old mock surface.
    expect(screen.queryByText(/saved jobs/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Your readiness/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Learning plan/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/HIGH IMPACT/)).not.toBeInTheDocument()
  })
})
