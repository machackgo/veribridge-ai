// Durable stop → finalize → upload pipeline for the recorder tab.
//
// The recorder tab's MediaRecorder produces the only copy of the screen
// recording. Losing it because a stop raced the final chunk, an upload failed,
// or the tab reloaded means the user must re-record — so every step here is
// explicit, observable, and recoverable:
//
//   RECORDING → STOP_REQUESTED → FLUSHING_FINAL_CHUNKS → MEDIA_FINALIZED
//     → READY_TO_UPLOAD → UPLOADING → UPLOAD_ACKNOWLEDGED → COMPLETED
//                              ↘ UPLOAD_FAILED → UPLOADING (retry, same upload)
//
// Pure logic lives here (no DOM, no chrome.*) so it is unit-testable in Node.

// ── Diagnostic codes ──────────────────────────────────────────────────────────

export const WPR_MEDIA_FINALIZATION_FAILED = "WPR-MEDIA-FINALIZATION-FAILED"
export const WPR_EMPTY_RECORDING = "WPR-EMPTY-RECORDING"
export const WPR_FINAL_CHUNK_TIMEOUT = "WPR-FINAL-CHUNK-TIMEOUT"
export const WPR_AUTH_UNAVAILABLE = "WPR-AUTH-UNAVAILABLE"
export const WPR_UPLOAD_REJECTED = "WPR-UPLOAD-REJECTED"
export const WPR_UPLOAD_NETWORK_FAILED = "WPR-UPLOAD-NETWORK-FAILED"
export const WPR_UPLOAD_ACK_LOST = "WPR-UPLOAD-ACK-LOST"
export const WPR_SESSION_MISMATCH = "WPR-SESSION-MISMATCH"
export const WPR_RECOVERY_DATA_MISSING = "WPR-RECOVERY-DATA-MISSING"

export type WprDiagnosticCode =
  | typeof WPR_MEDIA_FINALIZATION_FAILED
  | typeof WPR_EMPTY_RECORDING
  | typeof WPR_FINAL_CHUNK_TIMEOUT
  | typeof WPR_AUTH_UNAVAILABLE
  | typeof WPR_UPLOAD_REJECTED
  | typeof WPR_UPLOAD_NETWORK_FAILED
  | typeof WPR_UPLOAD_ACK_LOST
  | typeof WPR_SESSION_MISMATCH
  | typeof WPR_RECOVERY_DATA_MISSING

// ── Finalize state machine ────────────────────────────────────────────────────

export type FinalizePhase =
  | "recording"
  | "stop_requested"
  | "flushing_final_chunks"
  | "media_finalized"
  | "ready_to_upload"
  | "uploading"
  | "upload_acknowledged"
  | "upload_failed"
  | "completed"

const FINALIZE_TRANSITIONS: Record<FinalizePhase, readonly FinalizePhase[]> = {
  recording: ["stop_requested"],
  stop_requested: ["flushing_final_chunks", "upload_failed"],
  flushing_final_chunks: ["media_finalized", "upload_failed"],
  media_finalized: ["ready_to_upload", "upload_failed"],
  // ready_to_upload is also a valid entry point when a persisted recording is
  // recovered after a tab reload / service-worker restart.
  ready_to_upload: ["uploading"],
  uploading: ["upload_acknowledged", "upload_failed"],
  upload_acknowledged: ["completed"],
  upload_failed: ["uploading"],
  completed: [],
}

/**
 * Guards phase ordering so the recorder can never report success before the
 * backend acknowledged the upload (COMPLETED is only reachable through
 * UPLOAD_ACKNOWLEDGED) and never restarts a finished pipeline.
 */
export class RecorderFinalizeMachine {
  phase: FinalizePhase

  constructor(initial: FinalizePhase = "recording") {
    this.phase = initial
  }

  to(next: FinalizePhase): FinalizePhase {
    if (!FINALIZE_TRANSITIONS[this.phase].includes(next)) {
      throw new Error(`Illegal recorder finalize transition: ${this.phase} → ${next}`)
    }
    this.phase = next
    return next
  }
}

