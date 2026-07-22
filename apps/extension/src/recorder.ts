// Recorder tab — persistent WebM screen recording for fullscreen / media sessions.
//
// MV3 design: this is a real browser tab (not the popup), so it keeps running
// while the user is in fullscreen on another tab.  It uses MediaRecorder to
// capture a WebM video from getDisplayMedia, then uploads it directly to the
// VeriBridge backend — no hop through the background service worker for the
// video bytes.
//
// Flow:
//   1. User clicks "Start Recording" in the popup → popup auto-opens this tab.
//   2. User clicks "Start Screen Capture" → user gesture → getDisplayMedia().
//   3. Browser screen-share picker → user selects Entire Screen or Window.
//   4. MediaRecorder starts → WebM chunks accumulate in memory.
//   5. User minimises this tab, enters fullscreen on another tab.
//   6. Recording continues (this tab's JS runs in background).
//   7. User exits fullscreen, returns here, clicks "Stop Screen Capture".
//   8. MediaRecorder stops → WebM blob assembled → uploaded to /workflow/video.
//   9. Upload result reported back to background via RECORDER_VIDEO_UPLOADED.
//  10. User goes to popup → Stop Recording → Send Proof.
//
// Why getDisplayMedia instead of captureVisibleTab:
//   captureVisibleTab returns black frames for hardware-decoded fullscreen video
//   (GPU overlay compositor bypasses the normal tab pixel pipeline).
//   getDisplayMedia at OS level captures what is actually displayed on screen.

import type { ExtensionState } from "./types"
import {
  authorizedUploadHeaders,
  MISSING_RECORDER_AUTH_MESSAGE,
  RECORDER_AUTH_BUILD_FINGERPRINT,
  recorderTokenMetadata,
  uploadEndpointUrl,
} from "./recorderAuth"

// ── Constants ─────────────────────────────────────────────────────────────────
/** Maximum recording duration in ms (5 minutes) after which capture auto-stops. */
const MAX_RECORDING_MS = 5 * 60 * 1000
/** Maximum video size accepted by the backend (100 MB). */
const MAX_VIDEO_BYTES = 100 * 1024 * 1024

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
let mediaRecorder: MediaRecorder | null = null
let videoChunks: Blob[] = []
let videoMimeType = "video/webm"
let recordingStartMs = 0
let durationTimer: ReturnType<typeof setInterval> | null = null
let autoStopTimer: ReturnType<typeof setTimeout> | null = null

let isRecordingActive = false   // background recording is active
let currentSessionId = ""
let currentApiUrl = "http://localhost:8000"
let currentAuthToken = ""

let isUploading = false
let uploadDone = false
let uploadError: string | null = null

let statePoll: ReturnType<typeof setInterval> | null = null
let contextInvalidated = false

async function recorderPageAuthDebug(): Promise<Record<string, unknown>> {
  const tokenMetadata = recorderTokenMetadata(currentAuthToken)
  let background: Record<string, unknown> | null = null
  try {
    background = await chrome.runtime.sendMessage({ type: "GET_RECORDER_AUTH_DEBUG_STATE" }) as Record<string, unknown>
  } catch { /* extension reload/context invalidation is reflected by null */ }
  return {
    component: "recorder-page",
    buildFingerprint: RECORDER_AUTH_BUILD_FINGERPRINT,
    extensionId: chrome.runtime.id,
    sessionId: currentSessionId,
    apiUrl: currentApiUrl,
    ...tokenMetadata,
    background,
  }
}

;(globalThis as Record<string, unknown>).__VB_RECORDER_AUTH_DEBUG__ = recorderPageAuthDebug
console.info("[RecorderAuth] recorder page loaded", {
  component: "recorder-page",
  buildFingerprint: RECORDER_AUTH_BUILD_FINGERPRINT,
  extensionId: chrome.runtime.id,
})

// ── DOM helpers ────────────────────────────────────────────────────────────────
function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const btnStart      = el<HTMLButtonElement>("btnStart")
const btnStop       = el<HTMLButtonElement>("btnStop")
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
    streamLblEl.textContent = "Screen capture active — minimise this tab and enter fullscreen"
    streamLblEl.className = "stream-label active"
    instructionsEl.classList.add("visible")
  } else {
    streamIndEl.textContent = "⚪"
    streamLblEl.textContent = "No screen selected"
    streamLblEl.className = "stream-label"
    instructionsEl.classList.remove("visible")
  }
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

