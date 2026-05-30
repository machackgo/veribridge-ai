import type { ExtensionState, RecordingStatus } from "./types"

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const sessionIdInput       = el<HTMLInputElement>("sessionId")
const apiUrlInput          = el<HTMLInputElement>("apiUrl")
const authTokenInput       = el<HTMLInputElement>("authToken")
const finalNoteInput       = el<HTMLTextAreaElement>("finalNote")
const btnStart             = el<HTMLButtonElement>("btnStart")
const btnStop              = el<HTMLButtonElement>("btnStop")
const btnSend              = el<HTMLButtonElement>("btnSend")
const btnCaptureScreen     = el<HTMLButtonElement>("btnCaptureScreen")
const captureScreenStatus  = el("captureScreenStatus")
const btnOpenRecorder      = el<HTMLButtonElement>("btnOpenRecorder")
const recorderTabStatus    = el("recorderTabStatus")
const statusDot            = el("statusDot")
const statusText           = el("statusText")
const eventCountEl         = el("eventCount")
const detectedBanner       = el("detectedBanner")

// ── Restore persisted inputs ───────────────────────────────────────────────────
// currentSessionId is written by the background when a session is detected from a page URL.
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

  // Pre-fill session ID if the field is currently empty and the background has one.
  if (state.sessionId && !sessionIdInput.value.trim()) {
    sessionIdInput.value = state.sessionId
  }

  // Show detection banner when a session has been auto-detected but recording hasn't started.
  detectedBanner.style.display = state.status === "ready" ? "" : "none"

  btnStart.disabled = state.isRecording || state.status === "uploading"
  btnStop.disabled = !state.isRecording
  // Enable Send for stopped, upload_failed (retry), and error states.
  btnSend.disabled =
    state.isRecording ||
    state.status === "uploading" ||
    !["stopped", "upload_failed", "error"].includes(state.status)

  // Enable screen capture tools when a session is active (recording or stopped, before upload).
  const screenEnabled =
    state.status !== "idle" &&
    state.status !== "uploading" &&
    state.status !== "uploaded"
  btnCaptureScreen.disabled = !screenEnabled

  // Open Recorder Tab: enable when recording is active (user should set up before going fullscreen)
  btnOpenRecorder.disabled = !state.isRecording
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

// ── Open Fullscreen Recorder Tab ───────────────────────────────────────────────
// Opens recorder.html as a separate browser tab.  Unlike the popup (which closes
// when the user clicks away or enters fullscreen), this tab persists and continues
// running the getDisplayMedia frame-capture loop in the background.

btnOpenRecorder.addEventListener("click", () => {
  btnOpenRecorder.disabled = true
  recorderTabStatus.textContent = "Opening recorder tab…"

  chrome.runtime.sendMessage({ type: "OPEN_RECORDER_TAB" }, (resp: { ok: boolean; tabId?: number; error?: string }) => {
    if (chrome.runtime.lastError || !resp?.ok) {
      recorderTabStatus.textContent = `Error: ${chrome.runtime.lastError?.message ?? resp?.error ?? "unknown"}`
      btnOpenRecorder.disabled = false
      return
    }
    recorderTabStatus.textContent = "✓ Recorder tab opened — switch to it and click Start Screen Capture"
    // Re-enable after a short delay so the user can open another tab if needed
    setTimeout(() => {
      recorderTabStatus.textContent = ""
      refreshState()  // re-evaluates btnOpenRecorder.disabled
    }, 4000)
  })
})

// ── ImageCapture type shim ─────────────────────────────────────────────────────
// The TypeScript DOM lib does not include ImageCapture.grabFrame().
interface ImageCaptureShim {
  grabFrame(): Promise<ImageBitmap>
}
declare const ImageCapture: {
  new (track: MediaStreamTrack): ImageCaptureShim
} | undefined

// ── Screen / window capture (getDisplayMedia) — manual fallback ────────────────
// One-shot screen grab from the popup.  Useful for:
//   • After exiting fullscreen (popup is accessible again)
//   • Users who don't need the persistent recorder tab
//   • Quick frame grab at any point during recording
//
// For continuous capture DURING fullscreen, use the Recorder Tab instead.

btnCaptureScreen.addEventListener("click", () => {
  void captureScreenNow()
})

async function captureScreenNow(): Promise<void> {
  btnCaptureScreen.disabled = true
  captureScreenStatus.textContent = "Opening screen picker…"

  let stream: MediaStream | null = null
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 1 },   // one frame is enough for a snapshot
      audio: false,
    })

    captureScreenStatus.textContent = "Capturing frame…"

    const track = stream.getVideoTracks()[0]
    if (!track) throw new Error("No video track")

    let base64: string

    if (typeof ImageCapture !== "undefined" && ImageCapture !== undefined) {
      const capture = new ImageCapture(track)
      const bitmap  = await capture.grabFrame()
      const canvas  = document.createElement("canvas")
      canvas.width  = bitmap.width
      canvas.height = bitmap.height
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new Error("Canvas 2D context unavailable")
      ctx.drawImage(bitmap, 0, 0)
      bitmap.close()
      const dataUrl = canvas.toDataURL("image/jpeg", 0.5)
      const comma = dataUrl.indexOf(",")
      base64 = dataUrl.slice(comma + 1)
    } else {
      // Fallback: draw stream to a <video> element, then snapshot via canvas.
      const video = document.createElement("video")
      video.srcObject = stream
      video.muted = true
      await new Promise<void>((resolve) => {
        video.onloadedmetadata = () => { void video.play().then(resolve) }
      })
      const canvas  = document.createElement("canvas")
      canvas.width  = video.videoWidth  || 1280
      canvas.height = video.videoHeight || 720
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new Error("Canvas 2D context unavailable")
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const dataUrl = canvas.toDataURL("image/jpeg", 0.5)
      const comma = dataUrl.indexOf(",")
      base64 = dataUrl.slice(comma + 1)
    }

    // Send to background
    chrome.runtime.sendMessage(
      {
        type: "CAPTURE_SCREEN_FRAME",
        payload: { frame_base64: base64, frame_type: "screen_capture_manual" },
      },
      (resp: { ok: boolean; error?: string; total?: number }) => {
        if (chrome.runtime.lastError || !resp?.ok) {
          captureScreenStatus.textContent =
            `Failed: ${chrome.runtime.lastError?.message ?? resp?.error ?? "unknown"}`
        } else {
          captureScreenStatus.textContent =
            `✓ Screen captured (${resp.total ?? "?"} frames total)`
          setTimeout(() => { captureScreenStatus.textContent = "" }, 4000)
        }
        refreshState()
      }
    )
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (msg.includes("Permission denied") || msg.includes("NotAllowedError")) {
      captureScreenStatus.textContent = "Screen capture cancelled."
    } else {
      captureScreenStatus.textContent = `Error: ${msg.slice(0, 60)}`
    }
    setTimeout(() => { captureScreenStatus.textContent = "" }, 5000)
  } finally {
    // Always stop all tracks — never leave a persistent screen-share stream.
    stream?.getTracks().forEach((t) => t.stop())
    refreshState()  // re-evaluates btnCaptureScreen.disabled
  }
}
