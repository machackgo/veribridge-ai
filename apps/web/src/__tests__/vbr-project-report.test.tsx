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

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
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
      "This preview is private by default — it becomes recruiter-visible only for the project reports you choose to publish.",
    ],
    next_actions: ["Generate Project Defense questions for this project."],
    preview_only: true,
    public_recruiter_sharing_enabled: false,
    note: "This is a student preview of the evidence package collected for this project. It is private by default — use the controls below to publish a recruiter-safe link when you're ready to share.",
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
  it("renders an Evidence Traceability section with skill anchors and a private note", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
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
        evidence_traces: [
          {
            trace_id: "github-proof",
            source_type: "GitHub Proof",
            source_title: "octocat/Hello-World",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "Repository analyzed; Python backend files detected.",
            safe_detail: "Static analysis detected backend files.",
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
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(screen.getByText("Evidence Traceability")).toBeInTheDocument()
    expect(screen.getAllByTestId("evidence-trace").length).toBe(2)
    expect(screen.getByTestId("evidence-trace-link")).toHaveAttribute("href", "https://github.com/octocat/Hello-World")
    expect(screen.getByTestId("evidence-trace-private-note").textContent).toContain("evidence vault")
    expect(screen.getByTestId("skill-why").textContent).toContain("Demonstrated")
    expect(screen.getByTestId("skill-trace-links")).toBeInTheDocument()
  })

  it("Document Proof: matrix sources and the trace agree on the matched skill only", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        documents: [{ title: "Final Year Project Report", source_type: "document", status: "analyzed" }],
        skill_evidence: [
          {
            skill: "Python",
            status: "Supporting evidence",
            evidence_chip_count: 0,
            notes: "Supported by an attached Document Proof referencing this skill.",
            supporting_sources: ["Document Proof"],
            limitations: [],
            evidence_traces: ["document-proof-1"],
          },
          {
            skill: "React",
            status: "Not assessed",
            evidence_chip_count: 0,
            notes: "No evidence has been reviewed for this skill yet.",
            supporting_sources: [],
            limitations: ["Not yet strongly evidenced — treat as a claim pending more proof."],
            evidence_traces: [],
          },
        ],
        evidence_traces: [
          {
            trace_id: "document-proof-1",
            source_type: "Document Proof",
            source_title: "Final Year Project Report",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "Final Year Project Report (analyzed) — a supporting document the analyzer matched to Python.",
            safe_detail: "The document was analyzed and references these specific skills.",
            evidence_anchor: "document-proof-1",
            public_url: null,
            public_url_label: null,
            timestamp: null,
            limitation: "Recruiter can see the summarized evidence; the original private document is not publicly exposed.",
            is_publicly_openable: false,
            private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // Only Python's row lists Document Proof; React's does not (no over-claim).
    const sourceBlocks = screen.getAllByTestId("skill-supporting-sources")
    expect(sourceBlocks).toHaveLength(1)
    expect(sourceBlocks[0].textContent).toContain("Document Proof")

    // The Document Proof trace scopes itself to Python and shows the private note,
    // never an open document link.
    const docTrace = screen
      .getAllByTestId("evidence-trace")
      .find((el) => el.getAttribute("data-source-type") === "Document Proof")!
    expect(docTrace).toBeTruthy()
    expect(docTrace.textContent).toContain("Python")
    expect(docTrace.textContent).not.toContain("React")
    expect(screen.getByTestId("evidence-trace-private-note").textContent).toContain("evidence vault")
    expect(screen.queryByTestId("evidence-trace-link")).not.toBeInTheDocument()
  })

  it("Document Proof: an unmatched document is project-level only and claims no skill", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        documents: [{ title: "Design Notes", source_type: "document", status: "analyzed" }],
        skill_evidence: [
          {
            skill: "Python",
            status: "Not assessed",
            evidence_chip_count: 0,
            notes: "No evidence has been reviewed for this skill yet.",
            supporting_sources: [],
            limitations: ["Not yet strongly evidenced — treat as a claim pending more proof."],
            evidence_traces: [],
          },
        ],
        evidence_traces: [
          {
            trace_id: "document-proof-1",
            source_type: "Document Proof",
            source_title: "Design Notes",
            skill_names: [],
            qualitative_status: "Supporting evidence",
            safe_summary: "Design Notes (analyzed) — attached as project context; not mapped to specific skills.",
            safe_detail: "The document provides written project context.",
            evidence_anchor: "document-proof-1",
            public_url: null,
            public_url_label: null,
            timestamp: null,
            limitation: "Document evidence was attached as project context but not mapped to specific skills.",
            is_publicly_openable: false,
            private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // No skill row claims Document Proof support.
    expect(screen.queryByTestId("skill-supporting-sources")).not.toBeInTheDocument()

    // The trace renders the honest project-level limitation and the private note,
    // with no skill badges.
    const docTrace = screen
      .getAllByTestId("evidence-trace")
      .find((el) => el.getAttribute("data-source-type") === "Document Proof")!
    expect(docTrace.textContent).toContain("not mapped to specific skills")
    expect(docTrace.textContent).not.toContain("Python")
    expect(screen.getByTestId("evidence-trace-private-note")).toBeInTheDocument()
    expect(screen.queryByTestId("evidence-trace-link")).not.toBeInTheDocument()
  })

  it("renders the project summary", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(screen.getByText(/tracks student skill evidence/i)).toBeInTheDocument()
    expect(screen.getByText("octocat/Hello-World")).toBeInTheDocument()
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0)
    expect(screen.getAllByText("React").length).toBeGreaterThan(0)
  })

  it("renders the in-page jump nav and per-skill supporting sources + limitations", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
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
            status: "Not assessed",
            evidence_chip_count: 0,
            notes: "No evidence has been reviewed for this skill yet.",
            supporting_sources: [],
            limitations: ["Not yet strongly evidenced — treat as a claim pending more proof."],
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // Jump nav links to the evidence section anchors.
    const nav = screen.getByTestId("report-jump-nav")
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"))
    expect(hrefs).toEqual(
      expect.arrayContaining([
        "#github-proof",
        "#documents",
        "#website-proof",
        "#project-defense",
        "#skill-evidence",
        "#limitations",
      ]),
    )

    const sourceBlocks = screen.getAllByTestId("skill-supporting-sources")
    expect(sourceBlocks).toHaveLength(1)
    expect(sourceBlocks[0].textContent).toContain("GitHub Proof")
    expect(sourceBlocks[0].textContent).toContain("Video Evidence")

    expect(screen.getByTestId("skill-limitations").textContent).toContain("pending more proof")
  })

  it("shows the student-preview-only notice and does not claim public recruiter sharing", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())

    render(<ProjectReportView projectId="proj-1" />)

    const notice = await screen.findByTestId("report-preview-notice")
    expect(notice.textContent).toMatch(/student preview/i)
    expect(notice.textContent).toMatch(/private by default/i)
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

