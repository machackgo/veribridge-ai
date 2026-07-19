// Recorder tab — persistent WebM screen recording for fullscreen / media sessions.
//
// MV3 design: this is a real browser tab (not the popup), so it keeps running
// while the user is in fullscreen on another tab.  It uses MediaRecorder to
// capture a WebM video from getDisplayMedia, then uploads it directly to the
// VeriBridge backend — no hop through the background service worker for the
// video bytes.
//
// Flow:
//   1. User clicks "Start Recording" in the popup/proof page → recorder tab opens.
//   2. User clicks "Start Screen Recording" → user gesture → getDisplayMedia().
//   3. Browser screen-share picker → the ACTUAL selected surface (tab / window /
//      entire screen) is detected via MediaStreamTrack.getSettings().displaySurface
//      and shown as the capture scope. Tab/window selections require an explicit
//      confirmation because they cannot capture other windows.
//   4. MediaRecorder starts → WebM chunks accumulate in memory.
//   5. Recording continues while the user works (this tab's JS runs in background).
//   6. Stop (from this tab, the floating bar via the background finalize request,
//      or Chrome's native "Stop sharing") runs the durable finalize pipeline:
//      final chunk flush → blob validation → IndexedDB persistence → upload with
//      a stable idempotency key → backend acknowledgment.
//   7. Failures keep the recording recoverable (IndexedDB) and offer Retry with
//      the SAME session + upload id. A reloaded tab resumes the pending upload.
//
// Why getDisplayMedia instead of captureVisibleTab:
//   captureVisibleTab returns black frames for hardware-decoded fullscreen video
//   (GPU overlay compositor bypasses the normal tab pixel pipeline).
//   getDisplayMedia at OS level captures what is actually displayed on screen.

import type { RecorderPrivateState } from "./types"
import {
  RecorderFinalizeMachine,
  awaitMediaFinalization,
  classifyDisplaySurface,
  uploadRecordingOnce,
  validateRecordingBlob,
  WPR_RECOVERY_DATA_MISSING,
  WPR_SESSION_MISMATCH,
  finalizeRequestMatchesSession,
  shouldResetRecorderSessionState,
  type CaptureScopeInfo,
  type PendingVideoUpload,
  type VideoUploadResult,
  type WprDiagnosticCode,
} from "./recorderFinalize"
import {
  deletePendingVideoUpload,
  loadPendingVideoUpload,
  savePendingVideoUpload,
} from "./recorderMediaStore"

// ── Constants ─────────────────────────────────────────────────────────────────
/** Maximum recording duration in ms (5 minutes) after which capture auto-stops. */
const MAX_RECORDING_MS = 5 * 60 * 1000
/** Keep the MV3 service worker awake while an upload is in flight. */
const UPLOAD_KEEPALIVE_MS = 5000

// ── MediaRecorder MIME type selection ────────────────────────────────────────
function chooseMimeType(): string {
  const candidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ]
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c
  }
  return "video/webm"
}

// ── Module state ──────────────────────────────────────────────────────────────
let displayStream: MediaStream | null = null
/** Stream selected in the picker but awaiting scope confirmation (tab/window). */
let pendingStream: MediaStream | null = null
let mediaRecorder: MediaRecorder | null = null
let videoChunks: Blob[] = []
let videoMimeType = "video/webm"
let recordingStartMs = 0
let durationTimer: ReturnType<typeof setInterval> | null = null
let autoStopTimer: ReturnType<typeof setTimeout> | null = null

let isRecordingActive = false   // background recording is active
let currentSessionId = ""
/** Session the finalize/upload state in this tab belongs to — unlike
 *  currentSessionId it does NOT follow the background's active session, so a
 *  stale tab can be detected and reset when a new session takes over. */
let boundSessionId = ""
let currentApiUrl = ""
let currentAuthToken = ""

let isUploading = false
let uploadDone = false
let uploadError: string | null = null
let uploadErrorCode: WprDiagnosticCode | null = null
let lastKeyframeCount = 0

