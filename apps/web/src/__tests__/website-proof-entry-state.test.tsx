import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const apiMocks = vi.hoisted(() => ({
  createExtensionProofSession: vi.fn(),
  createSkillEvidence: vi.fn(),
  getExtensionProofGitHubAnalysis: vi.fn(),
  getExtensionProofSession: vi.fn(),
  getFinalEvaluation: vi.fn(),
  getLiveWebsiteCheck: vi.fn(),
  getProjectDefenseAnalysis: vi.fn(),
  getReviewStatus: vi.fn(),
  getWorkflowAnalysis: vi.fn(),
  getWorkflowPrivacyScan: vi.fn(),
  listExtensionProofSessions: vi.fn(),
  initializeWebsiteProofRecorder: vi.fn(),
  openWebsiteProofTarget: vi.fn(),
  startWebsiteProofRecording: vi.fn(),
  refreshWebsiteProofRecorderSessionAuth: vi.fn(),
  startExtensionProofSession: vi.fn(),
}))

const vbrMocks = vi.hoisted(() => ({
  finalizeWebsiteProof: vi.fn(),
  listVBRProjects: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...apiMocks,
}))

vi.mock("@/lib/vbr-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/vbr-api")>()),
  ...vbrMocks,
}))

import {
  ExtensionProofPanel,
  isResumableExtensionProofSession,
  saveActiveExtensionProofSession,
  websiteProofEntryState,
} from "../../components/skill-proof/extension-proof-panel"
import type { ExtensionProofSessionResponse } from "@/lib/api"

const PROJECT = {
  id: "project-wikitok",
  user_id: "user-1",
  title: "WikiTok Open-Source Pipeline Test",
  repo_url: "https://github.com/example/wikitok",
  repo_full_name: "example/wikitok",
  deployed_url: "https://wikitok.io/",
  status: "draft",
  metadata: { claimed_skills: ["React"] },
  created_at: "2026-07-14T10:00:00Z",
  updated_at: "2026-07-14T10:00:00Z",
}

function session(
  overrides: Partial<ExtensionProofSessionResponse> = {},
): ExtensionProofSessionResponse {
  return {
    id: "session-old-localhost",
    user_id: "user-1",
    skill_evidence_id: "evidence-old",
    project_id: null,
    project_relationship_state: "vault_only",
    website_url: "http://localhost:3000",
    github_url: null,
    claimed_skills: ["Next.js", "React"],
    proof_objective: "Demonstrate the historical local application workflow",
    finalized_at: null,
    finalized_project_id: null,
    status: "completed",
    started_at: "2026-07-01T10:00:00Z",
    proof_upload_id: "upload-old",
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:10:00Z",
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  vbrMocks.listVBRProjects.mockResolvedValue([PROJECT])
  apiMocks.initializeWebsiteProofRecorder.mockImplementation(async (input) => ({
    ok: true,
    config: {
      schema_version: 1,
      ...input,
      api_base_url: "http://localhost:8128",
      auth: { mechanism: "bearer", access_token: "private-recorder-token", expires_at: null },
      expires_at: null,
    },
    acknowledgement: {
      request_id: "request-1",
      session_id: input.session_id,
      config_revision: input.config_revision,
      api_base_url: "http://localhost:8128",
      schema_version: 1,
      build_version: "0.2.0",
      extension_id: "extension-id",
      ready: true,
    },
  }))
  apiMocks.openWebsiteProofTarget.mockImplementation(async (config) => ({
    request_id: "target-request-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
    api_base_url: config.api_base_url,
    claimed_skills: config.claimed_skills,
    target_tab_id: 42,
    target_url: config.website_url,
    ready: true,
  }))
  apiMocks.startWebsiteProofRecording.mockImplementation(async (config) => ({
    request_id: "start-request-1",
    session_id: config.session_id,
    config_revision: config.config_revision,
    started_at: "2026-07-14T12:00:00Z",
    idempotent: false,
    ready: true,
  }))
  apiMocks.refreshWebsiteProofRecorderSessionAuth.mockResolvedValue(true)
  apiMocks.startExtensionProofSession.mockResolvedValue(null)
  apiMocks.getWorkflowAnalysis.mockResolvedValue(null)
  apiMocks.getLiveWebsiteCheck.mockResolvedValue(null)
  apiMocks.getExtensionProofGitHubAnalysis.mockResolvedValue(null)
  apiMocks.getWorkflowPrivacyScan.mockResolvedValue(null)
  apiMocks.getProjectDefenseAnalysis.mockResolvedValue(null)
  apiMocks.getFinalEvaluation.mockResolvedValue(null)
  apiMocks.getReviewStatus.mockResolvedValue(null)
  apiMocks.listExtensionProofSessions.mockResolvedValue([])
})

