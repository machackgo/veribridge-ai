/**
 * Simplified Website Proof pipeline contract.
 *
 * Website Proof is ONE independent proof type: record a walkthrough, preserve
 * the recording, derive website workflow evidence from it, and attach the
 * completed proof to a project. The page must never embed the other proof
 * pipelines (GitHub, Live Website Check, Project Defense, Documents) or a
 * combined Final Evidence Score — cross-proof aggregation lives in the
 * Passport / Project Report / Skill Report synthesis layer.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const apiMocks = vi.hoisted(() => ({
  createExtensionProofSession: vi.fn(),
  createSkillEvidence: vi.fn(),
  getExtensionProofSession: vi.fn(),
  getReviewStatus: vi.fn(),
  getWorkflowAnalysis: vi.fn(),
  getWorkflowPrivacyScan: vi.fn(),
  listExtensionProofSessions: vi.fn(),
  initializeWebsiteProofRecorder: vi.fn(),
  openWebsiteProofTarget: vi.fn(),
  startWebsiteProofRecording: vi.fn(),
  refreshWebsiteProofRecorderSessionAuth: vi.fn(),
  startExtensionProofSession: vi.fn(),
  fetchAPI: vi.fn(),
}))

const vbrMocks = vi.hoisted(() => ({
  createVBRProject: vi.fn(),
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

import { ExtensionProofPanel } from "../../components/skill-proof/extension-proof-panel"
import type { ExtensionProofSessionResponse, WorkflowAnalysisResponse } from "@/lib/api"

const PROJECT = {
  id: "project-reactplay",
  user_id: "user-1",
  title: "ReactPlay Open-Source Learning Platform Test",
  repo_url: "https://github.com/reactplay/react-play",
  repo_full_name: "reactplay/react-play",
  deployed_url: "https://reactplay.io/",
  status: "draft",
  metadata: { claimed_skills: ["React"] },
  created_at: "2026-07-16T10:00:00Z",
  updated_at: "2026-07-16T10:00:00Z",
}

const SESSION_ID = "session-reactplay-1"

function session(
  overrides: Partial<ExtensionProofSessionResponse> = {},
): ExtensionProofSessionResponse {
  return {
    id: SESSION_ID,
    user_id: "user-1",
    skill_evidence_id: "evidence-1",
    project_id: null,
    project_relationship_state: "vault_only",
    website_url: "https://reactplay.io",
    github_url: "https://github.com/reactplay/react-play",
    claimed_skills: ["React", "JavaScript"],
    proof_objective: "Demonstrate the ReactPlay user workflow by browsing projects",
    finalized_at: null,
    finalized_project_id: null,
    status: "completed",
    started_at: "2026-07-16T11:00:00Z",
    proof_upload_id: "upload-1",
    created_at: "2026-07-16T11:00:00Z",
    updated_at: "2026-07-16T11:10:00Z",
    ...overrides,
  }
}

function analysis(
  overrides: Partial<WorkflowAnalysisResponse> = {},
): WorkflowAnalysisResponse {
  return {
    id: "analysis-1",
    proof_session_id: SESSION_ID,
    analysis_type: "workflow_timeline",
    analyzer_version: "v6",
    workflow_summary:
      "The recording shows the user browsing the ReactPlay project gallery and opening a play.",
    demonstrated_actions: ["Opened the ReactPlay project browser", "Interacted with a play"],
    supported_skills: ["React"],
    weakly_supported_skills: [],
    unsupported_skills: [],
    evidence_strength_score: 72,
    workflow_confidence: "medium",
    missing_evidence: [],
    risk_flags: [],
    recruiter_summary:
      "Recording shows a ReactPlay walkthrough. Evidence strength: 72/100 · Confidence: Medium (Workflow Timeline Analysis — visual video evidence not yet available).",
    student_improvement_suggestions: [],
    human_review_needed: false,
    video_keyframe_status: "extracted",
    video_keyframe_count: 6,
    video_keyframe_timestamps_ms: [0, 10_000, 20_000, 30_000, 40_000, 50_000],
    video_duration_ms: 95_000,
    ...overrides,
  } as WorkflowAnalysisResponse
}

/** Minimal ok-Response stub carrying a non-empty video blob. */
function okVideoResponse(): Response {
  const blob = new Blob([new Uint8Array(64)], { type: "video/webm" })
  return {
    ok: true,
    status: 200,
    blob: async () => blob,
  } as unknown as Response
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
  vbrMocks.listVBRProjects.mockResolvedValue([PROJECT])
  vbrMocks.finalizeWebsiteProof.mockResolvedValue({
    proof_type: "website",
    proof_id: SESSION_ID,
    project_id: PROJECT.id,
    already_finalized: false,
    finalized_at: "2026-07-16T11:20:00Z",
    project_relationship: { state: "directly_linked", project_id: PROJECT.id, project_title: PROJECT.title },
  })
  apiMocks.listExtensionProofSessions.mockResolvedValue([])
  apiMocks.getReviewStatus.mockResolvedValue(null)
  apiMocks.getWorkflowPrivacyScan.mockResolvedValue(null)
  apiMocks.getWorkflowAnalysis.mockResolvedValue(analysis())
  apiMocks.getExtensionProofSession.mockResolvedValue(session())
  apiMocks.fetchAPI.mockResolvedValue(okVideoResponse())
  if (!("createObjectURL" in URL) || !(URL.createObjectURL as unknown)) {
    Object.assign(URL, {
      createObjectURL: () => "blob:mock-replay",
      revokeObjectURL: () => undefined,
    })
  }
})