/** Detected capture scope of the active/pending display stream. */
let captureScope: CaptureScopeInfo | null = null
/** Durable finalize pipeline state for the current recording. */
let finalizeMachine: RecorderFinalizeMachine | null = null
/** Finished recording awaiting (or having failed) backend acknowledgment. */
let pendingUpload: { record: PendingVideoUpload; blob: Blob } | null = null
/** Deduplicates concurrent finalize/retry triggers (button, message, track-end). */
let inFlightFinalize: Promise<VideoUploadResult> | null = null
let uploadKeepaliveTimer: ReturnType<typeof setInterval> | null = null
let recoveryChecked = false

let statePoll: ReturnType<typeof setInterval> | null = null
let contextInvalidated = false

// ── DOM helpers ────────────────────────────────────────────────────────────────
function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const btnStart      = el<HTMLButtonElement>("btnStart")
const btnStop       = el<HTMLButtonElement>("btnStop")
const btnRetry      = el<HTMLButtonElement>("btnRetry")
const btnConfirmScope = el<HTMLButtonElement>("btnConfirmScope")
const btnReselect   = el<HTMLButtonElement>("btnReselect")
const confirmRow    = el("confirmRow")
const scopeRow      = el("scopeRow")
const scopeLabelEl  = el("scopeLabel")
const scopeWarnEl   = el("scopeWarn")
const recDot        = el("recDot")
const recStatusEl   = el("recStatus")
const recSessionEl  = el("recSession")
const streamIndEl   = el("streamIndicator")
const streamLblEl   = el("streamLabel")
const frameBadgeEl  = el("frameBadge")    // repurposed: shows duration / upload status
const msgBoxEl      = el("msgBox")
const instructionsEl = el("instructions")

// ── UI helpers ─────────────────────────────────────────────────────────────────

type MsgVariant = "default" | "ok" | "warn" | "err"

function setMsg(text: string, variant: MsgVariant = "default"): void {
  msgBoxEl.textContent = text
  msgBoxEl.className = `msg-box${variant !== "default" ? ` ${variant}` : ""}`
}

function updateStreamUI(active: boolean): void {
  if (active) {
    streamIndEl.textContent = "🔴"
    streamLblEl.textContent = "Screen capture active — you can minimise this tab"
    streamLblEl.className = "stream-label active"
    instructionsEl.classList.add("visible")
  } else {
    streamIndEl.textContent = "⚪"
    streamLblEl.textContent = "No screen selected"
    streamLblEl.className = "stream-label"
    instructionsEl.classList.remove("visible")
  }
}

function renderCaptureScope(): void {
  if (!captureScope) {
    scopeRow.style.display = "none"
    scopeWarnEl.style.display = "none"
    return
  }
  scopeRow.style.display = ""
  scopeLabelEl.textContent = `Capture scope: ${captureScope.label}`
  if (captureScope.warning) {
    scopeWarnEl.style.display = ""
    scopeWarnEl.textContent = `⚠ ${captureScope.warning}`
  } else {
    scopeWarnEl.style.display = "none"
    scopeWarnEl.textContent = ""
  }
}

function showRetryButton(visible: boolean): void {
  btnRetry.style.display = visible ? "" : "none"
  btnRetry.disabled = !visible
}

function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000)
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function updateDurationBadge(): void {
  if (isUploading) {
    frameBadgeEl.textContent = "Uploading…"
    frameBadgeEl.className = "frame-badge has-frames"
    return
  }
  if (uploadDone && !uploadError) {
    frameBadgeEl.textContent = "✓ Uploaded"
    frameBadgeEl.className = "frame-badge has-frames"
    return
  }
  if (uploadError) {
    frameBadgeEl.textContent = "Upload failed"
    frameBadgeEl.className = "frame-badge"
    return
  }
  if (mediaRecorder && mediaRecorder.state === "recording") {
    const elapsed = Date.now() - recordingStartMs
    frameBadgeEl.textContent = formatDuration(elapsed)
    frameBadgeEl.className = "frame-badge has-frames"
  } else {
    frameBadgeEl.textContent = "—"
    frameBadgeEl.className = "frame-badge"
  }
}