function applyRecordingState(state: ExtensionState): void {
  const wasRecording = isRecordingActive
  isRecordingActive  = state.isRecording
  currentSessionId   = state.sessionId ?? ""
  currentApiUrl      = (state.apiUrl || "http://localhost:8000").replace(/\/$/, "")
  currentAuthToken   = state.authToken ?? ""

  if (state.isRecording) {
    recDot.className = "status-dot recording"
    recStatusEl.textContent = `Recording active · ${state.eventCount} event(s)`
  } else if (state.status === "stopped") {
    recDot.className = "status-dot stopped"
    recStatusEl.textContent = "Recording stopped — send proof from popup"
  } else if (state.status === "uploaded") {
    recDot.className = "status-dot"
    recStatusEl.textContent = "Proof uploaded ✓"
  } else {
    recDot.className = "status-dot"
    recStatusEl.textContent = "No active recording — start one in the extension popup"
  }

  recSessionEl.textContent = currentSessionId ? currentSessionId.slice(0, 16) + "…" : ""

  // Buttons: Start enabled only when recording active and no capture in progress
  const capturing = displayStream !== null || isUploading
  btnStart.disabled = !isRecordingActive || capturing
  btnStop.disabled  = displayStream === null || isUploading

  // If recording stopped from popup while screen capture is active, warn
  if (wasRecording && !isRecordingActive && displayStream) {
    setMsg(
      "Background recording stopped. Stop screen capture here too.",
      "warn",
    )
  }

  if (!isRecordingActive && !displayStream && !isUploading) {
    if (uploadDone && !uploadError) {
      setMsg("✓ Video uploaded. Return to extension popup → Stop Recording → Send Proof.", "ok")
    } else if (uploadError) {
      setMsg(`Video upload failed: ${uploadError}`, "err")
    } else {
      setMsg('Start a recording session in the extension popup first, then click "Start Screen Capture" here.')
    }
  }
}

// ── Video upload ───────────────────────────────────────────────────────────────

async function uploadVideo(blob: Blob): Promise<void> {
  isUploading = true
  uploadDone  = false
  uploadError = null
  updateDurationBadge()
  setMsg(`Uploading recording (${(blob.size / 1024 / 1024).toFixed(1)} MB) to backend…`, "default")
  btnStop.disabled = true
  btnStart.disabled = true

  const sessionId = currentSessionId
  const apiUrl    = currentApiUrl
  const authToken = currentAuthToken

  if (!sessionId) {
    uploadError = "No session ID — cannot upload video"
    isUploading = false
    updateDurationBadge()
    setMsg(`Upload skipped: ${uploadError}`, "warn")
    notifyBackground(false, uploadError, 0)
    return
  }

  const headers = authorizedUploadHeaders(authToken)
  if (!headers) {
    uploadError = MISSING_RECORDER_AUTH_MESSAGE
    isUploading = false
    uploadDone = false
    updateDurationBadge()
    setMsg(`Video upload failed: ${uploadError}`, "err")
    notifyBackground(false, uploadError, 0)
    return
  }

  if (blob.size > MAX_VIDEO_BYTES) {
    uploadError = `Video too large (${(blob.size / 1024 / 1024).toFixed(0)} MB > 100 MB limit)`
    isUploading = false
    updateDurationBadge()
    setMsg(`Upload failed: ${uploadError}`, "err")
    notifyBackground(false, uploadError, 0)
    return
  }

  const ext  = videoMimeType.includes("mp4") ? "mp4" : "webm"
  const form = new FormData()
  form.append("video", blob, `recording.${ext}`)

  const url = uploadEndpointUrl(apiUrl, sessionId, "video")

  try {
    const resp = await fetch(url, { method: "POST", headers, body: form })
    const bodyText = await resp.text().catch(() => "")

    if (!resp.ok) {
      // Parse backend error detail for exact reason
      let reason = `HTTP ${resp.status}`
      try {
        const parsed = JSON.parse(bodyText) as { detail?: string | { message?: string } }
        const d = parsed?.detail
        reason = (typeof d === "string" ? d : d?.message) ?? reason
      } catch { /* keep HTTP status */ }
      reason = reason.slice(0, 200)
      if (resp.status === 401) {
        // Backend failed closed on a missing/expired token. Point the user at
        // the recovery path instead of the raw backend auth message.
        reason = MISSING_RECORDER_AUTH_MESSAGE
      }

      uploadError = reason
      isUploading = false
      uploadDone  = false
      updateDurationBadge()
      setMsg(`Video upload failed: ${reason}`, "err")
      notifyBackground(false, reason, 0)
      return
    }

    // Parse success response for keyframe count
    let keyframeCount = 0
    let uploadMsg = "Video uploaded."
    try {
      const parsed = JSON.parse(bodyText) as {
        keyframe_count?: number
        video_analysis_status?: string
        message?: string
      }
      keyframeCount = parsed?.keyframe_count ?? 0
      const status  = parsed?.video_analysis_status ?? "unknown"
      const kfStr   = keyframeCount > 0 ? `${keyframeCount} keyframe(s) extracted.` : "Keyframe extraction pending."
      uploadMsg = `✓ Video uploaded (${status}). ${kfStr}`
    } catch { /* keep default */ }

    uploadDone  = true
    isUploading = false
    uploadError = null
    updateDurationBadge()
    setMsg(uploadMsg + " Return to popup → Stop Recording → Send Proof.", "ok")
    notifyBackground(true, null, keyframeCount)

  } catch (err) {
    const msg = err instanceof Error ? err.message : "Network error — check your connection."
    uploadError = msg.slice(0, 200)
    isUploading = false
    updateDurationBadge()
    setMsg(`Video upload failed: ${uploadError}`, "err")
    notifyBackground(false, uploadError, 0)
  }

  // Re-evaluate button states
  btnStart.disabled = !isRecordingActive || displayStream !== null
  btnStop.disabled  = displayStream === null
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
    chrome.runtime.sendMessage({ type }, () => {
      if (chrome.runtime.lastError) { /* context may have been invalidated */ }
    })
  } catch { /* extension context may be gone */ }
}

