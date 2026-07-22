/**
 * /student — canonical Student Dashboard (dashboard consolidation Stage 2).
 *
 * Covers: the dashboard aggregates ONLY existing canonical APIs and launches
 * ONLY existing canonical routes; the deterministic next-action cascade;
 * proof-state rollups (closed vocabulary, honest "Failed / retry available");
 * defense projects are never queried for recorder sessions nor advertised as
 * recordable walkthroughs (contract inherited from the old Proof Studio);
 * per-section failure isolation (one API failing never blanks the page).
 */

import { render, screen, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

import StudentDashboardPage from "../app/student/page"
import {
  deriveNextAction,
  isDefenseProject,
  summarizeProofStatuses,
} from "../../components/student/dashboard-logic"
import {
  getVBRProjectQuestions,
  getVBRProjectReportPublishStatus,
  getWorkPassportStatus,
  listVBRProjects,
  type VBRProjectResponse,
  type WorkPassportStatus,
} from "@/lib/vbr-api"
import {
  listDocumentProofs,
  listGitHubProofs,
  listWebsiteProofs,
  type GitHubProofResponse,
} from "@/lib/passport-api"
import { getSkillGapsOverview } from "@/lib/skill-gaps-api"

let mockSearchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/student",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

vi.mock("@/lib/vbr-api", () => ({
  listVBRProjects: vi.fn(),
  getVBRProjectQuestions: vi.fn(),
  getVBRProjectReportPublishStatus: vi.fn(),
  getWorkPassportStatus: vi.fn(),
}))

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
  listWebsiteProofs: vi.fn(),
  listDocumentProofs: vi.fn(),
}))

vi.mock("@/lib/skill-gaps-api", () => ({
  getSkillGapsOverview: vi.fn(),
}))

function makeProject(overrides: Partial<VBRProjectResponse> = {}): VBRProjectResponse {
  return {
    id: "proj-1",
    title: "Skill Evidence Tracker",
    repo_url: "https://github.com/octocat/Hello-World",
    repo_full_name: "octocat/Hello-World",
    status: "draft",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    metadata: {},
    ...overrides,
  }
}