function applyRecordingState(state: RecorderPrivateState): void {
  const wasRecording = isRecordingActive
  isRecordingActive  = state.isRecording
  currentSessionId   = state.sessionId ?? ""
  currentApiUrl      = (state.apiUrl || "").replace(/\/$/, "")
  currentAuthToken   = state.authToken ?? ""

  // A new session took over while this tab still holds the previous session's
  // finalize/upload state — reset it so this tab can never report the old
  // upload as the new session's recording.
  const sessionBusy =
    isUploading ||
    inFlightFinalize !== null ||
    displayStream !== null ||
    pendingStream !== null ||
    (mediaRecorder !== null && mediaRecorder.state === "recording")
  if (shouldResetRecorderSessionState(boundSessionId, currentSessionId, sessionBusy)) {
    resetSessionScopedState()
  }
  if (!boundSessionId && currentSessionId) boundSessionId = currentSessionId

  if (state.isRecording) {
    recDot.className = "status-dot recording"
    recStatusEl.textContent = `Recording active · ${state.eventCount} event(s)`
  } else if (state.status === "stopped") {
    recDot.className = "status-dot stopped"
    recStatusEl.textContent = "Recording stopped — send proof from the proof page or popup"
  } else if (state.status === "uploaded") {
    recDot.className = "status-dot"
    recStatusEl.textContent = "Proof uploaded ✓"
  } else {
    recDot.className = "status-dot"
    recStatusEl.textContent = "No active recording — start one from the Website Proof page"
  }

  recSessionEl.textContent = currentSessionId ? currentSessionId.slice(0, 16) + "…" : ""

  // Buttons: Start enabled only when recording active and no capture in progress
  const capturing = displayStream !== null || pendingStream !== null || isUploading
  btnStart.disabled = !isRecordingActive || capturing || uploadDone
  btnStop.disabled  = displayStream === null || isUploading

  // If recording stopped from popup/floating bar while screen capture is still
  // running, finalize the video automatically instead of only warning.
  if (wasRecording && !isRecordingActive && displayStream && !inFlightFinalize) {
    setMsg("Background recording stopped — finishing and uploading the screen recording…")
    void stopAndFinalize("background_recording_stopped")
  }

  if (!isRecordingActive && !displayStream && !isUploading) {
    if (uploadDone && !uploadError) {
      setMsg("✓ Video uploaded. Return to the Website Proof page to send your proof.", "ok")
    } else if (uploadError) {
      setMsg(`Video upload failed: ${uploadError}`, "err")
    } else if (!pendingUpload) {
      setMsg('Start a recording session from the Website Proof page first, then click "Start Screen Recording" here.')
    }
  }

  // One-time recovery: a finished recording persisted before a tab reload /
  // browser restart resumes its upload as soon as the session is known.
  if (!recoveryChecked && currentSessionId) {
    recoveryChecked = true
    void recoverPendingUpload()
  }
}

// ── Durable finalize / upload pipeline ────────────────────────────────────────

/** A different session took over this tab — its finalize/upload state is
 *  stale. The previous session's persisted recording (if any) stays safe in
 *  IndexedDB under its own session id; only in-memory state resets here. */
function resetSessionScopedState(): void {
  uploadDone = false
  uploadError = null
  uploadErrorCode = null
  lastKeyframeCount = 0
  pendingUpload = null
  finalizeMachine = null
  boundSessionId = ""
  recoveryChecked = false   // recovery re-runs for the new session id
  showRetryButton(false)
  updateDurationBadge()
}

function beginUploadKeepalive(): void {
  if (uploadKeepaliveTimer) return
  uploadKeepaliveTimer = setInterval(() => {
    if (contextInvalidated) return
    try {
      chrome.runtime.sendMessage({ type: "RECORDER_VIDEO_UPLOAD_PROGRESS" }, () => {
        if (chrome.runtime.lastError) { /* worker may be restarting */ }
      })
    } catch { /* extension context may be gone */ }
  }, UPLOAD_KEEPALIVE_MS)
}

function endUploadKeepalive(): void {
  if (uploadKeepaliveTimer) { clearInterval(uploadKeepaliveTimer); uploadKeepaliveTimer = null }
}

function failureMessage(result: Extract<VideoUploadResult, { ok: false }>): string {
  return `${result.message} [${result.code}]`
}

/**
 * Stop capture (if running), flush the final MediaRecorder chunks, validate the
 * blob, persist it, and upload — an explicit, observable pipeline. Concurrent
 * triggers (Stop button, background finalize request, Chrome's "Stop sharing",
 * auto-stop) share one in-flight promise.
 */
