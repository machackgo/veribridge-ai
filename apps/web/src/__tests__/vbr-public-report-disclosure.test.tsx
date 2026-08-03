/**
 * Public VBR report — granular disclosure rendering tests.
 *
 * Covers the candidate-shared descriptors the disclosure backend now emits:
 * viewable documents (shared_view open/download split), website screenshot
 * strips + walkthrough replay, candidate-shared defense transcript/recording,
 * and the summary-only GitHub disclosure (label, no repo link, no repo
 * identity). Sections whose descriptors are absent must not render at all —
 * the frontend never invents empty shells or error-like wording.
 */

import { fireEvent, render, screen } from "@testing-library/react"
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
      documents_count: 2,
      website_proofs_count: 1,
      project_defense_completed: true,
      video_defense_recorded: true,
      video_evidence_chip_count: 0,
    },
    github_proof: {
      repo_url: "https://github.com/octocat/Hello-World",
      repo_owner: "octocat",
      repo_name: "Hello-World",
      status: "analyzed",
      detected_skills: ["Python", "React"],
      public_safe_summary: "GitHub proof for the project is partial evidence.",
      repo_is_public: true,
    },
    documents: [
      {
        title: "Final Year Project Report",
        source_type: "document",
        status: "analyzed",
        disclosure: "viewable",
        shared_view: {
          open_path: "/api/v1/public/vbr/reports/tok-1/documents/doc-1/view",
          mime_type: "application/pdf",
          page_count: 12,
          can_download: true,
          download_path: "/api/v1/public/vbr/reports/tok-1/documents/doc-1/download",
        },
      },
      {
        title: "Design Doc",
        source_type: "document",
        status: "analyzed",
        disclosure: "summary",
        shared_view: null,
      },
    ],
    website_proofs: [
      {
        target_website: "https://demo.example.com",
        evidence_strength: "Evidence observed",
        workflow_confidence: "high",
        supported_skills: ["React"],
        frame_views: [
          { view_path: "/api/v1/public/vbr/reports/tok-1/website/0/frames/0", mime_type: "image/jpeg" },
          { view_path: "/api/v1/public/vbr/reports/tok-1/website/0/frames/1", mime_type: "image/jpeg" },
        ],
        replay_path: "/api/v1/public/vbr/reports/tok-1/website/0/replay",
      },
    ],
    project_defense_analysis: null,
    skill_evidence: [],
    video_evidence_chips: [],
    defense_transcript_view: {
      view_path: "/api/v1/public/vbr/reports/tok-1/defense/transcript",
      mime_type: "text/plain",
    },
    defense_video_view: {
      view_path: "/api/v1/public/vbr/reports/tok-1/defense/recording",
      mime_type: "video/webm",
    },
    disclosure_version: 4,
    limitations: ["Evidence is shown with qualitative labels only."],
    published_at: "2026-07-02T00:00:00Z",
    generated_at: "2026-07-02T00:00:00Z",
    verification_note: "Evidence is described qualitatively.",
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPublicVBRProjectReport).mockReset()
})

async function renderReport(report: PublicVBRProjectReport) {
  vi.mocked(getPublicVBRProjectReport).mockResolvedValue(report)
  render(<PublicReportView token="tok-1" />)
  await screen.findByTestId("public-report")
}

function openDeepEvidence() {
  fireEvent.click(screen.getByTestId("public-report-deep-evidence-toggle"))
}

