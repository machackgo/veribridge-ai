/**
 * Project Defense (Phase 1 — individual project defense) — frontend wiring tests.
 *
 * Covers: the panel renders the project identity form, validates a title is
 * required, the generate-questions and paste-answers flows call the right
 * endpoints with the right ids, the explicit "Save to Skill Graph" action
 * calls the sync endpoint, and the copy never implies team proof, a
 * completed final public report, or "fully verified" status.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { ProjectDefensePanel } from "../../components/passport/ProjectDefensePanel"
import type {
  DefenseAnalysisResponse,
  ProjectDefenseCreateResponse,
  ProjectDefenseSyncResult,
  SubmitDefenseAnswersResponse,
  GenerateDefenseQuestionsResponse,
  VBRSessionDetailResponse,
  VideoEvidenceChip,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  createProjectDefense: vi.fn(),
  generateDefenseQuestions: vi.fn(),
  submitDefenseAnswers: vi.fn(),
  syncProjectDefenseToSkillGraph: vi.fn(),
  getVBRSession: vi.fn(),
  getVBRSessionRecordingReadiness: vi.fn(),
}))

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
  listDocumentProofs: vi.fn(),
  listWebsiteProofs: vi.fn(),
}))

const mockRouterPush = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

import {
  createProjectDefense,
  generateDefenseQuestions,
  submitDefenseAnswers,
  syncProjectDefenseToSkillGraph,
  getVBRSession,
  getVBRSessionRecordingReadiness,
} from "@/lib/vbr-api"
import { listGitHubProofs, listDocumentProofs, listWebsiteProofs } from "@/lib/passport-api"

function makeCreated(overrides: Partial<ProjectDefenseCreateResponse> = {}): ProjectDefenseCreateResponse {
  return {
    project: {
      id: "proj-1",
      title: "Skill Evidence Tracker",
      repo_url: "https://github.com/octocat/Hello-World",
      repo_full_name: "octocat/Hello-World",
      deployed_url: null,
      head_sha: null,
      status: "draft",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    metadata: {
      description: "A platform that tracks student skill evidence.",
      claimed_skills: ["Python", "React"],
      student_role: "I built the backend API.",
      individual_project_only: true,
      attached_proofs: {},
      phase: "project_defense_mvp_v1",
    },
    ...overrides,
  }
}

function makeGithubProof(overrides: Partial<import("@/lib/passport-api").GitHubProofResponse> = {}): import("@/lib/passport-api").GitHubProofResponse {
  return {
    id: "gh-proof-1",
    repo_url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
    repo_owner: "machackgo",
    repo_name: "boston-smart-accident-risk-rerouting-google-cloud",
    default_branch: "main",
    visibility: "public",
    status: "analyzed",
    submitted_skill_claims: ["Python"],
    detected_skills: ["Python", "Machine Learning"],
    evidence_strength: "partial",
    confidence_score: 72,
    missing_evidence: [],
    public_safe_summary: "GitHub proof for machackgo/boston-smart-accident-risk-rerouting-google-cloud is partial evidence with 72/100 confidence.",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function makeWebsiteProof(overrides: Partial<import("@/lib/passport-api").WebsiteProofSummaryResponse> = {}): import("@/lib/passport-api").WebsiteProofSummaryResponse {
  return {
    proof_session_id: "ws-1",
    target_website: "http://demo.example.com",
    evidence_strength_score: 75,
    workflow_confidence: "high",
    supported_skills: ["Machine Learning", "React"],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function makeQuestions(): GenerateDefenseQuestionsResponse {
  return {
    project_id: "proj-1",
    session_id: "sess-1",
    status: "questions_ready",
    questions: [
      {
        id: "q1",
        session_id: "sess-1",
        sort_order: 0,
        question_text: "Describe the overall architecture of your project.",
        target_ref: { kind: "architecture" },
        claim_ids: [],
        asked_at_s: null,
        answered: false,
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "q2",
        session_id: "sess-1",
        sort_order: 1,
        question_text: "How did you use Python in this project?",
        target_ref: { kind: "skill_link", skill: "Python" },
        claim_ids: [],
        asked_at_s: null,
        answered: false,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  }
}

function makeAnalysis(overrides: Partial<DefenseAnalysisResponse> = {}): DefenseAnalysisResponse {
  return {
    transcript_summary: "",
    skills_mentioned: ["Python"],
    skills_explained_well: ["Python"],
    skills_missing_from_explanation: [],
    consistency_with_evidence_score: 50,
    explanation_clarity_score: 70,
    ownership_signal_score: 65,
    technical_depth_score: 77,
    overall_defense_score: 60,
    risk_flags: [],
    recruiter_summary: "The student gave a clear, first-person explanation of their contribution.",
    recommended_improvements: [],
    privacy_scan_status: "clean",
    ...overrides,
  }
}

function makeSubmitResult(overrides: Partial<SubmitDefenseAnswersResponse> = {}): SubmitDefenseAnswersResponse {
  return {
    project_id: "proj-1",
    session_id: "sess-1",
    transcript_id: "trans-1",
    segment_count: 1,
    answered_question_count: 0,
    analysis: makeAnalysis(),
    video_evidence_chips: [],
    ...overrides,
  }
}

function makeVideoEvidenceChip(overrides: Partial<VideoEvidenceChip> = {}): VideoEvidenceChip {
  return {
    label: "Video 00:08",
    timestamp_start_s: 8,
    timestamp_end_s: 25,
    short_summary: "I built the backend risk-scoring API using Python and FastAPI.",
    related_skill: "Python",
    question_id: null,
    source: "project_defense_video",
    source_type: "video_transcript",
    ...overrides,
  }
}

function makeSyncResult(overrides: Partial<ProjectDefenseSyncResult> = {}): ProjectDefenseSyncResult {
  return {
    ok: true,
    already_synced: false,
    skills_synced: ["Python", "React"],
    pipelines_upserted: 2,
    artifacts_created: 2,
    errors: [],
    ...overrides,
  }
}

function makeSession(overrides: Partial<VBRSessionDetailResponse> = {}): VBRSessionDetailResponse {
  return {
    id: "sess-1",
    project_id: "proj-1",
    attempt_no: 1,
    status: "created",
    started_at: null,
    ended_at: null,
    duration_s: null,
    webcam_present: false,
    chunk_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    questions: [],
    video_evidence_chips: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(createProjectDefense).mockReset()
  vi.mocked(generateDefenseQuestions).mockReset()
  vi.mocked(submitDefenseAnswers).mockReset()
  vi.mocked(syncProjectDefenseToSkillGraph).mockReset()
  vi.mocked(listGitHubProofs).mockReset().mockResolvedValue([])
  vi.mocked(listDocumentProofs).mockReset().mockResolvedValue([])
  vi.mocked(listWebsiteProofs).mockReset().mockResolvedValue([])
  vi.mocked(getVBRSession).mockReset().mockResolvedValue(makeSession())
  vi.mocked(getVBRSessionRecordingReadiness).mockReset().mockResolvedValue({
    ready: true,
    code: null,
    message: "Recording upload storage is ready.",
  })
  mockRouterPush.mockReset()
})

describe("ProjectDefensePanel", () => {
  it("renders the project identity form", async () => {
    render(<ProjectDefensePanel />)

    expect(await screen.findByPlaceholderText(/skill evidence tracker/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /create project defense/i })).toBeInTheDocument()
  })

  it("does not expose a raw website proof session ID input (Phase 1)", async () => {
    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)
    expect(screen.queryByLabelText(/website proof session id/i)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/website proof session id/i)).not.toBeInTheDocument()
  })

  it("does not send website_proof_session_id when creating a project defense", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await waitFor(() => expect(createProjectDefense).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createProjectDefense).mock.calls[0][0]
    expect(body.attached_proofs).not.toHaveProperty("website_proof_session_id")
  })

  it("requires a title before creating a project defense", async () => {
    render(<ProjectDefensePanel />)

    fireEvent.click(await screen.findByRole("button", { name: /create project defense/i }))

    expect(await screen.findByText(/give your project a title/i)).toBeInTheDocument()
    expect(createProjectDefense).not.toHaveBeenCalled()
  })

  it("walks through create → generate questions → paste answers → save to Skill Graph", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())
    vi.mocked(syncProjectDefenseToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<ProjectDefensePanel />)

    // Step A — project identity
    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await waitFor(() => expect(createProjectDefense).toHaveBeenCalledTimes(1))
    expect(createProjectDefense).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Skill Evidence Tracker" })
    )

    // Step B — generate questions
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await waitFor(() => expect(generateDefenseQuestions).toHaveBeenCalledWith("proj-1"))

    expect(await screen.findByText(/describe the overall architecture/i)).toBeInTheDocument()
    expect(screen.getByText(/how did you use python/i)).toBeInTheDocument()

    // Step C — paste a combined explanation
    fireEvent.change(
      screen.getByPlaceholderText(/explain your project, your role/i),
      { target: { value: "I built the backend API using Python and FastAPI." } }
    )
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    await waitFor(() => expect(submitDefenseAnswers).toHaveBeenCalledWith("sess-1", {
      combined_text: "I built the backend API using Python and FastAPI.",
    }))

    // Step D — analysis results render
    expect(await screen.findByText(/overall defense score/i)).toBeInTheDocument()
    expect(screen.getByText(/60\/100/)).toBeInTheDocument()
    expect(screen.getByText(/clear, first-person explanation/i)).toBeInTheDocument()

    // Step E — explicit save to Skill Graph
    fireEvent.click(screen.getByRole("button", { name: /save explanation evidence to skill graph/i }))

    await waitFor(() => expect(syncProjectDefenseToSkillGraph).toHaveBeenCalledWith("sess-1"))
    expect(await screen.findByText(/saved as supporting evidence for python, react/i)).toBeInTheDocument()
  })

  it("renders Video Evidence chips with timestamps and related skills when available", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(
      makeSubmitResult({
        video_evidence_chips: [
          makeVideoEvidenceChip({
            label: "Video 00:08",
            short_summary: "Explains the backend risk-scoring API.",
            related_skill: "Python",
          }),
          makeVideoEvidenceChip({
            label: "Video 00:25",
            timestamp_start_s: 25,
            timestamp_end_s: 45,
            short_summary: "Explains the React dashboard components.",
            related_skill: "React",
          }),
        ],
      })
    )

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(
      screen.getByPlaceholderText(/explain your project, your role/i),
      { target: { value: "I built the backend API using Python and FastAPI." } }
    )
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    expect(await screen.findByText(/video evidence/i)).toBeInTheDocument()
    const chips = await screen.findAllByTestId("video-evidence-chip")
    expect(chips).toHaveLength(2)
    expect(screen.getByText(/video 00:08/i)).toBeInTheDocument()
    expect(screen.getByText(/explains the backend risk-scoring api/i)).toBeInTheDocument()
    expect(screen.getByText(/video 00:25/i)).toBeInTheDocument()
    expect(screen.getByText(/explains the react dashboard components/i)).toBeInTheDocument()

    // Related skill badges are shown alongside each chip.
    const pythonBadges = screen.getAllByText("Python")
    expect(pythonBadges.length).toBeGreaterThan(0)
    expect(screen.getAllByText("React").length).toBeGreaterThan(0)
  })

  it("shows a 'will appear after transcript analysis' fallback when no video evidence chips exist", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult({ video_evidence_chips: [] }))

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(
      screen.getByPlaceholderText(/explain your project, your role/i),
      { target: { value: "I built the backend API using Python and FastAPI." } }
    )
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    expect(await screen.findByText(/video evidence/i)).toBeInTheDocument()
    expect(
      await screen.findByText(/timestamped evidence will appear after transcript analysis/i)
    ).toBeInTheDocument()
    expect(screen.queryByTestId("video-evidence-chip")).not.toBeInTheDocument()

    // Manual fallback (save to Skill Graph) remains available.
    expect(screen.getByRole("button", { name: /save explanation evidence to skill graph/i })).toBeInTheDocument()
  })

  it("does not render full raw transcript or private fields alongside video evidence chips", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(
      makeSubmitResult({
        video_evidence_chips: [makeVideoEvidenceChip()],
      })
    )

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(
      screen.getByPlaceholderText(/explain your project, your role/i),
      { target: { value: "I built the backend API using Python and FastAPI." } }
    )
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    await screen.findByText(/video evidence/i)

    const bodyText = document.body.textContent ?? ""
    expect(bodyText).not.toMatch(/storage_path/i)
    expect(bodyText).not.toMatch(/signed_url/i)
    expect(bodyText).not.toMatch(/access_token/i)
    expect(bodyText).not.toMatch(/supabase\.co/i)
  })

  it("shows a 'Record defense' action after questions are generated and routes to the recorder", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    // Before questions are generated, there is no recording action yet.
    expect(screen.queryByRole("button", { name: /record defense/i })).not.toBeInTheDocument()

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    const recordButton = await screen.findByRole("button", { name: /record defense/i })
    fireEvent.click(recordButton)

    expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense/record/sess-1")
  })

  it("submits per-question answers when 'Answer each question' mode is selected", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.click(screen.getByRole("button", { name: /answer each question/i }))

    const architectureLabel = screen
      .getAllByText(/describe the overall architecture/i)
      .find((el) => el.tagName === "LABEL")
    const pythonLabel = screen
      .getAllByText(/how did you use python/i)
      .find((el) => el.tagName === "LABEL")

    const architectureTextarea = architectureLabel?.parentElement?.querySelector("textarea")
    const pythonTextarea = pythonLabel?.parentElement?.querySelector("textarea")
    expect(architectureTextarea).toBeTruthy()
    expect(pythonTextarea).toBeTruthy()

    fireEvent.change(architectureTextarea as HTMLTextAreaElement, {
      target: { value: "I designed a REST API with a React frontend." },
    })
    fireEvent.change(pythonTextarea as HTMLTextAreaElement, {
      target: { value: "I implemented the backend in Python with FastAPI." },
    })

    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    await waitFor(() => expect(submitDefenseAnswers).toHaveBeenCalledWith("sess-1", {
      answers: [
        { question_id: "q1", answer_text: "I designed a REST API with a React frontend." },
        { question_id: "q2", answer_text: "I implemented the backend in Python with FastAPI." },
      ],
    }))
  })

  it("never uses team proof, completed final report, or 'fully verified' language", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())
    vi.mocked(syncProjectDefenseToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(screen.getByPlaceholderText(/explain your project, your role/i), {
      target: { value: "I built the backend API using Python and FastAPI." },
    })
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))
    await screen.findByText(/overall defense score/i)

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/team proof/i)
    expect(text).not.toMatch(/teammate/i)
    expect(text).not.toMatch(/meeting/i)
    expect(text).not.toMatch(/final (public )?report (is )?complete/i)
    // Disclaiming "not fully verified" is fine — overclaiming "is fully verified" is not.
    expect(text).not.toMatch(/\bis fully verified\b/i)
    expect(text).not.toMatch(/(project|student|skill) (is|are) (now |fully )?verified/i)
  })

  // ── Repo-wise GitHub Proof attachment (VBR uses /student/proofs/github, not whole-account scan) ──

  it("lists repo-wise GitHub Proof submissions in the 'Attach a GitHub proof' dropdown", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([
      makeGithubProof({ id: "gh-1", repo_owner: "machackgo", repo_name: "boston-smart-accident-risk-rerouting-google-cloud", status: "analyzed", evidence_strength: "partial" }),
    ])

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    const select = await screen.findByLabelText(/attach a github proof/i)
    expect(select).toBeInTheDocument()
    expect(screen.getByText(/machackgo\/boston-smart-accident-risk-rerouting-google-cloud — analyzed · partial/i)).toBeInTheDocument()
  })

  it("attaches the selected repo-wise GitHub proof id and uses its repo URL as the project repo URL", async () => {
    const proof = makeGithubProof({ id: "gh-1" })
    vi.mocked(listGitHubProofs).mockResolvedValue([proof])
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    const select = await screen.findByLabelText(/attach a github proof/i)
    fireEvent.change(select, { target: { value: "gh-1" } })

    // Repo URL field is now derived from the attached proof and disabled.
    const repoUrlInput = screen.getByLabelText(/repository url \(from attached github proof\)/i) as HTMLInputElement
    expect(repoUrlInput).toBeDisabled()
    expect(repoUrlInput.value).toBe(proof.repo_url)

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await waitFor(() => expect(createProjectDefense).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createProjectDefense).mock.calls[0][0]
    expect(body.attached_proofs?.github_proof_id).toBe("gh-1")
    expect(body.repo_url).toBeFalsy()
  })

  it("ignores a stale manual repo URL when a repo-wise GitHub proof is selected afterward", async () => {
    const proof = makeGithubProof({ id: "gh-1" })
    vi.mocked(listGitHubProofs).mockResolvedValue([proof])
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    // User types a manual repo URL first.
    fireEvent.change(screen.getByLabelText(/repository url without attached github proof/i), {
      target: { value: "https://github.com/someone/stale-repo" },
    })

    // Then selects a repo-wise GitHub proof.
    const select = await screen.findByLabelText(/attach a github proof/i)
    fireEvent.change(select, { target: { value: "gh-1" } })

    const repoUrlInput = screen.getByLabelText(/repository url \(from attached github proof\)/i) as HTMLInputElement
    expect(repoUrlInput).toBeDisabled()
    expect(repoUrlInput.value).toBe(proof.repo_url)

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await waitFor(() => expect(createProjectDefense).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createProjectDefense).mock.calls[0][0]
    expect(body.repo_url).toBeFalsy()
    expect(body.attached_proofs?.github_proof_id).toBe("gh-1")
  })

  it("shows the attached repo-wise GitHub proof and its detected skills in the Attached Evidence summary", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([makeGithubProof({ id: "gh-1" })])
    vi.mocked(createProjectDefense).mockResolvedValue(
      makeCreated({
        metadata: {
          description: "",
          claimed_skills: ["Python"],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            github_proof: {
              github_proof_id: "gh-1",
              repo_url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
              repo_owner: "machackgo",
              repo_name: "boston-smart-accident-risk-rerouting-google-cloud",
              status: "analyzed",
              detected_skills: ["Python", "Machine Learning"],
              public_safe_summary: "GitHub proof for machackgo/boston-smart-accident-risk-rerouting-google-cloud is partial evidence with 72/100 confidence.",
            },
          },
        },
      })
    )

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    const select = await screen.findByLabelText(/attach a github proof/i)
    fireEvent.change(select, { target: { value: "gh-1" } })

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    expect(await screen.findByText(/github proof attached: machackgo\/boston-smart-accident-risk-rerouting-google-cloud \(analyzed\)/i)).toBeInTheDocument()
    expect(screen.getByText("Machine Learning")).toBeInTheDocument()
  })

  it("labels a manual repo URL clearly when no GitHub proof is attached", async () => {
    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    expect(screen.getByLabelText(/repository url without attached github proof/i)).toBeInTheDocument()
    expect(screen.getByText(/not verified github evidence/i)).toBeInTheDocument()
  })

  it("never shows old whole-GitHub / profile scan language", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([makeGithubProof({ id: "gh-1" })])

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/github profile/i)
    expect(text).not.toMatch(/portfolio scan/i)
    expect(text).not.toMatch(/whole.?github/i)
    expect(text).not.toMatch(/scan your github account/i)
  })

  // ── Project Evidence Package — unified evidence workspace ──

  function checklistCard(labelText: string): HTMLElement {
    const label = screen.getByText(labelText, { selector: "span" })
    return label.parentElement as HTMLElement
  }

  it("renders the Project Evidence Package checklist after Project Defense creation", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    expect(await screen.findByText(/project evidence package/i)).toBeInTheDocument()

    expect(within(checklistCard("GitHub Proof")).getByText("Missing")).toBeInTheDocument()
    expect(within(checklistCard("Documents")).getByText("Missing")).toBeInTheDocument()
    expect(within(checklistCard("Website Proof")).getByText("Missing")).toBeInTheDocument()
    expect(within(checklistCard("Manual Project Defense")).getByText("Missing")).toBeInTheDocument()
    expect(within(checklistCard("Video Defense")).getByText("Not started")).toBeInTheDocument()
    expect(within(checklistCard("Skill Graph")).getByText("Not saved")).toBeInTheDocument()
  })

  it("shows GitHub Proof as attached in the checklist when a repo-wise proof is selected", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([makeGithubProof({ id: "gh-1" })])
    vi.mocked(createProjectDefense).mockResolvedValue(
      makeCreated({
        metadata: {
          description: "",
          claimed_skills: ["Python"],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            github_proof: {
              github_proof_id: "gh-1",
              repo_url: "https://github.com/machackgo/boston-smart-accident-risk-rerouting-google-cloud",
              repo_owner: "machackgo",
              repo_name: "boston-smart-accident-risk-rerouting-google-cloud",
              status: "analyzed",
              detected_skills: ["Python"],
              public_safe_summary: "GitHub proof summary.",
            },
          },
        },
      })
    )

    render(<ProjectDefensePanel />)

    const select = await screen.findByLabelText(/attach a github proof/i)
    fireEvent.change(select, { target: { value: "gh-1" } })

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)
    expect(within(checklistCard("GitHub Proof")).getByText("Attached")).toBeInTheDocument()
  })

  it("labels the manual repo URL fallback clearly in the Project Evidence Package", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    expect(
      await screen.findByText(/repository url only — no attached github proof: octocat\/hello-world/i)
    ).toBeInTheDocument()
  })

  it("shows document proof count and names in the Project Evidence Package", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(
      makeCreated({
        metadata: {
          description: "",
          claimed_skills: [],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            documents: [
              { document_evidence_id: "doc-1", title: "Resume.pdf", source_type: "document", status: "analyzed" },
              { document_evidence_id: "doc-2", source_type: "document", status: "analyzed" },
            ],
          },
        },
      })
    )

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)
    expect(within(checklistCard("Documents")).getByText("2 attached")).toBeInTheDocument()
    expect(await screen.findByText(/documents: resume\.pdf, untitled document/i)).toBeInTheDocument()
  })

  it("lists existing Website Proofs and lets the student attach one", async () => {
    vi.mocked(listWebsiteProofs).mockResolvedValue([makeWebsiteProof({ proof_session_id: "ws-1" })])
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())

    render(<ProjectDefensePanel />)

    await screen.findByPlaceholderText(/skill evidence tracker/i)

    const checkbox = await screen.findByLabelText(/demo\.example\.com — high confidence/i)
    fireEvent.click(checkbox)

    fireEvent.change(screen.getByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await waitFor(() => expect(createProjectDefense).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createProjectDefense).mock.calls[0][0]
    expect(body.attached_proofs?.website_proof_session_ids).toEqual(["ws-1"])
  })

  it("shows website proof count in the checklist when attached, and 'Missing' when not", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(
      makeCreated({
        metadata: {
          description: "",
          claimed_skills: [],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            website_proofs: [
              {
                proof_session_id: "ws-1",
                target_website: "http://demo.example.com",
                evidence_strength_score: 75,
                workflow_confidence: "high",
                supported_skills: ["Machine Learning"],
                created_at: "2026-01-01T00:00:00Z",
              },
            ],
          },
        },
      })
    )

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)
    expect(within(checklistCard("Website Proof")).getByText("1 attached")).toBeInTheDocument()
    expect(await screen.findByText(/website proof: http:\/\/demo\.example\.com/i)).toBeInTheDocument()
  })

  it("never renders raw website proof artifact data (screenshots, storage paths, tokens)", async () => {
    vi.mocked(listWebsiteProofs).mockResolvedValue([makeWebsiteProof({ proof_session_id: "ws-1" })])
    vi.mocked(createProjectDefense).mockResolvedValue(
      makeCreated({
        metadata: {
          description: "",
          claimed_skills: [],
          student_role: "",
          individual_project_only: true,
          phase: "project_defense_mvp_v1",
          attached_proofs: {
            website_proofs: [
              {
                proof_session_id: "ws-1",
                target_website: "http://demo.example.com",
                evidence_strength_score: 75,
                workflow_confidence: "high",
                supported_skills: ["Machine Learning"],
                created_at: "2026-01-01T00:00:00Z",
              },
            ],
          },
        },
      })
    )

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/screenshot/i)
    expect(text).not.toMatch(/token=/i)
    expect(text).not.toMatch(/proof_session_id/i)
  })

  it("shows Manual Project Defense as completed after analysis runs", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)
    expect(within(checklistCard("Manual Project Defense")).getByText("Missing")).toBeInTheDocument()

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(screen.getByPlaceholderText(/explain your project, your role/i), {
      target: { value: "I built the backend API using Python and FastAPI." },
    })
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))

    await screen.findByText(/overall defense score/i)

    expect(within(checklistCard("Manual Project Defense")).getByText("Completed")).toBeInTheDocument()
    expect(await screen.findByText(/analysis status: completed/i)).toBeInTheDocument()
  })

  it("shows Skill Graph as saved after the explicit sync action", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())
    vi.mocked(syncProjectDefenseToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    await screen.findByText(/project evidence package/i)
    expect(within(checklistCard("Skill Graph")).getByText("Not saved")).toBeInTheDocument()

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(screen.getByPlaceholderText(/explain your project, your role/i), {
      target: { value: "I built the backend API using Python and FastAPI." },
    })
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))
    await screen.findByText(/overall defense score/i)

    fireEvent.click(screen.getByRole("button", { name: /save explanation evidence to skill graph/i }))
    await waitFor(() => expect(syncProjectDefenseToSkillGraph).toHaveBeenCalledWith("sess-1"))

    expect(await within(checklistCard("Skill Graph")).findByText("Saved")).toBeInTheDocument()
  })

  it("keeps the 'Record defense' action visible after manual analysis and Skill Graph save", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())
    vi.mocked(syncProjectDefenseToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    expect(await screen.findByRole("button", { name: /record defense/i })).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(/explain your project, your role/i), {
      target: { value: "I built the backend API using Python and FastAPI." },
    })
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))
    await screen.findByText(/overall defense score/i)

    // Still visible after manual analysis is complete.
    expect(screen.getByRole("button", { name: /record defense/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /save explanation evidence to skill graph/i }))
    await waitFor(() => expect(syncProjectDefenseToSkillGraph).toHaveBeenCalledWith("sess-1"))

    // Still visible after the Skill Graph save.
    const recordButton = screen.getByRole("button", { name: /record defense/i })
    expect(recordButton).toBeInTheDocument()

    fireEvent.click(recordButton)
    expect(mockRouterPush).toHaveBeenCalledWith("/student/proofs/project-defense/record/sess-1")
  })

  it("shows Video Defense as 'Storage not configured' when recording readiness fails, with manual fallback noted", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(getVBRSessionRecordingReadiness).mockResolvedValue({
      ready: false,
      code: "vbr_media_bucket_not_configured",
      message: "Recording upload storage is not configured.",
    })

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    await screen.findByText(/project evidence package/i)

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    expect(await within(checklistCard("Video Defense")).findByText("Storage not configured")).toBeInTheDocument()
    expect(
      await screen.findByText(/video defense: storage not configured — pasting your explanation remains the primary available path/i)
    ).toBeInTheDocument()
  })

  it("never renders storage paths, signed URLs, bucket names, or upload tokens in the evidence workspace", async () => {
    vi.mocked(createProjectDefense).mockResolvedValue(makeCreated())
    vi.mocked(generateDefenseQuestions).mockResolvedValue(makeQuestions())
    vi.mocked(submitDefenseAnswers).mockResolvedValue(makeSubmitResult())
    vi.mocked(syncProjectDefenseToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<ProjectDefensePanel />)

    fireEvent.change(await screen.findByPlaceholderText(/skill evidence tracker/i), {
      target: { value: "Skill Evidence Tracker" },
    })
    fireEvent.click(screen.getByRole("button", { name: /create project defense/i }))
    await screen.findByText(/project evidence package/i)

    fireEvent.click(await screen.findByRole("button", { name: /generate questions/i }))
    await screen.findByText(/describe the overall architecture/i)

    fireEvent.change(screen.getByPlaceholderText(/explain your project, your role/i), {
      target: { value: "I built the backend API using Python and FastAPI." },
    })
    fireEvent.click(screen.getByRole("button", { name: /analyze my answers/i }))
    await screen.findByText(/overall defense score/i)

    fireEvent.click(screen.getByRole("button", { name: /save explanation evidence to skill graph/i }))
    await waitFor(() => expect(syncProjectDefenseToSkillGraph).toHaveBeenCalledWith("sess-1"))

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/upload_url/i)
    expect(text).not.toMatch(/bucket/i)
    expect(text).not.toMatch(/token=/i)
    expect(text).not.toMatch(/https?:\/\/storage/i)
  })
})
