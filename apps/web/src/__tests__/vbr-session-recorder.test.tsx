import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { VBRSessionRecorder } from "../app/student/vbr/sessions/[sessionId]/VBRSessionRecorder"
import {
  createVBRSessionConsent,
  getVBRProject,
  getVBRSession,
  startVBRSession,
  type VBRSessionDetailResponse,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", () => ({
  getVBRSession: vi.fn(),
  getVBRProject: vi.fn(),
  createVBRSessionConsent: vi.fn(),
  startVBRSession: vi.fn(),
  uploadVBRSessionChunk: vi.fn(),
  updateVBRSessionTelemetry: vi.fn(),
  finalizeVBRSession: vi.fn(),
}))

function makeSession(overrides: Partial<VBRSessionDetailResponse> = {}): VBRSessionDetailResponse {
  return {
    id: "session-1",
    project_id: "project-1",
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
        session_id: "session-1",
        sort_order: 0,
        question_text: "Walk through how the auth flow works.",
        target_ref: { path: "src/auth.ts" },
        claim_ids: ["claim-aaaaaaaa"],
        asked_at_s: null,
        answered: false,
        created_at: "2026-06-01T00:00:00Z",
      },
      {
        id: "q2",
        session_id: "session-1",
        sort_order: 1,
        question_text: "How is the database schema structured?",
        target_ref: {},
        claim_ids: [],
        asked_at_s: null,
        answered: false,
        created_at: "2026-06-01T00:00:00Z",
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe("VBRSessionRecorder", () => {
  it("renders session status, project title, and the first question", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession())
    vi.mocked(getVBRProject).mockResolvedValue({
      id: "project-1",
      title: "My Capstone Project",
      repo_url: "https://github.com/octocat/Hello-World",
      status: "questions_ready",
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:00:00Z",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.getByText("My Capstone Project")).toBeInTheDocument()
    expect(screen.getByText("Walk through how the auth flow works.")).toBeInTheDocument()
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument()
    expect(screen.getByText("[file: src/auth.ts]")).toBeInTheDocument()
  })

  it("shows a friendly message when the session is not found", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(null)

    render(<VBRSessionRecorder sessionId="missing-session" />)

    await waitFor(() => expect(screen.getByText("Session not found or unavailable.")).toBeInTheDocument())
  })

  it("enables the start button after consent is granted", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession())
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(createVBRSessionConsent).mockResolvedValue({
      id: "consent-1",
      user_id: "user-1",
      kind: "recording",
      granted: true,
      text_version: "recording_v1",
      created_at: "2026-06-01T00:00:00Z",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const startButton = screen.getByRole("button", { name: "Start recording session" })
    expect(startButton).toBeDisabled()

    fireEvent.click(screen.getByRole("button", { name: "I consent to record this session" }))

    await waitFor(() => expect(createVBRSessionConsent).toHaveBeenCalledWith("session-1", "recording_v1"))
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
  })

  it("navigates to the next question and advances the question counter", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession())
    vi.mocked(getVBRProject).mockResolvedValue(null)

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Next" }))

    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument()
    expect(screen.getByText("How is the database schema structured?")).toBeInTheDocument()
    // Telemetry is only sent once the session is recording.
    expect(screen.getByText("Telemetry is only recorded once the session is recording.")).toBeInTheDocument()
  })

  it("calls the start endpoint and updates session status when starting", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession())
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(createVBRSessionConsent).mockResolvedValue({
      id: "consent-1",
      user_id: "user-1",
      kind: "recording",
      granted: true,
      text_version: "recording_v1",
      created_at: "2026-06-01T00:00:00Z",
    })
    vi.mocked(startVBRSession).mockResolvedValue({
      id: "session-1",
      project_id: "project-1",
      attempt_no: 1,
      status: "recording",
      started_at: "2026-06-01T00:00:00Z",
      ended_at: null,
      duration_s: null,
      webcam_present: false,
      chunk_count: 0,
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:00:00Z",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "I consent to record this session" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())

    fireEvent.click(screen.getByRole("button", { name: "Start recording session" }))

    await waitFor(() => expect(startVBRSession).toHaveBeenCalledWith("session-1"))
    await waitFor(() => expect(screen.getByText("Recording in progress")).toBeInTheDocument())
  })
})