function stopAndFinalize(trigger: string): Promise<VideoUploadResult> {
  if (inFlightFinalize) return inFlightFinalize
  const run = doStopAndFinalize(trigger).finally(() => { inFlightFinalize = null })
  inFlightFinalize = run
  return run
}

async function doStopAndFinalize(trigger: string): Promise<VideoUploadResult> {
  if (uploadDone) {
    return {
      ok: true,
      keyframe_count: lastKeyframeCount,
      video_analysis_status: "already_uploaded",
      message: "Recording already uploaded.",
    }
  }

  const machine = finalizeMachine ?? new RecorderFinalizeMachine("recording")
  finalizeMachine = machine

  const recorder = mediaRecorder
  if (recorder) {
    if (machine.phase === "recording") machine.to("stop_requested")
    setMsg("Stopping — flushing the final video chunks…")
    if (machine.phase === "stop_requested") machine.to("flushing_final_chunks")
    const finalized = await awaitMediaFinalization(recorder)
    if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
    if (autoStopTimer) { clearTimeout(autoStopTimer);  autoStopTimer  = null }
    if (!finalized.ok) {
      machine.to("upload_failed")
      uploadError = finalized.message
      uploadErrorCode = finalized.code
      cleanupStreamTracks()
      updateDurationBadge()
      setMsg(`Recording could not be finalized: ${finalized.message} [${finalized.code}]`, "err")
      notifyBackground(false, `${finalized.message} [${finalized.code}]`, 0)
      return { ok: false, code: finalized.code, message: finalized.message, retryable: false }
    }
  }
  cleanupStreamTracks()

  // Build + validate the blob from every flushed chunk (final one included).
  const blob = new Blob(videoChunks, { type: videoMimeType })
  videoChunks = []
  mediaRecorder = null
  const validation = validateRecordingBlob(blob)
  if (!validation.ok) {
    if (machine.phase !== "upload_failed") machine.to("upload_failed")
    uploadError = validation.message
    uploadErrorCode = validation.code
    updateDurationBadge()
    setMsg(`${validation.message} [${validation.code}] (trigger: ${trigger})`, "err")
    notifyBackground(false, `${validation.message} [${validation.code}]`, 0)
    return { ok: false, code: validation.code, message: validation.message, retryable: false }
  }
  machine.to("media_finalized")

  const record: PendingVideoUpload = {
    session_id: currentSessionId,
    upload_id: crypto.randomUUID(),
    mime_type: videoMimeType,
    duration_ms: Math.max(0, Date.now() - recordingStartMs),
    display_surface: captureScope?.scope ?? null,
    created_at: new Date().toISOString(),
    attempt_count: 0,
  }
  pendingUpload = { record, blob }

  // Persist BEFORE uploading so a tab close / crash cannot lose the recording.
  try {
    await savePendingVideoUpload({ ...record, blob })
  } catch (err) {
    console.warn("VeriBridge recorder: could not persist recording before upload:", err)
  }
  machine.to("ready_to_upload")

  return runUploadAttempt()
}

