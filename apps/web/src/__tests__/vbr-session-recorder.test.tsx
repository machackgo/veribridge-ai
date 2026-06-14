import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { VBRSessionRecorder } from "../app/student/vbr/sessions/[sessionId]/VBRSessionRecorder"
import {
  cancelVBRSessionRecording,
  createVBRSessionConsent,
  finalizeVBRSession,
  getVBRProject,
  getVBRSession,
  getVBRSessionRecordingReadiness,
  processVBRSession,
  requestVBRChunkUploadUrl,
  startVBRSession,
  transcribeVBRSession,
  uploadVBRChunkBytes,
  uploadVBRSessionChunk,
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

// SHA-256 of 32 zero-filled "fake" chunk bytes used by the digest mock below.
const FAKE_CHUNK_SHA256 = "ab".repeat(32)

function makeBlobLike(size: number) {
  return {
    size,
    type: "video/webm",
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(size)),
  }
}

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
  static shouldThrowOnStart = false

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
    if (MockMediaRecorder.shouldThrowOnStart) {
      throw new Error("Recorder start failed")
    }
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
  MockMediaRecorder.shouldThrowOnStart = false
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

  // jsdom does not implement crypto.subtle — stub a deterministic digest.
  Object.defineProperty(globalThis.crypto, "subtle", {
    value: { digest: vi.fn(async () => new Uint8Array(32).fill(0xab).buffer) },
    configurable: true,
  })

  vi.mocked(requestVBRChunkUploadUrl).mockResolvedValue({
    upload_url: "https://storage.example/upload?token=signed",
    storage_path: "vbr/sessions/session-1/chunks/000.webm",
    chunk_index: 0,
    expires_in: 600,
  })
  vi.mocked(uploadVBRChunkBytes).mockResolvedValue(undefined)

  vi.mocked(getVBRSessionRecordingReadiness).mockResolvedValue({
    ready: true,
    code: null,
    message: "Recording upload storage is ready.",
  })
})

