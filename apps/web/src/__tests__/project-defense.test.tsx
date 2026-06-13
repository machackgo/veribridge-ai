/**
 * Project Defense (Phase 1 — individual project defense) — frontend wiring tests.
 *
 * Covers: the panel renders the project identity form, validates a title is
 * required, the generate-questions and paste-answers flows call the right
 * endpoints with the right ids, the explicit "Save to Skill Graph" action
 * calls the sync endpoint, and the copy never implies team proof, a
 * completed final public report, or "fully verified" status.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { ProjectDefensePanel } from "../../components/passport/ProjectDefensePanel"
import type {
  DefenseAnalysisResponse,
  ProjectDefenseCreateResponse,
  ProjectDefenseSyncResult,
  SubmitDefenseAnswersResponse,
  GenerateDefenseQuestionsResponse,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  createProjectDefense: vi.fn(),
  generateDefenseQuestions: vi.fn(),
  submitDefenseAnswers: vi.fn(),
  syncProjectDefenseToSkillGraph: vi.fn(),
}))

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
  listDocumentProofs: vi.fn(),
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
} from "@/lib/vbr-api"
import { listGitHubProofs, listDocumentProofs } from "@/lib/passport-api"

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

beforeEach(() => {
  vi.mocked(createProjectDefense).mockReset()
  vi.mocked(generateDefenseQuestions).mockReset()
  vi.mocked(submitDefenseAnswers).mockReset()
  vi.mocked(syncProjectDefenseToSkillGraph).mockReset()
  vi.mocked(listGitHubProofs).mockReset().mockResolvedValue([])
  vi.mocked(listDocumentProofs).mockReset().mockResolvedValue([])
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
})
