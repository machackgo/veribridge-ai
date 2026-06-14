"use client"

import { useEffect, useRef, useState, type CSSProperties } from "react"
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
  updateVBRSessionTelemetry,
  uploadVBRChunkBytes,
  uploadVBRSessionChunk,
  type VBRProjectResponse,
  type VBRSessionDetailResponse,
} from "@/lib/vbr-api"

type PreflightStatus = "idle" | "testing" | "granted" | "denied"
type PreflightKey = "microphone" | "camera" | "screen"

export type VBRSessionRecorderVariant = "walkthrough" | "project_defense"

const STATUS_LABELS: Record<string, string> = {
  created: "Not started",
  recording: "Recording in progress",
  uploaded: "Uploaded",
}

type BrowserRecordingState = "inactive" | "recording" | "stopping" | "stopped"

const BROWSER_RECORDING_LABELS: Record<BrowserRecordingState, string> = {
  inactive: "Browser recording inactive",
  recording: "Browser recording active",
  stopping: "Stopping…",
  stopped: "Browser recording stopped",
}

const TRANSCRIPT_STATUS_LABELS: Record<string, string> = {
  not_generated: "Not generated",
  not_configured: "Provider not configured",
  transcribed: "Ready",
  failed: "Generation failed",
}

// Preferred MediaRecorder mimeTypes, in order of preference. Browsers vary in
// codec support, so we pick the first one the browser reports as supported.
const RECORDER_MIME_TYPES = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]

// If the browser's screen-share/mic permission flow hasn't resolved within
// this window, exit the "Starting…" state instead of hanging forever.
const START_TIMEOUT_MS = 30_000

const START_TIMEOUT_MESSAGE =
  "Screen sharing did not start. Please try again or use the manual transcript fallback."

function pickRecorderMimeType(): string | undefined {
  const Recorder = typeof window !== "undefined" ? window.MediaRecorder : undefined
  if (!Recorder || typeof Recorder.isTypeSupported !== "function") return undefined
  return RECORDER_MIME_TYPES.find((type) => Recorder.isTypeSupported(type))
}

type ChunkUploadState = "queued" | "uploading" | "saved" | "failed"

async function calculateSha256(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const digest = await crypto.subtle.digest("SHA-256", buffer)
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")
}

function formatDuration(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const m = Math.floor(safe / 60)
  const s = safe % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

function describeTargetRef(targetRef: Record<string, unknown>): string | null {
  if (!targetRef || typeof targetRef !== "object") return null
  if (typeof targetRef.path === "string") return `file: ${targetRef.path}`
  if (typeof targetRef.commit === "string") return `commit: ${targetRef.commit.slice(0, 7)}`
  if (typeof targetRef.url === "string") return `url: ${targetRef.url}`
  return null
}

type AttachedProofsSummary = {
  github_proof?: { repo_url?: string; repo_owner?: string; repo_name?: string; status?: string }
  documents?: Array<{ title?: string }>
  website_proofs?: Array<{ target_website?: string; workflow_confidence?: string }>
}

/** Read the safe attached-proofs summary from a Project Defense project's metadata. */
function getAttachedProofs(project: VBRProjectResponse | null): AttachedProofsSummary {
  const metadata = project?.metadata as { attached_proofs?: AttachedProofsSummary } | undefined
  return metadata?.attached_proofs ?? {}
}

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 16,
}

const sectionTitleStyle: CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: "var(--ink)",
  marginBottom: 8,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
}

const buttonStyle: CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
}

const primaryButtonStyle: CSSProperties = {
  ...buttonStyle,
  background: "var(--indigo)",
  color: "#fff",
}

const disabledButtonStyle: CSSProperties = {
  ...buttonStyle,
  opacity: 0.5,
  cursor: "not-allowed",
}

const chipStyle: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink-2)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
}

const PREFLIGHT_LABELS: Record<VBRSessionRecorderVariant, Record<PreflightKey, string>> = {
  walkthrough: {
    microphone: "Test microphone permission",
    camera: "Test camera permission",
    screen: "Test screen share permission",
  },
  project_defense: {
    microphone: "Test microphone permission",
    camera: "Test camera permission (optional)",
    screen: "Test screen share permission",
  },
}

// Which preflight checks are shown per variant. Project Defense Phase 2A
// recording does not include the camera, so its preflight check is hidden.
const PREFLIGHT_KEYS: Record<VBRSessionRecorderVariant, PreflightKey[]> = {
  walkthrough: ["microphone", "camera", "screen"],
  project_defense: ["microphone", "screen"],
}