describe("PublicReportView — candidate-shared documents", () => {
  it("renders View + Download for a viewable shared document, summary docs stay link-free", async () => {
    await renderReport(makePublicReport())
    openDeepEvidence()

    const view = screen.getByTestId("public-doc-view-link")
    expect(view.getAttribute("href")).toMatch(/^https?:\/\//)
    expect(view.getAttribute("href")).toContain("/api/v1/public/vbr/reports/tok-1/documents/doc-1/view")
    expect(view).toHaveAttribute("target", "_blank")

    const download = screen.getByTestId("public-doc-download-link")
    expect(download.getAttribute("href")).toContain("/documents/doc-1/download")

    // Only ONE viewable doc gets links; the summary doc renders without any
    // repeated warning sentence.
    expect(screen.getAllByTestId("public-doc-view-link")).toHaveLength(1)
    expect(screen.getByText(/Design Doc/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain("Original artifact is not public")
  })

  it("hides the Download action when the candidate allowed view-only access", async () => {
    const report = makePublicReport()
    report.documents[0].shared_view = {
      ...report.documents[0].shared_view!,
      can_download: false,
      download_path: null,
    }
    await renderReport(report)
    openDeepEvidence()

    expect(screen.getByTestId("public-doc-view-link")).toBeInTheDocument()
    expect(screen.queryByTestId("public-doc-download-link")).not.toBeInTheDocument()
  })
})

describe("PublicReportView — candidate-shared website evidence", () => {
  it("renders the screenshots strip and the walkthrough replay player", async () => {
    await renderReport(makePublicReport())
    openDeepEvidence()

    const frames = screen.getAllByTestId("public-website-frame")
    expect(frames).toHaveLength(2)
    expect(frames[0].getAttribute("src")).toContain("/website/0/frames/0")
    expect(frames[0]).toHaveAttribute("loading", "lazy")

    const replay = screen.getByTestId("public-website-replay")
    expect(replay.tagName).toBe("VIDEO")
    expect(replay.getAttribute("src")).toContain("/website/0/replay")
    expect(replay).toHaveAttribute("controls")
    expect(replay).toHaveAttribute("preload", "metadata")
  })

  it("renders neither frames nor replay when the candidate shared none", async () => {
    await renderReport(
      makePublicReport({
        website_proofs: [
          {
            target_website: "https://demo.example.com",
            evidence_strength: "Evidence observed",
            workflow_confidence: "high",
            supported_skills: ["React"],
          },
        ],
      }),
    )
    openDeepEvidence()

    expect(screen.queryByTestId("public-website-frame")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-website-replay")).not.toBeInTheDocument()
  })
})

describe("PublicReportView — candidate-shared defense media", () => {
  it("renders the transcript link and inline recording player when shared", async () => {
    await renderReport(makePublicReport())

    const transcript = screen.getByTestId("public-defense-transcript-link")
    expect(transcript.getAttribute("href")).toContain("/defense/transcript")
    expect(transcript).toHaveAttribute("target", "_blank")

    const video = screen.getByTestId("public-defense-video")
    expect(video.tagName).toBe("VIDEO")
    expect(video.getAttribute("src")).toContain("/defense/recording")
    expect(video).toHaveAttribute("controls")
  })

  it("omits the defense-media section entirely when nothing was shared", async () => {
    await renderReport(
      makePublicReport({ defense_transcript_view: null, defense_video_view: null }),
    )

    expect(screen.queryByTestId("public-defense-transcript-link")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-defense-video")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain("Candidate-Shared Defense Recording")
  })
})

describe("PublicReportView — summary-only GitHub disclosure", () => {
  it("shows the verified-summary label with no repo link and no repo identity", async () => {
    await renderReport(
      makePublicReport({
        github_proof: {
          repo_url: "https://github.com/octocat/Hello-World",
          repo_owner: "octocat",
          repo_name: "Hello-World",
          status: "analyzed",
          detected_skills: ["Python"],
          public_safe_summary: "Verified GitHub evidence supports the Python claim.",
          repo_is_public: true,
          disclosure: "summary",
        },
      }),
    )
    openDeepEvidence()

    expect(screen.getByTestId("github-proof-summary-disclosure")).toHaveTextContent(
      "Verified GitHub evidence summary — repository access is not enabled by the candidate.",
    )
    // No repository link anywhere: neither the Evidence-by-Source block nor
    // the Direct Links section may link the repo.
    expect(screen.queryByTestId("public-github-proof-repo-link")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-safe-repo-link")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-report-repo-identity")).not.toBeInTheDocument()
    // The repo identity string itself never renders.
    expect(document.body.textContent).not.toContain("octocat/Hello-World")
  })

  it("keeps the three-truth-state repo behavior when access is viewable", async () => {
    await renderReport(makePublicReport())
    expect(screen.getByTestId("public-safe-repo-link")).toHaveAttribute(
      "href",
      "https://github.com/octocat/Hello-World",
    )
  })
})

// The Evidence Traceability note uses the same `sharesOriginalEvidence` helper
// as the Direct Links note, but its card only renders when the report carries
// evidence traces (this fixture has none), so the assertions below target the
// always-present Direct Links note.
describe("PublicReportView — honesty copy tracks what is actually shared", () => {
  it('drops the "never linked" promise once the candidate shares originals', async () => {
    // The default fixture shares a viewable document, screenshots and a replay
    // — exactly what Full access produces. Promising recruiters that private
    // evidence "is never linked" while linking it would be a false statement.
    await renderReport(makePublicReport())

    const note = screen.getByTestId("public-direct-links-note")
    expect(note).not.toHaveTextContent(/never linked/i)
    expect(note).toHaveTextContent(/chosen to share original evidence/i)
  })

  it("keeps the original promise for a report that shares no originals", async () => {
    // Recruiter-safe / restrictive-custom behavior must be untouched.
    const report = makePublicReport()
    report.documents = report.documents.map((doc) => ({
      ...doc,
      disclosure: "summary",
      shared_view: null,
    }))
    report.website_proofs = report.website_proofs.map((wp) => ({
      ...wp,
      frame_views: [],
      replay_path: null,
    }))
    await renderReport(report)

    expect(screen.getByTestId("public-direct-links-note")).toHaveTextContent(/never linked/i)
    openDeepEvidence()
    expect(screen.queryByTestId("public-doc-view-link")).not.toBeInTheDocument()
    expect(screen.queryByTestId("public-website-replay")).not.toBeInTheDocument()
  })
})