// ── MediaRecorder finalization ────────────────────────────────────────────────

/** Minimal MediaRecorder surface required for finalization. */
export interface FinalizableRecorder {
  state: "inactive" | "recording" | "paused"
  stop(): void
  addEventListener(type: string, listener: (event?: unknown) => void): void
  removeEventListener(type: string, listener: (event?: unknown) => void): void
}

export type MediaFinalizationResult =
  | { ok: true }
  | { ok: false; code: WprDiagnosticCode; message: string }

export const DEFAULT_MEDIA_FINALIZE_TIMEOUT_MS = 8000

/**
 * Request stop and resolve only after the recorder's `stop` event has fired.
 * Per the MediaRecorder spec the final `dataavailable` event is dispatched
 * BEFORE `stop`, so once this resolves every chunk (including the final one)
 * has been delivered to the caller's `ondataavailable` collector.
 */
export function awaitMediaFinalization(
  recorder: FinalizableRecorder,
  opts: { timeoutMs?: number } = {},
): Promise<MediaFinalizationResult> {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_MEDIA_FINALIZE_TIMEOUT_MS
  if (recorder.state === "inactive") {
    // Already stopped — the stop event (and final chunk) already fired.
    return Promise.resolve({ ok: true })
  }
  return new Promise<MediaFinalizationResult>((resolve) => {
    let settled = false
    const onStop = (): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      recorder.removeEventListener("stop", onStop)
      resolve({ ok: true })
    }
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      recorder.removeEventListener("stop", onStop)
      resolve({
        ok: false,
        code: WPR_FINAL_CHUNK_TIMEOUT,
        message: "The recorder did not deliver its final video chunk in time.",
      })
    }, timeoutMs)
    recorder.addEventListener("stop", onStop)
    try {
      if (recorder.state !== "inactive") recorder.stop()
    } catch (err) {
      if (!settled) {
        settled = true
        clearTimeout(timer)
        recorder.removeEventListener("stop", onStop)
        resolve({
          ok: false,
          code: WPR_MEDIA_FINALIZATION_FAILED,
          message: `The recorder could not be stopped: ${err instanceof Error ? err.message : String(err)}`,
        })
      }
    }
  })
}

// ── Blob validation ───────────────────────────────────────────────────────────

/** Anything smaller than this cannot be a playable WebM/MP4 recording. */
export const MIN_RECORDING_BYTES = 100

export type BlobValidationResult =
  | { ok: true }
  | { ok: false; code: typeof WPR_EMPTY_RECORDING; message: string }

export function validateRecordingBlob(blob: { size: number }): BlobValidationResult {
  if (!blob || blob.size < MIN_RECORDING_BYTES) {
    return {
      ok: false,
      code: WPR_EMPTY_RECORDING,
      message:
        "The recording finished with no video data. The captured screen may have " +
        "ended immediately — start screen capture again and re-record.",
    }
  }
  return { ok: true }
}

// ── Upload (idempotent, retry-safe) ───────────────────────────────────────────

/** Durable descriptor persisted alongside the recording blob before upload. */
export interface PendingVideoUpload {
  session_id: string
  /** Stable idempotency key — every retry of this recording reuses it. */
  upload_id: string
  mime_type: string
  duration_ms: number
  display_surface: string | null
  created_at: string
  attempt_count: number
}

export type VideoUploadResult =
  | { ok: true; keyframe_count: number; video_analysis_status: string; message: string }
  | {
      ok: false
      code: WprDiagnosticCode
      message: string
      /** True when re-attempting the same upload_id is safe and sensible. */
      retryable: boolean
      /** True when the backend may have stored the video although the response was lost. */
      ack_uncertain?: boolean
    }

export interface VideoUploadRequest {
  apiBaseUrl: string
  authToken: string
  record: PendingVideoUpload
  blob: Blob
  fetchFn: typeof fetch
}

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024

