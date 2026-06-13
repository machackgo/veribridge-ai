/**
 * GitHub Proof → Skill Graph sync — frontend wiring tests.
 *
 * Covers: GitHubProofPanel calls syncGitHubProofToSkillGraph after a
 * successful "Analyze Repo" when the proof becomes analyzed (or
 * needs_more_evidence), does NOT call it on initial submit, shows an
 * honest "Couldn't save" + Retry state on sync failure, and recovers
 * when the user retries.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { GitHubProofPanel } from "../../components/passport/GitHubProofPanel"
import type { GitHubProofResponse, GitHubProofSyncResult } from "@/lib/passport-api"

vi.mock("@/lib/passport-api", () => ({
  listGitHubProofs: vi.fn(),
  submitGitHubProof: vi.fn(),
  analyzeGitHubProof: vi.fn(),
  archiveGitHubProof: vi.fn(),
  syncGitHubProofToSkillGraph: vi.fn(),
}))

import {
  listGitHubProofs,
  submitGitHubProof,
  analyzeGitHubProof,
  syncGitHubProofToSkillGraph,
} from "@/lib/passport-api"

function makeProof(overrides: Partial<GitHubProofResponse> = {}): GitHubProofResponse {
  return {
    id: "proof-1",
    repo_url: "https://github.com/octocat/hello-world",
    repo_owner: "octocat",
    repo_name: "hello-world",
    status: "submitted",
    submitted_skill_claims: [],
    detected_skills: [],
    missing_evidence: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function makeSyncResult(overrides: Partial<GitHubProofSyncResult> = {}): GitHubProofSyncResult {
  return {
    ok: true,
    already_synced: false,
    skills_synced: ["React"],
    pipelines_upserted: 1,
    artifacts_created: 1,
    errors: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(listGitHubProofs).mockReset()
  vi.mocked(submitGitHubProof).mockReset()
  vi.mocked(analyzeGitHubProof).mockReset()
  vi.mocked(syncGitHubProofToSkillGraph).mockReset()
})

describe("GitHubProofPanel — Skill Graph sync", () => {
  it("calls syncGitHubProofToSkillGraph and shows 'Saved to Skill Graph' after Analyze succeeds with status analyzed", async () => {
    const submitted = makeProof({ status: "submitted" })
    const analyzed = makeProof({ status: "analyzed", detected_skills: ["React"], confidence_score: 70 })

    vi.mocked(listGitHubProofs).mockResolvedValue([submitted])
    vi.mocked(analyzeGitHubProof).mockResolvedValue(analyzed)
    vi.mocked(syncGitHubProofToSkillGraph).mockResolvedValue(makeSyncResult())

    render(<GitHubProofPanel />)

    const analyzeBtn = await screen.findByRole("button", { name: /analyze repo/i })
    fireEvent.click(analyzeBtn)

    await waitFor(() => expect(syncGitHubProofToSkillGraph).toHaveBeenCalledWith("proof-1"))
    expect(await screen.findByText(/saved to skill graph/i)).toBeInTheDocument()
  })

  it("does not call syncGitHubProofToSkillGraph on initial submit", async () => {
    vi.mocked(listGitHubProofs).mockResolvedValue([])
    const created = makeProof({ id: "proof-new", status: "submitted" })
    vi.mocked(submitGitHubProof).mockResolvedValue(created)

    render(<GitHubProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /add repository/i }))
    fireEvent.change(screen.getByPlaceholderText(/github.com\/username\/repo/i), {
      target: { value: "https://github.com/octocat/hello-world" },
    })
    fireEvent.click(screen.getByRole("button", { name: /submit repository/i }))

    await waitFor(() => expect(submitGitHubProof).toHaveBeenCalled())
    expect(syncGitHubProofToSkillGraph).not.toHaveBeenCalled()
  })

  it("does not show 'Saved to Skill Graph' when result.ok is true but no artifacts were created and errors are present", async () => {
    const submitted = makeProof({ status: "submitted" })
    const analyzed = makeProof({ status: "analyzed", detected_skills: [], confidence_score: 30 })

    vi.mocked(listGitHubProofs).mockResolvedValue([submitted])
    vi.mocked(analyzeGitHubProof).mockResolvedValue(analyzed)
    vi.mocked(syncGitHubProofToSkillGraph).mockResolvedValue(
      makeSyncResult({
        already_synced: false,
        skills_synced: [],
        pipelines_upserted: 0,
        artifacts_created: 0,
        errors: ["No skills detected from GitHub analysis — nothing to sync."],
      }),
    )

    render(<GitHubProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /analyze repo/i }))

    await waitFor(() => expect(syncGitHubProofToSkillGraph).toHaveBeenCalledWith("proof-1"))
    expect(await screen.findByText(/couldn.t save to skill graph/i)).toBeInTheDocument()
    expect(screen.queryByText(/saved to skill graph/i)).not.toBeInTheDocument()
  })

  it("shows 'Couldn't save to Skill Graph' with Retry when sync fails, and recovers on retry", async () => {
    const submitted = makeProof({ status: "submitted" })
    const analyzed = makeProof({ status: "analyzed", detected_skills: ["React"], confidence_score: 70 })

    vi.mocked(listGitHubProofs).mockResolvedValue([submitted])
    vi.mocked(analyzeGitHubProof).mockResolvedValue(analyzed)
    vi.mocked(syncGitHubProofToSkillGraph).mockRejectedValueOnce(new Error("sync_failed"))

    render(<GitHubProofPanel />)

    fireEvent.click(await screen.findByRole("button", { name: /analyze repo/i }))

    expect(await screen.findByText(/couldn.t save to skill graph/i)).toBeInTheDocument()
    expect(screen.queryByText(/saved to skill graph/i)).not.toBeInTheDocument()

    vi.mocked(syncGitHubProofToSkillGraph).mockResolvedValueOnce(makeSyncResult())
    fireEvent.click(screen.getByRole("button", { name: /retry/i }))

    await waitFor(() => expect(syncGitHubProofToSkillGraph).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/saved to skill graph/i)).toBeInTheDocument()
  })
})