function makeGitHubProof(overrides: Partial<GitHubProofResponse> = {}): GitHubProofResponse {
  return {
    id: "gh-1",
    repo_url: "https://github.com/octocat/Hello-World",
    status: "analyzed",
    submitted_skill_claims: [],
    detected_skills: [],
    missing_evidence: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

const unpublishedPassport: WorkPassportStatus = {
  is_published: false,
  public_slug: null,
  public_path: null,
  published_at: null,
  headline: "",
  summary: "",
}

beforeEach(() => {
  mockSearchParams = new URLSearchParams()
  vi.mocked(listVBRProjects).mockReset().mockResolvedValue([])
  vi.mocked(getVBRProjectQuestions).mockReset().mockResolvedValue({
    project_id: "proj-1",
    session_id: null,
    questions: [],
  })
  vi.mocked(getVBRProjectReportPublishStatus).mockReset().mockResolvedValue({
    project_id: "proj-1",
    is_public: false,
    public_token: null,
    public_path: null,
    published_at: null,
  })
  vi.mocked(getWorkPassportStatus).mockReset().mockResolvedValue(unpublishedPassport)
  vi.mocked(listGitHubProofs).mockReset().mockResolvedValue([])
  vi.mocked(listWebsiteProofs).mockReset().mockResolvedValue([])
  vi.mocked(listDocumentProofs).mockReset().mockResolvedValue([])
  vi.mocked(getSkillGapsOverview).mockReset().mockResolvedValue({
    projects: [],
    total_gap_count: 0,
    generated_at: "2026-01-01T00:00:00Z",
  })
})

describe("dashboard sections and canonical launch routes", () => {
  it("renders all launch sections with links to the existing canonical workflows", async () => {
    render(<StudentDashboardPage />)

    expect(await screen.findByTestId("student-dashboard")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("dashboard-next-action-link")).toBeInTheDocument())

    for (const [testId, href] of [
      ["proof-card-github", "/student/proofs/github"],
      ["proof-card-website", "/student/proofs/website"],
      ["proof-card-documents", "/student/proofs/documents"],
      ["proof-card-defense", "/student/proofs/project-defense"],
    ] as const) {
      const card = screen.getByTestId(testId)
      expect(card.querySelector(`a[href="${href}"]`)).not.toBeNull()
    }

    expect(screen.getByTestId("dashboard-skill-gaps-link")).toHaveAttribute("href", "/dashboard/skill-gaps")
    expect(screen.getByTestId("dashboard-passport-link")).toHaveAttribute("href", "/student/vbr/passport")
    expect(screen.getByTestId("dashboard-reports-section")).toBeInTheDocument()
  })

  it("shows honest proof states from real records", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([makeGitHubProof({ status: "failed" })])
    vi.mocked(listWebsiteProofs).mockResolvedValue([
      {
        proof_session_id: "wp-1",
        target_website: "https://demo.app",
        evidence_strength_score: 3,
        workflow_confidence: "high",
        supported_skills: ["react"],
        created_at: "2026-01-02T00:00:00Z",
      },
    ])

    render(<StudentDashboardPage />)

    await waitFor(() =>
      expect(screen.getByTestId("proof-card-github")).toHaveTextContent("Failed / retry available")
    )
    expect(screen.getByTestId("proof-card-website")).toHaveTextContent("Complete")
    expect(screen.getByTestId("proof-card-documents")).toHaveTextContent("Not started")
    expect(screen.getByTestId("proof-card-defense")).toHaveTextContent("Not started")
  })

  it("lists project report rows with the canonical report route and publish status", async () => {
    vi.mocked(listVBRProjects).mockResolvedValue([makeProject()])
    vi.mocked(getVBRProjectReportPublishStatus).mockResolvedValue({
      project_id: "proj-1",
      is_public: true,
      public_token: "tok",
      public_path: "/vbr/report/tok",
      published_at: "2026-01-03T00:00:00Z",
    })

    render(<StudentDashboardPage />)

    const row = await screen.findByTestId("report-row-proj-1")
    expect(row.querySelector('a[href="/student/vbr/projects/proj-1/report"]')).not.toBeNull()
    await waitFor(() => expect(row).toHaveTextContent("Published"))
    expect(row.querySelector('a[href="/vbr/report/tok"]')).not.toBeNull()
  })

  it("never queries recorder sessions for defense projects nor advertises them as recordable", async () => {
    const defense = makeProject({
      id: "proj-defense",
      title: "Defense Project",
      metadata: { phase: "project_defense_mvp_v1" },
    })
    vi.mocked(listVBRProjects).mockResolvedValue([defense])

    render(<StudentDashboardPage />)

    await screen.findByTestId("report-row-proj-defense")
    expect(getVBRProjectQuestions).not.toHaveBeenCalled()
    expect(screen.queryByText(/continue recording/i)).not.toBeInTheDocument()
  })

  it("surfaces resumable walkthrough checkpoints via the canonical recorder route", async () => {
    vi.mocked(listVBRProjects).mockResolvedValue([makeProject()])
    vi.mocked(getVBRProjectQuestions).mockResolvedValue({
      project_id: "proj-1",
      session_id: "sess-9",
      questions: [],
    })

    render(<StudentDashboardPage />)

    const resume = await screen.findByTestId("dashboard-resume-section")
    const link = Array.from(resume.querySelectorAll("a")).find((a) =>
      a.getAttribute("href")?.includes("/student/vbr/sessions/sess-9")
    )
    expect(link).toBeTruthy()
  })

  it("keeps rendering other sections when skill gaps and passport APIs fail", async () => {
    vi.mocked(getSkillGapsOverview).mockRejectedValue(new Error("boom"))
    vi.mocked(getWorkPassportStatus).mockRejectedValue(new Error("boom"))

    render(<StudentDashboardPage />)

    await waitFor(() =>
      expect(screen.getByTestId("dashboard-skills-section")).toHaveTextContent(
        "Skill gap assessment is unavailable right now."
      )
    )
    expect(screen.getByTestId("dashboard-passport-section")).toHaveTextContent("Status unavailable")
    expect(screen.getByTestId("dashboard-proofs-section")).toBeInTheDocument()
  })

  it("focuses the Proofs section for legacy ?section=proofs links", async () => {
    mockSearchParams = new URLSearchParams("section=proofs")
    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy

    render(<StudentDashboardPage />)

    await screen.findByTestId("dashboard-proofs-section")
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled())
  })
})