/**
 * One upload attempt. Never throws — every outcome maps to a diagnostic code.
 * The backend treats repeated deliveries for the same session as idempotent
 * (the first retained replay stays canonical), so retrying after a lost
 * acknowledgment (WPR-UPLOAD-NETWORK-FAILED with ack_uncertain) cannot create
 * duplicate evidence.
 */
export async function uploadRecordingOnce(req: VideoUploadRequest): Promise<VideoUploadResult> {
  const { apiBaseUrl, authToken, record, blob, fetchFn } = req

  if (!record.session_id) {
    return {
      ok: false,
      code: WPR_SESSION_MISMATCH,
      message: "No Website Proof session is bound to this recording.",
      retryable: false,
    }
  }
  if (!apiBaseUrl) {
    return {
      ok: false,
      code: WPR_SESSION_MISMATCH,
      message: "No API base is configured for this Website Proof session.",
      retryable: false,
    }
  }
  if (!authToken) {
    return {
      ok: false,
      code: WPR_AUTH_UNAVAILABLE,
      message:
        "Recording isn't signed in. Open the VeriBridge Website Proof page while " +
        "signed in, then retry the upload.",
      retryable: true,
    }
  }
  if (blob.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      code: WPR_UPLOAD_REJECTED,
      message: `Video too large (${(blob.size / 1024 / 1024).toFixed(0)} MB > 100 MB limit).`,
      retryable: false,
    }
  }

  const ext = record.mime_type.includes("mp4") ? "mp4" : "webm"
  const form = new FormData()
  form.append("video", blob, `recording.${ext}`)

  const url =
    `${apiBaseUrl.replace(/\/$/, "")}/api/v1/student/extension-proof/sessions/` +
    `${record.session_id}/workflow/video`

  let resp: Response
  try {
    resp = await fetchFn(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "X-Upload-Id": record.upload_id,
        "X-Idempotency-Key": record.upload_id,
      },
      body: form,
    })
  } catch (err) {
    return {
      ok: false,
      code: WPR_UPLOAD_NETWORK_FAILED,
      message:
        "The upload could not reach the VeriBridge backend. Check your connection " +
        "and retry — the recording is saved locally.",
      retryable: true,
      // The request may have completed server-side before the connection broke.
      // Retrying is safe because the backend is idempotent per session.
      ack_uncertain: true,
    }
  }

  const bodyText = await resp.text().catch(() => "")

  if (!resp.ok) {
    let reason = `HTTP ${resp.status}`
    try {
      const parsed = JSON.parse(bodyText) as { detail?: string | { message?: string } }
      const d = parsed?.detail
      reason = (typeof d === "string" ? d : d?.message) ?? reason
    } catch {
      /* keep HTTP status */
    }
    reason = reason.slice(0, 200)
    if (resp.status === 401 || resp.status === 403) {
      return {
        ok: false,
        code: WPR_AUTH_UNAVAILABLE,
        message:
          "Recording isn't signed in. Open the VeriBridge Website Proof page while " +
          "signed in, then retry the upload.",
        retryable: true,
      }
    }
    return {
      ok: false,
      code: WPR_UPLOAD_REJECTED,
      message: reason,
      retryable: resp.status >= 500 || resp.status === 409 || resp.status === 429,
    }
  }

  let keyframeCount = 0
  let statusVal = "unknown"
  let replayRetained = false
  try {
    const parsed = JSON.parse(bodyText) as {
      keyframe_count?: number
      video_analysis_status?: string
      replay_retained?: boolean
    }
    keyframeCount = parsed?.keyframe_count ?? 0
    statusVal = parsed?.video_analysis_status ?? "unknown"
    replayRetained = parsed?.replay_retained === true
  } catch {
    // A 2xx whose body cannot be parsed leaves the acknowledgment uncertain.
    return {
      ok: false,
      code: WPR_UPLOAD_ACK_LOST,
      message:
        "The backend accepted the upload but the acknowledgment could not be read. " +
        "Retry to confirm — duplicate delivery is safe.",
      retryable: true,
      ack_uncertain: true,
    }
  }

  if (!replayRetained) {
    return {
      ok: false,
      code: WPR_UPLOAD_REJECTED,
      message: "The recording could not be retained for replay. Retry the upload.",
      retryable: true,
    }
  }

  return {
    ok: true,
    keyframe_count: keyframeCount,
    video_analysis_status: statusVal,
    message: `✓ Video uploaded (${statusVal}).`,
  }
}