const PREFLIGHT_NOTE: Record<VBRSessionRecorderVariant, string | null> = {
  walkthrough: null,
  project_defense: "Camera is optional and not included in this Phase 2A recording.",
}

const HEADER_COPY: Record<VBRSessionRecorderVariant, { title: string; subtitle: string | null }> = {
  walkthrough: {
    title: "Verified Build Report — Recording session",
    subtitle: null,
  },
  project_defense: {
    title: "Project Defense Recording",
    subtitle: "Record your screen and microphone while answering your defense questions.",
  },
}

const CONSENT_COPY: Record<VBRSessionRecorderVariant, string> = {
  walkthrough:
    "Talk like you are showing a teammate. This session can record your screen, microphone, and optionally your webcam.",
  project_defense:
    "This session records your screen and microphone while you answer your defense questions. Camera is optional — it is not required. This recording is protected evidence for your Skill Graph.",
}

export function VBRSessionRecorder({
  sessionId,
  variant = "walkthrough",
}: {
  sessionId: string
  variant?: VBRSessionRecorderVariant
}) {
  const [session, setSession] = useState<VBRSessionDetailResponse | null>(null)
  const [project, setProject] = useState<VBRProjectResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [consentGranted, setConsentGranted] = useState(false)
  const [consentLoading, setConsentLoading] = useState(false)
  const [consentError, setConsentError] = useState<string | null>(null)

  const [startLoading, setStartLoading] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [readinessError, setReadinessError] = useState<string | null>(null)

  const [resetLoading, setResetLoading] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)

  const [finalizeLoading, setFinalizeLoading] = useState(false)
  const [finalizeError, setFinalizeError] = useState<string | null>(null)
  const [finalizeMessage, setFinalizeMessage] = useState<string | null>(null)

  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)
  const [transcriptMessage, setTranscriptMessage] = useState<string | null>(null)


  const [telemetryStatus, setTelemetryStatus] = useState<string | null>(null)
  const [telemetryError, setTelemetryError] = useState<string | null>(null)

  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)

  const [browserSupport, setBrowserSupport] = useState<{ mediaDevices: boolean; mediaRecorder: boolean } | null>(null)
  const [preflight, setPreflight] = useState<Record<PreflightKey, { status: PreflightStatus; error: string | null }>>({
    microphone: { status: "idle", error: null },
    camera: { status: "idle", error: null },
    screen: { status: "idle", error: null },
  })

  const [elapsedS, setElapsedS] = useState(0)

  const [recordingState, setRecordingState] = useState<BrowserRecordingState>("inactive")
  const [recordingError, setRecordingError] = useState<string | null>(null)
  const [recordedChunkCount, setRecordedChunkCount] = useState(0)
  const [lastChunkBytes, setLastChunkBytes] = useState<number | null>(null)
  const [chunkUploadCounts, setChunkUploadCounts] = useState({ queued: 0, uploading: 0, saved: 0, failed: 0 })
  const [lastUploadError, setLastUploadError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const screenStreamRef = useRef<MediaStream | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const combinedStreamRef = useRef<MediaStream | null>(null)
  const chunkIndexRef = useRef(0)
  const recordedChunkCountRef = useRef(0)
  const chunkQueueRef = useRef<Promise<void>>(Promise.resolve())
  const chunkUploadStatesRef = useRef<Map<number, ChunkUploadState>>(new Map())

  // Tracks the in-flight "Starting…" attempt so a late-resolving permission
  // prompt (after a timeout or Cancel) can be detected and torn down.
  const startGenerationRef = useRef(0)
  const startTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Browser support is only known on the client — compute after mount to avoid hydration mismatch.
  useEffect(() => {
    setBrowserSupport({
      mediaDevices: typeof navigator !== "undefined" && !!navigator.mediaDevices,
      mediaRecorder: typeof window !== "undefined" && typeof window.MediaRecorder !== "undefined",
    })
  }, [])

  // Make sure recording never keeps running after the component unmounts (e.g. navigation).
  useEffect(() => {
    return () => {
      startGenerationRef.current += 1
      if (startTimeoutRef.current) {
        clearTimeout(startTimeoutRef.current)
        startTimeoutRef.current = null
      }
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== "inactive") {
        recorder.stop()
      }
      stopAllStreams()
    }
  }, [])

  useEffect(() => {
    let active = true

    async function load() {
      setLoading(true)
      setLoadError(null)
      setNotFound(false)
      try {
        const sessionData = await getVBRSession(sessionId)
        if (!active) return
        if (!sessionData) {
          setNotFound(true)
          return
        }
        setSession(sessionData)
        try {
          const projectData = await getVBRProject(sessionData.project_id)
          if (active) setProject(projectData)
        } catch {
          // Project title is a nice-to-have — don't fail the whole page if it can't load.
        }
      } catch (err) {
        if (active) setLoadError(err instanceof Error ? err.message : "Failed to load session.")
      } finally {
        if (active) setLoading(false)
      }
    }

    load()
    return () => {
      active = false
    }
  }, [sessionId])

  useEffect(() => {
    if (session?.status !== "recording" || !session.started_at) {
      setElapsedS(session?.duration_s ?? 0)
      return
    }
    const startedAtMs = new Date(session.started_at).getTime()
    const tick = () => setElapsedS(Math.floor((Date.now() - startedAtMs) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [session?.status, session?.started_at, session?.duration_s])

  async function refreshSession() {
    try {
      const updated = await getVBRSession(sessionId)
      if (updated) setSession(updated)
    } catch {
      // Keep showing the last known state if a background refresh fails.
    }
  }

  function stopAllStreams() {
    for (const ref of [screenStreamRef, micStreamRef, cameraStreamRef]) {
      ref.current?.getTracks().forEach((track) => track.stop())
      ref.current = null
    }
    combinedStreamRef.current = null
  }

  function clearStartTimeout() {
    if (startTimeoutRef.current) {
      clearTimeout(startTimeoutRef.current)
      startTimeoutRef.current = null
    }
  }

  /**
   * Exit the "Starting…" state: invalidate the in-flight attempt (so a
   * late-resolving permission prompt is discarded), stop any acquired media
   * tracks and recorder, and show the given message (or clear it for Cancel).
   */
  function abortStart(message: string | null) {
    startGenerationRef.current += 1
    clearStartTimeout()

    const recorder = mediaRecorderRef.current
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onerror = null
      recorder.onstop = null
      if (recorder.state !== "inactive") {
        recorder.stop()
      }
      mediaRecorderRef.current = null
    }
    stopAllStreams()

    setRecordingState("inactive")
    setStartLoading(false)
    setRecordingError(message)
  }

  function handleCancelStart() {
    abortStart(null)
    setStartError(null)
    setReadinessError(null)
  }

  function setChunkUploadState(chunkIndex: number, state: ChunkUploadState) {
    chunkUploadStatesRef.current.set(chunkIndex, state)
    const counts = { queued: 0, uploading: 0, saved: 0, failed: 0 }
    for (const value of chunkUploadStatesRef.current.values()) counts[value] += 1
    setChunkUploadCounts(counts)
  }

  async function uploadAndSaveChunk(chunkIndex: number, blob: Blob) {
    setChunkUploadState(chunkIndex, "queued")
    try {
      const sha256 = await calculateSha256(blob)

      setChunkUploadState(chunkIndex, "uploading")
      const target = await requestVBRChunkUploadUrl(sessionId, {
        chunk_index: chunkIndex,
        bytes: blob.size,
        sha256,
      })

      await uploadVBRChunkBytes(target.upload_url, blob)

      const chunk = await uploadVBRSessionChunk(sessionId, {
        chunk_index: chunkIndex,
        storage_path: target.storage_path,
        bytes: blob.size,
        sha256,
      })

      setChunkUploadState(chunkIndex, "saved")
      recordedChunkCountRef.current += 1
      setRecordedChunkCount(recordedChunkCountRef.current)
      setLastChunkBytes(chunk.bytes ?? blob.size)
      await refreshSession()
    } catch (err) {
      setChunkUploadState(chunkIndex, "failed")
      const message = err instanceof Error ? err.message : "Failed to upload recording chunk."
      setLastUploadError(message)
    }
  }

  async function stopBrowserRecording() {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === "inactive") {
      stopAllStreams()
      setRecordingState((prev) => (prev === "recording" || prev === "stopping" ? "stopped" : prev))
      return
    }

    setRecordingState("stopping")
    await new Promise<void>((resolve) => {
      recorder.addEventListener("stop", () => resolve(), { once: true })
      recorder.stop()
    })

    await chunkQueueRef.current
  }

  async function handleConsent() {
    setConsentLoading(true)
    setConsentError(null)
    try {
      await createVBRSessionConsent(sessionId, "recording_v1")
      setConsentGranted(true)
    } catch (err) {
      setConsentError(err instanceof Error ? err.message : "Failed to record consent.")
    } finally {
      setConsentLoading(false)
    }
  }

  async function handleStart() {
    setStartLoading(true)
    setStartError(null)
    setRecordingError(null)
    setReadinessError(null)

    // Guard against the browser's permission flow hanging forever (e.g. the
    // screen-share picker never resolves under browser automation). If this
    // attempt is still in "Starting…" when the timer fires, exit cleanly.
    const myGeneration = ++startGenerationRef.current
    clearStartTimeout()
    startTimeoutRef.current = setTimeout(() => {
      abortStart(START_TIMEOUT_MESSAGE)
    }, START_TIMEOUT_MS)

    try {
      if (
        typeof navigator === "undefined" ||
        !navigator.mediaDevices ||
        typeof window === "undefined" ||
        typeof window.MediaRecorder === "undefined"
      ) {
        setRecordingError("This browser does not support browser-based recording.")
        return
      }

      // Check that recording upload storage is ready before requesting any
      // media permissions — if it isn't, never call getDisplayMedia,
      // getUserMedia, or startVBRSession.
      try {
        const readiness = await getVBRSessionRecordingReadiness(sessionId)
        if (startGenerationRef.current !== myGeneration) return
        if (!readiness.ready) {
          setReadinessError(
            `${readiness.message} You can still use the manual transcript fallback.`
          )
          return
        }
      } catch (err) {
        if (startGenerationRef.current !== myGeneration) return
        setReadinessError(
          err instanceof Error
            ? `${err.message} You can still use the manual transcript fallback.`
            : "Recording upload storage is not configured. You can still use the manual transcript fallback."
        )
        return
      }

      // Acquire browser media and construct the recorder before touching the
      // backend session — if permissions are denied here, the backend session
      // must stay in "created" so the user can retry.
      let screenStream: MediaStream
      try {
        screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true })
      } catch (err) {
        if (startGenerationRef.current !== myGeneration) return
        setRecordingError(err instanceof Error ? err.message : "Screen share permission was denied.")
        return
      }
      if (startGenerationRef.current !== myGeneration) {
        // Cancelled or timed out while waiting on the screen-share prompt —
        // stop the stream that just arrived and discard it.
        screenStream.getTracks().forEach((track) => track.stop())
        return
      }
      screenStreamRef.current = screenStream

      let micStream: MediaStream
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (err) {
        // Mic permission failed after the screen was already acquired — clean
        // up the screen stream too and leave the session retryable.
        stopAllStreams()
        if (startGenerationRef.current !== myGeneration) return
        setRecordingError(
          err instanceof Error
            ? `${err.message} Please try again or use the manual transcript fallback.`
            : "Microphone permission was denied. Please try again or use the manual transcript fallback."
        )
        return
      }
      if (startGenerationRef.current !== myGeneration) {
        micStream.getTracks().forEach((track) => track.stop())
        stopAllStreams()
        return
      }
      micStreamRef.current = micStream

      // Both permission prompts have resolved — the rest of the setup is
      // synchronous/fast, so the "Starting…" timeout no longer applies.
      clearStartTimeout()

      // TODO(T4D): optional webcam capture/PiP is not implemented in T4C.

      let recorder: MediaRecorder
      try {
        const tracks: MediaStreamTrack[] = [...screenStream.getVideoTracks()]
        const audioTrack = micStream.getAudioTracks()[0] ?? screenStream.getAudioTracks()[0]
        if (audioTrack) tracks.push(audioTrack)

        const combinedStream = new MediaStream(tracks)
        combinedStreamRef.current = combinedStream

        const mimeType = pickRecorderMimeType()
        recorder = mimeType ? new MediaRecorder(combinedStream, { mimeType }) : new MediaRecorder(combinedStream)
      } catch (err) {
        setRecordingError(err instanceof Error ? err.message : "Failed to start browser recording.")
        stopAllStreams()
        return
      }

      chunkIndexRef.current = 0
      recordedChunkCountRef.current = 0
      chunkQueueRef.current = Promise.resolve()
      chunkUploadStatesRef.current = new Map()
      setRecordedChunkCount(0)
      setLastChunkBytes(null)
      setChunkUploadCounts({ queued: 0, uploading: 0, saved: 0, failed: 0 })
      setLastUploadError(null)

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          const chunkIndex = chunkIndexRef.current
          chunkIndexRef.current += 1
          const blob = event.data
          chunkQueueRef.current = chunkQueueRef.current.then(() => uploadAndSaveChunk(chunkIndex, blob))
        }
      }

      recorder.onerror = () => {
        setRecordingError("Browser recording stopped due to an error.")
        stopAllStreams()
        mediaRecorderRef.current = null
        setRecordingState("stopped")
      }

      recorder.onstop = () => {
        stopAllStreams()
        mediaRecorderRef.current = null
        setRecordingState("stopped")
      }

      // If the user stops sharing via the browser's own UI, stop the recorder too.
      screenStream.getVideoTracks()[0]?.addEventListener("ended", () => {
        if (mediaRecorderRef.current?.state === "recording") {
          mediaRecorderRef.current.stop()
        }
      })

      // Start the local recorder before touching the backend — if this throws,
      // the backend session must stay in "created" so the user can retry.
      mediaRecorderRef.current = recorder
      try {
        recorder.start(10_000)
      } catch (err) {
        setRecordingError(err instanceof Error ? err.message : "Failed to start browser recording.")
        mediaRecorderRef.current = null
        stopAllStreams()
        return
      }
      setRecordingState("recording")

      // Browser recording is live — now move the backend session to "recording".
      let updated
      try {
        updated = await startVBRSession(sessionId)
      } catch (err) {
        setStartError(err instanceof Error ? err.message : "Failed to start session.")
        // Backend never moved to "recording" — tear down the local recorder so
        // the session stays retryable from "created".
        recorder.ondataavailable = null
        recorder.onerror = null
        recorder.onstop = null
        if (recorder.state !== "inactive") {
          recorder.stop()
        }
        mediaRecorderRef.current = null
        stopAllStreams()
        setRecordingState("inactive")
        return
      }
      setSession((prev) => (prev ? { ...prev, ...updated } : prev))
    } finally {
      clearStartTimeout()
      setStartLoading(false)
    }
  }

  async function handleFinalize() {
    setFinalizeLoading(true)
    setFinalizeError(null)
    setFinalizeMessage(null)

    try {
      if (recordingState === "recording" || recordingState === "stopping") {
        await stopBrowserRecording()
      }

      // Wait for any chunk uploads still in flight before finalizing.
      await chunkQueueRef.current

      if (recordedChunkCountRef.current === 0 && (session?.chunk_count ?? 0) === 0) {
        setFinalizeMessage("No recording chunks captured yet.")
        return
      }

      const updated = await finalizeVBRSession(sessionId, elapsedS)
      setSession((prev) => (prev ? { ...prev, ...updated } : prev))
      setFinalizeMessage("Session finalized and marked as uploaded.")
    } catch (err) {
      setFinalizeError(err instanceof Error ? err.message : "Failed to finalize session.")
    } finally {
      setFinalizeLoading(false)
    }
  }


  async function handleGenerateTranscript() {
    setTranscriptLoading(true)
    setTranscriptError(null)
    setTranscriptMessage(null)
    try {
      if (session?.status === "uploaded") {
        await processVBRSession(sessionId)
      }
      const result = await transcribeVBRSession(sessionId)
      setTranscriptMessage(result.message)
    } catch (err) {
      setTranscriptError(err instanceof Error ? err.message : "Failed to generate transcript.")
    } finally {
      setTranscriptLoading(false)
      await refreshSession()
    }
  }

  async function handleResetRecording() {
    setResetLoading(true)
    setResetError(null)
    try {
      const updated = await cancelVBRSessionRecording(sessionId)
      setSession((prev) => (prev ? { ...prev, ...updated } : prev))
      setRecordingState("inactive")
      setRecordingError(null)
      setReadinessError(null)
      setStartError(null)
    } catch (err) {
      setResetError(err instanceof Error ? err.message : "Failed to reset the recording session.")
    } finally {
      setResetLoading(false)
    }
  }

  async function goToQuestion(index: number) {
    if (!session) return
    const clamped = Math.max(0, Math.min(session.questions.length - 1, index))
    if (clamped === currentQuestionIndex) return
    setCurrentQuestionIndex(clamped)

    const question = session.questions[clamped]
    if (!question || session.status !== "recording") return

    setTelemetryError(null)
    setTelemetryStatus("Sending telemetry…")
    try {
      await updateVBRSessionTelemetry(sessionId, {
        events: [{ type: "question_viewed", question_id: question.id, ts: Date.now() }],
        current_question_id: question.id,
      })
      setTelemetryStatus(`Recorded question_viewed for question ${clamped + 1}.`)
    } catch (err) {
      setTelemetryStatus(null)
      setTelemetryError(err instanceof Error ? err.message : "Failed to record telemetry.")
    }
  }

  async function runPreflightCheck(key: PreflightKey) {
    setPreflight((prev) => ({ ...prev, [key]: { status: "testing", error: null } }))
    try {
      if (typeof navigator === "undefined" || !navigator.mediaDevices) {
        throw new Error("This browser does not support media device access.")
      }

      let stream: MediaStream
      if (key === "screen") {
        stream = await navigator.mediaDevices.getDisplayMedia({ video: true })
      } else if (key === "camera") {
        stream = await navigator.mediaDevices.getUserMedia({ video: true })
      } else {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      }
      // Stop tracks immediately — this is a permission probe, not a real recording.
      stream.getTracks().forEach((track) => track.stop())
      setPreflight((prev) => ({ ...prev, [key]: { status: "granted", error: null } }))
    } catch (err) {
      setPreflight((prev) => ({
        ...prev,
        [key]: { status: "denied", error: err instanceof Error ? err.message : "Permission denied." },
      }))
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 24, fontFamily: "var(--font-sans)" }}>
        <p style={{ color: "var(--muted)" }}>Loading session…</p>
      </div>
    )
  }

  if (notFound) {
    return (
      <div style={{ padding: 24, fontFamily: "var(--font-sans)" }}>
        <div style={cardStyle}>
          <p style={{ color: "var(--ink)", fontWeight: 600, margin: 0 }}>Session not found or unavailable.</p>
        </div>
      </div>
    )
  }

  if (loadError || !session) {
    return (
      <div style={{ padding: 24, fontFamily: "var(--font-sans)" }}>
        <div style={cardStyle}>
          <p style={{ color: "var(--rose)", fontWeight: 600, margin: 0 }}>
            {loadError ?? "Something went wrong loading this session."}
          </p>
        </div>
      </div>
    )
  }

  const currentQuestion = session.questions[currentQuestionIndex] ?? null
  const isRecording = session.status === "recording"
  const canStart = consentGranted && session.status === "created" && !startLoading
  const headerCopy = HEADER_COPY[variant]
  const preflightLabels = PREFLIGHT_LABELS[variant]
  const preflightKeys = PREFLIGHT_KEYS[variant]
  const preflightNote = PREFLIGHT_NOTE[variant]

  // The backend session can be left in "recording" with zero uploaded chunks
  // if the browser recorder never started/stayed running (e.g. a storage
  // preflight failure after /start, or a stale session from a previous tab).
  // Offer a recovery action to reset it back to "created".
  const showResetRecording =
    isRecording &&
    recordingState !== "recording" &&
    recordingState !== "stopping" &&
    session.chunk_count === 0 &&
    recordedChunkCount === 0

  return (
    <div style={{ padding: 24, maxWidth: 760, margin: "0 auto", fontFamily: "var(--font-sans)", display: "grid", gap: 16 }}>
      <header>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--ink)", margin: 0 }}>
          {headerCopy.title}
        </h1>
        {variant === "walkthrough" && project?.title && (
          <p style={{ color: "var(--muted)", marginTop: 4 }}>{project.title}</p>
        )}
        {headerCopy.subtitle && <p style={{ color: "var(--muted)", marginTop: 4 }}>{headerCopy.subtitle}</p>}
      </header>

      {variant === "project_defense" && (
        <section style={cardStyle} data-testid="project-defense-context">
          <div style={sectionTitleStyle}>Project context</div>
          {project ? (
            (() => {
              const attached = getAttachedProofs(project)
              const repoLabel = attached.github_proof?.repo_url
                ? `${attached.github_proof.repo_owner ?? ""}/${attached.github_proof.repo_name ?? ""}`.replace(/^\/|\/$/g, "") +
                  (attached.github_proof.status ? ` (${attached.github_proof.status})` : "")
                : project.repo_full_name || project.repo_url || "Repository URL only — no attached GitHub Proof"
              const documentCount = attached.documents?.length ?? 0
              const websiteProofCount = attached.website_proofs?.length ?? 0
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, color: "var(--ink)" }}>
                  <div><strong>Project:</strong> {project.title}</div>
                  <div><strong>Repository:</strong> {repoLabel}</div>
                  <div><strong>Documents:</strong> {documentCount > 0 ? `${documentCount} attached` : "none attached"}</div>
                  <div><strong>Website Proof:</strong> {websiteProofCount > 0 ? `${websiteProofCount} attached` : "none attached"}</div>
                  <div><strong>Defense questions:</strong> {session.questions.length}</div>
                </div>
              )
            })()
          ) : (
            <p style={{ fontSize: 12, color: "var(--muted)", margin: 0 }}>Project details unavailable.</p>
          )}
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8, marginBottom: 0 }}>
            Phase 2A records screen + microphone. Camera is not included yet.
          </p>
        </section>
      )}

      <section style={cardStyle} data-testid="vbr-session-status">
        <div style={sectionTitleStyle}>Session status</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 13, color: "var(--ink)" }}>
          <div><strong>Status:</strong> {STATUS_LABELS[session.status] ?? session.status}</div>
          <div><strong>Attempt:</strong> {session.attempt_no}</div>
          <div><strong>Chunks recorded:</strong> {session.chunk_count}</div>
          <div style={{ fontFamily: "var(--font-mono)" }}><strong>Timer:</strong> {formatDuration(elapsedS)}</div>
        </div>
      </section>

      <section style={cardStyle}>
        <div style={sectionTitleStyle}>Consent</div>
        <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 0 }}>
          {CONSENT_COPY[variant]}
        </p>
        <button
          type="button"
          style={consentGranted ? disabledButtonStyle : primaryButtonStyle}
          disabled={consentGranted || consentLoading}
          onClick={handleConsent}
        >
          {consentGranted ? "Consent recorded" : consentLoading ? "Recording consent…" : "I consent to record this session"}
        </button>
        {consentError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{consentError}</p>}
      </section>

      <section style={cardStyle}>
        <div style={sectionTitleStyle}>Browser preflight</div>
        {browserSupport && (
          <div style={{ fontSize: 13, color: "var(--ink)", marginBottom: 12, display: "grid", gap: 4 }}>
            <div>{browserSupport.mediaDevices ? "✓" : "✗"} navigator.mediaDevices supported</div>
            <div>{browserSupport.mediaRecorder ? "✓" : "✗"} MediaRecorder supported</div>
          </div>
        )}
        {preflightNote && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 0, marginBottom: 12 }}>{preflightNote}</p>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
          {preflightKeys.map((key) => {
            const state = preflight[key]
            return (
              <div key={key} style={{ display: "grid", gap: 4 }}>
                <button
                  type="button"
                  style={buttonStyle}
                  onClick={() => runPreflightCheck(key)}
                  disabled={state.status === "testing"}
                >
                  {preflightLabels[key]}
                </button>
                {state.status === "testing" && <span style={{ fontSize: 12, color: "var(--muted)" }}>Testing…</span>}
                {state.status === "granted" && <span style={{ fontSize: 12, color: "var(--emerald)" }}>✓ Granted</span>}
                {state.status === "denied" && (
                  <span style={{ fontSize: 12, color: "var(--rose)" }}>✗ {state.error ?? "Denied"}</span>
                )}
              </div>
            )
          })}
        </div>
      </section>

      <section style={cardStyle}>
        <div style={sectionTitleStyle}>Start recording</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" style={canStart ? primaryButtonStyle : disabledButtonStyle} disabled={!canStart} onClick={handleStart}>
            {startLoading ? "Starting…" : isRecording ? "Recording started" : "Start recording session"}
          </button>
          {startLoading && (
            <button type="button" style={buttonStyle} onClick={handleCancelStart}>
              Cancel
            </button>
          )}
        </div>
        {!consentGranted && session.status === "created" && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>Give consent above to enable this.</p>
        )}
        {startError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{startError}</p>}
        {readinessError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{readinessError}</p>}

        {showResetRecording && (
          <div style={{ marginTop: 12 }}>
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 0, marginBottom: 8 }}>
              This session shows recording in progress, but no recording is active in this browser.
            </p>
            <button
              type="button"
              style={resetLoading ? disabledButtonStyle : buttonStyle}
              disabled={resetLoading}
              onClick={handleResetRecording}
            >
              {resetLoading ? "Resetting…" : "Reset recording session"}
            </button>
            {resetError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{resetError}</p>}
          </div>
        )}
      </section>

      {(isRecording || recordingState !== "inactive" || recordingError) && (
        <section style={cardStyle} data-testid="vbr-browser-recording">
          <div style={sectionTitleStyle}>Browser recording</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 13, color: "var(--ink)" }}>
            <div><strong>Status:</strong> {BROWSER_RECORDING_LABELS[recordingState]}</div>
            <div><strong>Chunks captured:</strong> {recordedChunkCount}</div>
            <div><strong>Last chunk size:</strong> {lastChunkBytes !== null ? `${lastChunkBytes} bytes` : "—"}</div>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
            <div>Queued: {chunkUploadCounts.queued}</div>
            <div>Uploading: {chunkUploadCounts.uploading}</div>
            <div>Saved: {chunkUploadCounts.saved}</div>
            <div>Failed: {chunkUploadCounts.failed}</div>
          </div>
          {lastUploadError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{lastUploadError}</p>}
          {recordingError && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 8 }}>{recordingError}</p>}
        </section>
      )}

      <section style={cardStyle}>
        <div style={sectionTitleStyle}>
          Question {session.questions.length > 0 ? `${currentQuestionIndex + 1} of ${session.questions.length}` : "—"}
        </div>
        {currentQuestion ? (
          <div style={{ display: "grid", gap: 8 }}>
            <p style={{ fontSize: 14, color: "var(--ink)", margin: 0 }}>{currentQuestion.question_text}</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {describeTargetRef(currentQuestion.target_ref) && (
                <span style={chipStyle}>[{describeTargetRef(currentQuestion.target_ref)}]</span>
              )}
              {currentQuestion.claim_ids.map((claimId) => (
                <span key={claimId} style={chipStyle}>[claim {claimId.slice(0, 8)}]</span>
              ))}
            </div>
          </div>
        ) : (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>No questions available for this session.</p>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button
            type="button"
            style={currentQuestionIndex === 0 ? disabledButtonStyle : buttonStyle}
            disabled={currentQuestionIndex === 0}
            onClick={() => goToQuestion(currentQuestionIndex - 1)}
          >
            Previous
          </button>
          <button
            type="button"
            style={currentQuestionIndex >= session.questions.length - 1 ? disabledButtonStyle : buttonStyle}
            disabled={currentQuestionIndex >= session.questions.length - 1}
            onClick={() => goToQuestion(currentQuestionIndex + 1)}
          >
            Next
          </button>
        </div>
        {telemetryStatus && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>{telemetryStatus}</p>}
        {telemetryError && <p style={{ fontSize: 12, color: "var(--rose)", marginTop: 8 }}>{telemetryError}</p>}
        {!isRecording && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
            Telemetry is only recorded once the session is recording.
          </p>
        )}
      </section>



      <section style={cardStyle}>
        <div style={sectionTitleStyle}>Finish</div>
        <button
          type="button"
          style={isRecording && !finalizeLoading ? primaryButtonStyle : disabledButtonStyle}
          disabled={!isRecording || finalizeLoading}
          onClick={handleFinalize}
        >
          {finalizeLoading ? "Finalizing…" : "Finalize session"}
        </button>
        {session.status === "uploaded" && (
          <p style={{ fontSize: 12, color: "var(--emerald)", marginTop: 8 }}>✓ Session uploaded.</p>
        )}
        {finalizeMessage && <p style={{ fontSize: 12, color: "var(--emerald)", marginTop: 8 }}>{finalizeMessage}</p>}
        {finalizeError && <p style={{ fontSize: 12, color: "var(--rose)", marginTop: 8 }}>{finalizeError}</p>}
      </section>

      {(session.status === "uploaded" || session.status === "processed") && (
        <section style={cardStyle} data-testid="vbr-transcript">
          <div style={sectionTitleStyle}>Transcript</div>
          <p style={{ fontSize: 13, color: "var(--ink)", marginTop: 0 }}>
            <strong>Status:</strong>{" "}
            {transcriptLoading
              ? "Generating…"
              : TRANSCRIPT_STATUS_LABELS[session.transcript_status ?? "not_generated"] ??
                TRANSCRIPT_STATUS_LABELS.not_generated}
          </p>
          <button
            type="button"
            style={transcriptLoading ? disabledButtonStyle : primaryButtonStyle}
            disabled={transcriptLoading}
            onClick={handleGenerateTranscript}
          >
            {transcriptLoading ? "Generating transcript…" : "Generate transcript"}
          </button>
          {transcriptMessage && (
            <p style={{ fontSize: 12, color: "var(--emerald)", marginTop: 8 }}>{transcriptMessage}</p>
          )}
          {transcriptError && <p style={{ fontSize: 12, color: "var(--rose)", marginTop: 8 }}>{transcriptError}</p>}

          {session.transcript_status === "transcribed" && (
            <div style={{ marginTop: 12 }} data-testid="vbr-video-evidence-preview">
              <div style={{ ...sectionTitleStyle, marginBottom: 6 }}>Video evidence</div>
              {session.video_evidence_chips.length === 0 ? (
                <p style={{ fontSize: 12, color: "var(--muted)", margin: 0 }}>
                  Timestamped evidence will appear after transcript analysis.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {session.video_evidence_chips.map((chip, i) => (
                    <div
                      key={`${chip.label}-${i}`}
                      data-testid="vbr-video-evidence-chip"
                      style={{ fontSize: 12, color: "var(--ink-2)", display: "flex", alignItems: "baseline", gap: 8 }}
                    >
                      <span style={chipStyle}>{chip.label}</span>
                      <span>{chip.short_summary}</span>
                      {chip.related_skill && <span style={chipStyle}>{chip.related_skill}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
