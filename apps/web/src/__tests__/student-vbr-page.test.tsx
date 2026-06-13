/**
 * /student/vbr (Proof Studio) — Phase 1 Project Defense navigation tests.
 *
 * Covers: a VBR project created via the Phase 1 manual Project Defense flow
 * (metadata.phase === "project_defense_mvp_v1") is never advertised as a
 * recordable walkthrough — it does not show "Continue recording" and links
 * back to /student/proofs/project-defense, not the old recorder route at
 * /student/vbr/sessions/{sessionId}. Legacy recorder projects keep their
 * existing "Continue recording" behavior.
 */

import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import StudentVBRPage from "../app/student/vbr/page"
import {
  getVBRProjectQuestions,
  listVBRProjects,
  type VBRProjectResponse,
  type VBRProjectQuestionsResponse,
} from "@/lib/vbr-api"
import { listGitHubProofs } from "@/lib/passport-api"

vi.mock("@/lib/vbr-api", () => ({
  listVBRProjects: vi.fn(),
  getVBRProjectQuestions: vi.fn(),
}))

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
}))

function makeProject(overrides: Partial<VBRProjectResponse> = {}): VBRProjectResponse {
  return {
    id: "proj-1",
    title: "Skill Evidence Tracker",
    repo_url: "https://github.com/octocat/Hello-World",
    repo_full_name: "octocat/Hello-World",
    deployed_url: null,
    head_sha: null,
    status: "draft",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    metadata: {},
    ...overrides,
  }
}

function makeQuestionsResponse(
  overrides: Partial<VBRProjectQuestionsResponse> = {}
): VBRProjectQuestionsResponse {
  return {
    project_id: "proj-1",
    session_id: null,
    questions: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(listVBRProjects).mockReset()
  vi.mocked(getVBRProjectQuestions).mockReset()
  vi.mocked(listGitHubProofs).mockReset().mockResolvedValue([])
})

describe("StudentVBRPage", () => {
  it("does not show 'Continue recording' for a Phase 1 Project Defense project, and links to /student/proofs/project-defense", async () => {
    const project = makeProject({ metadata: { phase: "project_defense_mvp_v1" } })
    vi.mocked(listVBRProjects).mockResolvedValue([project])
    vi.mocked(getVBRProjectQuestions).mockResolvedValue(
      makeQuestionsResponse({ session_id: "sess-1" })
    )

    render(<StudentVBRPage />)

    expect(await screen.findByText("Skill Evidence Tracker")).toBeInTheDocument()
    expect(screen.queryByText(/continue recording/i)).not.toBeInTheDocument()

    const defenseLink = screen.getByRole("link", { name: /view project defense/i })
    expect(defenseLink).toHaveAttribute("href", "/student/proofs/project-defense")
    expect(screen.queryByRole("link", { name: /sessions\/sess-1/i })).not.toBeInTheDocument()
  })

  it("shows 'Manual defense available' when project_defense_status is analyzed", async () => {
    const project = makeProject({
      metadata: { phase: "project_defense_mvp_v1", project_defense_status: "analyzed" },
    })
    vi.mocked(listVBRProjects).mockResolvedValue([project])
    vi.mocked(getVBRProjectQuestions).mockResolvedValue(makeQuestionsResponse())

    render(<StudentVBRPage />)

    expect(await screen.findByText(/manual defense available/i)).toBeInTheDocument()
  })

  it("still shows 'Continue recording' linking to the recorder route for legacy (non-Phase-1) VBR projects", async () => {
    const project = makeProject({ metadata: {} })
    vi.mocked(listVBRProjects).mockResolvedValue([project])
    vi.mocked(getVBRProjectQuestions).mockResolvedValue(
      makeQuestionsResponse({ session_id: "sess-legacy" })
    )

    render(<StudentVBRPage />)

    const continueLink = await screen.findByRole("link", { name: /continue recording/i })
    expect(continueLink).toHaveAttribute("href", "/student/vbr/sessions/sess-legacy")
  })

  it("Project Defense entry-point card links to /student/proofs/project-defense, not the recorder", async () => {
    vi.mocked(listVBRProjects).mockResolvedValue([])

    render(<StudentVBRPage />)

    const link = await screen.findByRole("link", { name: /start project defense/i })
    expect(link).toHaveAttribute("href", "/student/proofs/project-defense")
    expect(screen.queryByText(/record a short walkthrough/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/shareable verified build report/i)).not.toBeInTheDocument()
  })
})
