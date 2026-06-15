/**
 * Final VBR Report v1 (student preview) — frontend rendering tests.
 *
 * Covers: project summary, evidence package cards, skill evidence table
 * (qualitative labels, no numeric scores), video evidence chips (with and
 * without), limitations / not-assessed section, and the "student preview
 * only" notice. Never renders raw transcript text or private fields.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { ProjectReportView } from "../app/student/vbr/projects/[projectId]/report/ProjectReportView"
import type { VBRStudentProjectReportResponse } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  getVBRProjectReport: vi.fn(),
  getVBRProjectReportPublishStatus: vi.fn(),
  publishVBRProjectReport: vi.fn(),
  unpublishVBRProjectReport: vi.fn(),
}))

import {
  getVBRProjectReport,
  getVBRProjectReportPublishStatus,
  publishVBRProjectReport,
  unpublishVBRProjectReport,
  type ProjectReportPublishStatus,
} from "@/lib/vbr-api"

function unpublishedStatus(): ProjectReportPublishStatus {
  return { project_id: "proj-1", is_public: false, public_token: null, public_path: null, published_at: null }
}

function publishedStatus(token = "tok-abc123"): ProjectReportPublishStatus {
  return {
    project_id: "proj-1",
    is_public: true,
    public_token: token,
    public_path: `/vbr/report/${token}`,
    published_at: "2026-01-02T00:00:00Z",
  }
}

function makeReport(overrides: Partial<VBRStudentProjectReportResponse> = {}): VBRStudentProjectReportResponse {
  return {
    project_id: "proj-1",
    project_title: "Skill Evidence Tracker",
    project_description: "A platform that tracks student skill evidence across proof sources.",
    repo_url: "https://github.com/octocat/Hello-World",
    repo_full_name: "octocat/Hello-World",
    student_role: "I built the backend API and the React dashboard.",
    claimed_skills: ["Python", "React"],
    project_status: "questions_ready",
    session_id: "sess-1",
    generated_at: "2026-01-01T00:00:00Z",
    evidence_package: {
      github_proof_attached: false,
      documents_count: 0,
      website_proofs_count: 0,
      project_defense_completed: false,
      video_defense_recorded: false,
      video_evidence_chip_count: 0,
    },
    github_proof: null,
    documents: [],
    website_proofs: [],
    project_defense_analysis: null,
    defense_questions: [],
    video_evidence_chips: [],
    skill_evidence: [
      { skill: "Python", status: "Not assessed", evidence_chip_count: 0, notes: "No evidence has been reviewed for this skill yet." },
      { skill: "React", status: "Not assessed", evidence_chip_count: 0, notes: "No evidence has been reviewed for this skill yet." },
    ],
    limitations: [
      "Website proof not attached.",
      "Video defense not recorded yet.",
      "No timestamped video evidence chips yet.",
      "No document proof attached.",
      "Project Defense has not been analyzed yet.",
      "Project Defense reflects the student's own process and explanation of their work — it is not independent proof of code authorship.",
      "This is a private student preview — public recruiter sharing is not enabled for this report yet.",
    ],
    next_actions: ["Generate Project Defense questions for this project."],
    preview_only: true,
    public_recruiter_sharing_enabled: false,
    note: "This is a student preview of the evidence package collected for this project. It is not a public recruiter report — public recruiter sharing is not enabled yet.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getVBRProjectReport).mockReset()
  vi.mocked(getVBRProjectReportPublishStatus).mockReset()
  vi.mocked(publishVBRProjectReport).mockReset()
  vi.mocked(unpublishVBRProjectReport).mockReset()
  // Default: report has no public link yet.
  vi.mocked(getVBRProjectReportPublishStatus).mockResolvedValue(unpublishedStatus())
})

describe("ProjectReportView", () => {
  it("renders the project summary", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(screen.getByText(/tracks student skill evidence/i)).toBeInTheDocument()
    expect(screen.getByText("octocat/Hello-World")).toBeInTheDocument()
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0)
    expect(screen.getAllByText("React").length).toBeGreaterThan(0)
  })

  it("shows the student-preview-only notice and does not claim public recruiter sharing", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    const notice = await screen.findByTestId("report-preview-notice")
    expect(notice.textContent).toMatch(/student preview/i)
    expect(notice.textContent).toMatch(/public recruiter sharing is not enabled/i)
    expect(screen.queryByText(/fully verified/i)).not.toBeInTheDocument()
  })

  it("renders evidence package summary cards", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByText("Evidence Package Summary")).toBeInTheDocument()
    expect(screen.getAllByText("GitHub Proof").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Documents").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Website Proof").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Project Defense").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Video Defense").length).toBeGreaterThan(0)
  })

  it("renders the skill evidence table with qualitative labels, never numeric scores", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, notes: "Explained clearly during the Project Defense." },
          { skill: "React", status: "Partially demonstrated", evidence_chip_count: 1, notes: "Mentioned during the Project Defense but not fully explained." },
        ],
      })
    )

    render(<ProjectReportView projectId="proj-1" />)

    const rows = await screen.findAllByTestId("skill-evidence-row")
    expect(rows).toHaveLength(2)
    expect(screen.getByText("Demonstrated")).toBeInTheDocument()
    expect(screen.getByText("Partially demonstrated")).toBeInTheDocument()

    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/confidence_score/i)
    expect(raw).not.toMatch(/trust score/i)
  })

  it("renders timestamped video evidence chips when available", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        evidence_package: {
          github_proof_attached: false,
          documents_count: 0,
          website_proofs_count: 0,
          project_defense_completed: true,
          video_defense_recorded: true,
          video_evidence_chip_count: 1,
        },
        video_evidence_chips: [
          {
            label: "Video 03:12",
            timestamp_start_s: 192,
            timestamp_end_s: 210,
            short_summary: "explains backend risk-scoring API",
            related_skill: "Python",
            question_id: null,
            source: "project_defense_video",
            source_type: "video_transcript",
          },
        ],
        limitations: [],
      })
    )

    render(<ProjectReportView projectId="proj-1" />)

    const chip = await screen.findByTestId("report-video-evidence-chip")
    expect(chip.textContent).toContain("Video 03:12")
    expect(chip.textContent).toContain("explains backend risk-scoring API")
    expect(chip.textContent).toContain("Python")
  })

  it("shows an honest empty state when there are no video evidence chips", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect((await screen.findAllByText("Video defense not recorded yet.")).length).toBeGreaterThan(0)
    expect(screen.queryByTestId("report-video-evidence-chip")).not.toBeInTheDocument()
  })

  it("renders the limitations / not-assessed section", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByText("Limitations / Not Assessed")).toBeInTheDocument()
    expect(screen.getAllByText("Website proof not attached.").length).toBeGreaterThan(0)
    expect(screen.getAllByText("No document proof attached.").length).toBeGreaterThan(0)
    expect(screen.getByText(/not independent proof of code authorship/i)).toBeInTheDocument()
  })

  it("never renders raw transcript text or private storage fields", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        project_defense_analysis: {
          transcript_summary: "Student explained the backend API design and React dashboard work.",
          skills_mentioned: ["Python", "React"],
          skills_explained_well: ["Python"],
          skills_missing_from_explanation: ["React"],
          overall_assessment: "Partially demonstrated",
          explanation_clarity: "Partially demonstrated",
          ownership_signal: "Partially demonstrated",
          technical_depth: "Supporting evidence",
          consistency_with_evidence: "Demonstrated",
          risk_flags: [],
          recruiter_summary: "Student gave a clear explanation of their individual contribution.",
          recommended_improvements: [],
          privacy_scan_status: "clean",
        },
      })
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    const raw = document.body.textContent ?? ""
    for (const unsafe of ["storage_path", "signed_url", "access_token", "vbr/sessions", "full_text", ".webm", ".mp4", "Bearer "]) {
      expect(raw).not.toContain(unsafe)
    }
  })

  // ── Score / trust-score overclaim guardrails ──────────────────────────────

  it("never renders numeric analysis scores, /100 bars, or trust-score wording", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        project_defense_analysis: {
          transcript_summary: "Student explained the backend API design and React dashboard work.",
          skills_mentioned: ["Python", "React"],
          skills_explained_well: ["Python"],
          skills_missing_from_explanation: ["React"],
          overall_assessment: "Partially demonstrated",
          explanation_clarity: "Demonstrated",
          ownership_signal: "Partially demonstrated",
          technical_depth: "Supporting evidence",
          consistency_with_evidence: "Needs review",
          risk_flags: [],
          recruiter_summary: "Student gave a clear explanation of their individual contribution.",
          recommended_improvements: [],
          privacy_scan_status: "clean",
        },
        website_proofs: [
          {
            target_website: "http://demo.example.com",
            evidence_strength: "Evidence observed",
            workflow_confidence: "high",
            supported_skills: ["React"],
          },
        ],
      })
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/\/100/)
    expect(raw).not.toMatch(/\bscore\b/i)
    expect(raw).not.toMatch(/trust score/i)
    expect(raw).not.toMatch(/fully verified/i)
    expect(raw).not.toMatch(/\b\d{1,3}%/)

    // Qualitative labels are rendered instead.
    expect(screen.getAllByText("Partially demonstrated").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Demonstrated").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Supporting evidence").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Needs review").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Evidence observed").length).toBeGreaterThan(0)
  })
})

describe("ProjectReportView — recruiter-safe publish controls", () => {
  it("shows the publish control in student-preview state by default", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByTestId("publish-controls")).toBeInTheDocument()
    expect(await screen.findByTestId("student-preview-badge")).toBeInTheDocument()
    expect(screen.getByTestId("publish-link-button")).toHaveTextContent(/publish recruiter-safe link/i)
    expect(screen.queryByTestId("public-link-url")).not.toBeInTheDocument()
  })

  it("renders the public-link-active state with copy and unpublish controls", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())
    vi.mocked(getVBRProjectReportPublishStatus).mockResolvedValue(publishedStatus("tok-xyz"))

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByTestId("public-link-active-badge")).toBeInTheDocument()
    const url = screen.getByTestId("public-link-url")
    expect(url.textContent).toContain("/vbr/report/tok-xyz")
    expect(screen.getByTestId("copy-link-button")).toBeInTheDocument()
    expect(screen.getByTestId("unpublish-link-button")).toBeInTheDocument()
    expect(screen.queryByTestId("publish-link-button")).not.toBeInTheDocument()
  })

  it("publishes when the publish button is clicked and reveals the link", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())
    vi.mocked(publishVBRProjectReport).mockResolvedValue(publishedStatus("tok-new"))

    render(<ProjectReportView projectId="proj-1" />)

    const publishBtn = await screen.findByTestId("publish-link-button")
    fireEvent.click(publishBtn)

    await waitFor(() => expect(screen.getByTestId("public-link-url")).toBeInTheDocument())
    expect(vi.mocked(publishVBRProjectReport)).toHaveBeenCalledWith("proj-1")
    expect(screen.getByTestId("public-link-url").textContent).toContain("/vbr/report/tok-new")
  })
})