/** One upload attempt for the pending recording. Reuses the same upload id. */
async function runUploadAttempt(): Promise<VideoUploadResult> {
  const pending = pendingUpload
  const machine = finalizeMachine
  if (!pending || !machine) {
    const message = "No recorded video is available to upload. Start a new screen recording."
    return { ok: false, code: WPR_RECOVERY_DATA_MISSING, message, retryable: false }
  }

  if (!pending.record.session_id) pending.record.session_id = currentSessionId
  pending.record.attempt_count += 1

  machine.to("uploading")
  isUploading = true
  uploadError = null
  uploadErrorCode = null
  showRetryButton(false)
  updateDurationBadge()
  setMsg(
    `Uploading recording (${(pending.blob.size / 1024 / 1024).toFixed(1)} MB, attempt ${pending.record.attempt_count})…`,
  )
  btnStop.disabled = true
  btnStart.disabled = true
  notifyUploadStarted()
  beginUploadKeepalive()

  const result = await uploadRecordingOnce({
    apiBaseUrl: currentApiUrl,
    authToken: currentAuthToken,
    record: pending.record,
    blob: pending.blob,
    fetchFn: fetch.bind(globalThis),
  })

  endUploadKeepalive()
  isUploading = false

  if (result.ok) {
    machine.to("upload_acknowledged")
    machine.to("completed")
    uploadDone = true
    uploadError = null
    uploadErrorCode = null
    lastKeyframeCount = result.keyframe_count
    pendingUpload = null
    try {
      await deletePendingVideoUpload(pending.record.session_id)
    } catch { /* stale entry is harmless — it is keyed by session */ }
    updateDurationBadge()
    const kfStr = result.keyframe_count > 0
      ? `${result.keyframe_count} keyframe(s) extracted.`
      : "Keyframe extraction pending."
    setMsg(`${result.message} ${kfStr} Return to the Website Proof page to send your proof.`, "ok")
    showRetryButton(false)
    notifyBackground(true, null, result.keyframe_count, pending.record.session_id)
  } else {
    machine.to("upload_failed")
    uploadError = result.message
    uploadErrorCode = result.code
    updateDurationBadge()
    setMsg(
      `Video upload failed: ${failureMessage(result)}` +
      (result.retryable ? " Your recording is saved — click Retry Upload." : ""),
      "err",
    )
    showRetryButton(true)
    notifyBackground(false, failureMessage(result), 0, pending.record.session_id)
  }

  btnStart.disabled = !isRecordingActive || displayStream !== null || uploadDone
  btnStop.disabled  = displayStream === null
  return result
}

/** Retry the pending upload — same session, same upload id, no duplicate media. */
function retryUpload(): Promise<VideoUploadResult> {
  if (inFlightFinalize) return inFlightFinalize
  const run = doRetryUpload().finally(() => { inFlightFinalize = null })
  inFlightFinalize = run
  return run
}

async function doRetryUpload(): Promise<VideoUploadResult> {
  if (uploadDone) {
    return {
      ok: true,
      keyframe_count: lastKeyframeCount,
      video_analysis_status: "already_uploaded",
      message: "Recording already uploaded.",
    }
  }
  if (!pendingUpload) {
    // The tab may have been reloaded — recover the persisted recording.
    try {
      const stored = await loadPendingVideoUpload(currentSessionId)
      if (stored) {
        const { blob, ...record } = stored
        pendingUpload = { record, blob }
        finalizeMachine = new RecorderFinalizeMachine("ready_to_upload")
      }
    } catch (err) {
      console.warn("VeriBridge recorder: pending-upload recovery failed:", err)
    }
  }
  if (!pendingUpload) {
    const message =
      "The recording data for this session is no longer available. " +
      "Start a new screen recording."
    uploadError = message
    uploadErrorCode = WPR_RECOVERY_DATA_MISSING
    setMsg(`${message} [${WPR_RECOVERY_DATA_MISSING}]`, "err")
    showRetryButton(false)
    return { ok: false, code: WPR_RECOVERY_DATA_MISSING, message, retryable: false }
  }
  if (!finalizeMachine || finalizeMachine.phase === "completed") {
    finalizeMachine = new RecorderFinalizeMachine("ready_to_upload")
  } else if (finalizeMachine.phase === "upload_failed") {
    // upload_failed → uploading happens inside runUploadAttempt
  }
  return runUploadAttempt()
}

/** Resume a persisted, unacknowledged upload after a tab reload / restart. */
async function recoverPendingUpload(): Promise<void> {
  if (uploadDone || displayStream || pendingStream || inFlightFinalize || pendingUpload) return
  let stored
  try {
    stored = await loadPendingVideoUpload(currentSessionId)
  } catch {
    return
  }
  if (!stored) return
  setMsg("Found a finished recording that was not uploaded yet — resuming the upload…", "warn")
  void retryUpload()
}

/**
 * Notify the background service worker whether the screen capture stream is active.
 * Background broadcasts this to the popup so it shows ONE unified status
 * ("Screen recording active in recorder tab") instead of two conflicting indicators.
 */