describe("deterministic next action cascade", () => {
  const base = {
    projects: [] as VBRProjectResponse[],
    githubProofs: [] as GitHubProofResponse[],
    websiteProofs: [],
    documentProofs: [],
    gaps: null,
    passport: null,
    resumableSessionId: null,
  }

  it("starts with the first proof when nothing exists", () => {
    expect(deriveNextAction(base).href).toBe("/student/proofs/github")
    expect(deriveNextAction(base).label).toBe("Add your first proof")
  })

  it("prioritizes retrying a failed GitHub proof", () => {
    const action = deriveNextAction({
      ...base,
      githubProofs: [makeGitHubProof({ status: "analysis_failed" })],
    })
    expect(action.label).toBe("Retry GitHub Proof")
  })

  it("resumes an unfinished walkthrough next", () => {
    const action = deriveNextAction({
      ...base,
      githubProofs: [makeGitHubProof()],
      resumableSessionId: "sess-3",
    })
    expect(action.href).toBe("/student/vbr/sessions/sess-3")
  })

  it("asks to complete a pending Project Defense", () => {
    const action = deriveNextAction({
      ...base,
      projects: [makeProject({ metadata: { phase: "project_defense_mvp_v1" } })],
    })
    expect(action.label).toBe("Complete Project Defense")
    expect(action.href).toBe("/student/proofs/project-defense")
  })

  it("points at open skill gaps before passport publishing", () => {
    const action = deriveNextAction({
      ...base,
      githubProofs: [makeGitHubProof()],
      gaps: { projects: [], total_gap_count: 3, generated_at: "" },
      passport: unpublishedPassport,
    })
    expect(action.href).toBe("/dashboard/skill-gaps")
  })

  it("suggests publishing the passport once evidence exists and gaps are clear", () => {
    const action = deriveNextAction({
      ...base,
      githubProofs: [makeGitHubProof()],
      gaps: { projects: [], total_gap_count: 0, generated_at: "" },
      passport: unpublishedPassport,
    })
    expect(action.href).toBe("/student/vbr/passport")
    expect(action.label).toBe("Review & publish your Work Passport")
  })

  it("links to the published passport when live", () => {
    const action = deriveNextAction({
      ...base,
      githubProofs: [makeGitHubProof()],
      gaps: { projects: [], total_gap_count: 0, generated_at: "" },
      passport: { ...unpublishedPassport, is_published: true, public_slug: "s", public_path: "/p/s" },
    })
    expect(action.label).toBe("View your published Work Passport")
  })
})

describe("pure helpers", () => {
  it("summarizes statuses with a closed vocabulary", () => {
    expect(summarizeProofStatuses([])).toBe("Not started")
    expect(summarizeProofStatuses(["analyzed"])).toBe("Complete")
    expect(summarizeProofStatuses(["analyzed", "analyzing"])).toBe("Processing")
    expect(summarizeProofStatuses(["submitted"])).toBe("In progress")
    expect(summarizeProofStatuses(["analyzed", "failed"])).toBe("Failed / retry available")
  })

  it("identifies defense projects by canonical metadata only", () => {
    expect(isDefenseProject(makeProject())).toBe(false)
    expect(isDefenseProject(makeProject({ metadata: { phase: "project_defense_mvp_v1" } }))).toBe(true)
  })
})