// ── Session-scoped recorder tab state (multi-tab safety) ─────────────────────
//
// A recorder tab left open after finishing one session must never answer for
// the next session: its uploadDone/keyframe state belongs to the session it
// recorded. Both helpers are pure so the multi-tab rules are unit-testable.

/**
 * True when the background's active session moved to a different session than
 * the one this tab's finalize/upload state belongs to, so that state must be
 * reset. Never resets mid-capture or mid-upload (`busy`) — the in-flight
 * pipeline still belongs to the bound session and the finalize-request session
 * guard keeps a busy stale tab silent for the new session.
 */
export function shouldResetRecorderSessionState(
  boundSessionId: string,
  nextSessionId: string,
  busy: boolean,
): boolean {
  return Boolean(boundSessionId) && Boolean(nextSessionId) && nextSessionId !== boundSessionId && !busy
}

/**
 * Whether this recorder tab may answer a finalize request targeting
 * `targetSessionId`. A tab bound to a different session must stay silent so
 * the target session's own recorder tab (or a definitive no-listener result)
 * wins — a stale tab's `uploadDone` answering first is exactly how a missing
 * recording gets reported as uploaded. Requests without a target session
 * (older builds) are answered for compatibility.
 */
export function finalizeRequestMatchesSession(
  targetSessionId: string | null | undefined,
  boundSessionId: string,
): boolean {
  if (!targetSessionId || !boundSessionId) return true
  return targetSessionId === boundSessionId
}

// ── Capture scope (displaySurface) classification ─────────────────────────────

export type CaptureScope = "tab" | "window" | "screen" | "unknown"

export interface CaptureScopeInfo {
  scope: CaptureScope
  /** Short UI label, e.g. "Browser tab". */
  label: string
  /** True only when the capture follows the user across windows/apps. */
  capturesOtherWindows: boolean
  /** Warning to surface when the proof workflow may span multiple windows. */
  warning: string | null
}

/**
 * Classify MediaStreamTrack.getSettings().displaySurface.
 * Chrome reports "browser" (a tab), "window", or "monitor" (entire screen).
 * Older browsers may omit the setting entirely → "unknown" (treated cautiously).
 */
export function classifyDisplaySurface(displaySurface: string | null | undefined): CaptureScopeInfo {
  switch (displaySurface) {
    case "browser":
      return {
        scope: "tab",
        label: "Browser tab",
        capturesOtherWindows: false,
        warning:
          "You selected a single browser tab. Anything you do in another tab or " +
          "window (e.g. opening GitHub elsewhere) will NOT be captured. Keep your " +
          "whole workflow inside this captured tab, or restart capture and share " +
          "your Entire Screen.",
      }
    case "window":
      return {
        scope: "window",
        label: "Window",
        capturesOtherWindows: false,
        warning:
          "You selected a single window. Anything you do in another window (e.g. " +
          "opening GitHub elsewhere) will NOT be captured. Keep your whole workflow " +
          "inside this captured window, or restart capture and share your Entire Screen.",
      }
    case "monitor":
      return {
        scope: "screen",
        label: "Entire screen",
        capturesOtherWindows: true,
        warning: null,
      }
    default:
      return {
        scope: "unknown",
        label: "Unknown surface",
        capturesOtherWindows: false,
        warning:
          "The browser did not report what is being captured. If you selected a tab " +
          "or window, other windows will NOT be recorded — share your Entire Screen " +
          "for cross-window workflows.",
      }
  }
}