describe("Simplified Website Proof — completed session view", () => {
  async function renderCompleted() {
    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId={SESSION_ID} />)
    // Anchor on the workflow evidence card so the view is fully hydrated.
    expect(await screen.findByText("Workflow Evidence Analysis")).toBeInTheDocument()
  }

  it("renders the recorded proof video as the primary artifact", async () => {
    await renderCompleted()
    expect(screen.getByTestId("website-proof-recording-section")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId("website-proof-recording-video")).toBeInTheDocument()
    })
    expect(apiMocks.fetchAPI).toHaveBeenCalledWith(
      `/api/v1/proofs/website/${SESSION_ID}/replay`,
    )
    expect(screen.getByTestId("website-proof-recording-privacy")).toHaveTextContent(
      "Private retained evidence",
    )
  })

  it("renders website workflow evidence derived from the current recording", async () => {
    await renderCompleted()
    expect(
      screen.getByText(/browsing the ReactPlay project gallery/),
    ).toBeInTheDocument()
    expect(screen.getByText("Opened the ReactPlay project browser")).toBeInTheDocument()
    expect(screen.getByText("Workflow Evidence Checklist")).toBeInTheDocument()
  })

  it("does not render any legacy multi-source proof sections", async () => {
    await renderCompleted()
    for (const legacy of [
      /Run GitHub Evidence Analysis/i,
      /GitHub Evidence: Not Provided/i,
      /Run Live Website Check/i,
      /Project Defense/i,
      /Final Evidence Score/i,
      /Additional Evidence/i,
      /Detected Skill Profile/i,
      /learning opportunit/i,
      /Verification Review/i,
      /Final Verification/i,
    ]) {
      expect(screen.queryByText(legacy)).not.toBeInTheDocument()
    }
  })

  it("never presents numeric recruiter-facing skill scores", async () => {
    await renderCompleted()
    expect(document.body.textContent).not.toMatch(/\d+\s*\/\s*100/)
    // Historical narratives with embedded numeric strength are presented qualitatively.
    expect(screen.getByText(/Evidence strength: strong/)).toBeInTheDocument()
  })

  it("attaches the completed proof to an explicitly selected project", async () => {
    await renderCompleted()
    // A vault-only session defaults to "Keep in Proof Vault"; attaching is an
    // explicit mode switch.
    fireEvent.click(await screen.findByTestId("website-proof-save-mode-existing"))
    const select = await screen.findByTestId("website-proof-save-project-select")
    fireEvent.change(select, { target: { value: PROJECT.id } })
    fireEvent.click(screen.getByRole("button", { name: "Save this proof" }))
    await waitFor(() => {
      expect(vbrMocks.finalizeWebsiteProof).toHaveBeenCalledWith({
        proof_id: SESSION_ID,
        project_id: PROJECT.id,
      })
    })
    expect(await screen.findByText(`Saved to project: ${PROJECT.title}`)).toBeInTheDocument()
  })

  it("keeps a vault-only proof in the Proof Vault without requiring any project", async () => {
    // Brand-new student: zero projects. The completed proof must still be
    // preservable — this was the V1.0.0 dead end.
    vbrMocks.listVBRProjects.mockResolvedValue([])
    await renderCompleted()
    const keepButton = await screen.findByRole("button", { name: "Keep in Proof Vault" })
    fireEvent.click(keepButton)
    expect(await screen.findByTestId("website-proof-kept-in-vault")).toBeInTheDocument()
    expect(screen.getByText("Kept in Proof Vault")).toBeInTheDocument()
    // Vault-keeping mutates nothing and never silently attaches to a project.
    expect(vbrMocks.finalizeWebsiteProof).not.toHaveBeenCalled()
    expect(vbrMocks.createVBRProject).not.toHaveBeenCalled()
  })

  it("guides a zero-project student from the existing-project mode instead of dead-ending", async () => {
    vbrMocks.listVBRProjects.mockResolvedValue([])
    await renderCompleted()
    fireEvent.click(await screen.findByTestId("website-proof-save-mode-existing"))
    expect(await screen.findByTestId("website-proof-no-projects")).toBeInTheDocument()
    expect(screen.queryByTestId("website-proof-save-project-select")).not.toBeInTheDocument()
  })

  it("creates a new project inline and attaches the completed proof to it", async () => {
    vbrMocks.listVBRProjects.mockResolvedValue([])
    const newProject = {
      ...PROJECT,
      id: "project-fresh",
      title: "My First Project",
      repo_url: "https://github.com/student/first",
    }
    vbrMocks.createVBRProject.mockResolvedValue(newProject)
    vbrMocks.finalizeWebsiteProof.mockResolvedValue({
      proof_type: "website",
      proof_id: SESSION_ID,
      project_id: newProject.id,
      already_finalized: false,
      finalized_at: "2026-08-20T11:20:00Z",
      project_relationship: { state: "directly_linked", project_id: newProject.id, project_title: newProject.title },
    })

    await renderCompleted()
    fireEvent.click(await screen.findByTestId("website-proof-save-mode-create"))
    const titleInput = await screen.findByTestId("website-proof-create-title")
    const repoInput = screen.getByTestId("website-proof-create-repo")
    // The repository URL entered at recording time is offered as an editable
    // prefill — never auto-submitted on its own.
    expect((repoInput as HTMLInputElement).value).toBe("https://github.com/reactplay/react-play")
    fireEvent.change(titleInput, { target: { value: "My First Project" } })
    fireEvent.change(repoInput, { target: { value: "https://github.com/student/first" } })
    fireEvent.click(screen.getByRole("button", { name: "Create project & attach proof" }))

    await waitFor(() => {
      expect(vbrMocks.createVBRProject).toHaveBeenCalledWith({
        title: "My First Project",
        repo_url: "https://github.com/student/first",
        deployed_url: "https://reactplay.io",
      })
    })
    await waitFor(() => {
      expect(vbrMocks.finalizeWebsiteProof).toHaveBeenCalledWith({
        proof_id: SESSION_ID,
        project_id: newProject.id,
      })
    })
    expect(await screen.findByText(`Saved to project: ${newProject.title}`)).toBeInTheDocument()
  })

  it("preserves the completed proof when project creation fails", async () => {
    vbrMocks.listVBRProjects.mockResolvedValue([])
    vbrMocks.createVBRProject.mockRejectedValue(new Error("repo_url must be a supported GitHub repository URL."))
    await renderCompleted()
    fireEvent.click(await screen.findByTestId("website-proof-save-mode-create"))
    fireEvent.change(await screen.findByTestId("website-proof-create-title"), { target: { value: "Broken" } })
    fireEvent.change(screen.getByTestId("website-proof-create-repo"), { target: { value: "not-a-repo" } })
    fireEvent.click(screen.getByRole("button", { name: "Create project & attach proof" }))

    expect(await screen.findByTestId("website-proof-save-error")).toHaveTextContent(
      "repo_url must be a supported GitHub repository URL.",
    )
    // The proof itself is untouched and the flow remains retryable.
    expect(vbrMocks.finalizeWebsiteProof).not.toHaveBeenCalled()
    expect(screen.getByTestId("website-proof-finalization")).toBeInTheDocument()
  })

  it("defaults to attaching when the session was started against a project", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session({ project_id: PROJECT.id }))
    await renderCompleted()
    const select = await screen.findByTestId("website-proof-save-project-select")
    expect((select as HTMLSelectElement).value).toBe(PROJECT.id)
    fireEvent.click(screen.getByRole("button", { name: "Save this proof" }))
    await waitFor(() => {
      expect(vbrMocks.finalizeWebsiteProof).toHaveBeenCalledWith({
        proof_id: SESSION_ID,
        project_id: PROJECT.id,
      })
    })
  })

  it("reconciles an already-saved proof against the same project without creating a new session", async () => {
    apiMocks.getExtensionProofSession.mockResolvedValue(session({
      project_id: PROJECT.id,
      project_relationship_state: "directly_linked",
      finalized_at: "2026-07-16T11:20:00Z",
      finalized_project_id: PROJECT.id,
    }))
    vbrMocks.finalizeWebsiteProof.mockResolvedValue({
      proof_type: "website",
      proof_id: SESSION_ID,
      project_id: PROJECT.id,
      already_finalized: true,
      finalized_at: "2026-07-16T11:20:00Z",
      project_relationship: { state: "directly_linked", project_id: PROJECT.id, project_title: PROJECT.title },
    })

    await renderCompleted()
    fireEvent.click(await screen.findByTestId("website-proof-reconcile-save"))

    await waitFor(() => {
      expect(vbrMocks.finalizeWebsiteProof).toHaveBeenCalledWith({
        proof_id: SESSION_ID,
        project_id: PROJECT.id,
      })
    })
    expect(apiMocks.createExtensionProofSession).not.toHaveBeenCalled()
    expect(await screen.findByText("Already saved — no duplicate evidence was created.")).toBeInTheDocument()
  })

  it("shows the honest not-retained state instead of a broken player", async () => {
    // Simulate a legacy session with no retained replay: bounded rechecks are
    // still pending, so the section reports the upload/processing state rather
    // than claiming a missing video or rendering a broken player.
    apiMocks.fetchAPI.mockResolvedValue({
      ok: false,
      status: 404,
      blob: async () => new Blob([]),
    } as unknown as Response)
    await renderCompleted()
    await waitFor(() => {
      expect(screen.getByTestId("website-proof-recording-processing")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("website-proof-recording-video")).not.toBeInTheDocument()
  })
})