async function startRecordingSession(options?: { onBeforeStart?: () => void }) {
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

  // Allow tests to override the default mocks above before the recording flow runs.
  options?.onBeforeStart?.()

  render(<VBRSessionRecorder sessionId="session-1" />)

  await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

  fireEvent.click(screen.getByRole("button", { name: "I consent to record this session" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())

  fireEvent.click(screen.getByRole("button", { name: "Start recording session" }))
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

  it("starts MediaRecorder via getDisplayMedia/getUserMedia after backend start, and uploads+saves chunk metadata on dataavailable", async () => {
    vi.mocked(uploadVBRSessionChunk).mockResolvedValue({
      id: "chunk-1",
      session_id: "session-1",
      chunk_index: 0,
      bytes: 4096,
      sha256: FAKE_CHUNK_SHA256,
      received_at: "2026-06-01T00:00:01Z",
    })

    await startRecordingSession()

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true }))
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true }))
    await waitFor(() => expect(MockMediaRecorder.instances).toHaveLength(1))

    const recorder = MockMediaRecorder.instances[0]
    await waitFor(() => expect(recorder.state).toBe("recording"))

    await act(async () => {
      recorder.ondataavailable?.({ data: makeBlobLike(4096) })
      await Promise.resolve()
    })

    await waitFor(() =>
      expect(requestVBRChunkUploadUrl).toHaveBeenCalledWith("session-1", {
        chunk_index: 0,
        bytes: 4096,
        sha256: FAKE_CHUNK_SHA256,
      })
    )

    await waitFor(() =>
      expect(uploadVBRChunkBytes).toHaveBeenCalledWith(
        "https://storage.example/upload?token=signed",
        expect.objectContaining({ size: 4096 })
      )
    )

    await waitFor(() =>
      expect(uploadVBRSessionChunk).toHaveBeenCalledWith("session-1", {
        chunk_index: 0,
        storage_path: "vbr/sessions/session-1/chunks/000.webm",
        bytes: 4096,
        sha256: FAKE_CHUNK_SHA256,
      })
    )

    const recordingSection = screen.getByTestId("vbr-browser-recording")
    await waitFor(() => expect(recordingSection.textContent).toContain("4096 bytes"))
    expect(recordingSection.textContent).toContain("Chunks captured: 1")
    expect(recordingSection.textContent).toContain("Saved: 1")
  })

  it("shows a friendly error when requesting a chunk upload URL fails", async () => {
    vi.mocked(requestVBRChunkUploadUrl).mockRejectedValue(new Error("Failed to request an upload URL (HTTP 409)."))

    await startRecordingSession()

    await waitFor(() => expect(MockMediaRecorder.instances).toHaveLength(1))
    const recorder = MockMediaRecorder.instances[0]
    await waitFor(() => expect(recorder.state).toBe("recording"))

    await act(async () => {
      recorder.ondataavailable?.({ data: makeBlobLike(4096) })
      await Promise.resolve()
    })

    await waitFor(() =>
      expect(screen.getByText("Failed to request an upload URL (HTTP 409).")).toBeInTheDocument()
    )

    expect(uploadVBRChunkBytes).not.toHaveBeenCalled()
    expect(uploadVBRSessionChunk).not.toHaveBeenCalled()

    const recordingSection = screen.getByTestId("vbr-browser-recording")
    expect(recordingSection.textContent).toContain("Failed: 1")
  })

  it("finalize waits for a pending chunk upload before calling the finalize endpoint", async () => {
    let resolveUpload: (() => void) | undefined
    vi.mocked(uploadVBRChunkBytes).mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveUpload = () => resolve(undefined)
        })
    )
    vi.mocked(uploadVBRSessionChunk).mockResolvedValue({
      id: "chunk-1",
      session_id: "session-1",
      chunk_index: 0,
      bytes: 2048,
      sha256: FAKE_CHUNK_SHA256,
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
    await waitFor(() => expect(recorder.state).toBe("recording"))

    await act(async () => {
      recorder.ondataavailable?.({ data: makeBlobLike(2048) })
      await Promise.resolve()
    })

    await waitFor(() => expect(uploadVBRChunkBytes).toHaveBeenCalled())

    fireEvent.click(screen.getByRole("button", { name: "Finalize session" }))

    // While the upload is still pending, finalize must not have been called yet.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(finalizeVBRSession).not.toHaveBeenCalled()

    await act(async () => {
      resolveUpload?.()
      await Promise.resolve()
      await Promise.resolve()
    })

    await waitFor(() => expect(uploadVBRSessionChunk).toHaveBeenCalled())
    await waitFor(() => expect(finalizeVBRSession).toHaveBeenCalledWith("session-1", expect.any(Number)))
  })

  it("finalize stops the MediaRecorder, stops media tracks, and calls the finalize endpoint", async () => {
    vi.mocked(uploadVBRSessionChunk).mockResolvedValue({
      id: "chunk-1",
      session_id: "session-1",
      chunk_index: 0,
      bytes: 2048,
      sha256: FAKE_CHUNK_SHA256,
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
    await waitFor(() => expect(recorder.state).toBe("recording"))
    const recordedTracks = recorder.stream.getTracks()

    await act(async () => {
      recorder.ondataavailable?.({ data: makeBlobLike(2048) })
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

    // Recorder construction happens before the backend session is started, so
    // a construction failure must never move the backend session to "recording".
    expect(startVBRSession).not.toHaveBeenCalled()

    const screenStream = (await getDisplayMedia.mock.results[0].value) as MockMediaStream
    const micStream = (await getUserMedia.mock.results[0].value) as MockMediaStream
    screenStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
    micStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
  })

  it("shows a friendly error when screen-share permission is denied and does not start the backend session", async () => {
    getDisplayMedia.mockRejectedValueOnce(new Error("Permission denied"))

    await startRecordingSession()

    await waitFor(() => expect(screen.getByText("Permission denied")).toBeInTheDocument())
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(MockMediaRecorder.instances).toHaveLength(0)
    expect(startVBRSession).not.toHaveBeenCalled()
  })

  it("leaves the session able to retry start after screen-share permission is denied", async () => {
    getDisplayMedia.mockRejectedValueOnce(new Error("Permission denied"))

    await startRecordingSession()

    await waitFor(() => expect(screen.getByText("Permission denied")).toBeInTheDocument())

    // The backend session never moved to "recording", so the start button
    // is enabled again and the status still reads "Not started".
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()
  })

  it("calls the backend start endpoint only after browser media setup succeeds", async () => {
    const callOrder: string[] = []

    await startRecordingSession({
      onBeforeStart: () => {
        getDisplayMedia.mockImplementation(async () => {
          callOrder.push("getDisplayMedia")
          return new MockMediaStream([new MockMediaStreamTrack("video"), new MockMediaStreamTrack("audio")])
        })
        getUserMedia.mockImplementation(async () => {
          callOrder.push("getUserMedia")
          return new MockMediaStream([new MockMediaStreamTrack("audio")])
        })
        vi.mocked(startVBRSession).mockImplementation(async () => {
          callOrder.push("startVBRSession")
          return {
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
          }
        })
      },
    })

    await waitFor(() => expect(callOrder).toContain("startVBRSession"))

    expect(callOrder.indexOf("getDisplayMedia")).toBeLessThan(callOrder.indexOf("startVBRSession"))
    expect(callOrder.indexOf("getUserMedia")).toBeLessThan(callOrder.indexOf("startVBRSession"))
  })

  it("shows a friendly error, leaves the session retryable, and stops acquired tracks when MediaRecorder.start throws", async () => {
    MockMediaRecorder.shouldThrowOnStart = true

    await startRecordingSession()

    await waitFor(() => expect(MockMediaRecorder.instances).toHaveLength(1))
    await waitFor(() => expect(screen.getByText("Recorder start failed")).toBeInTheDocument())

    // recorder.start() throwing must prevent the backend session from moving
    // to "recording" at all.
    expect(startVBRSession).not.toHaveBeenCalled()

    const screenStream = (await getDisplayMedia.mock.results[0].value) as MockMediaStream
    const micStream = (await getUserMedia.mock.results[0].value) as MockMediaStream
    screenStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
    micStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))

    // The backend session never moved to "recording", so the start button
    // is enabled again and the status still reads "Not started".
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()
  })

  it("calls startVBRSession only after MediaRecorder.start succeeds", async () => {
    const callOrder: string[] = []
    const originalStart = MockMediaRecorder.prototype.start
    vi.spyOn(MockMediaRecorder.prototype, "start").mockImplementation(function (this: MockMediaRecorder, ...args: unknown[]) {
      callOrder.push("recorder.start")
      return originalStart.apply(this, args as [])
    })

    await startRecordingSession({
      onBeforeStart: () => {
        vi.mocked(startVBRSession).mockImplementation(async () => {
          callOrder.push("startVBRSession")
          return {
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
          }
        })
      },
    })

    await waitFor(() => expect(callOrder).toContain("startVBRSession"))

    expect(callOrder).toEqual(["recorder.start", "startVBRSession"])
  })

  it("stops acquired browser tracks if the backend start call fails after media setup succeeds", async () => {
    await startRecordingSession({
      onBeforeStart: () => {
        vi.mocked(startVBRSession).mockRejectedValue(new Error("Failed to start session (HTTP 500)."))
      },
    })

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled())
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Failed to start session (HTTP 500).")).toBeInTheDocument())

    // The recorder was started locally (before the backend call), but is
    // stopped again once the backend start fails.
    expect(MockMediaRecorder.instances).toHaveLength(1)
    expect(MockMediaRecorder.instances[0].state).toBe("inactive")

    const screenStream = (await getDisplayMedia.mock.results[0].value) as MockMediaStream
    const micStream = (await getUserMedia.mock.results[0].value) as MockMediaStream
    screenStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))
    micStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))

    // The backend session never moved to "recording", so the start button
    // is enabled again for a retry.
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()
  })

  it("does not request any media permissions or start the session when storage readiness fails", async () => {
    vi.mocked(getVBRSessionRecordingReadiness).mockResolvedValue({
      ready: false,
      code: "vbr_media_bucket_not_configured",
      message: "Recording upload storage is not configured.",
    })

    await startRecordingSession()

    await waitFor(() =>
      expect(screen.getByText(/Recording upload storage is not configured\./)).toBeInTheDocument()
    )

    expect(getDisplayMedia).not.toHaveBeenCalled()
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(startVBRSession).not.toHaveBeenCalled()
    expect(MockMediaRecorder.instances).toHaveLength(0)

    // Clear, retryable blocking message that mentions the manual fallback.
    expect(screen.getByText(/You can still use the manual transcript fallback\./)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()
  })

  it("shows a 'Reset recording session' action when the backend says recording but the browser recorder never started, and resets on click", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "recording", started_at: "2026-06-01T00:00:00Z", chunk_count: 0 })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(cancelVBRSessionRecording).mockResolvedValue({
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
      updated_at: "2026-06-01T00:00:01Z",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    const resetButton = screen.getByRole("button", { name: "Reset recording session" })
    fireEvent.click(resetButton)

    await waitFor(() => expect(cancelVBRSessionRecording).toHaveBeenCalledWith("session-1"))
    await waitFor(() => expect(screen.getByText("Not started")).toBeInTheDocument())
    expect(screen.queryByRole("button", { name: "Reset recording session" })).not.toBeInTheDocument()

    // Session is retryable again — the Start button is still gated on consent
    // (a fresh page load has no consent yet), but the consent flow is available.
    expect(screen.getByRole("button", { name: "Start recording session" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "I consent to record this session" })).not.toBeDisabled()
  })

  it("exits 'Starting…' and shows a retry/fallback message if the screen-share prompt never resolves", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // Simulate a screen-share permission picker that never completes.
      getDisplayMedia.mockImplementation(() => new Promise(() => {}))

      await startRecordingSession()

      await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled())
      await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000)
      })

      await waitFor(() =>
        expect(
          screen.getByText("Screen sharing did not start. Please try again or use the manual transcript fallback.")
        ).toBeInTheDocument()
      )

      // The "Starting…" timer must not be left running — the Cancel button
      // disappears and the start button returns to a retryable state.
      expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
      expect(screen.getByText("Not started")).toBeInTheDocument()

      expect(startVBRSession).not.toHaveBeenCalled()
      expect(MockMediaRecorder.instances).toHaveLength(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it("Cancel during 'Starting…' resets the UI, stops acquired tracks, and does not call startVBRSession", async () => {
    // Simulate a screen-share permission picker that never completes.
    getDisplayMedia.mockImplementation(() => new Promise(() => {}))

    await startRecordingSession()

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument()
    expect(screen.getByText("Not started")).toBeInTheDocument()

    expect(startVBRSession).not.toHaveBeenCalled()
    expect(cancelVBRSessionRecording).not.toHaveBeenCalled()
    expect(MockMediaRecorder.instances).toHaveLength(0)
  })

  it("recovers from 'Starting…' and does not call startVBRSession when getDisplayMedia rejects", async () => {
    getDisplayMedia.mockRejectedValueOnce(new Error("Permission denied"))

    await startRecordingSession()

    await waitFor(() => expect(screen.getByText("Permission denied")).toBeInTheDocument())
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()

    expect(getUserMedia).not.toHaveBeenCalled()
    expect(startVBRSession).not.toHaveBeenCalled()
  })

  it("cleans up screen tracks and does not call startVBRSession when mic acquisition fails after screen is acquired", async () => {
    getUserMedia.mockRejectedValueOnce(new Error("Microphone permission denied"))

    await startRecordingSession()

    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled())
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/Microphone permission denied/)).toBeInTheDocument())

    const screenStream = (await getDisplayMedia.mock.results[0].value) as MockMediaStream
    screenStream.getTracks().forEach((track) => expect(track.stopped).toBe(true))

    expect(MockMediaRecorder.instances).toHaveLength(0)
    expect(startVBRSession).not.toHaveBeenCalled()

    await waitFor(() => expect(screen.getByRole("button", { name: "Start recording session" })).not.toBeDisabled())
    expect(screen.getByText("Not started")).toBeInTheDocument()
  })
})

