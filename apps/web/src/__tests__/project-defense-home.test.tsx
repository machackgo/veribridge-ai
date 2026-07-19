/**
 * Project-first Project Defense flow — selection home + selected-project workspace.
 *
 * Covers the product model: Project Defense is a defense layer on top of an
 * existing project, not a fourth standalone proof form. The page first shows
 * "Choose a project to defend"; selecting a project opens a workspace pre-loaded
 * with that project's existing evidence; the report link is gated conservatively;
 * and the recorder route stays reachable from the workspace.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { ProjectDefenseHome, dedupeEligibleProjects } from "../../components/passport/ProjectDefenseHome"
import type {
  EligibleProjectResponse,
  ProjectDefenseContextResponse,
  DefenseStatus,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  listEligibleDefenseProjects: vi.fn(),
  getProjectDefenseContext: vi.fn(),
  attachProjectDefenseProofs: vi.fn(),
  generateDefenseQuestions: vi.fn(),
  submitDefenseAnswers: vi.fn(),
  syncProjectDefenseToSkillGraph: vi.fn(),
  createProjectDefense: vi.fn(),
  getVBRSession: vi.fn(),
  getVBRSessionRecordingReadiness: vi.fn(),
}))

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
  listDocumentProofs: vi.fn(),
  listWebsiteProofs: vi.fn(),
  recommendWebsiteProofs: vi.fn(),
  uploadDocumentProof: vi.fn(),
}))

const mockRouterPush = vi.fn()
let searchParamValue: string | null = null

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useSearchParams: () => ({ get: (_k: string) => searchParamValue }),
}))

import {
  listEligibleDefenseProjects,
  getProjectDefenseContext,
  attachProjectDefenseProofs,
  generateDefenseQuestions,
  getVBRSession,
  getVBRSessionRecordingReadiness,
} from "@/lib/vbr-api"
import {
  listGitHubProofs,
  listDocumentProofs,
  listWebsiteProofs,
  recommendWebsiteProofs,
  uploadDocumentProof,
} from "@/lib/passport-api"

function makeEvidenceType(over: Partial<{ attached: boolean; count: number; label: string }> = {}) {
  return { attached: false, count: 0, label: "", ...over }
}

function makeEligibleProject(over: Partial<EligibleProjectResponse> = {}): EligibleProjectResponse {
  return {
    id: "proj-1",
    title: "Boston Smart Accident Risk Rerouting",
    description: "Accident-risk-aware routing on Google Cloud.",
    claimed_skills: ["Python", "Machine Learning"],
    repo_full_name: "machackgo/boston-smart-accident-risk-rerouting-google-cloud",
    defense_status: "not_started" as DefenseStatus,
    report_ready: false,
    evidence: {
      github_proof: makeEvidenceType({ attached: true, count: 1, label: "machackgo/boston" }),
      documents: makeEvidenceType(),
      website_proof: makeEvidenceType(),
      project_defense: makeEvidenceType(),
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}

function makeContext(over: Partial<ProjectDefenseContextResponse> = {}): ProjectDefenseContextResponse {
  return {
    project: {
      id: "proj-1",
      title: "Boston Smart Accident Risk Rerouting",
      repo_url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
      repo_full_name: "machackgo/boston-smart-accident-risk-rerouting-google-cloud",
      deployed_url: null,
      head_sha: null,
      status: "draft",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    metadata: {
      description: "Accident-risk-aware routing on Google Cloud.",
      claimed_skills: ["Python", "Machine Learning"],
      student_role: "I built the risk-scoring API.",
      individual_project_only: true,
      attached_proofs: {},
      phase: "project_defense_mvp_v1",
    },
    evidence: {
      github_proof: makeEvidenceType({ attached: true, count: 1, label: "machackgo/boston" }),
      documents: makeEvidenceType(),
      website_proof: makeEvidenceType(),
      project_defense: makeEvidenceType(),
    },
    defense_status: "not_started",
    report_ready: false,
    session_id: null,
    questions: [],
    ...over,
  }
}

beforeEach(() => {
  searchParamValue = null
  mockRouterPush.mockReset()
  vi.mocked(listEligibleDefenseProjects).mockReset().mockResolvedValue([])
  vi.mocked(getProjectDefenseContext).mockReset().mockResolvedValue(makeContext())
  vi.mocked(attachProjectDefenseProofs).mockReset()
  vi.mocked(generateDefenseQuestions).mockReset()
  vi.mocked(getVBRSession).mockReset().mockResolvedValue(null)
  vi.mocked(getVBRSessionRecordingReadiness)
    .mockReset()
    .mockResolvedValue({ ready: true, code: null, message: "Recording upload storage is ready." })
  vi.mocked(listGitHubProofs).mockReset().mockResolvedValue([])
  vi.mocked(listDocumentProofs).mockReset().mockResolvedValue([])
  vi.mocked(listWebsiteProofs).mockReset().mockResolvedValue([])
  vi.mocked(recommendWebsiteProofs).mockReset().mockRejectedValue(new Error("no backend"))
  vi.mocked(uploadDocumentProof).mockReset()
})

describe("ProjectDefenseHome — project selection", () => {
  it("first shows 'Choose a project to defend'", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([makeEligibleProject()])

    render(<ProjectDefenseHome />)

    expect(await screen.findByText(/choose a project to defend/i)).toBeInTheDocument()
    expect(
      screen.getByText(/strengthens an existing project by asking questions grounded/i),
    ).toBeInTheDocument()
  })

  it("renders existing projects as selectable cards with an evidence summary", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([makeEligibleProject()])

    render(<ProjectDefenseHome />)

    expect(await screen.findByText(/boston smart accident risk rerouting/i)).toBeInTheDocument()
    expect(screen.getByText(/accident-risk-aware routing on google cloud/i)).toBeInTheDocument()
    expect(screen.getByText("Python")).toBeInTheDocument()
    // Evidence summary rows: GitHub attached, Document/Website missing.
    expect(screen.getByText("GitHub Proof")).toBeInTheDocument()
    expect(screen.getByText("Document Proof")).toBeInTheDocument()
    expect(screen.getByText("Website Proof")).toBeInTheDocument()
    expect(screen.getByText(/project defense not started/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /defend this project/i })).toBeInTheDocument()
  })

  it("shows an empty state with create-from-proof options when there are no projects", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([])

    render(<ProjectDefenseHome />)

    expect(await screen.findByText(/no projects ready for defense yet/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /create project from github proof/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /create project from document proof/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /create project from website proof/i })).toBeInTheDocument()
  })
})

describe("ProjectDefenseHome — selected project workspace", () => {
  async function openWorkspace(context = makeContext()) {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([makeEligibleProject()])
    vi.mocked(getProjectDefenseContext).mockResolvedValue(context)

    render(<ProjectDefenseHome />)

    fireEvent.click(await screen.findByRole("button", { name: /defend this project/i }))
    await screen.findByText(/defend: boston smart accident risk rerouting/i)
  }

  // The Project Evidence Package renders each evidence layer as a labelled card
  // (a <Mono> label span followed by its status badge). Returns the card element
  // so a test can assert on that specific layer's status.
  function checklistCard(labelText: string): HTMLElement {
    const label = screen.getByText(labelText, { selector: "span" })
    return label.parentElement as HTMLElement
  }

  it("opens the selected project's workspace on 'Defend this project'", async () => {
    await openWorkspace()
    await waitFor(() => expect(getProjectDefenseContext).toHaveBeenCalledWith("proj-1"))
    expect(mockRouterPush).toHaveBeenCalledWith(
      "/student/proofs/project-defense?projectId=proj-1",
    )
  })

  it("shows the project title, description, skills, and evidence sections", async () => {
    await openWorkspace()

    expect(screen.getByText(/defend: boston smart accident risk rerouting/i)).toBeInTheDocument()
    expect(screen.getByText(/accident-risk-aware routing on google cloud/i)).toBeInTheDocument()
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0)

    // Evidence package sections for the four evidence layers.
    await screen.findByText(/project evidence package/i)
    expect(screen.getByText("GitHub Proof", { selector: "span" })).toBeInTheDocument()
    expect(screen.getByText("Documents", { selector: "span" })).toBeInTheDocument()
    expect(screen.getByText("Website Proof", { selector: "span" })).toBeInTheDocument()
    expect(screen.getByText("Manual Project Defense", { selector: "span" })).toBeInTheDocument()
  })

  it("shows an existing attached document proof from the loaded context", async () => {
    await openWorkspace(
      makeContext({
        metadata: {
          description: "Accident-risk-aware routing on Google Cloud.",
          claimed_skills: ["Python"],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            documents: [{ document_evidence_id: "doc-1", title: "Final Year Report.pdf" }],
          },
        },
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Final Year Report.pdf" }),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
    )

    await screen.findByText(/project evidence package/i)
    expect(await screen.findByText(/documents: final year report\.pdf/i)).toBeInTheDocument()
  })

  it("offers inline document upload in the workspace without navigating to /student/proofs/documents", async () => {
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    await openWorkspace()

    // Expand the inline "Add or update evidence" section.
    fireEvent.click(screen.getByText(/add or update evidence for this project/i))

    // The workspace upload path is inline — a button, not a navigation link.
    const uploadTrigger = await screen.findByRole("button", { name: /upload new document/i })
    expect(screen.queryByRole("link", { name: /add a new document proof/i })).not.toBeInTheDocument()

    // Clicking it reveals an inline upload form on the same page.
    fireEvent.click(uploadTrigger)
    expect(await screen.findByTestId("inline-document-uploader")).toBeInTheDocument()
    expect(screen.getByLabelText(/document file/i)).toBeInTheDocument()

    // No navigation away to the standalone Document Proof manager.
    expect(mockRouterPush).not.toHaveBeenCalledWith(
      expect.stringContaining("/student/proofs/documents"),
    )
    // …and no "Open Document Proof manager" primary link.
    expect(screen.queryByText(/open document proof manager/i)).not.toBeInTheDocument()
  })

  it("inline-uploads a new document, attaches it, and stays in the selected project workspace", async () => {
    vi.mocked(listDocumentProofs).mockResolvedValue([])
    vi.mocked(uploadDocumentProof).mockResolvedValue({
      id: "doc-new-1",
      source_type: "document",
      status: "analyzed",
      title: "Final Year Report.pdf",
      claimed_skills: [],
      analysis_json: {},
      evidence_objects: [],
      created_at: "2026-01-01T00:00:00Z",
    })
    vi.mocked(attachProjectDefenseProofs).mockResolvedValue({
      project: makeContext().project,
      metadata: {
        ...makeContext().metadata,
        attached_proofs: {
          documents: [{ document_evidence_id: "doc-new-1", title: "Final Year Report.pdf" }],
        },
      },
      evidence: {
        github_proof: makeEvidenceType(),
        documents: makeEvidenceType({ attached: true, count: 1, label: "Final Year Report.pdf" }),
        website_proof: makeEvidenceType(),
        project_defense: makeEvidenceType(),
      },
    })

    await openWorkspace()
    fireEvent.click(screen.getByText(/add or update evidence for this project/i))

    fireEvent.click(await screen.findByRole("button", { name: /upload new document/i }))

    const fileInput = screen.getByLabelText(/document file/i) as HTMLInputElement
    const file = new File(["dummy report content"], "report.pdf", { type: "application/pdf" })
    fireEvent.change(fileInput, { target: { files: [file] } })

    fireEvent.click(screen.getByRole("button", { name: /^upload document$/i }))

    await waitFor(() => expect(uploadDocumentProof).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(attachProjectDefenseProofs).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({ document_evidence_ids: ["doc-new-1"] }),
      ),
    )

    // The workspace stays visible (no navigation) and the Documents status updates.
    expect(screen.getByText(/defend: boston smart accident risk rerouting/i)).toBeInTheDocument()
    expect(mockRouterPush).not.toHaveBeenCalledWith(
      expect.stringContaining("/student/proofs/documents"),
    )
    expect(await screen.findByText(/documents: final year report\.pdf/i)).toBeInTheDocument()
  })

  it("inline-attaches a selected saved website proof to the existing project", async () => {
    vi.mocked(listWebsiteProofs).mockResolvedValue([
      {
        proof_session_id: "ws-boston",
        target_website: "https://boston-smart-accident.vercel.app",
        evidence_strength_score: 75,
        workflow_confidence: "high",
        supported_skills: ["Machine Learning"],
        created_at: "2026-01-01T00:00:00Z",
      },
    ])
    vi.mocked(attachProjectDefenseProofs).mockResolvedValue({
      project: makeContext().project,
      metadata: makeContext().metadata,
      evidence: makeContext().evidence,
    })

    await openWorkspace()
    fireEvent.click(screen.getByText(/add or update evidence for this project/i))

    const row = await screen.findByLabelText(/boston-smart-accident\.vercel\.app/i)
    fireEvent.click(row)
    fireEvent.click(screen.getByRole("button", { name: /attach to this project/i }))

    await waitFor(() =>
      expect(attachProjectDefenseProofs).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({ website_proof_session_ids: ["ws-boston"] }),
      ),
    )
  })

  it("does not show 'View Project Report' in a document-only / not-report-ready state", async () => {
    await openWorkspace(
      makeContext({
        defense_status: "not_started",
        report_ready: false,
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Report.pdf" }),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
    )

    await screen.findByText(/project evidence package/i)
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
  })

  it("never shows 'View Project Report' in the Project Defense workspace even when the loaded context is report-ready", async () => {
    // Product decision: report navigation lives outside this workspace. Even a
    // fully completed / report-ready persisted context must NOT surface the CTA.
    await openWorkspace(makeContext({ defense_status: "completed", report_ready: true }))

    await screen.findByText(/project evidence package/i)

    // Persisted completed status may still render as "Completed" in the checklist…
    expect(within(checklistCard("Manual Project Defense")).getByText(/completed/i)).toBeInTheDocument()

    // …but the report CTAs must be entirely absent.
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /view vbr report preview/i }),
    ).not.toBeInTheDocument()
  })

  // Regression: browser validation flagged the report link surfacing too early
  // in a selected workspace. Document + website evidence, generated questions,
  // a "ready to record" video defense, and an existing project-report route are
  // NOT enough — the report stays hidden until the defense is genuinely
  // report-ready (analysis complete / Skill-Graph synced / defense analyzed).
  const IN_PROGRESS_QUESTION = {
    id: "q1",
    session_id: "sess-1",
    sort_order: 0,
    question_text: "Explain the main architecture of this project.",
    target_ref: { kind: "architecture" },
    claim_ids: [],
    asked_at_s: null,
    answered: false,
    created_at: "2026-01-01T00:00:00Z",
  }

  it("does not show 'View Project Report' for the observed early state (doc + website attached, questions generated, video ready to record, analysis not run, skill graph not saved)", async () => {
    await openWorkspace(
      makeContext({
        defense_status: "in_progress",
        report_ready: false,
        session_id: "sess-1",
        questions: [IN_PROGRESS_QUESTION],
        metadata: {
          description: "Accident-risk-aware routing on Google Cloud.",
          claimed_skills: ["Python", "Machine Learning"],
          student_role: "I built the risk-scoring API.",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            documents: [{ document_evidence_id: "doc-1", title: "Report.pdf" }],
            website_proofs: [
              {
                target_website: "https://boston-smart-accident.vercel.app",
                workflow_confidence: "high",
                evidence_strength_score: 70,
              },
            ],
          },
        },
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Report.pdf" }),
          website_proof: makeEvidenceType({ attached: true, count: 1, label: "boston.vercel.app" }),
          project_defense: makeEvidenceType(),
        },
      }),
    )

    // Wait for the async recording-readiness to settle so the whole workspace
    // (including the report link, were it to appear) has rendered.
    await within(checklistCard("Video Defense")).findByText(/ready to record/i)

    // Sanity: this really is the flagged state — evidence + questions + a
    // ready-to-record video, but no completed analysis and no Skill-Graph sync.
    expect(within(checklistCard("Video Defense")).getByText(/ready to record/i)).toBeInTheDocument()
    expect(within(checklistCard("Manual Project Defense")).getByText(/missing/i)).toBeInTheDocument()
    expect(within(checklistCard("Skill Graph")).getByText(/not saved/i)).toBeInTheDocument()

    // The report link must be hidden, and the old over-eager label must be gone.
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /view vbr report preview/i }),
    ).not.toBeInTheDocument()
  })

  it("does not show 'View Project Report' with generated questions alone", async () => {
    await openWorkspace(
      makeContext({
        defense_status: "in_progress",
        report_ready: false,
        session_id: "sess-1",
        questions: [IN_PROGRESS_QUESTION],
      }),
    )

    await within(checklistCard("Video Defense")).findByText(/ready to record/i)
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
  })

  it("does not show 'View Project Report' when the video defense is only 'ready to record'", async () => {
    // sessionId present + storage ready + no recorded chunks → "Ready to record".
    await openWorkspace(
      makeContext({
        defense_status: "in_progress",
        report_ready: false,
        session_id: "sess-1",
        questions: [IN_PROGRESS_QUESTION],
      }),
    )

    await within(checklistCard("Video Defense")).findByText(/ready to record/i)
    expect(within(checklistCard("Video Defense")).getByText(/ready to record/i)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
  })

  it("keeps the recorder route reachable when the context has an in-progress session", async () => {
    await openWorkspace(
      makeContext({
        defense_status: "in_progress",
        session_id: "sess-1",
        questions: [
          {
            id: "q1",
            session_id: "sess-1",
            sort_order: 0,
            question_text: "Explain the main architecture of this project.",
            target_ref: { kind: "architecture" },
            claim_ids: [],
            asked_at_s: null,
            answered: false,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    )

    const record = await screen.findByRole("button", { name: /record defense/i })
    fireEvent.click(record)
    expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense/record/sess-1")
  })

  it("returns to project selection via the back action", async () => {
    await openWorkspace()

    fireEvent.click(screen.getByRole("button", { name: /back to project selection/i }))
    expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense")
    expect(await screen.findByText(/choose a project to defend/i)).toBeInTheDocument()
  })

  // ── Post-analysis completion / next-steps panel ──
  //
  // Once the defense is analyzed (persisted completed context on reload, or a
  // live result this session), the workspace surfaces a clear completion panel
  // with next-step choices instead of leaving the student on another blank
  // manual answer box. It must never reintroduce report navigation.

  const COMPLETED_QUESTION = {
    id: "q1",
    session_id: "sess-1",
    sort_order: 0,
    question_text: "Explain the main architecture of this project.",
    target_ref: { kind: "architecture" },
    claim_ids: [],
    asked_at_s: null,
    answered: true,
    created_at: "2026-01-01T00:00:00Z",
  }

  function completedContext() {
    return makeContext({
      defense_status: "completed",
      report_ready: true,
      session_id: "sess-1",
      questions: [COMPLETED_QUESTION],
    })
  }

  it("renders the 'Project Defense analyzed' completion panel when the defense is completed", async () => {
    await openWorkspace(completedContext())
    expect(await screen.findByText(/project defense analyzed/i)).toBeInTheDocument()
    expect(
      screen.getByText(/added as supporting evidence for this project/i),
    ).toBeInTheDocument()
  })

  it("renders a 'Back to Project Defense home' next-step button when completed", async () => {
    await openWorkspace(completedContext())
    expect(
      await screen.findByRole("button", { name: /back to project defense home/i }),
    ).toBeInTheDocument()
  })

  it("renders a 'Record another defense' next-step button when completed", async () => {
    await openWorkspace(completedContext())
    expect(
      await screen.findByRole("button", { name: /record another defense/i }),
    ).toBeInTheDocument()
  })

  it("renders an 'Add or update evidence' next-step button when completed", async () => {
    await openWorkspace(completedContext())
    expect(
      await screen.findByRole("button", { name: /^add or update evidence$/i }),
    ).toBeInTheDocument()
  })

  it("does NOT render 'View Project Report' in the completed state", async () => {
    await openWorkspace(completedContext())
    await screen.findByText(/project defense analyzed/i)
    expect(screen.queryByRole("button", { name: /view project report/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/view project report/i)).not.toBeInTheDocument()
  })

  it("does NOT render 'View VBR report preview' in the completed state", async () => {
    await openWorkspace(completedContext())
    await screen.findByText(/project defense analyzed/i)
    expect(
      screen.queryByRole("button", { name: /view vbr report preview/i }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/view vbr report preview/i)).not.toBeInTheDocument()
  })

  it("'Back to Project Defense home' clears the selected project/session query state", async () => {
    await openWorkspace(completedContext())

    fireEvent.click(await screen.findByRole("button", { name: /back to project defense home/i }))
    // Navigates to the bare route (no projectId / sessionId query params) …
    expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense")
    // … and returns to the project selection view.
    expect(await screen.findByText(/choose a project to defend/i)).toBeInTheDocument()
  })

  it("keeps the completed manual answer box optional, not the primary next step", async () => {
    await openWorkspace(completedContext())
    await screen.findByText(/project defense analyzed/i)

    // The manual answer box is collapsed behind an optional "answer again" toggle
    // rather than presented as the required next step.
    expect(screen.getByText(/answer again manually/i)).toBeInTheDocument()
  })

  it("early/incomplete state still shows the Generate questions flow and no completion panel", async () => {
    await openWorkspace(makeContext({ defense_status: "not_started", session_id: null, questions: [] }))

    expect(await screen.findByRole("button", { name: /generate questions/i })).toBeInTheDocument()
    expect(screen.queryByText(/project defense analyzed/i)).not.toBeInTheDocument()
  })

  it("early/incomplete state with a session still shows the Record + manual answer flow, no completion panel", async () => {
    await openWorkspace(
      makeContext({
        defense_status: "in_progress",
        session_id: "sess-1",
        questions: [COMPLETED_QUESTION],
      }),
    )

    // Manual answer flow is the primary step, presented directly (not collapsed).
    expect(
      await screen.findByPlaceholderText(/explain your project, your role/i),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /analyze my answers/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /record defense/i })).toBeInTheDocument()
    // No completion panel yet.
    expect(screen.queryByText(/project defense analyzed/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/answer again manually/i)).not.toBeInTheDocument()
  })
})

describe("ProjectDefenseHome — duplicate project collapsing", () => {
  it("renders one card per logical project (Boston duplicates collapse to one)", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([
      makeEligibleProject({ id: "boston-a" }),
      makeEligibleProject({
        id: "boston-b",
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Report.pdf" }),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
      makeEligibleProject({
        id: "boston-c",
        title: "  boston smart accident risk rerouting ",
      }),
      makeEligibleProject({
        id: "teachable",
        title: "Teachable Machine Image Classification Demo",
        repo_full_name: "machackgo/teachable-machine-demo",
      }),
    ])

    render(<ProjectDefenseHome />)

    await screen.findByText(/boston smart accident risk rerouting/i)
    // Exactly one Boston card and one Teachable card.
    expect(screen.getAllByText(/boston smart accident risk rerouting/i)).toHaveLength(1)
    expect(screen.getAllByText(/teachable machine image classification demo/i)).toHaveLength(1)
    // Two logical projects → two "primary" CTA buttons.
    expect(screen.getAllByRole("button", { name: /defend this project/i })).toHaveLength(2)
  })

  it("merged Boston card shows GitHub attached when any duplicate has GitHub", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([
      // This (more recent) row is missing GitHub …
      makeEligibleProject({
        id: "boston-a",
        updated_at: "2026-02-01T00:00:00Z",
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType(),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
      // … but a sibling duplicate carries the GitHub proof.
      makeEligibleProject({
        id: "boston-b",
        updated_at: "2026-01-01T00:00:00Z",
        evidence: {
          github_proof: makeEvidenceType({
            attached: true,
            count: 1,
            label: "machackgo/boston-smart-accident-risk-rerouting-google-cloud",
          }),
          documents: makeEvidenceType(),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
    ])

    render(<ProjectDefenseHome />)

    await screen.findByText(/boston smart accident risk rerouting/i)
    expect(screen.getAllByText(/boston smart accident risk rerouting/i)).toHaveLength(1)
    expect(
      screen.getByText("machackgo/boston-smart-accident-risk-rerouting-google-cloud"),
    ).toBeInTheDocument()
  })

  it("does not merge two different projects that share one repository (monorepo)", () => {
    const merged = dedupeEligibleProjects([
      makeEligibleProject({
        id: "billing",
        title: "Billing Service",
        repo_full_name: "acme/mono",
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Billing Spec.pdf" }),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
      makeEligibleProject({
        id: "analytics",
        title: "Analytics Dashboard",
        repo_full_name: "acme/mono",
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType(),
          website_proof: makeEvidenceType({ attached: true, count: 1, label: "https://analytics.app" }),
          project_defense: makeEvidenceType(),
        },
      }),
    ])

    // Same repo, different titles → two distinct cards (no collapse).
    expect(merged).toHaveLength(2)
    const billing = merged.find((p) => p.title === "Billing Service")!
    const analytics = merged.find((p) => p.title === "Analytics Dashboard")!
    // Evidence must not cross-contaminate.
    expect(billing.evidence.documents.attached).toBe(true)
    expect(billing.evidence.website_proof.attached).toBe(false)
    expect(analytics.evidence.website_proof.attached).toBe(true)
    expect(analytics.evidence.documents.attached).toBe(false)
  })

  it("dedupeEligibleProjects merges evidence and picks the strongest status", () => {
    const merged = dedupeEligibleProjects([
      makeEligibleProject({
        id: "a",
        defense_status: "not_started",
        report_ready: false,
        evidence: {
          github_proof: makeEvidenceType({ attached: true, count: 1, label: "machackgo/boston" }),
          documents: makeEvidenceType(),
          website_proof: makeEvidenceType(),
          project_defense: makeEvidenceType(),
        },
      }),
      makeEligibleProject({
        id: "b",
        defense_status: "completed",
        report_ready: true,
        evidence: {
          github_proof: makeEvidenceType(),
          documents: makeEvidenceType({ attached: true, count: 1, label: "Report.pdf" }),
          website_proof: makeEvidenceType({ attached: true, count: 1, label: "https://boston.app" }),
          project_defense: makeEvidenceType({ attached: true, count: 1, label: "Completed" }),
        },
      }),
    ])

    expect(merged).toHaveLength(1)
    expect(merged[0].defense_status).toBe("completed")
    expect(merged[0].report_ready).toBe(true)
    expect(merged[0].evidence.github_proof.attached).toBe(true)
    expect(merged[0].evidence.documents.attached).toBe(true)
    expect(merged[0].evidence.website_proof.attached).toBe(true)
  })
})

describe("ProjectDefenseHome — status-aware CTA copy", () => {
  it("labels the CTA 'Defend this project' when the defense has not started", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([
      makeEligibleProject({ defense_status: "not_started" }),
    ])
    render(<ProjectDefenseHome />)
    expect(await screen.findByRole("button", { name: /^defend this project$/i })).toBeInTheDocument()
  })

  it("labels the CTA 'Continue defense' when the defense is in progress", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([
      makeEligibleProject({ defense_status: "in_progress" }),
    ])
    render(<ProjectDefenseHome />)
    expect(await screen.findByRole("button", { name: /continue defense/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^defend this project$/i })).not.toBeInTheDocument()
  })

  it("labels the CTA 'Review defense' when the defense is completed", async () => {
    vi.mocked(listEligibleDefenseProjects).mockResolvedValue([
      makeEligibleProject({ defense_status: "completed", report_ready: true }),
    ])
    render(<ProjectDefenseHome />)
    expect(await screen.findByRole("button", { name: /review defense/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^defend this project$/i })).not.toBeInTheDocument()
  })
})