describe("Simplified Website Proof — create form", () => {
  it("contains only the simplified create fields", async () => {
    render(<ExtensionProofPanel onBack={() => undefined} requestedSessionId={null} />)
    expect(await screen.findByText("Website Proof")).toBeInTheDocument()

    // Present: privacy consent, project relationship, website URL, optional
    // GitHub metadata, skills, objective, start action.
    expect(screen.getByTestId("website-proof-project-select")).toBeInTheDocument()
    expect(screen.getByText(/Website URL/)).toBeInTheDocument()
    expect(screen.getByText(/GitHub Repository URL/)).toBeInTheDocument()
    expect(screen.getByText(/Skills this demonstrates/)).toBeInTheDocument()
    expect(screen.getByText(/Proof objective/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Start proof/ })).toBeInTheDocument()

    // Vault-only is the explicit default project relationship.
    expect(
      screen.getByText("Proof Vault only — do not count in project reports"),
    ).toBeInTheDocument()

    // Absent: every legacy multi-source builder and the live page scanner.
    for (const legacy of [
      /Live Website Check/i,
      /GitHub Evidence Analysis/i,
      /Project Defense/i,
      /Final Evidence Score/i,
      /Discover evidence/i,
      /Scan page/i,
      /learning opportunit/i,
    ]) {
      expect(screen.queryByText(legacy)).not.toBeInTheDocument()
    }
  })
})
