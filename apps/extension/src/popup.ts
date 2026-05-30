// Popup — VeriBridge extension recording controls.
//
// Unified Phase-0 flow:
//   1. Paste session ID → Start Recording
//   2. Recorder tab opens automatically (getDisplayMedia requires user gesture there)
//   3. In recorder tab: Start Screen Capture → go fullscreen → Stop Screen Capture → video uploads
//   4. Back to popup: Stop Recording → Send Proof
//
// captureVisibleTab is used ONLY as a background helper for DOM-event correlated
// screenshots — it is NOT the primary visual recorder and NOT surfaced in the UI.

import type { ExtensionState, RecordingStatus } from "./types"

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const sessionIdInput    = el<HTMLInputElement>("sessionId")
const apiUrlInput       = el<HTMLInputElement>("apiUrl")
const authTokenInput    = el<HTMLInputElement>("authToken")
const finalNoteInput    = el<HTMLTextAreaElement>("finalNote")
const btnStart          = el<HTMLButtonElement>("btnStart")
const btnStop           = el<HTMLButtonElement>("btnStop")
const btnSend           = el<HTMLButtonElement>("btnSend")
const btnReopenRecorder = el<HTMLButtonElement>("btnReopenRecorder")
const statusDot         = el("statusDot")
const statusText        = el("statusText")
const eventCountEl      = el("eventCount")
const detectedBanner    = el("detectedBanner")
const videoStatusEl     = el("videoStatus")

// ── Restore persisted inputs ───────────────────────────────────────────────────
chrome.storage.local.get(["sessionId", "apiUrl", "authToken", "currentSessionId"], (data) => {
  const preFill = (data.currentSessionId as string | undefined) ?? (data.sessionId as string | undefined) ?? ""
  if (preFill) sessionIdInput.value = preFill
  apiUrlInput.value = (data.apiUrl as string | undefined) ?? "http://localhost:8000"
  if (data.authToken) authTokenInput.value = data.authToken as string
})

sessionIdInput.addEventListener("input", () => {
  void chrome.storage.local.set({ sessionId: sessionIdInput.value })
})
apiUrlInput.addEventListener("input", () => {
  void chrome.storage.local.set({ apiUrl: apiUrlInput.value })
})
authTokenInput.addEventListener("input", () => {
  void chrome.storage.local.set({ authToken: authTokenInput.value })
})

// ── Status dot class mapping ───────────────────────────────────────────────────
const DOT_CLASS: Record<RecordingStatus, string> = {
  idle:          "",
  ready:         "ready",
  recording:     "recording",
  stopped:       "stopped",
  uploading:     "stopped",
  uploaded:      "uploaded",
  upload_failed: "error",
  error:         "error",
}

function applyState(state: ExtensionState): void {
  statusDot.className = `status-dot ${DOT_CLASS[state.status] ?? ""}`.trim()
  statusText.textContent = state.statusMessage

  eventCountEl.textContent =
    state.eventCount > 0 ? `${state.eventCount} event(s) captured` : ""

  if (state.sessionId && !sessionIdInput.value.trim()) {
    sessionIdInput.value = state.sessionId
  }

  detectedBanner.style.display = state.status === "ready" ? "" : "none"

  btnStart.disabled = state.isRecording || state.status === "uploading"
  btnStop.disabled = !state.isRecording
  btnSend.disabled =
    state.isRecording ||
    state.status === "uploading" ||
    !["stopped", "upload_failed", "error"].includes(state.status)

  // "Re-open Recorder Tab" — available whenever recording is active
  btnReopenRecorder.style.display = state.isRecording ? "" : "none"

  // ── Video upload status bar ────────────────────────────────────────────────
  const vs = state.videoUploadStatus
  if (vs === "none" || !vs) {
    videoStatusEl.style.display = "none"
    videoStatusEl.textContent = ""
  } else if (vs === "uploading") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status uploading"
    videoStatusEl.textContent = "⏳ Uploading screen recording…"
  } else if (vs === "uploaded") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status uploaded"
    const kf = state.videoKeyframeCount ?? 0
    videoStatusEl.textContent =
      kf > 0
        ? `✓ Recording uploaded — ${kf} keyframe(s) extracted`
        : "✓ Screen recording uploaded"
  } else if (vs === "failed") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status failed"
    videoStatusEl.textContent = `✗ Video upload failed: ${state.videoUploadError ?? "unknown error"}`
  }
}

function refreshState(): void {
  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp: ExtensionState) => {
    if (chrome.runtime.lastError) return
    applyState(resp)
  })
}

refreshState()
const poll = setInterval(refreshState, 1000)
window.addEventListener("unload", () => clearInterval(poll))

// ── Start recording ────────────────────────────────────────────────────────────
// The background service worker auto-opens the recorder tab on START_RECORDING.

btnStart.addEventListener("click", () => {
  const sessionId = sessionIdInput.value.trim()
  const apiUrl = apiUrlInput.value.trim() || "http://localhost:8000"
  const authToken = authTokenInput.value.trim()

  if (!sessionId) {
    statusText.textContent = "Enter a session ID first."
    return
  }

  chrome.runtime.sendMessage(
    { type: "START_RECORDING", payload: { sessionId, apiUrl, authToken } },
    () => refreshState()
  )
})

// ── Stop recording ─────────────────────────────────────────────────────────────

btnStop.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "STOP_RECORDING" }, () => refreshState())
})

// ── Send proof ─────────────────────────────────────────────────────────────────

btnSend.addEventListener("click", () => {
  const finalNote = finalNoteInput.value.trim() || null
  btnSend.disabled = true
  statusText.textContent = "Uploading…"

  chrome.runtime.sendMessage(
    { type: "SEND_PROOF", payload: { finalNote } },
    (resp: { ok: boolean; error?: string }) => {
      if (chrome.runtime.lastError) {
        statusText.textContent = `Error: ${chrome.runtime.lastError.message ?? "unknown"}`
        btnSend.disabled = false
        return
      }
      if (!resp?.ok && resp?.error) {
        statusText.textContent = `Upload failed: ${resp.error}`
      }
      refreshState()
    }
  )
})

// ── Re-open Recorder Tab (fallback if user closed it) ─────────────────────────

btnReopenRecorder.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "OPEN_RECORDER_TAB" }, () => { /* tab opens */ })
})