describe("ProjectReportView — proof-native matrix links + precise anchors", () => {
  it("renders proof-native labels and every matrix link resolves to its exact trace card", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          {
            skill: "Python",
            status: "Supporting evidence",
            evidence_chip_count: 0,
            notes: "Matched in a defense answer and the repository.",
            supporting_sources: ["GitHub Proof", "Project Defense"],
            limitations: [],
            // References the coarse GitHub overview trace whose anchor would
            // collide with the "github-proof" section id unless namespaced.
            evidence_traces: ["github-proof", "project-defense-q1"],
          },
        ],
        evidence_traces: [
          {
            trace_id: "github-proof",
            source_type: "GitHub Proof",
            source_title: "octocat/Hello-World",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "Repository analyzed.",
            safe_detail: "Repository-level evidence, not line-level proof.",
            evidence_anchor: "trace-github-proof",
            location_type: "repo_level",
            location_label: "repo-level",
            public_url: "https://github.com/octocat/Hello-World",
            public_url_label: "View public repository",
            is_publicly_openable: true,
            limitation: "Repository-level analysis; not line-level proof.",
            private_evidence_note: null,
          },
          {
            trace_id: "project-defense-q1",
            source_type: "Project Defense",
            source_title: "Project Defense — Q1",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "The candidate answered this question in their own words.",
            safe_detail: "Self-explanation evidence.",
            evidence_anchor: "trace-project-defense-q1",
            location_type: "defense_question",
            location_label: "Q1",
            question_text: "How did you implement the risk-scoring API?",
            is_publicly_openable: false,
            limitation: "Self-explanation evidence; combine with artifact evidence.",
            private_evidence_note: "Answer is summarized; the raw transcript is not exposed.",
          },
        ],
      }),
    )

    const { container } = render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // Proof-native short labels, not bare source names.
    const links = screen.getByTestId("skill-trace-links")
    expect(links.textContent).toContain("GitHub: repo-level")
    expect(links.textContent).toContain("Defense Q1")
    expect(links.textContent).not.toContain("Project Defense →")

    // Every matrix link resolves to a rendered trace *card* (not a section header).
    const anchors = Array.from(links.querySelectorAll("a")) as HTMLAnchorElement[]
    expect(anchors).toHaveLength(2)
    for (const a of anchors) {
      const id = (a.getAttribute("href") || "").slice(1)
      const target = container.querySelector(`#${id}`)
      expect(target).not.toBeNull()
      expect(target?.getAttribute("data-testid")).toBe("evidence-trace")
    }

    // No DOM id is duplicated across the whole report (section ids vs trace ids).
    const allIds = Array.from(container.querySelectorAll("[id]")).map((el) => el.id)
    expect(new Set(allIds).size).toBe(allIds.length)

    // The defense question text renders on its trace card; no numeric scores leak.
    expect(screen.getByTestId("evidence-trace-question").textContent).toContain(
      "How did you implement the risk-scoring API?",
    )
    expect(document.body.textContent ?? "").not.toMatch(/\/100|\btrust score\b/i)
  })

  it("renders proof-native deeper evidence: GitHub file path, document page+snippet, defense answer excerpt", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          {
            skill: "Python",
            status: "Supporting evidence",
            evidence_chip_count: 0,
            notes: "File-level GitHub evidence + a document page and a defense answer.",
            supporting_sources: ["GitHub Proof", "Document Proof", "Project Defense"],
            limitations: [],
            evidence_traces: ["github-file-app-routes-py", "document-1-python", "project-defense-q1"],
          },
        ],
        evidence_traces: [
          {
            trace_id: "github-file-app-routes-py",
            source_type: "GitHub Proof",
            source_title: "octocat/Hello-World — app/routes.py",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "The analyzer flagged app/routes.py.",
            safe_detail: "File-level evidence; not line-level proof.",
            evidence_anchor: "trace-github-file-app-routes-py",
            location_type: "github_file",
            location_label: "app/routes.py",
            location_detail: "app/routes.py",
            file_path: "app/routes.py",
            public_url: "https://github.com/octocat/Hello-World/blob/main/app/routes.py",
            public_url_label: "View file on GitHub",
            is_publicly_openable: true,
            limitation: "Identifies a relevant file, not the exact lines or author.",
            private_evidence_note: null,
          },
          {
            trace_id: "document-1-python",
            source_type: "Document Proof",
            source_title: "Final Year Project Report",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "A supporting document matched to Python on page 2.",
            safe_detail: "A safe excerpt/page is shown rather than the raw file.",
            evidence_anchor: "trace-document-1-python",
            location_type: "document_page",
            location_label: "Page 2",
            page_number: 2,
            snippet: "Implements the FastAPI routing layer.",
            is_publicly_openable: false,
            limitation: "Document evidence supports but does not prove authorship.",
            private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
          },
          {
            trace_id: "project-defense-q1",
            source_type: "Project Defense",
            source_title: "Project Defense — Q1",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "The candidate answered this question in their own words.",
            safe_detail: "Self-explanation evidence.",
            evidence_anchor: "trace-project-defense-q1",
            location_type: "defense_question",
            location_label: "Q1",
            question_text: "How did you build the routing layer?",
            answer_excerpt: "I built the routing layer and the React dashboard myself.",
            is_publicly_openable: false,
            limitation: "Self-explanation evidence; combine with artifact evidence.",
            private_evidence_note: "Answer is summarized; the raw transcript is not exposed.",
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // Proof-native matrix labels for the deeper sources.
    const links = screen.getByTestId("skill-trace-links")
    expect(links.textContent).toContain("GitHub: app/routes.py")
    expect(links.textContent).toContain("Doc: Page 2")
    expect(links.textContent).toContain("Defense Q1")

    // The file path renders on the GitHub file trace card, with its public file link.
    expect(screen.getByTestId("evidence-trace-file").textContent).toContain("app/routes.py")

    // Document page + bounded snippet render on the document trace card.
    expect(screen.getByTestId("evidence-trace-page").textContent).toContain("Page 2")
    expect(screen.getByTestId("evidence-trace-snippet").textContent).toContain(
      "Implements the FastAPI routing layer.",
    )

    // Bounded defense answer excerpt renders (private surface only).
    expect(screen.getByTestId("evidence-trace-answer").textContent).toContain(
      "I built the routing layer and the React dashboard myself.",
    )
  })

  it("renders GitHub line/function code evidence, Website OCR card, and a document citation", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          {
            skill: "Python",
            status: "Supporting evidence",
            evidence_chip_count: 0,
            notes: "Line-level GitHub code, a Website OCR card, and a document citation.",
            supporting_sources: ["GitHub Proof", "Website Proof", "Document Proof"],
            limitations: [],
            evidence_traces: ["github-code-src-main-py", "website-proof-1-ocr", "document-1-python"],
          },
        ],
        evidence_traces: [
          {
            trace_id: "github-code-src-main-py",
            source_type: "GitHub Proof",
            source_title: "octocat/Hello-World — src/main.py (lines 24-38)",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "The analyzer located code in src/main.py (lines 24-38).",
            safe_detail: "Line-level code evidence.",
            evidence_anchor: "trace-github-code-src-main-py",
            location_type: "github_function",
            location_label: "function classify_image",
            location_detail: "src/main.py (lines 24-38)",
            file_path: "src/main.py",
            line_start: 24,
            line_end: 38,
            function_name: "classify_image",
            commit_sha: "abcdef0123456789abcdef0123456789abcdef01",
            code_snippet: "def classify_image(img):\n    return model.predict(img)",
            public_url: "https://github.com/octocat/Hello-World/blob/main/src/main.py#L24-L38",
            public_url_label: "View code on GitHub",
            is_publicly_openable: true,
            limitation: "Pinpoints skill-relevant code, but is not proof of sole authorship.",
            private_evidence_note: null,
          },
          {
            trace_id: "website-proof-1-ocr",
            source_type: "Website Proof",
            source_title: "https://demo.example.com — OCR summary",
            skill_names: ["Python"],
            qualitative_status: "Evidence observed",
            safe_summary: "Text read on-screen: Prediction: cat.",
            safe_detail: "Safe OCR summary; no raw OCR dump is exposed.",
            evidence_anchor: "trace-website-proof-1-ocr",
            location_type: "website_ocr",
            location_label: "OCR summary",
            is_publicly_openable: false,
            limitation: "Website proof confirms observed behaviour, not source-code authorship.",
            private_evidence_note: "Captured during the proof session; only a safe summary is shown.",
          },
          {
            trace_id: "document-1-python",
            source_type: "Document Proof",
            source_title: "Final Year Project Report",
            skill_names: ["Python"],
            qualitative_status: "Supporting evidence",
            safe_summary: "A supporting document matched to Python.",
            safe_detail: "A safe citation is shown rather than the raw file.",
            evidence_anchor: "trace-document-1-python",
            location_type: "document_citation",
            location_label: "Citation",
            location_detail: "System Design",
            citation: "System Design",
            is_publicly_openable: false,
            limitation: "Document evidence supports but does not prove authorship.",
            private_evidence_note: "Private document retained in student evidence vault.",
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    // Proof-native matrix labels for the deepest GitHub/Website/Document sources.
    const links = screen.getByTestId("skill-trace-links")
    expect(links.textContent).toContain("GitHub: function classify_image")
    expect(links.textContent).toContain("Website: OCR summary")
    expect(links.textContent).toContain("Doc: Citation")

    // The GitHub code card shows file + line range + function + a safe snippet.
    const fileCell = screen.getByTestId("evidence-trace-file")
    expect(fileCell.textContent).toContain("src/main.py")
    expect(screen.getByTestId("evidence-trace-lines").textContent).toContain("lines 24-38")
    expect(screen.getByTestId("evidence-trace-function").textContent).toContain("classify_image")
    // The pinned commit SHA renders, shortened to 7 chars.
    expect(screen.getByTestId("evidence-trace-commit").textContent).toContain("abcdef0")
    expect(screen.getByTestId("evidence-trace-code").textContent).toContain("classify_image")

    // The Website OCR summary card renders with no raw payload / URL link.
    const ocrCard = screen
      .getAllByTestId("evidence-trace")
      .find((el) => el.getAttribute("id") === "trace-website-proof-1-ocr")
    expect(ocrCard?.textContent).toContain("Prediction: cat")

    // The document citation renders (no raw download URL).
    expect(screen.getByTestId("evidence-trace-citation").textContent).toContain("System Design")
  })
})
