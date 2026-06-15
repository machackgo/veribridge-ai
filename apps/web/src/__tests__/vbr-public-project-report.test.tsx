/**
 * Public recruiter-safe VBR project report page — frontend rendering tests.
 *
 * Covers: recruiter-readable report rendering, the revoked/missing empty
 * state, and the guardrails that the public page never renders raw/private
 * fields, numeric scores, /100 bars, score wording, or "fully verified".
 */

import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PublicReportView } from "../app/vbr/report/[token]/PublicReportView"
import type { PublicVBRProjectReport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  getPublicVBRProjectReport: vi.fn(),
}))

import { getPublicVBRProjectReport } from "@/lib/vbr-api"

function makePublicReport(overrides: Partial<PublicVBRProjectReport> = {}): PublicVBRProjectReport {
  return {
    report_title: "Verified Build Report",
    project_title: "Skill Evidence Tracker",
    candidate_display_name: "Jordan Rivera",
    project_summary: "A platform that tracks student skill evidence across proof sources.",
    student_role: "I built the backend API and the React dashboard.",
    repo_full_name: "octocat/Hello-World",
    claimed_skills: ["Python", "React"],
    evidence_package: {
      github_proof_attached: true,
      documents_count: 1,
      website_proofs_count: 1,
      project_defense_completed: true,
      video_defense_recorded: true,
      video_evidence_chip_count: 1,
    },
    github_proof: {
      repo_url: "https://github.com/octocat/Hello-World",
      repo_owner: "octocat",
      repo_name: "Hello-World",
      status: "analyzed",
      detected_skills: ["Python", "React"],
      public_safe_summary: "GitHub proof for octocat/Hello-World is partial evidence.",
    },
    documents: [{ title: "Final Year Project Report", source_type: "document", status: "analyzed" }],
    website_proofs: [
      { target_website: "http://demo.example.com", evidence_strength: "Evidence observed", workflow_confidence: "high", supported_skills: ["React"] },
    ],
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
    skill_evidence: [
      { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, notes: "Explained clearly during the Project Defense." },
      { skill: "React", status: "Partially demonstrated", evidence_chip_count: 1, notes: "Mentioned but not fully explained." },
    ],
    video_evidence_chips: [
      {
        label: "Video 03:12",
        timestamp_start_s: 192,
        timestamp_end_s: 210,
        short_summary: "explains backend risk-scoring API",
        related_skill: "Python",
        source: "project_defense_video",
        source_type: "video_transcript",
      },
    ],
    limitations: [
      "Project Defense reflects the student's own process and explanation of their work — it is not independent proof of code authorship.",
    ],
    published_at: "2026-01-02T00:00:00Z",
    generated_at: "2026-01-02T00:00:00Z",
    verification_note: "Evidence is described as observed, supporting, or process evidence — never as a number, percentage, or ranking.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPublicVBRProjectReport).mockReset()
})

describe("PublicReportView", () => {
  it("renders a recruiter-readable safe report", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport())

    render(<PublicReportView token="tok-1" />)

    expect(await screen.findByTestId("public-report")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Verified Build Report" })).toBeInTheDocument()
    expect(screen.getByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(screen.getByText("Jordan Rivera")).toBeInTheDocument()
    expect(screen.getByText("Skills Demonstrated")).toBeInTheDocument()
    expect(screen.getAllByTestId("public-skill-row")).toHaveLength(2)
    expect(screen.getByTestId("public-video-chip").textContent).toContain("Video 03:12")
    // CTA present.
    expect(screen.getByTestId("public-report-cta")).toBeInTheDocument()
    expect(screen.getByText(/Request a VBR from your candidates/i)).toBeInTheDocument()
  })

  it("renders the revoked/missing empty state safely", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(null)

    render(<PublicReportView token="bad-token" />)

    expect(await screen.findByTestId("public-report-not-found")).toBeInTheDocument()
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument()
    expect(screen.queryByTestId("public-report")).not.toBeInTheDocument()
  })

  it("never renders raw/private fields", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport())

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    const raw = document.body.textContent ?? ""
    for (const unsafe of [
      "storage_path",
      "signed_url",
      "access_token",
      "vbr/sessions",
      "full_text",
      ".webm",
      ".mp4",
      "Bearer ",
      "question_id",
      "session_id",
      "confidence_score",
    ]) {
      expect(raw).not.toContain(unsafe)
    }
  })

  it("never renders numeric scores, /100 bars, score wording, or 'fully verified'", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport())

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/\/100/)
    expect(raw).not.toMatch(/\bscore\b/i)
    expect(raw).not.toMatch(/trust score/i)
    expect(raw).not.toMatch(/fully verified/i)
    expect(raw).not.toMatch(/\b\d{1,3}%/)

    // Qualitative labels are rendered instead.
    expect(screen.getAllByText("Demonstrated").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Partially demonstrated").length).toBeGreaterThan(0)
  })
})