/** Inform the background service worker about the upload result. */
function notifyBackground(ok: boolean, error: string | null, keyframeCount: number): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage(
      {
        type: "RECORDER_VIDEO_UPLOADED",
        payload: { ok, error, keyframe_count: keyframeCount },
      },
      () => { if (chrome.runtime.lastError) { /* ignore */ } },
    )
  } catch { /* context may be gone */ }
}

// ── MediaRecorder lifecycle ───────────────────────────────────────────────────

function startMediaRecorder(stream: MediaStream): void {
  videoChunks    = []
  videoMimeType  = chooseMimeType()
  recordingStartMs = Date.now()

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

  mediaRecorder.onstop = () => {
    if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
    if (autoStopTimer) { clearTimeout(autoStopTimer);  autoStopTimer  = null }
    const blob = new Blob(videoChunks, { type: videoMimeType })
    videoChunks = []
    if (blob.size < 100) {
      // Near-empty blob — nothing was captured
      setMsg("Recording stopped with no video data. Was the stream active?", "warn")
      updateDurationBadge()
      return
    }
    void uploadVideo(blob)
  }

  // 2-second timeslice — chunks arrive frequently so onstop gets data quickly
  mediaRecorder.start(2000)

  // Duration counter
  durationTimer = setInterval(updateDurationBadge, 1000)

  // Safety cap: auto-stop after MAX_RECORDING_MS
  autoStopTimer = setTimeout(() => {
    stopCapture()
    setMsg(`Auto-stopped after ${formatDuration(MAX_RECORDING_MS)} (max recording duration).`, "warn")
  }, MAX_RECORDING_MS)
}

// ── Start / stop capture ───────────────────────────────────────────────────────

async function startCapture(): Promise<void> {
  if (displayStream) return
  btnStart.disabled = true
  setMsg("Opening screen picker… select Entire Screen or your Window.", "default")

  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        frameRate: { ideal: 15, max: 30 },
        // No width/height constraints — let the OS pick native resolution
      },
      audio: false,  // Audio recording would require system permissions; skip for now
    })
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

  displayStream = stream
  uploadDone    = false
  uploadError   = null

  // Notify background so popup shows ONE unified status (no duplicate indicators)
  notifyStreamState(true)

  updateStreamUI(true)
  updateDurationBadge()
  setMsg("✓ Recording started! Minimise this tab and go fullscreen. Return here when done.", "ok")

  btnStart.disabled = true
  btnStop.disabled  = false

  startMediaRecorder(stream)

  // Auto-stop when user clicks browser "Stop sharing" button
  stream.getVideoTracks().forEach((track) => {
    track.addEventListener("ended", () => {
      // MediaRecorder.stop() triggers onstop → uploadVideo
      cleanupStream()
    })
  })
}

/** Stop the MediaRecorder (which triggers onstop → uploadVideo), then clean up stream. */
function stopCapture(): void {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    // Requesting final chunk, then onstop fires
    mediaRecorder.stop()
  }
  cleanupStream()
}

function cleanupStream(): void {
  if (durationTimer)  { clearInterval(durationTimer); durationTimer = null }
  if (autoStopTimer)  { clearTimeout(autoStopTimer);  autoStopTimer  = null }
  const hadStream = displayStream !== null
  if (displayStream) {
    displayStream.getTracks().forEach((t) => t.stop())
    displayStream = null
  }
  mediaRecorder = null
  // Notify background that screen capture ended (popup can re-enable Stop/Send)
  if (hadStream) notifyStreamState(false)
  updateStreamUI(false)
  btnStart.disabled = !isRecordingActive
  btnStop.disabled  = true
}

// ── Button handlers ────────────────────────────────────────────────────────────

btnStart.addEventListener("click", () => { void startCapture() })
btnStop.addEventListener("click",  stopCapture)

// ── State polling ──────────────────────────────────────────────────────────────

function safeSendGet(): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp: ExtensionState) => {
      if (chrome.runtime.lastError) {
        const m = chrome.runtime.lastError.message ?? ""
        if (m.includes("Extension context invalidated")) contextInvalidated = true
        return
      }
      if (resp) applyRecordingState(resp)
    })
  } catch { /* context may be gone */ }
}

// Initial state check
safeSendGet()
// Poll every 1.5 s to keep recording status in sync
statePoll = setInterval(safeSendGet, 1500)

// Cleanup on page unload
window.addEventListener("unload", () => {
  if (statePoll) clearInterval(statePoll)
  cleanupStream()
})
