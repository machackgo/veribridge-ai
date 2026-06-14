/**
 * Project Defense recording route (Phase 2A) — `/student/proofs/project-defense/record/[sessionId]`.
 *
 * Covers: the route renders Project Defense-specific recording copy (not the
 * generic VBR walkthrough copy), camera is presented as optional and never
 * required, no team/diarization/public-report language leaks in, permission
 * denials are shown as friendly messages without exposing storage internals,
 * no storage paths/signed URLs/tokens are ever rendered, and the manual
 * pasted-transcript fallback remains reachable.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import ProjectDefenseRecordPage from "../app/student/proofs/project-defense/record/[sessionId]/page"
import {
  getVBRProject,
  getVBRSession,
  getVBRSessionRecordingReadiness,
  type VBRProjectResponse,
  type VBRSessionDetailResponse,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  getVBRSession: vi.fn(),
  getVBRProject: vi.fn(),
  createVBRSessionConsent: vi.fn(),
  startVBRSession: vi.fn(),
  getVBRSessionRecordingReadiness: vi.fn(),
  cancelVBRSessionRecording: vi.fn(),
  requestVBRChunkUploadUrl: vi.fn(),
  uploadVBRChunkBytes: vi.fn(),
  uploadVBRSessionChunk: vi.fn(),
  updateVBRSessionTelemetry: vi.fn(),
  finalizeVBRSession: vi.fn(),
  processVBRSession: vi.fn(),
  transcribeVBRSession: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "sess-1" }),
}))

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
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
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
        created_at: "2026-06-01T00:00:00Z",
      },
    ],
    ...overrides,
  }
}

function makeProject(overrides: Partial<VBRProjectResponse> = {}): VBRProjectResponse {
  return {
    id: "proj-1",
    title: "Skill Evidence Tracker",
    repo_url: "https://github.com/octocat/Hello-World",
    repo_full_name: "octocat/Hello-World",
    deployed_url: null,
    head_sha: null,
    status: "draft",
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    metadata: {},
    ...overrides,
  }
}

const getDisplayMedia = vi.fn()
const getUserMedia = vi.fn()

class MockMediaRecorder {
  static isTypeSupported = vi.fn(() => true)
  state: "inactive" | "recording" | "paused" = "inactive"
  ondataavailable: (() => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  start() {
    this.state = "recording"
  }
  stop() {
    this.state = "inactive"
    this.onstop?.()
  }
  addEventListener() {
    // no-op for tests
  }
}

beforeEach(() => {
  vi.mocked(getVBRSession).mockReset().mockResolvedValue(makeSession())
  vi.mocked(getVBRProject).mockReset().mockResolvedValue(null)
  vi.mocked(getVBRSessionRecordingReadiness).mockReset().mockResolvedValue({
    ready: true,
    code: null,
    message: "Recording upload storage is ready.",
  })

  getDisplayMedia.mockReset().mockRejectedValue(new Error("Permission denied"))
  getUserMedia.mockReset().mockRejectedValue(new Error("Permission denied"))

  Object.defineProperty(navigator, "mediaDevices", {
    value: { getDisplayMedia, getUserMedia },
    configurable: true,
    writable: true,
  })
  ;(globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = MockMediaRecorder
})

describe("ProjectDefenseRecordPage", () => {
  it("renders Project Defense recording copy and does not claim a completed public report", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getAllByText(/project defense recording/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/record your screen and microphone while answering your defense questions/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/camera is optional/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/protected evidence for your skill graph/i).length).toBeGreaterThan(0)

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/team proof/i)
    expect(text).not.toMatch(/diariz/i)
    expect(text).not.toMatch(/final (public )?report (is )?complete/i)
    expect(text).not.toMatch(/\bis fully verified\b/i)
    expect(text).not.toMatch(/(project|student|skill) (is|are) (now |fully )?verified/i)
  })

  it("does not show a camera preflight check and notes camera is not part of Phase 2A recording", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.queryByRole("button", { name: /test camera permission/i })).not.toBeInTheDocument()
    expect(screen.getByText(/camera is optional and not included in this phase 2a recording/i)).toBeInTheDocument()

    // Recording start is gated on consent, not on any camera permission state.
    const startButton = screen.getByRole("button", { name: /start recording session/i })
    expect(startButton).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: /i consent to record this session/i }))
    await waitFor(() => expect(startButton).not.toBeDisabled())
  })

  it("shows a friendly permission-denied message for screen share without exposing storage internals", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: /test screen share permission/i }))

    await waitFor(() => expect(screen.getByText(/permission denied/i)).toBeInTheDocument())

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/https?:\/\/storage/i)
  })

  it("never renders storage paths, signed URLs, or upload tokens", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/signedUrl/)
    expect(text).not.toMatch(/token=/i)
    expect(text).not.toMatch(/\.webm/)
  })

  it("blocks recording start and shows the manual fallback when recording storage is not ready, without exposing internals", async () => {
    vi.mocked(getVBRSessionRecordingReadiness).mockResolvedValue({
      ready: false,
      code: "vbr_media_bucket_not_configured",
      message: "Recording upload storage is not configured.",
    })

    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: /i consent to record this session/i }))
    await waitFor(() => expect(screen.getByRole("button", { name: /start recording session/i })).not.toBeDisabled())

    fireEvent.click(screen.getByRole("button", { name: /start recording session/i }))

    await waitFor(() =>
      expect(screen.getByText(/Recording upload storage is not configured\./)).toBeInTheDocument()
    )
    expect(screen.getByText(/You can still use the manual transcript fallback\./)).toBeInTheDocument()

    expect(getDisplayMedia).not.toHaveBeenCalled()
    expect(getUserMedia).not.toHaveBeenCalled()

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/bucket/i)
  })

  it("keeps the manual pasted-transcript fallback reachable from the recorder", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getByText(/paste your explanation instead/i)).toBeInTheDocument()

    const links = screen.getAllByRole("link", { name: /project defense/i })
    expect(links.length).toBeGreaterThan(0)
    links.forEach((link) => expect(link).toHaveAttribute("href", "/student/proofs/project-defense"))
  })

  it("shows transcript status and a Generate transcript button once the recording is uploaded, with no internals leaked", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession({ status: "uploaded", chunk_count: 1 }))

    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    const section = screen.getByTestId("vbr-transcript")
    expect(within(section).getByText(/Not generated/)).toBeInTheDocument()
    expect(within(section).getByRole("button", { name: "Generate transcript" })).toBeInTheDocument()

    // Manual fallback stays reachable even once a recording exists.
    expect(screen.getByText(/paste your explanation instead/i)).toBeInTheDocument()

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/vbr\/sessions/)
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/\.webm/)
  })

  it("shows project context with attached evidence summary and the Phase 2A recording scope", async () => {
    vi.mocked(getVBRProject).mockResolvedValue(
      makeProject({
        metadata: {
          attached_proofs: {
            github_proof: {
              repo_url: "https://github.com/octocat/Hello-World",
              repo_owner: "octocat",
              repo_name: "Hello-World",
              status: "analyzed",
            },
            documents: [{ title: "Resume.pdf" }],
          },
        },
      })
    )

    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const context = await screen.findByTestId("project-defense-context")
    expect(within(context).getByText(/skill evidence tracker/i)).toBeInTheDocument()
    expect(within(context).getByText(/octocat\/Hello-World \(analyzed\)/i)).toBeInTheDocument()
    expect(within(context).getAllByText(/1 attached/i).length).toBeGreaterThan(0)
    expect(context.textContent).toMatch(/defense questions:\s*1/i)
    expect(within(context).getByText(/phase 2a records screen \+ microphone\. camera is not included yet\./i)).toBeInTheDocument()
  })

  it("shows the website proof attached count in project context", async () => {
    vi.mocked(getVBRProject).mockResolvedValue(
      makeProject({
        metadata: {
          attached_proofs: {
            documents: [{ title: "Resume.pdf" }],
            website_proofs: [
              { target_website: "http://demo.example.com", workflow_confidence: "high" },
            ],
          },
        },
      })
    )

    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const context = await screen.findByTestId("project-defense-context")
    expect(context.textContent).toMatch(/website proof:\s*1 attached/i)
  })

  it("falls back to the repo URL and a safe placeholder when no GitHub Proof or documents are attached", async () => {
    vi.mocked(getVBRProject).mockResolvedValue(makeProject({ metadata: {} }))

    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const context = await screen.findByTestId("project-defense-context")
    expect(within(context).getByText(/octocat\/Hello-World/i)).toBeInTheDocument()
    expect(within(context).getAllByText(/none attached/i).length).toBeGreaterThan(0)
  })

  it("shows a safe fallback when project details are unavailable", async () => {
    render(<ProjectDefenseRecordPage />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const context = screen.getByTestId("project-defense-context")
    expect(within(context).getByText(/project details unavailable/i)).toBeInTheDocument()
    expect(within(context).getByText(/phase 2a records screen \+ microphone\. camera is not included yet\./i)).toBeInTheDocument()
  })
})
