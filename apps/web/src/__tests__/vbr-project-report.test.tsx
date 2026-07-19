/**
 * Final VBR Report v1 (student preview) — frontend rendering tests.
 *
 * Covers: project summary, evidence package cards, skill evidence table
 * (qualitative labels, no numeric scores), video evidence chips (with and
 * without), limitations / not-assessed section, and the "student preview
 * only" notice. Never renders raw transcript text or private fields.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
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
    // The skill card groups its evidence by proof source (GitHub + Document).
    const groups = screen.getAllByTestId("skill-evidence-group")
    expect(groups.map((g) => g.getAttribute("data-source-type"))).toEqual(
      expect.arrayContaining(["GitHub Proof", "Document Proof"]),
    )
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
        "#skills-demonstrated",
        "#github-proof",
        "#documents",
        "#website-proof",
        "#project-defense",
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

    expect(await screen.findByText("Project Evidence Summary")).toBeInTheDocument()
    expect(screen.getAllByText("GitHub Proof").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Documents").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Website Proof").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Project Defense").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Video Defense").length).toBeGreaterThan(0)
  })

  it("renders skill evidence cards with qualitative labels, never numeric scores", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, notes: "Explained clearly during the Project Defense." },
          { skill: "React", status: "Partially demonstrated", evidence_chip_count: 1, notes: "Mentioned during the Project Defense but not fully explained." },
        ],
      })
    )

    render(<ProjectReportView projectId="proj-1" />)

    const cards = await screen.findAllByTestId("skill-evidence-card")
    expect(cards).toHaveLength(2)
    expect(screen.getByText("Demonstrated")).toBeInTheDocument()
    expect(screen.getByText("Partially demonstrated")).toBeInTheDocument()

    // The report is no longer a spreadsheet: no evidence table renders.
    expect(document.querySelector("table")).toBeNull()

    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/confidence_score/i)
    expect(raw).not.toMatch(/trust score/i)
  })

  it("links each skill card to its full Skill Report (Phase 2)", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        skill_evidence: [
          { skill: "Python", status: "Demonstrated", evidence_chip_count: 2, notes: "" },
          { skill: "Machine Learning", status: "Supporting evidence", evidence_chip_count: 1, notes: "" },
        ],
      })
    )

    render(<ProjectReportView projectId="proj-1" />)

    const links = await screen.findAllByTestId("skill-report-cta")
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute("href", "/student/vbr/passport/skills/python")
    expect(links[1]).toHaveAttribute("href", "/student/vbr/passport/skills/machine-learning")
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

  // ── Skill-specific Website Behavior Evidence (owner/private view) ────────────

  it("Website Behavior Evidence: renders the behaviour claim + per-skill relevance under the correct skill only", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        website_skill_evidence: [
          {
            target_website: "https://demo.example.com",
            behavior_claim: "User input produces a prediction/result display.",
            website_purpose_key: "prediction_result_display",
            website_purpose_label: "Prediction / result display",
            website_purpose_summary: "An input → prediction/result flow was shown.",
            skill_mapping_available: true,
            skills: [
              {
                skill_name: "React",
                relevance_key: "direct_frontend_evidence",
                relevance_label: "Direct React evidence — interactive product UI demonstrated",
                relevance_summary: "The recorded interactive UI behaviour is itself the subject of React.",
                limitation:
                  "Confirms observed behaviour at inspection time, not source-code authorship or ongoing uptime.",
                is_direct_evidence: true,
              },
            ],
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(screen.getByTestId("website-skill-evidence")).toBeInTheDocument()
    expect(screen.getByTestId("website-behavior-claim")).toHaveTextContent(
      "User input produces a prediction/result display.",
    )
    expect(screen.getByText("Prediction / result display")).toBeInTheDocument()

    const rows = screen.getAllByTestId("website-skill-relevance")
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute("data-skill", "React")
    expect(rows[0]).toHaveTextContent("Direct React evidence")
    // A frontend UI reads as DIRECT evidence.
    expect(rows[0]).toHaveTextContent("Direct")
  })

  it("Website Runtime Inspection: renders the runtime claim, target site, observed action/output and recruiter checklist", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        claimed_skills: ["Machine Learning"],
        website_skill_evidence: [
          {
            target_website: "https://demo.example.com",
            behavior_claim: "User input produces a prediction/result display.",
            website_purpose_key: "prediction_result_display",
            website_purpose_label: "Prediction / result display",
            website_purpose_summary: "An input → prediction/result flow was shown.",
            runtime_claim_observed:
              "Recorded website behavior shows a browser-based Machine Learning workflow where user input leads to a visible prediction/result output.",
            target_domain: "demo.example.com",
            app_context: "Crash Risk Predictor",
            page_context_label: "Prediction / output page",
            user_action_observed: "Input was provided to run a prediction/inference.",
            output_observed: "A prediction/result was displayed after the input.",
            verification_mode: "directly_verifiable_live",
            verification_mode_label: "Directly verifiable live",
            recruiter_checklist: [
              "Open the live website.",
              "Navigate to the same workflow/page shown in this proof.",
              "Provide similar input — input was provided to run a prediction/inference.",
              "Confirm the same output/result appears — a prediction/result was displayed after the input.",
              "Compare what you see with the recorded evidence below.",
            ],
            skill_mapping_available: true,
            skills: [
              {
                skill_name: "Machine Learning",
                relevance_key: "ml_product_context",
                relevance_label:
                  "Machine Learning product behaviour context — not Machine Learning implementation proof",
                relevance_summary: "The website shows model-powered product behaviour.",
                limitation:
                  "Website prediction/output demonstrates product behaviour at inspection time; it does not, by itself, prove model training or ML implementation.",
                is_direct_evidence: false,
              },
            ],
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(screen.getByTestId("website-runtime-claim")).toHaveTextContent(
      "browser-based Machine Learning workflow",
    )
    expect(screen.getByTestId("website-target-site")).toHaveTextContent("demo.example.com")
    expect(screen.getByTestId("website-target-site")).toHaveTextContent("Crash Risk Predictor")
    expect(screen.getByTestId("website-user-action")).toHaveTextContent(
      "Input was provided to run a prediction/inference.",
    )
    expect(screen.getByTestId("website-output-observed")).toHaveTextContent(
      "A prediction/result was displayed after the input.",
    )
    expect(screen.getByTestId("website-verification-mode")).toHaveAttribute("data-mode", "live")
    const steps = screen.getAllByTestId("website-checklist-item").map((s) => s.textContent)
    expect(steps[0]).toContain("Open the live website.")
    expect(steps.some((s) => s?.includes("Provide similar input"))).toBe(true)
  })

  it("Website Behavior Evidence: a Machine Learning skill reads as supporting context, never direct implementation proof", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        claimed_skills: ["Machine Learning"],
        website_skill_evidence: [
          {
            target_website: "https://demo.example.com",
            behavior_claim: "User input produces a prediction/result display.",
            website_purpose_key: "prediction_result_display",
            website_purpose_label: "Prediction / result display",
            website_purpose_summary: "An input → prediction/result flow was shown.",
            skill_mapping_available: true,
            skills: [
              {
                skill_name: "Machine Learning",
                relevance_key: "ml_product_context",
                relevance_label:
                  "Machine Learning product behaviour context — not Machine Learning implementation proof",
                relevance_summary: "The website shows model-powered product behaviour.",
                limitation:
                  "Website prediction/output demonstrates product behaviour at inspection time; it does not, by itself, prove model training or ML implementation.",
                is_direct_evidence: false,
              },
            ],
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    const row = screen.getByTestId("website-skill-relevance")
    expect(row).toHaveTextContent("not Machine Learning implementation proof")
    expect(row).toHaveTextContent("Supporting context")
    expect(row).not.toHaveTextContent("Direct React")
    expect(screen.getByText(/does not, by itself, prove model training/)).toBeInTheDocument()
  })

  it("Website Behavior Evidence: states the gap honestly when no claimed skill maps, and never leaks raw fields", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(
      makeReport({
        website_skill_evidence: [
          {
            target_website: "https://demo.example.com",
            behavior_claim: "The deployed application was live and reachable at inspection time.",
            website_purpose_key: "deployed_availability",
            website_purpose_label: "Deployed application availability",
            website_purpose_summary: "A live deployment was reachable.",
            skill_mapping_available: false,
            skills: [],
          },
        ],
      }),
    )

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(screen.getByTestId("website-skill-mapping-empty")).toHaveTextContent(
      "skill-specific mapping not available yet",
    )
    expect(screen.queryByTestId("website-skill-relevance")).not.toBeInTheDocument()

    // No raw DOM/OCR/visual/provider/storage-shaped fields ever render.
    const raw = document.body.textContent ?? ""
    expect(raw).not.toMatch(/screenshot|storage|signed|s3:\/\/|\.jpg|raw_/i)
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

    // Proof-native short labels on the grouped evidence jump links, not bare
    // source names.
    const cards = screen.getByTestId("skill-evidence-cards")
    expect(cards.textContent).toContain("GitHub: repo-level")
    expect(cards.textContent).toContain("Defense Q1")
    expect(cards.textContent).not.toContain("Project Defense →")

    // Every grouped-evidence jump link resolves to a rendered trace *card* (not a
    // section header).
    const anchors = screen.getAllByTestId("skill-evidence-jump") as HTMLAnchorElement[]
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

    // Proof-native labels for the deeper sources, on the grouped evidence links.
    const links = screen.getByTestId("skill-evidence-cards")
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

    // Proof-native labels for the deepest GitHub/Website/Document sources, on
    // the grouped evidence jump links.
    const links = screen.getByTestId("skill-evidence-cards")
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

// Domain integration: copied/shared public project-report links must stay on the
// canonical app origin (NEXT_PUBLIC_APP_URL) rather than a preview origin.
describe("ProjectReportView — canonical public link origin", () => {
  afterEach(() => vi.unstubAllEnvs())

  function renderPublishedReport() {
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())
    vi.mocked(getVBRProjectReportPublishStatus).mockResolvedValue(publishedStatus("tok-xyz"))
    render(<ProjectReportView projectId="proj-1" />)
  }

  it("uses NEXT_PUBLIC_APP_URL for the public report link when it is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com")
    renderPublishedReport()

    const url = await screen.findByTestId("public-link-url")
    expect(url.textContent).toContain("https://veribridgeai.com/vbr/report/tok-xyz")
    // In production the canonical origin must win — never a localhost link.
    expect(url.textContent).not.toContain("localhost")
  })

  it("normalizes a trailing slash on NEXT_PUBLIC_APP_URL (no double slash)", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com/")
    renderPublishedReport()

    const url = await screen.findByTestId("public-link-url")
    expect(url.textContent).toContain("https://veribridgeai.com/vbr/report/tok-xyz")
    expect(url.textContent).not.toContain("veribridgeai.com//vbr/")
  })

  it("falls back to window.location.origin when NEXT_PUBLIC_APP_URL is unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "")
    renderPublishedReport()

    const url = await screen.findByTestId("public-link-url")
    expect(url.textContent).toContain(`${window.location.origin}/vbr/report/tok-xyz`)
  })
})

// ── Skill-first Project Report (skill cards, not a spreadsheet) ───────────────
//
// The main body is now "Skills Demonstrated in This Project": one card per
// claimed skill answering skill → this project → proof types → evidence
// summaries → limitations. These tests assert the redesigned pattern.
describe("ProjectReportView — skill-first evidence cards", () => {
  // Python is well-evidenced (GitHub + Document + Website + Project Defense);
  // React is Not assessed. A vault-only proof exists for a related skill.
  function skillFirstReport() {
    return makeReport({
      claimed_skills: ["Python", "React"],
      website_proofs: [
        { target_website: "https://demo.example.com", evidence_strength: "Evidence observed", workflow_confidence: "high", supported_skills: ["Python"] },
      ],
      skill_evidence: [
        {
          skill: "Python",
          status: "Partially demonstrated",
          evidence_chip_count: 1,
          notes: "Supported across GitHub, Website, and the Project Defense.",
          supporting_sources: ["GitHub Proof", "Website Proof", "Document Proof", "Project Defense"],
          limitations: ["Website behavior supports runtime output, not code authorship."],
          why_this_status: "Marked 'Partially demonstrated' because supporting evidence was found in: GitHub Proof, Website Proof, Document Proof and Project Defense.",
          recruiter_can_verify: "Open the evidence trace(s) below to see why this skill is supported.",
          evidence_traces: ["gh-python", "web-python", "doc-python", "def-python"],
        },
        {
          skill: "React",
          status: "Not assessed",
          evidence_chip_count: 0,
          notes: "No evidence has been reviewed for this skill yet.",
          supporting_sources: [],
          limitations: ["Not yet strongly evidenced — treat as a claim pending more proof."],
          why_this_status: "Marked 'Not assessed' because no evidence source has been reviewed for this skill yet.",
          recruiter_can_verify: "No evidence is attached for this skill yet — there is nothing to verify.",
          evidence_traces: [],
        },
      ],
      evidence_traces: [
        {
          trace_id: "gh-python",
          source_type: "GitHub Proof",
          source_title: "octocat/Hello-World — app/routes.py",
          skill_names: ["Python"],
          qualitative_status: "Supporting evidence",
          safe_summary: "API route/service files support backend endpoint implementation.",
          safe_detail: "File-level GitHub evidence.",
          evidence_anchor: "trace-gh-python",
          location_type: "github_file",
          location_label: "app/routes.py",
          file_path: "app/routes.py",
          public_url: "https://github.com/octocat/Hello-World/blob/main/app/routes.py",
          public_url_label: "View file on GitHub",
          is_publicly_openable: true,
          limitation: "Identifies a relevant file, not sole authorship.",
          private_evidence_note: null,
        },
        {
          trace_id: "web-python",
          source_type: "Website Proof",
          source_title: "https://demo.example.com — behaviour",
          skill_names: ["Python"],
          qualitative_status: "Evidence observed",
          safe_summary: "Runtime/demo behavior shows an input → prediction flow.",
          safe_detail: "Safe website behaviour summary.",
          evidence_anchor: "trace-web-python",
          location_type: "website_url",
          location_label: "Live URL",
          is_publicly_openable: false,
          limitation: "Website behavior supports runtime output, not code authorship.",
          private_evidence_note: "Captured during the proof session; only a safe summary is shown.",
        },
        {
          trace_id: "doc-python",
          source_type: "Document Proof",
          source_title: "Final Year Project Report",
          skill_names: ["Python"],
          qualitative_status: "Supporting evidence",
          safe_summary: "Project report describes the API workflow.",
          safe_detail: "Written context.",
          evidence_anchor: "trace-doc-python",
          location_type: "document_page",
          location_label: "Page 2",
          page_number: 2,
          is_publicly_openable: false,
          limitation: "Document evidence supports but does not prove authorship.",
          private_evidence_note: "Private document retained in student evidence vault; only a safe summary is shown.",
        },
        {
          trace_id: "def-python",
          source_type: "Project Defense",
          source_title: "Project Defense — Q1",
          skill_names: ["Python"],
          qualitative_status: "Supporting evidence",
          safe_summary: "Candidate explained the API design in their own words.",
          safe_detail: "Self-explanation evidence.",
          evidence_anchor: "trace-def-python",
          location_type: "defense_question",
          location_label: "Q1",
          question_text: "How did you design the API?",
          is_publicly_openable: false,
          limitation: "Self-explanation evidence; combine with artifact evidence.",
          private_evidence_note: "Answer is summarized; the raw transcript is not exposed.",
        },
      ],
      other_student_proofs: [
        {
          skill: "Node",
          proofs: [
            {
              skill_name: "Node",
              proof_type: "GitHub Proof",
              source_id: "vault-1",
              source_table: "github_proof_submissions",
              project_id: null,
              attached_project_ids: [],
              title: "another-repo",
              source_label: "GitHub",
              safe_summary: "A repo from another project in your vault.",
              public_safe: true,
              visibility: "private",
              limitation: "Not attached to this project.",
              is_attached_to_project: false,
            },
          ],
          proof_types: ["GitHub Proof"],
          attached_count: 0,
          unattached_count: 1,
          has_unattached: true,
        },
      ],
    })
  }

  it("renders the 'Skills Demonstrated in This Project' main section", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)

    expect(await screen.findByText("Skills Demonstrated in This Project")).toBeInTheDocument()
    // One card per claimed skill.
    expect(screen.getAllByTestId("skill-evidence-card")).toHaveLength(2)
  })

  it("renders a skill card with its status and skill-specific proof chips", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    const python = screen.getAllByTestId("skill-evidence-card").find((c) => c.getAttribute("data-skill") === "Python")!
    expect(python).toBeTruthy()
    expect(python.getAttribute("data-status")).toBe("Partially demonstrated")

    // The chips are the skill/project-specific supporting sources — not blindly
    // every project proof type.
    const chips = python.querySelector("[data-testid='skill-supporting-sources']")!
    expect(chips.textContent).toContain("GitHub Proof")
    expect(chips.textContent).toContain("Website Proof")
    expect(chips.textContent).toContain("Project Defense")
  })

  it("groups a skill's evidence rows by proof source", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    const python = screen.getAllByTestId("skill-evidence-card").find((c) => c.getAttribute("data-skill") === "Python")!
    const groups = Array.from(python.querySelectorAll("[data-testid='skill-evidence-group']"))
    const sourceTypes = groups.map((g) => g.getAttribute("data-source-type"))
    // Canonical order: GitHub → Document → Website → Project Defense.
    expect(sourceTypes).toEqual(["GitHub Proof", "Document Proof", "Website Proof", "Project Defense"])

    // Each group carries its safe evidence summary.
    const github = groups.find((g) => g.getAttribute("data-source-type") === "GitHub Proof")!
    expect(github.textContent).toContain("API route/service files")
  })

  it("marks an unevidenced skill 'Not assessed' and explains what is missing", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    const react = screen.getAllByTestId("skill-evidence-card").find((c) => c.getAttribute("data-skill") === "React")!
    expect(react.getAttribute("data-status")).toBe("Not assessed")
    // No proof chips and no evidence groups on the unevidenced skill.
    expect(react.querySelector("[data-testid='skill-supporting-sources']")).toBeNull()
    expect(react.querySelector("[data-testid='skill-evidence-group']")).toBeNull()
    // It explains what is missing rather than implying silent support.
    expect(react.querySelector("[data-testid='skill-not-assessed']")!.textContent).toMatch(/pending more evidence/i)
  })

  it("shows Website Proof under the relevant skill only", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    // Exactly one Website Proof evidence group in the whole skills section, and
    // it lives on the Python card (the skill the website evidence supports).
    const websiteGroups = screen
      .getAllByTestId("skill-evidence-group")
      .filter((g) => g.getAttribute("data-source-type") === "Website Proof")
    expect(websiteGroups).toHaveLength(1)

    const react = screen.getAllByTestId("skill-evidence-card").find((c) => c.getAttribute("data-skill") === "React")!
    expect(react.querySelector("[data-source-type='Website Proof']")).toBeNull()
  })

  it("keeps wider-vault evidence in a separate section, not counted as project proof", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    // The vault-only proof is in its own clearly-labelled section.
    const vault = screen.getByTestId("other-student-proofs")
    expect(vault.textContent).toMatch(/not attached to this project/i)

    // The vault skill ("Node") never appears as a project skill card.
    const cardSkills = screen.getAllByTestId("skill-evidence-card").map((c) => c.getAttribute("data-skill"))
    expect(cardSkills).not.toContain("Node")
  })

  it("no longer renders the old table-like Skill Evidence Matrix", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    expect(screen.queryByText("Skill Evidence Matrix")).not.toBeInTheDocument()
    expect(document.querySelector("table")).toBeNull()
  })

  it("never renders raw/private fields on the skill cards", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(skillFirstReport())

    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skills Demonstrated in This Project")

    const raw = document.body.textContent ?? ""
    for (const unsafe of ["storage_path", "signed_url", "access_token", "vbr/sessions", "full_text", ".webm", ".mp4", "Bearer ", "source_id", "vault-1"]) {
      expect(raw).not.toContain(unsafe)
    }
    expect(raw).not.toMatch(/\/100/)
    expect(raw).not.toMatch(/trust score/i)
  })
})

describe("ProjectReportView — Project Defense inspection", () => {
  function inspectionReport(): VBRStudentProjectReportResponse {
    return makeReport({
      evidence_package: {
        github_proof_attached: true,
        documents_count: 0,
        website_proofs_count: 0,
        project_defense_completed: true,
        video_defense_recorded: true,
        video_evidence_chip_count: 1,
      },
      project_defense_inspection: [
        {
          evidence_id_safe: "defense-inspection-1",
          question_text: "How does your React dashboard update state?",
          question_kind: "skill_explanation",
          project_title: "Skill Evidence Tracker",
          mapped_skill: "React",
          claim_type: "skill_understanding",
          answer_purpose: "skill_explanation",
          evidence_role: "candidate_explanation",
          qualitative_status: "Explained with evidence",
          safe_answer_summary: "I used hooks and lifted shared state up to a context provider.",
          evidence_basis_chips: ["Targeted question", "Candidate answer", "Privacy-safe summary"],
          timestamp_label: "Video 01:40",
          clip_start_seconds: 100.0,
          clip_end_seconds: 120.0,
          clip_available: true,
          corroborates_github: true,
          corroborates_website: false,
          corroborates_document: false,
          corroboration_summary: "Corroborating defense evidence: GitHub Proof (implementation) for the same project.",
          what_this_demonstrates: "The student explained this React claim in their own words.",
          limitation: "Project Defense is explanation evidence.",
          public_safe: true,
          withheld_reason: null,
        },
      ],
    })
  }

  it("renders the Project Defense inspection section with a safe card", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(inspectionReport())
    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(await screen.findByTestId("report-project-defense-inspection")).toBeInTheDocument()
    expect(screen.getByTestId("pdi-question")).toHaveTextContent("How does your React dashboard update state?")
    expect(screen.getByTestId("pdi-answer-summary")).toHaveTextContent("hooks")
    expect(screen.getByTestId("pdi-skill")).toHaveTextContent("React")
    expect(screen.getByTestId("pdi-timestamp")).toHaveTextContent("Video 01:40")
    expect(screen.getByTestId("pdi-limitation")).toHaveTextContent("explanation evidence")
  })

  it("does not leak raw transcript / ids / storage in the inspection section", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(inspectionReport())
    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByTestId("report-project-defense-inspection")

    const raw = document.body.textContent ?? ""
    for (const unsafe of ["question_id", "transcript_segments", "storage_path", "signed_url", "vbr/sessions"]) {
      expect(raw).not.toContain(unsafe)
    }
  })
})

describe("ProjectReportView — Attached proof not yet skill-mapped strip", () => {
  const realUnmappedReport = () =>
    makeReport({
      real_unmapped_proof_context: [
        {
          proof_type: "GitHub Proof",
          project_id: "proj-1",
          project_title: "Skill Evidence Tracker",
          report_url: "/student/vbr/projects/proj-1/report",
          reason: "Analyzed source evidence exists, but no exact skill row consumed it yet.",
          safe_summary: "Analyzed GitHub source-code evidence is attached to this project.",
          evidence_label: "Analyzed source evidence",
          source_count: 2,
          inspection_anchor: "github-proof",
        },
        {
          proof_type: "Document Proof",
          project_id: "proj-1",
          project_title: "Skill Evidence Tracker",
          report_url: "/student/vbr/projects/proj-1/report",
          reason: "Analyzed document evidence exists, but it is not mapped to a specific skill yet.",
          safe_summary: "Final Year Project Report was analyzed and is attached as project context.",
          evidence_label: "Analyzed document evidence",
          inspection_anchor: "documents",
        },
      ],
    })

  it("renders the strip with per-proof-type honest entries and section jump links", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(realUnmappedReport())
    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    const strip = await screen.findByTestId("report-real-unmapped-strip")
    expect(strip).toHaveTextContent("Attached proof not yet skill-mapped")
    expect(strip).toHaveTextContent(
      "These proof sources are attached to this project but are not yet mapped to a specific skill claim",
    )

    const entries = screen.getAllByTestId("report-real-unmapped-entry")
    expect(entries.map((e) => e.getAttribute("data-proof-type"))).toEqual([
      "GitHub Proof",
      "Document Proof",
    ])
    expect(entries[0]).toHaveTextContent(
      "Analyzed source evidence exists, but no exact skill row consumed it yet.",
    )
    expect(entries[1]).toHaveTextContent(
      "Analyzed document evidence exists, but it is not mapped to a specific skill yet.",
    )

    // Entries jump to the existing proof sections instead of duplicating cards.
    const jumps = screen.getAllByTestId("report-real-unmapped-jump")
    expect(jumps.map((j) => j.getAttribute("href"))).toEqual(["#github-proof", "#documents"])
  })

  it("keeps the strip separate from the skill evidence cards — exact rows stay exact", async () => {
    vi.mocked(getVBRProjectReport).mockResolvedValue(realUnmappedReport())
    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByTestId("report-real-unmapped-strip")

    // The skill cards still render exactly the claimed skills, unchanged and
    // Not assessed — the unmapped context never promotes a skill claim.
    const cards = screen.getAllByTestId("skill-evidence-card")
    expect(cards.map((c) => c.getAttribute("data-skill"))).toEqual(["Python", "React"])
    for (const card of cards) {
      expect(card.getAttribute("data-status")).toBe("Not assessed")
    }
    // No unmapped entry renders inside a skill evidence card.
    for (const card of cards) {
      expect(card.textContent).not.toContain("not yet skill-mapped")
    }
  })

  it("renders no strip when the report has no real-unmapped context (URL-only metadata is never proof)", async () => {
    // repo_url is set on the report, but the backend qualified nothing.
    vi.mocked(getVBRProjectReport).mockResolvedValue(makeReport())
    render(<ProjectReportView projectId="proj-1" />)
    await screen.findByText("Skill Evidence Tracker")

    expect(screen.queryByTestId("report-real-unmapped-strip")).not.toBeInTheDocument()
    expect(screen.queryByText("Attached proof not yet skill-mapped")).not.toBeInTheDocument()
  })
})