describe("Transcript generation", () => {
  it("does not show the Transcript section before the session is uploaded", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(makeSession({ status: "created" }))
    vi.mocked(getVBRProject).mockResolvedValue(null)

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-session-status")).toBeInTheDocument())

    expect(screen.queryByTestId("vbr-transcript")).not.toBeInTheDocument()
  })

  it("shows 'Not generated' status and a Generate transcript button after the recording is uploaded", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "uploaded", chunk_count: 1, transcript_status: null })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    const section = screen.getByTestId("vbr-transcript")
    expect(within(section).getByText(/Not generated/)).toBeInTheDocument()
    expect(within(section).getByRole("button", { name: "Generate transcript" })).toBeInTheDocument()
  })

  it("processes then transcribes an uploaded session, and shows the ready status after refresh", async () => {
    vi.mocked(getVBRSession)
      .mockResolvedValueOnce(makeSession({ status: "uploaded", chunk_count: 1, transcript_status: null }))
      .mockResolvedValue(makeSession({ status: "processed", chunk_count: 1, transcript_status: "transcribed" }))
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(processVBRSession).mockResolvedValue({
      session_id: "session-1",
      status: "processed",
      chunk_count: 1,
      total_bytes: 2048,
      full_video_bytes: 2048,
      full_video_sha256: "abc123",
      next_steps: [],
      message: "Media processed.",
    })
    vi.mocked(transcribeVBRSession).mockResolvedValue({
      session_id: "session-1",
      status: "transcribed",
      transcript_id: "transcript-1",
      segment_count: 2,
      duration_s: 20,
      provider: "openai",
      configured: true,
      message: "Transcript generated using openai.",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Generate transcript" }))

    await waitFor(() => expect(processVBRSession).toHaveBeenCalledWith("session-1"))
    await waitFor(() => expect(transcribeVBRSession).toHaveBeenCalledWith("session-1"))
    await waitFor(() => expect(screen.getByText("Transcript generated using openai.")).toBeInTheDocument())

    const section = screen.getByTestId("vbr-transcript")
    await waitFor(() => expect(within(section).getByText(/Ready/)).toBeInTheDocument())
  })

  it("does not call process for a session that is already 'processed'", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "processed", chunk_count: 1, transcript_status: null })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(transcribeVBRSession).mockResolvedValue({
      session_id: "session-1",
      status: "transcribed",
      transcript_id: "transcript-1",
      segment_count: 2,
      duration_s: 20,
      provider: "openai",
      configured: true,
      message: "Transcript generated using openai.",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Generate transcript" }))

    await waitFor(() => expect(transcribeVBRSession).toHaveBeenCalledWith("session-1"))
    expect(processVBRSession).not.toHaveBeenCalled()
  })

  it("shows the manual fallback message when the transcription provider is not configured", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "processed", chunk_count: 1, transcript_status: null })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(transcribeVBRSession).mockResolvedValue({
      session_id: "session-1",
      status: "not_configured",
      transcript_id: null,
      segment_count: 0,
      duration_s: null,
      provider: null,
      configured: false,
      message: "Transcription provider is not configured. Use manual transcript fallback.",
    })

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Generate transcript" }))

    await waitFor(() =>
      expect(
        screen.getByText("Transcription provider is not configured. Use manual transcript fallback.")
      ).toBeInTheDocument()
    )

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/storage_path/i)
    expect(text).not.toMatch(/signed/i)
    expect(text).not.toMatch(/vbr\/sessions/)
  })

  it("shows an error message if transcript generation fails", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "processed", chunk_count: 1, transcript_status: null })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)
    vi.mocked(transcribeVBRSession).mockRejectedValue(new Error("Failed to generate transcript (HTTP 502)."))

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Generate transcript" }))

    await waitFor(() =>
      expect(screen.getByText("Failed to generate transcript (HTTP 502).")).toBeInTheDocument()
    )
  })

  it("shows only the generic safe message on provider/runtime transcription failure", async () => {
    vi.mocked(getVBRSession).mockResolvedValue(
      makeSession({ status: "processed", chunk_count: 1, transcript_status: null })
    )
    vi.mocked(getVBRProject).mockResolvedValue(null)
    // Backend never sends provider/runtime details — only the fixed safe message.
    vi.mocked(transcribeVBRSession).mockRejectedValue(
      new Error("Transcription failed. Please try again later or use the manual transcript fallback.")
    )

    render(<VBRSessionRecorder sessionId="session-1" />)

    await waitFor(() => expect(screen.getByTestId("vbr-transcript")).toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Generate transcript" }))

    await waitFor(() =>
      expect(
        screen.getByText("Transcription failed. Please try again later or use the manual transcript fallback.")
      ).toBeInTheDocument()
    )

    const text = document.body.textContent ?? ""
    expect(text).not.toMatch(/\/Users\//)
    expect(text).not.toMatch(/ffmpeg/i)
    expect(text).not.toMatch(/signed_url/i)
    expect(text).not.toMatch(/storage_path/i)
  })
})
