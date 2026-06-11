import { render, screen, fireEvent, waitFor, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { VBRSessionRecorder } from "../app/student/vbr/sessions/[sessionId]/VBRSessionRecorder"
import {
  createVBRSessionConsent,
  finalizeVBRSession,
  getVBRProject,
  getVBRSession,
  startVBRSession,
  uploadVBRSessionChunk,
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

// ── Browser media mocks ──────────────────────────────────────────────────────

class MockMediaStreamTrack {
  kind: string
  stopped = false
  private listeners: Record<string, Array<() => void>> = {}

  constructor(kind: string) {
    this.kind = kind
  }

  stop() {
    this.stopped = true
  }

  addEventListener(event: string, cb: () => void) {
    ;(this.listeners[event] ??= []).push(cb)
  }

  removeEventListener() {
    // no-op for tests
  }
}

class MockMediaStream {
  private tracks: MockMediaStreamTrack[]

  constructor(tracks: MockMediaStreamTrack[] = []) {
    this.tracks = tracks
  }

  getTracks() {
    return this.tracks
  }

  getVideoTracks() {
    return this.tracks.filter((t) => t.kind === "video")
  }

  getAudioTracks() {
    return this.tracks.filter((t) => t.kind === "audio")
  }
}

class MockMediaRecorder {
  static instances: MockMediaRecorder[] = []
  static isTypeSupported = vi.fn(() => true)
  static shouldThrowOnConstruct = false

  state: "inactive" | "recording" | "paused" = "inactive"
  ondataavailable: ((event: { data: { size: number } }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  stream: MockMediaStream
  options?: Record<string, unknown>
  private listeners: Record<string, Array<() => void>> = {}

  constructor(stream: MockMediaStream, options?: Record<string, unknown>) {
    if (MockMediaRecorder.shouldThrowOnConstruct) {
      throw new Error("Recorder construction failed")
    }
    this.stream = stream
    this.options = options
    MockMediaRecorder.instances.push(this)
  }

  start() {
    this.state = "recording"
  }

  stop() {
    if (this.state === "inactive") return
    this.state = "inactive"
    this.onstop?.()
    ;(this.listeners["stop"] ?? []).forEach((cb) => cb())
  }

  addEventListener(event: string, cb: () => void) {
    ;(this.listeners[event] ??= []).push(cb)
  }

  removeEventListener() {
    // no-op for tests
  }
}

const getDisplayMedia = vi.fn()
const getUserMedia = vi.fn()

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

  MockMediaRecorder.instances = []
  MockMediaRecorder.shouldThrowOnConstruct = false
  MockMediaRecorder.isTypeSupported = vi.fn(() => true)
  ;(globalThis as unknown as { MediaStream: unknown }).MediaStream = MockMediaStream
  ;(globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = MockMediaRecorder

  getDisplayMedia.mockReset()
  getUserMedia.mockReset()
  getDisplayMedia.mockResolvedValue(
    new MockMediaStream([new MockMediaStreamTrack("video"), new MockMediaStreamTrack("audio")])
  )
  getUserMedia.mockResolvedValue(new MockMediaStream([new MockMediaStreamTrack("audio")]))

  Object.defineProperty(navigator, "mediaDevices", {
    value: { getDisplayMedia, getUserMedia },
    configurable: true,
    writable: true,
  })
})

async function startRecordingSession() {
  const createdSession = makeSession({ status: "created" })
  const recordingSession = makeSession({ status: "recording", started_at: "2026-06-01T00:00:00Z", chunk_count: 1 })

  // First load returns the not-yet-started session; subsequent refreshes (after
  // chunk saves) return the in-progress session so the recording UI stays enabled.
  vi.mocked(getVBRSession).mockResolvedValueOnce(createdSession).mockResolvedValue(recordingSession)
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
}

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

  it("starts MediaRecorder via getDisplayMedia/getUserMedia after backend start, and saves chunk metadata on dataavailable", async () => {
    vi.mocked(uploadVBRSessionChunk).mockResolvedValue({
      id: "chunk-1",
      session_id: "session-1",
      chunk_index: 0,
      bytes: 4096,
      sha256: "0".repeat(64),
      received_at: "2026-06-01T00:00:01Z",
    })

    await startRecordingSession()

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true }))
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true }))
    await waitFor(() => expect(MockMediaRecorder.instances).toHaveLength(1))

    const recorder = MockMediaRecorder.instances[0]
    expect(recorder.state).toBe("recording")

    await act(async () => {
      recorder.ondataavailable?.({ data: { size: 4096 } })
      await Promise.resolve()
    })

    await waitFor(() =>
      expect(uploadVBRSessionChunk).toHaveBeenCalledWith("session-1", {
        chunk_index: 0,
        storage_path: "vbr/sessions/session-1/chunks/000.webm",
        bytes: 4096,
        sha256: "0".repeat(64),
      })
    )

    const recordingSection = screen.getByTestId("vbr-browser-recording")
    await waitFor(() => expect(recordingSection.textContent).toContain("4096 bytes"))
    expect(recordingSection.textContent).toContain("Chunks captured: 1")
  })

  it("finalize stops the MediaRecorder, stops media tracks, and calls the finalize endpoint", async () => {
    vi.mocked(uploadVBRSessionChunk).mockResolvedValue({
      id: "chunk-1",
      session_id: "session-1",
      chunk_index: 0,
      bytes: 2048,
      sha256: "0".repeat(64),
      received_at: "2026-06-01T00:00:01Z",
    })
    vi.mocked(finalizeVBRSession).mockResolvedValue({
      id: "session-1",
      project_id: "project-1",
      attempt_no: 1,
      status: "uploaded",
      started_at: "2026-06-01T00:00:00Z",
      ended_at: "2026-06-01T00:05:00Z",
      duration_s: 300,
      webcam_present: false,
      chunk_count: 1,
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:05:00Z",
    })

    await startRecordingSession()

    await waitFor(() => expect(MockMediaRecorder.instances).toHaveLength(1))
    const recorder = MockMediaRecorder.instances[0]
    const recordedTracks = recorder.stream.getTracks()

    await act(async () => {
      recorder.ondataavailable?.({ data: { size: 2048 } })
      await Promise.resolve()
    })

    await waitFor(() => expect(uploadVBRSessionChunk).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByRole("button", { name: "Finalize session" })).not.toBeDisabled())

    fireEvent.click(screen.getByRole("button", { name: "Finalize session" }))

    await waitFor(() => expect(finalizeVBRSession).toHaveBeenCalledWith("session-1", expect.any(Number)))
    await waitFor(() => expect(screen.getByText("Session finalized and marked as uploaded.")).toBeInTheDocument())

    expect(recorder.state).toBe("inactive")
    recordedTracks.forEach((track) => expect(track.stopped).toBe(true))
  })

  it("shows a friendly error and stops acquired tracks when the recorder fails to start", async () => {
    MockMediaRecorder.shouldThrowOnConstruct = true

    await startRecordingSession()

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled())
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Recorder construction failed")).toBeInTheDocument())

    expect(MockMediaRecorder.instances).toHaveLength(0)

    const screenStream = (await getDisplayMedia.mock.results[0].value) as MockMediaStream
    const micStream = (await getUserMedia.mock.results[0].value) as MockMediaStream
    screenStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
    micStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
  })

  it("shows a friendly error when screen-share permission is denied", async () => {
    getDisplayMedia.mockRejectedValueOnce(new Error("Permission denied"))

    await startRecordingSession()

    await waitFor(() => expect(screen.getByText("Permission denied")).toBeInTheDocument())
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(MockMediaRecorder.instances).toHaveLength(0)
  })
})