function notifyStreamState(active: boolean): void {
  if (contextInvalidated) return
  const type = active ? "RECORDER_STREAM_STARTED" : "RECORDER_STREAM_STOPPED"
  try {
    chrome.runtime.sendMessage(
      { type, payload: { display_surface: captureScope?.scope ?? null } },
      () => {
        if (chrome.runtime.lastError) { /* context may have been invalidated */ }
      },
    )
  } catch { /* extension context may be gone */ }
}

/** Inform the background service worker about the upload result. */
function notifyBackground(
  ok: boolean,
  error: string | null,
  keyframeCount: number,
  sessionId?: string,
): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage(
      {
        type: "RECORDER_VIDEO_UPLOADED",
        payload: {
          ok,
          error,
          keyframe_count: keyframeCount,
          // Session this upload result actually belongs to — the background
          // ignores results for a session other than its active one.
          session_id: sessionId ?? boundSessionId ?? null,
        },
      },
      () => { if (chrome.runtime.lastError) { /* ignore */ } },
    )
  } catch { /* context may be gone */ }
}

function notifyUploadStarted(): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage(
      { type: "RECORDER_VIDEO_UPLOAD_STARTED", payload: { session_id: boundSessionId || null } },
      () => { if (chrome.runtime.lastError) { /* ignore */ } },
    )
  } catch { /* extension context may be gone */ }
}

// ── MediaRecorder lifecycle ───────────────────────────────────────────────────

function startMediaRecorder(stream: MediaStream): void {
  videoChunks    = []
  videoMimeType  = chooseMimeType()
  recordingStartMs = Date.now()
  finalizeMachine = new RecorderFinalizeMachine("recording")

  const options: MediaRecorderOptions = {
    mimeType: videoMimeType,
    videoBitsPerSecond: 500_000,   // 500 kbps — good quality, small file
  }

  try {
    mediaRecorder = new MediaRecorder(stream, options)
  } catch {
    // Some browsers don't support all codec options — fall back to defaults
    mediaRecorder = new MediaRecorder(stream)
    videoMimeType = mediaRecorder.mimeType || "video/webm"
  }

  mediaRecorder.ondataavailable = (e: BlobEvent) => {
    if (e.data && e.data.size > 0) videoChunks.push(e.data)
  }

  // 2-second timeslice — chunks arrive frequently so finalization is fast
  mediaRecorder.start(2000)

  // Duration counter + video-track liveness watchdog: if the captured surface
  // disappears (window closed, screen unplugged) without an `ended` event,
  // finalize instead of silently recording nothing.
  durationTimer = setInterval(() => {
    updateDurationBadge()
    const track = displayStream?.getVideoTracks()[0]
    if (track && track.readyState === "ended" && !inFlightFinalize) {
      setMsg("Screen capture ended unexpectedly — finalizing the recording…", "warn")
      void stopAndFinalize("track_ended_watchdog")
    }
  }, 1000)

  // Safety cap: auto-stop after MAX_RECORDING_MS
  autoStopTimer = setTimeout(() => {
    setMsg(`Auto-stopping after ${formatDuration(MAX_RECORDING_MS)} (max recording duration)…`, "warn")
    void stopAndFinalize("auto_stop")
  }, MAX_RECORDING_MS)
}

// ── Start / stop capture ───────────────────────────────────────────────────────

const PRE_PICKER_GUIDANCE =
  "Choose what to share. If your workflow spans more than one window " +
  "(e.g. your deployed app AND GitHub), select “Entire Screen” — a single tab " +
  "or window records only itself."