describe("Website Proof entry-state contract", () => {
  it("maps NEW, ACTIVE, COMPLETED, SAVED, and FAILED_RETRYABLE distinctly", () => {
    expect(websiteProofEntryState(null)).toBe("NEW")
    expect(websiteProofEntryState(session({ status: "recording" }))).toBe("ACTIVE")
    expect(websiteProofEntryState(session())).toBe("COMPLETED")
    expect(websiteProofEntryState(session({ finalized_at: "2026-07-14T12:00:00Z" }))).toBe("SAVED")
    expect(websiteProofEntryState(session({ status: "expired" }))).toBe("FAILED_RETRYABLE")
    expect(isResumableExtensionProofSession(session({ status: "analyzing" }))).toBe(true)
    expect(isResumableExtensionProofSession(session())).toBe(false)
  })

  it("keeps the bare landing route NEW and never auto-selects a stored completed proof", async () => {
    saveActiveExtensionProofSession({
      sessionId: "session-old-localhost",
      form: {
        websiteUrl: "http://localhost:3000",
        githubUrl: "",
        skillName: "Old React logs",
        proofObjective: "Old completed proof objective should not render",
      },
      savedAt: "2026-07-01T10:10:00Z",
    })
    apiMocks.getExtensionProofSession.mockResolvedValue(session())

    render(<ExtensionProofPanel onBack={() => undefined} />)

    await waitFor(() => expect(apiMocks.getExtensionProofSession).toHaveBeenCalledWith("session-old-localhost"))
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
    expect(screen.queryByText("Old React logs")).not.toBeInTheDocument()
    expect(screen.queryByText(/DEV: session\.id/)).not.toBeInTheDocument()
    expect(screen.queryByTestId("unfinished-website-proof")).not.toBeInTheDocument()
    expect(localStorage.getItem("vb_active_extension_proof_session")).toBeNull()
  })

  it("offers Resume and Start new for an unfinished session without forcing resume", async () => {
    saveActiveExtensionProofSession({
      sessionId: "session-active",
      form: {
        websiteUrl: "https://wikitok.io/",
        githubUrl: "",
        skillName: "React",
        proofObjective: "Demonstrate a fresh WikiTok workflow end to end",
      },
      savedAt: "2026-07-14T10:10:00Z",
    })
    apiMocks.getExtensionProofSession.mockResolvedValue(session({
      id: "session-active",
      website_url: "https://wikitok.io/",
      status: "recording",
    }))

    render(<ExtensionProofPanel onBack={() => undefined} />)

    expect(await screen.findByText("You have an unfinished Website Proof.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
    fireEvent.click(screen.getByRole("button", { name: "Resume" }))
    expect(await screen.findByText(/session-active/)).toBeInTheDocument()
    expect(screen.getByText("https://wikitok.io/")).toBeInTheDocument()
  })

  it("never selects an implicit latest session when no explicit local pointer exists", async () => {
    apiMocks.listExtensionProofSessions.mockResolvedValue([
      session(),
      session({
        id: "session-active-from-server",
        website_url: "https://wikitok.io/",
        claimed_skills: ["React"],
        proof_objective: "Resume the server-owned unfinished workflow",
        status: "analyzing",
        updated_at: "2026-07-14T11:00:00Z",
      }),
    ])

    render(<ExtensionProofPanel onBack={() => undefined} />)

    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
    expect(document.querySelector('[data-entry-state="NEW"]')).toBeInTheDocument()
    expect(apiMocks.getExtensionProofSession).not.toHaveBeenCalled()
    expect(apiMocks.listExtensionProofSessions).not.toHaveBeenCalled()
    expect(screen.queryByText("You have an unfinished Website Proof.")).not.toBeInTheDocument()
  })

  it("Start new clears only the active pointer and leaves the backend session untouched", async () => {
    const active = session({ id: "session-active", status: "recording", website_url: "https://wikitok.io/" })
    saveActiveExtensionProofSession({
      sessionId: active.id,
      form: { websiteUrl: "https://wikitok.io/", githubUrl: "", skillName: "React", proofObjective: "Show the active feed workflow" },
      savedAt: "2026-07-14T10:10:00Z",
    })
    apiMocks.getExtensionProofSession.mockResolvedValue(active)

    render(<ExtensionProofPanel onBack={() => undefined} />)
    fireEvent.click(await screen.findByRole("button", { name: "Start new proof" }))

    expect(localStorage.getItem("vb_active_extension_proof_session")).toBeNull()
    expect(apiMocks.getExtensionProofSession).toHaveBeenCalledTimes(1)
    expect(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i)).toHaveValue("")
  })

  it("history preserves owned sessions and opens each through an explicit session URL", async () => {
    apiMocks.listExtensionProofSessions.mockResolvedValue([
      session(),
      session({ id: "session-active", status: "recording", website_url: "https://wikitok.io/", created_at: "2026-07-14T10:00:00Z" }),
    ])

    render(<ExtensionProofPanel onBack={() => undefined} historyMode />)

    const rows = await screen.findAllByTestId("website-proof-history-row")
    expect(rows).toHaveLength(2)
    expect(screen.getByText("http://localhost:3000")).toBeInTheDocument()
    const links = screen.getAllByRole("link", { name: "Open proof" })
    expect(links[0]).toHaveAttribute("href", "/student/proofs/website?session=session-old-localhost")
    expect(links[1]).toHaveAttribute("href", "/student/proofs/website?session=session-active")
  })

  it("opening a historical proof never binds that ID over the fresh extension config", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session())

    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId="session-old-localhost" />)

    await waitFor(() => expect(apiMocks.getExtensionProofSession).toHaveBeenCalledWith("session-old-localhost"))
    expect(apiMocks.initializeWebsiteProofRecorder.mock.calls.some(([config]) =>
      config?.session_id === "session-old-localhost"
    )).toBe(false)
  })

  it("an explicit session route opens that exact completed proof and exposes canonical save", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session())
    vbrMocks.finalizeWebsiteProof.mockResolvedValue({
      proof_id: "session-old-localhost",
      proof_type: "website",
      project_id: PROJECT.id,
      project_relationship: {
        state: "directly_linked",
        project_id: PROJECT.id,
        project_title: PROJECT.title,
        match_method: "user_confirmation",
        counted: true,
        confirmed_by_user: true,
        reasons: ["The student confirmed this Website Proof belongs to the selected project."],
        action_label: null,
      },
      evidence_item_count: 1,
      supported_skill_count: 1,
      unsupported_skill_count: 0,
      claim_link_count: 1,
      artifact_ids: ["artifact-1"],
      report_eligibility: "report_ready",
      warnings: [],
      failure_category: null,
      already_finalized: false,
      finalized_at: "2026-07-14T12:00:00Z",
    })

    render(
      <ExtensionProofPanel
        onBack={() => undefined}
        requestedSessionId="session-old-localhost"
      />,
    )

    expect(await screen.findByTestId("website-proof-finalization")).toHaveTextContent("Save this proof")
    expect(apiMocks.getExtensionProofSession).toHaveBeenCalledWith("session-old-localhost")
    fireEvent.change(screen.getByTestId("website-proof-save-project-select"), { target: { value: PROJECT.id } })
    fireEvent.click(screen.getByRole("button", { name: "Save this proof" }))

    await waitFor(() => expect(vbrMocks.finalizeWebsiteProof).toHaveBeenCalledWith({
      proof_id: "session-old-localhost",
      project_id: PROJECT.id,
    }))
    expect(await screen.findByText(`Saved to project: ${PROJECT.title}`)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "View in Passport" })).toHaveAttribute("href", "/student/vbr/passport")
    expect(screen.getByRole("link", { name: "View Project Report" })).toHaveAttribute("href", `/student/vbr/projects/${PROJECT.id}/report`)
    expect(screen.getByRole("link", { name: "View Proof Vault" })).toHaveAttribute("href", "/student/vbr/passport/vault")
    expect(screen.queryByRole("button", { name: "Save this proof" })).not.toBeInTheDocument()
  })

  it("reload renders a persisted completed finalization as Saved without another mutation", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session({
      project_id: PROJECT.id,
      project_relationship_state: "directly_linked",
      finalized_at: "2026-07-14T12:00:00Z",
      finalized_project_id: PROJECT.id,
    }))

    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId="session-old-localhost" />)

    expect(await screen.findByText(`Saved to project: ${PROJECT.title}`)).toBeInTheDocument()
    expect(screen.getByTestId("website-proof-finalization")).toHaveTextContent("Saved")
    expect(vbrMocks.finalizeWebsiteProof).not.toHaveBeenCalled()
  })

  it("requires an explicitly owned project selection before save", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session())
    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId="session-old-localhost" />)

    fireEvent.click(await screen.findByRole("button", { name: "Save this proof" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Select the project")
    expect(vbrMocks.finalizeWebsiteProof).not.toHaveBeenCalled()
  })

  it("creates a new session ID from the fresh form without reusing historical state", async () => {
    apiMocks.createSkillEvidence.mockResolvedValue({ id: "evidence-new" })
    apiMocks.createExtensionProofSession.mockResolvedValue(session({
      id: "session-new-wikitok",
      skill_evidence_id: "evidence-new",
      status: "created",
      website_url: "https://wikitok.io/",
      claimed_skills: ["React"],
      proof_objective: "Demonstrate the WikiTok feed workflow end to end",
      proof_upload_id: null,
      started_at: null,
    }))
    apiMocks.startExtensionProofSession.mockResolvedValue(session({
      id: "session-new-wikitok",
      skill_evidence_id: "evidence-new",
      status: "recording",
      website_url: "https://wikitok.io/",
      claimed_skills: ["React"],
      proof_objective: "Demonstrate the WikiTok feed workflow end to end",
      proof_upload_id: null,
      started_at: "2026-07-14T12:00:00Z",
    }))
    render(<ExtensionProofPanel onBack={() => undefined} />)
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-project\.vercel\.app/i), { target: { value: "https://wikitok.io/" } })
    fireEvent.change(screen.getByPlaceholderText("e.g. FastAPI, React, Machine Learning"), { target: { value: "React" } })
    fireEvent.change(screen.getByPlaceholderText(/Describe what you'll walk through/i), { target: { value: "Demonstrate the WikiTok feed workflow end to end" } })
    fireEvent.click(screen.getByText(/I understand and will avoid showing sensitive information/i))
    fireEvent.click(screen.getByRole("button", { name: "Start proof" }))

    await waitFor(() => expect(apiMocks.createExtensionProofSession).toHaveBeenCalledWith(
      "evidence-new",
      expect.objectContaining({
        website_url: "https://wikitok.io/",
        claimed_skills: ["React"],
      }),
    ))
    await waitFor(() => {
      expect(document.querySelector('[data-entry-state="ACTIVE"]')).toBeInTheDocument()
      expect(JSON.parse(localStorage.getItem("vb_active_extension_proof_session") || "{}").sessionId)
        .toBe("session-new-wikitok")
    })
    expect(apiMocks.createExtensionProofSession).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole("button", { name: /Start Proof Demo/i }))

    await waitFor(() => expect(apiMocks.openWebsiteProofTarget).toHaveBeenCalledTimes(1))
    expect(apiMocks.initializeWebsiteProofRecorder).toHaveBeenCalledWith(expect.objectContaining({
      session_id: "session-new-wikitok",
      config_revision: 1,
      website_url: "https://wikitok.io/",
      claimed_skills: ["React"],
    }))
    expect(apiMocks.startExtensionProofSession).toHaveBeenCalledWith("session-new-wikitok")
    expect(apiMocks.startWebsiteProofRecording).toHaveBeenCalledTimes(1)
    const [launchConfig] = apiMocks.openWebsiteProofTarget.mock.calls[0]
    expect(launchConfig.website_url).toBe("https://wikitok.io/")
    expect(launchConfig.website_url).not.toContain("private-recorder-token")
    expect(launchConfig.website_url).not.toContain("localhost%3A8128")
  })

  it("fails closed when an explicit foreign session cannot be fetched", async () => {
    apiMocks.getExtensionProofSession.mockRejectedValue(new Error("not found"))
    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId="foreign-session" />)

    expect(await screen.findByRole("alert")).toHaveTextContent("not found or is not available to this account")
    expect(screen.queryByText(/DEV: session\.id/)).not.toBeInTheDocument()
  })
})
