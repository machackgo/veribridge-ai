/**
 * Public recruiter-safe VBR project report page — frontend rendering tests.
 *
 * Covers: recruiter-readable report rendering, the revoked/missing empty
 * state, and the guardrails that the public page never renders raw/private
 * fields, numeric scores, /100 bars, score wording, or "fully verified".
 */

import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PublicReportView } from "../app/vbr/report/[token]/PublicReportView"
import type { PublicVBRProjectReport } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
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

const SAFE_TRACES = [
  {
    trace_id: "github-proof",
    source_type: "GitHub Proof",
    source_title: "octocat/Hello-World",
    skill_names: ["Python"],
    qualitative_status: "Supporting evidence",
    safe_summary: "Repository analyzed; Python backend files detected.",
    safe_detail: "Static analysis detected backend files consistent with Python.",
    evidence_anchor: "github-proof",
    public_url: "https://github.com/octocat/Hello-World",
    public_url_label: "View public repository",
    timestamp: null,
    limitation: "Confirms code shape, not sole authorship.",
    is_publicly_openable: true,
    private_evidence_note: null,
  },
  {
    trace_id: "document-proof-1",
    source_type: "Document Proof",
    source_title: "Final Year Project Report",
    skill_names: ["Python"],
    qualitative_status: "Supporting evidence",
    safe_summary: "A supporting document describing the project.",
    safe_detail: "Written context for the claimed skills.",
    evidence_anchor: "document-proof-1",
    public_url: null,
    public_url_label: null,
    timestamp: null,
    limitation: "Original private document is not publicly exposed.",
    is_publicly_openable: false,
    private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
  },
]