async function startCapture(): Promise<void> {
  if (displayStream || pendingStream) return
  btnStart.disabled = true
  setMsg(PRE_PICKER_GUIDANCE)

  let stream: MediaStream
  try {
    // displaySurface:"monitor" asks Chrome to promote "Entire Screen" in the
    // picker (a hint — the user stays in control). selfBrowserSurface:"exclude"
    // hides this recorder tab from the choices; surfaceSwitching:"include"
    // lets the user re-target a shared tab via Chrome's own UI.
    const constraints = {
      video: {
        frameRate: { ideal: 15, max: 30 },
        displaySurface: "monitor",
        // No width/height constraints — let the OS pick native resolution
      },
      audio: false,  // Audio recording would require system permissions; skip for now
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      monitorTypeSurfaces: "include",
    } as MediaStreamConstraints
    stream = await navigator.mediaDevices.getDisplayMedia(constraints)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (msg.toLowerCase().includes("permission denied") || msg.includes("NotAllowedError")) {
      setMsg("Screen selection cancelled. Click Start to try again.")
    } else {
      setMsg(`Could not open screen picker: ${msg.slice(0, 100)}`, "err")
    }
    btnStart.disabled = !isRecordingActive
    return
  }

  // Detect what the user ACTUALLY selected (tab / window / entire screen).
  const track = stream.getVideoTracks()[0]
  const settings = (track?.getSettings() ?? {}) as { displaySurface?: string }
  captureScope = classifyDisplaySurface(settings.displaySurface)
  renderCaptureScope()

  if (!captureScope.capturesOtherWindows) {
    // Tab/window scope cannot follow the user to another window. Recording is
    // NOT started until the user explicitly confirms the limitation (or
    // re-selects Entire Screen) — no silent missing evidence.
    pendingStream = stream
    confirmRow.style.display = "grid"
    btnStart.disabled = true
    btnStop.disabled = true
    setMsg(
      `You selected a ${captureScope.label.toLowerCase()}. Other windows will NOT be recorded. ` +
      "Confirm to continue with this limitation, or re-select and share your Entire Screen.",
      "warn",
    )
    // If the user dismisses via Chrome's "Stop sharing" while deciding:
    stream.getVideoTracks().forEach((t) => {
      t.addEventListener("ended", () => {
        if (pendingStream === stream) discardPendingStream("Screen selection ended. Click Start to try again.")
      })
    })
    return
  }

  beginConfirmedCapture(stream)
}

function discardPendingStream(message: string): void {
  if (pendingStream) {
    pendingStream.getTracks().forEach((t) => t.stop())
    pendingStream = null
  }
  captureScope = null
  renderCaptureScope()
  confirmRow.style.display = "none"
  btnStart.disabled = !isRecordingActive
  btnStop.disabled = true
  setMsg(message)
}

/** Start recording on a stream whose capture scope the user has accepted. */
function beginConfirmedCapture(stream: MediaStream): void {
  pendingStream = null
  confirmRow.style.display = "none"
  displayStream = stream
  uploadDone    = false
  uploadError   = null
  uploadErrorCode = null
  showRetryButton(false)

  // Notify background so popup shows ONE unified status (no duplicate indicators)
  notifyStreamState(true)

  updateStreamUI(true)
  updateDurationBadge()
  const scopeNote = captureScope?.capturesOtherWindows
    ? "Everything on your screen is being recorded."
    : `Only the selected ${captureScope?.label.toLowerCase() ?? "surface"} is being recorded — stay inside it.`
  setMsg(`✓ Recording started. ${scopeNote} Return here (or use the floating bar) when done.`, "ok")

  btnStart.disabled = true
  btnStop.disabled  = false

  startMediaRecorder(stream)

  // Chrome's native "Stop sharing" button ends the track → run the SAME durable
  // finalize pipeline (final chunk flush → persist → upload), never a bare cleanup.
  stream.getVideoTracks().forEach((track) => {
    track.addEventListener("ended", () => {
      if (!inFlightFinalize) void stopAndFinalize("browser_stop_sharing")
    })
  })
}

function cleanupStreamTracks(): void {
  if (durationTimer)  { clearInterval(durationTimer); durationTimer = null }
  if (autoStopTimer)  { clearTimeout(autoStopTimer);  autoStopTimer  = null }
  const hadStream = displayStream !== null
  if (displayStream) {
    displayStream.getTracks().forEach((t) => t.stop())
    displayStream = null
  }
  // Notify background that screen capture ended (popup can re-enable Stop/Send)
  if (hadStream) notifyStreamState(false)
  updateStreamUI(false)
  btnStart.disabled = !isRecordingActive
  btnStop.disabled  = true
}

// ── Button handlers ────────────────────────────────────────────────────────────

btnStart.addEventListener("click", () => { void startCapture() })
btnStop.addEventListener("click",  () => { void stopAndFinalize("user_stop_button") })
btnRetry.addEventListener("click", () => { void retryUpload() })
btnConfirmScope.addEventListener("click", () => {
  const stream = pendingStream
  if (stream) beginConfirmedCapture(stream)
})
btnReselect.addEventListener("click", () => {
  discardPendingStream("Re-opening the screen picker — select “Entire Screen”.")
  void startCapture()
})

