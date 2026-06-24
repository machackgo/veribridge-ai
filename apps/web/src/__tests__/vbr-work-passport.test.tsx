/**
 * Private Verified Work Passport — frontend rendering tests.
 *
 * Covers: evidence-source groups/badges, grouped skills, per-project report
 * actions, and the publish / copy / unpublish controls.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PrivatePassportView } from "../app/student/vbr/passport/PrivatePassportView"
import type { PrivateWorkPassport, WorkPassportStatus } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPrivateWorkPassport: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
  publishVBRProjectReport: vi.fn(),
}))

import {
  getPrivateWorkPassport,
  getWorkPassportStatus,
  publishWorkPassport,
  unpublishWorkPassport,
  publishVBRProjectReport,
} from "@/lib/vbr-api"

function makePassport(overrides: Partial<PrivateWorkPassport> = {}): PrivateWorkPassport {
  return {
    candidate_display_name: "Jordan Rivera",
    headline: "Full-stack builder",
    summary: "I ship and defend real projects.",
    is_published: false,
    public_slug: null,
    public_path: null,
    published_at: null,
    skills: [
      { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, project_count: 1, evidence_sources: ["GitHub Proof"], projects: [], evidence_chips: [], notes: "", limitations: [] },
      { skill: "React", status: "Partially demonstrated", evidence_chip_count: 1, project_count: 1, evidence_sources: [], projects: [], evidence_chips: [], notes: "", limitations: [] },
    ],
    projects: [
      {
        project_id: "proj-1",
        project_title: "Skill Evidence Tracker",
        project_summary: "Tracks student skill evidence.",
        repo_full_name: "octocat/Hello-World",
        claimed_skills: ["Python", "React"],
        evidence_sources: ["GitHub Proof", "Document Proof", "Project Defense", "Video Evidence"],
        evidence_package: {
          github_proof_attached: true,
          documents_count: 1,
          website_proofs_count: 0,
          project_defense_completed: true,
          video_defense_recorded: true,
          video_evidence_chip_count: 1,
        },
        attempt_count: 1,
        report: { is_public: false, public_token: null, public_path: null, published_at: null },
      },
    ],
    evidence_source_counts: { "GitHub Proof": 1, "Document Proof": 1, "Project Defense": 1, "Video Evidence": 1 },
    project_count: 1,
    published_report_count: 0,
    limitations: ["Skills and evidence are shown with qualitative labels only — never numeric trust scores."],
    generated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

function statusFrom(p: PrivateWorkPassport): WorkPassportStatus {
  return {
    is_published: p.is_published,
    public_slug: p.public_slug,
    public_path: p.public_path,
    published_at: p.published_at,
    headline: p.headline,
    summary: p.summary,
  }
}

beforeEach(() => {
  vi.mocked(getPrivateWorkPassport).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  vi.mocked(publishWorkPassport).mockReset()
  vi.mocked(unpublishWorkPassport).mockReset()
  vi.mocked(publishVBRProjectReport).mockReset()
})

describe("PrivatePassportView", () => {
  it("renders evidence source groups/badges and grouped skills", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-header")).toBeInTheDocument()
    expect(screen.getByText("Jordan Rivera")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-source-counts")).toBeInTheDocument()
    expect(screen.getAllByTestId("evidence-source-count").length).toBeGreaterThan(0)
    expect(screen.getAllByTestId("passport-skill")).toHaveLength(2)
    expect(screen.getByText("Python")).toBeInTheDocument()
  })

  it("shows a merged-attempts badge when duplicate evidence is grouped into one card", async () => {
    const base = makePassport()
    const p = makePassport({
      projects: [{ ...base.projects[0], attempt_count: 9 }],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")
    // One card, not nine, with a badge surfacing the merged attempt count.
    expect(screen.getAllByTestId("passport-project-card")).toHaveLength(1)
    expect(screen.getByTestId("attempt-count-badge")).toHaveTextContent("9 attempts merged")
  })

  it("expands a skill to show safe drilldown detail with a report preview link", async () => {
    const base = makePassport()
    const p = makePassport({
      skills: [
        {
          ...base.skills[0],
          evidence_sources: ["GitHub Proof", "Project Defense"],
          notes: "Explained clearly during the Project Defense.",
          projects: [
            {
              project_title: "Skill Evidence Tracker",
              project_id: "proj-1",
              evidence_sources: ["GitHub Proof"],
              report_is_public: false,
              public_report_path: null,
            },
          ],
          evidence_chips: [{ label: "00:42", short_summary: "Walks through the risk scoring function.", source: "project_defense_video" }],
          limitations: [],
        },
        base.skills[1],
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-header")

    // Detail hidden until expanded.
    expect(screen.queryByTestId("skill-detail")).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByTestId("skill-expand-toggle")[0])

    const detail = await screen.findByTestId("skill-detail")
    expect(detail).toHaveTextContent("Explained clearly during the Project Defense.")
    expect(screen.getByTestId("skill-project-ref")).toBeInTheDocument()
    expect(detail).toHaveTextContent("Walks through the risk scoring function.")
  })

  it("shows aggregated evidence traces in the private skill drilldown", async () => {
    const base = makePassport()
    const p = makePassport({
      skills: [
        {
          ...base.skills[0],
          evidence_sources: ["GitHub Proof", "Document Proof"],
          notes: "Backed by repository and document evidence.",
          projects: [
            { project_title: "Skill Evidence Tracker", project_id: "proj-1", evidence_sources: ["GitHub Proof"], report_is_public: false, public_report_path: null },
          ],
          evidence_chips: [],
          evidence_traces: [
            {
              trace_id: "github-proof",
              source_type: "GitHub Proof",
              source_title: "octocat/Hello-World",
              skill_names: ["Python"],
              qualitative_status: "Supporting evidence",
              safe_summary: "Repository analyzed.",
              safe_detail: "Static analysis.",
              evidence_anchor: "github-proof",
              public_url: "https://github.com/octocat/Hello-World",
              public_url_label: "View public repository",
              timestamp: null,
              limitation: "Not sole authorship.",
              is_publicly_openable: true,
              private_evidence_note: null,
            },
            {
              trace_id: "document-proof-1",
              source_type: "Document Proof",
              source_title: "Final Year Project Report",
              skill_names: ["Python"],
              qualitative_status: "Supporting evidence",
              safe_summary: "A supporting document.",
              safe_detail: "Written context.",
              evidence_anchor: "document-proof-1",
              public_url: null,
              public_url_label: null,
              timestamp: null,
              limitation: "Original private document is not publicly exposed.",
              is_publicly_openable: false,
              private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
            },
          ],
          limitations: [],
        },
        base.skills[1],
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-header")
    fireEvent.click(screen.getAllByTestId("skill-expand-toggle")[0])

    const detail = await screen.findByTestId("skill-detail")
    expect(detail.querySelector('[data-testid="evidence-traceability"]')).toBeTruthy()
    expect(screen.getAllByTestId("evidence-trace").length).toBe(2)
    expect(screen.getByTestId("evidence-trace-link")).toHaveAttribute("href", "https://github.com/octocat/Hello-World")
    expect(screen.getByTestId("evidence-trace-private-note").textContent).toContain("evidence vault")
  })

  it("renders project report actions including publish when no report exists", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-project-card")).toBeInTheDocument()
    expect(screen.getByTestId("project-report-actions")).toBeInTheDocument()
    expect(screen.getByTestId("view-report-preview-link")).toHaveAttribute(
      "href",
      "/student/vbr/projects/proj-1/report",
    )
    expect(screen.getByTestId("publish-report-button")).toBeInTheDocument()
  })

  it("shows copy report link when a project report is already public", async () => {
    const p = makePassport({
      published_report_count: 1,
      projects: [
        {
          ...makePassport().projects[0],
          report: { is_public: true, public_token: "tok-abc", public_path: "/vbr/report/tok-abc", published_at: "2026-01-02T00:00:00Z" },
        },
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-project-card")

    expect(screen.getByTestId("copy-report-link-button")).toBeInTheDocument()
    expect(screen.queryByTestId("publish-report-button")).not.toBeInTheDocument()
  })

  it("renders publish control, then copy/unpublish after publishing", async () => {
    const p = makePassport()
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))
    vi.mocked(publishWorkPassport).mockResolvedValue({
      is_published: true,
      public_slug: "slug123",
      public_path: "/p/slug123",
      published_at: "2026-01-02T00:00:00Z",
      headline: p.headline,
      summary: p.summary,
    })

    render(<PrivatePassportView />)

    const publishBtn = await screen.findByTestId("publish-passport-button")
    fireEvent.click(publishBtn)

    await waitFor(() => expect(screen.getByTestId("passport-public-link")).toBeInTheDocument())
    expect(screen.getByTestId("passport-public-link").textContent).toContain("/p/slug123")
    expect(screen.getByTestId("copy-passport-link-button")).toBeInTheDocument()
    expect(screen.getByTestId("unpublish-passport-button")).toBeInTheDocument()
  })

  it("renders safe empty states with no projects or skills", async () => {
    const p = makePassport({
      skills: [],
      projects: [],
      evidence_source_counts: {},
      project_count: 0,
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)

    expect(await screen.findByTestId("passport-no-projects")).toBeInTheDocument()
    expect(screen.getByTestId("passport-no-skills")).toBeInTheDocument()
    expect(screen.getByTestId("passport-no-evidence")).toBeInTheDocument()
  })

  it("renders a cross-project skill report: per-project status, deep links and source counts", async () => {
    const base = makePassport()
    const p = makePassport({
      skills: [
        {
          ...base.skills[0],
          skill: "Machine Learning",
          status: "Demonstrated",
          evidence_sources: ["GitHub Proof", "Document Proof"],
          projects: [
            {
              project_title: "Boston Housing",
              project_id: "proj-boston",
              skill_status: "Demonstrated",
              evidence_sources: ["GitHub Proof", "Project Defense"],
              report_is_public: false,
              public_report_path: null,
              evidence_traces: [
                {
                  trace_id: "github-proof",
                  source_type: "GitHub Proof",
                  source_title: "octocat/boston",
                  skill_names: ["Machine Learning"],
                  qualitative_status: "Supporting evidence",
                  safe_summary: "Repo analyzed.",
                  safe_detail: "Repo-level.",
                  evidence_anchor: "trace-github-proof",
                  location_label: "repo-level",
                  is_publicly_openable: false,
                  limitation: "Repo-level only.",
                },
              ],
            },
            {
              project_title: "Teachable Machine",
              project_id: "proj-teachable",
              skill_status: "Supporting evidence",
              evidence_sources: ["Document Proof", "Website Proof"],
              report_is_public: false,
              public_report_path: null,
              evidence_traces: [],
            },
          ],
          evidence_chips: [],
          evidence_traces: [
            {
              trace_id: "github-proof",
              source_type: "GitHub Proof",
              source_title: "octocat/boston",
              skill_names: ["Machine Learning"],
              qualitative_status: "Supporting evidence",
              safe_summary: "Repo analyzed.",
              safe_detail: "Repo-level.",
              evidence_anchor: "trace-github-proof",
              location_label: "repo-level",
              is_publicly_openable: false,
              limitation: "Repo-level only.",
            },
          ],
          notes: "Evidenced across two projects.",
          limitations: [],
        },
        base.skills[1],
      ],
    })
    vi.mocked(getPrivateWorkPassport).mockResolvedValue(p)
    vi.mocked(getWorkPassportStatus).mockResolvedValue(statusFrom(p))

    render(<PrivatePassportView />)
    await screen.findByTestId("passport-header")
    fireEvent.click(screen.getAllByTestId("skill-expand-toggle")[0])

    const detail = await screen.findByTestId("skill-detail")
    // Two projects compared under this one skill.
    expect(screen.getAllByTestId("skill-project-ref")).toHaveLength(2)
    expect(detail.textContent).toContain("Boston Housing")
    expect(detail.textContent).toContain("Teachable Machine")
    // Per-skill source counts.
    expect(screen.getByTestId("skill-source-counts")).toBeInTheDocument()
    // A deep link to the exact project report trace anchor.
    const deepLinks = screen.getByTestId("skill-project-trace-links")
    const a = deepLinks.querySelector("a") as HTMLAnchorElement
    expect(a.getAttribute("href")).toBe("/student/vbr/projects/proj-boston/report#trace-github-proof")
    expect(a.textContent).toContain("GitHub: repo-level")
    // Missing-evidence guidance is shown for un-evidenced sources.
    expect(screen.getByTestId("skill-missing-evidence").textContent).toContain("Website Proof")
  })
})