describe("PublicReportView", () => {
  it("renders a recruiter-readable safe report", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport())

    render(<PublicReportView token="tok-1" />)

    expect(await screen.findByTestId("public-report")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Verified Build Report" })).toBeInTheDocument()
    expect(screen.getByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(screen.getByText("Jordan Rivera")).toBeInTheDocument()
    // The public report renders the same canonical section title the student
    // report uses — one report design, not a separate public product.
    expect(screen.getByText("Skills Demonstrated in This Project")).toBeInTheDocument()
    expect(screen.getAllByTestId("public-skill-row")).toHaveLength(2)
    // Timestamped video chips live in the collapsed deep-evidence section.
    fireEvent.click(screen.getByTestId("public-report-deep-evidence-toggle"))
    expect(screen.getByTestId("public-video-chip").textContent).toContain("Video 03:12")
    // CTA present.
    expect(screen.getByTestId("public-report-cta")).toBeInTheDocument()
    expect(screen.getByText(/Request a VBR from your candidates/i)).toBeInTheDocument()
  })

  it("renders an Evidence Traceability section with safe links and private notes", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        evidence_traces: SAFE_TRACES,
        skill_evidence: [
          {
            skill: "Python",
            status: "Demonstrated",
            evidence_chip_count: 2,
            notes: "Explained clearly during the Project Defense.",
            supporting_sources: ["GitHub Proof", "Document Proof"],
            limitations: [],
            why_this_status: "Marked 'Demonstrated' because supporting evidence was found in: GitHub Proof and Document Proof.",
            recruiter_can_verify: "Open the GitHub Proof and Document Proof evidence trace(s) below.",
            evidence_traces: ["github-proof", "document-proof-1"],
          },
        ],
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    // Traceability is progressive disclosure: opened explicitly.
    fireEvent.click(screen.getByTestId("public-report-deep-evidence-toggle"))
    expect(screen.getByText("Evidence Traceability")).toBeInTheDocument()
    expect(screen.getAllByTestId("evidence-trace").length).toBe(2)
    // Public source links directly; private source shows a generic note (no raw file).
    expect(screen.getByTestId("evidence-trace-link")).toHaveAttribute(
      "href",
      "https://github.com/octocat/Hello-World",
    )
    expect(screen.getByTestId("evidence-trace-private-note").textContent).toContain("evidence vault")
    // Skill row exposes why + recruiter-verify + jump links to the traces.
    expect(screen.getByTestId("public-skill-why").textContent).toContain("Demonstrated")
    expect(screen.getByTestId("public-skill-verify")).toBeInTheDocument()
    expect(screen.getByTestId("public-skill-trace-links")).toBeInTheDocument()
  })

  it("re-gates an unsafe trace link as defence in depth and never renders it", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        evidence_traces: [
          {
            ...SAFE_TRACES[0],
            // Should never arrive, but if it does the UI must not link it.
            public_url: "http://localhost:3000",
            is_publicly_openable: true,
            private_evidence_note: "A direct link was omitted because it was private or internal.",
          },
        ],
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")
    fireEvent.click(screen.getByTestId("public-report-deep-evidence-toggle"))

    expect(screen.queryByTestId("evidence-trace-link")).not.toBeInTheDocument()
    expect(screen.getByTestId("evidence-trace-private-note")).toBeInTheDocument()
    expect(document.body.textContent ?? "").not.toContain("localhost:3000")
  })

  it("renders per-skill supporting evidence sources and a passport backlink", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        skill_evidence: [
          {
            skill: "Python",
            status: "Demonstrated",
            evidence_chip_count: 2,
            notes: "Explained clearly during the Project Defense.",
            supporting_sources: ["GitHub Proof", "Project Defense", "Video Evidence"],
            limitations: [],
          },
          {
            skill: "React",
            status: "Needs review",
            evidence_chip_count: 0,
            notes: "No evidence has been reviewed for this skill yet.",
            supporting_sources: [],
            limitations: ["Not yet strongly evidenced — treat as a claim pending more proof."],
          },
        ],
        public_passport_path: "/p/abc123",
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    const sourceBlocks = screen.getAllByTestId("public-skill-supporting-sources")
    expect(sourceBlocks).toHaveLength(1)
    expect(sourceBlocks[0].textContent).toContain("GitHub")
    expect(sourceBlocks[0].textContent).toContain("Project Defense")
    expect(sourceBlocks[0].textContent).toContain("Video")

    expect(screen.getByTestId("public-skill-limitations").textContent).toContain("pending more proof")

    const backlink = screen.getByTestId("public-report-passport-link")
    expect(backlink).toHaveAttribute("href", "/p/abc123")
  })

  it("omits the passport backlink when none is published", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport({ public_passport_path: null }))

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    expect(screen.queryByTestId("public-report-passport-link")).not.toBeInTheDocument()
  })

  it("renders safe direct verification links", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        deployed_url: "https://my-live-app.example.com",
        github_proof: {
          repo_url: "https://github.com/octocat/Hello-World",
          repo_owner: "octocat",
          repo_name: "Hello-World",
          status: "analyzed",
          detected_skills: ["Python"],
          public_safe_summary: "Public repo evidence observed.",
          repo_is_public: true,
        },
        website_proofs: [
          { target_website: "https://threejs.org", evidence_strength: "Evidence observed", workflow_confidence: "high", supported_skills: ["React"] },
        ],
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    const repoLink = screen.getByTestId("public-safe-repo-link")
    expect(repoLink).toHaveAttribute("href", "https://github.com/octocat/Hello-World")
    const liveLinks = screen.getAllByTestId("public-safe-live-link").map((a) => a.getAttribute("href"))
    expect(liveLinks).toContain("https://my-live-app.example.com")
    expect(liveLinks).toContain("https://threejs.org")
  })

  it("does not render unsafe direct verification links if they somehow arrive", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        deployed_url: "http://localhost:3000",
        github_proof: {
          repo_url: "http://127.0.0.1:8080/repo",
          repo_owner: "octocat",
          repo_name: "Hello-World",
          status: "analyzed",
          detected_skills: ["Python"],
          public_safe_summary: "Repo evidence observed.",
          repo_is_public: true,
        },
        website_proofs: [
          { target_website: "http://192.168.1.10/app", evidence_strength: "Supporting evidence", workflow_confidence: "low", supported_skills: [] },
        ],
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")

    expect(screen.queryByTestId("public-safe-repo-link")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-safe-live-link")).not.toBeInTheDocument()

    const raw = document.body.textContent ?? ""
    for (const unsafe of ["localhost:3000", "127.0.0.1", "192.168.1.10"]) {
      expect(raw).not.toContain(unsafe)
    }
  })

  it("shows a generic omitted note instead of a raw unsafe website target", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(
      makePublicReport({
        website_proofs: [
          { target_website: "http://10.0.0.5/internal", evidence_strength: "Supporting evidence", workflow_confidence: "medium", supported_skills: ["Node"] },
        ],
      }),
    )

    render(<PublicReportView token="tok-1" />)
    await screen.findByTestId("public-report")
    fireEvent.click(screen.getByTestId("public-report-deep-evidence-toggle"))

    expect(screen.getByText(/Private\/internal link omitted/i)).toBeInTheDocument()
    const raw = document.body.textContent ?? ""
    expect(raw).not.toContain("10.0.0.5")
  })

  it("renders the revoked/missing empty state safely", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(null)

    render(<PublicReportView token="bad-token" />)

    expect(await screen.findByTestId("public-report-not-found")).toBeInTheDocument()
    expect(screen.getByText(/This report is not available/i)).toBeInTheDocument()
    // The empty state explains the private-Passport master switch without leaking why.
    expect(screen.getByText(/currently private/i)).toBeInTheDocument()
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

  it("stays viewport-safe on small screens (VBR-RRO-D001 regression)", async () => {
    vi.mocked(getPublicVBRProjectReport).mockResolvedValue(makePublicReport())

    render(<PublicReportView token="tok-1" />)
    const container = await screen.findByTestId("public-report")

    // The width:100% + min-width:0 guard now lives in the CSS module's .page
    // class — assert the class is applied so a flex parent can never pin the
    // report at min-content width (VBR-RRO-D001).
    expect(container.className).toMatch(/page/)

    // Skill evidence renders as stacked cards — there is no min-content table
    // in the primary content that could drag the page wider than a phone
    // viewport (tables cannot shrink below min-content width).
    expect(container.querySelector("table")).toBeNull()
    const rows = screen.getAllByTestId("public-skill-row")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      expect(row.tagName).toBe("DIV")
    }
  })
})