// ── Background finalize requests ──────────────────────────────────────────────
// The background sends RECORDER_FINALIZE_REQUEST when the user stops/sends the
// proof from the floating bar or popup while this tab still holds the capture
// or a failed upload. Responding only after the upload settles lets sendProof
// wait for a real acknowledgment instead of hard-failing.

interface FinalizeRequestResponse {
  ok: boolean
  has_media: boolean
  keyframe_count: number
  code?: WprDiagnosticCode
  message?: string
  retryable?: boolean
}

async function handleFinalizeRequest(): Promise<FinalizeRequestResponse> {
  if (uploadDone) {
    return { ok: true, has_media: true, keyframe_count: lastKeyframeCount }
  }
  if (inFlightFinalize) {
    const settled = await inFlightFinalize
    return toFinalizeResponse(settled)
  }
  if (pendingStream) {
    // Awaiting scope confirmation — nothing was recorded yet.
    discardPendingStream("Screen selection discarded before recording started.")
    return {
      ok: false,
      has_media: false,
      keyframe_count: 0,
      code: WPR_RECOVERY_DATA_MISSING,
      message: "Screen capture never started recording. Click Start Screen Recording in the recorder tab.",
      retryable: false,
    }
  }
  if (displayStream) {
    return toFinalizeResponse(await stopAndFinalize("background_finalize_request"))
  }
  if (pendingUpload) {
    return toFinalizeResponse(await retryUpload())
  }
  // Tab reloaded with a persisted recording? retryUpload() recovers it.
  const recovered = await retryUpload()
  if (recovered.ok || recovered.code !== WPR_RECOVERY_DATA_MISSING) {
    return toFinalizeResponse(recovered)
  }
  return {
    ok: false,
    has_media: false,
    keyframe_count: 0,
    code: WPR_RECOVERY_DATA_MISSING,
    message:
      "No screen recording exists for this session. Open the recorder tab and " +
      "click Start Screen Recording before sending proof.",
    retryable: false,
  }
}

function toFinalizeResponse(result: VideoUploadResult): FinalizeRequestResponse {
  if (result.ok) {
    return { ok: true, has_media: true, keyframe_count: result.keyframe_count }
  }
  return {
    ok: false,
    has_media: result.code !== WPR_RECOVERY_DATA_MISSING && result.code !== WPR_SESSION_MISMATCH,
    keyframe_count: 0,
    code: result.code,
    message: result.message,
    retryable: result.retryable,
  }
}

chrome.runtime.onMessage.addListener(
  (
    msg: { type?: string; payload?: { session_id?: string } },
    _sender,
    sendResponse: (response: unknown) => void,
  ) => {
    if (msg?.type !== "RECORDER_FINALIZE_REQUEST") return undefined
    // A tab bound to a different session stays silent so the target session's
    // recorder tab (or a definitive no-listener result) answers instead.
    if (!finalizeRequestMatchesSession(msg.payload?.session_id, boundSessionId)) return undefined
    void handleFinalizeRequest().then(sendResponse)
    return true  // async sendResponse
  },
)

// ── State polling ──────────────────────────────────────────────────────────────

function safeSendGet(): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage({ type: "GET_RECORDER_PRIVATE_STATE" }, (resp: RecorderPrivateState) => {
      if (chrome.runtime.lastError) {
        const m = chrome.runtime.lastError.message ?? ""
        if (m.includes("Extension context invalidated")) contextInvalidated = true
        return
      }
      if (resp && typeof (resp as { isRecording?: unknown }).isRecording === "boolean") {
        applyRecordingState(resp)
      }
    })
  } catch { /* context may be gone */ }
}

// Initial state check
safeSendGet()
// Poll every 1.5 s to keep recording status in sync
statePoll = setInterval(safeSendGet, 1500)

// Cleanup on page unload — the recording (if finalized) is already persisted in
// IndexedDB, so closing this tab never loses an unacknowledged upload.
window.addEventListener("unload", () => {
  if (statePoll) clearInterval(statePoll)
  endUploadKeepalive()
  cleanupStreamTracks()
})
