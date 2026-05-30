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
const statusDot            = el("statusDot")
const statusText           = el("statusText")
const eventCountEl         = el("eventCount")
const detectedBanner       = el("detectedBanner")

// Restore persisted inputs.
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

const DOT_CLASS: Record<RecordingStatus, string> = {
  idle:         "",
  ready:        "ready",
  recording:    "recording",
  stopped:      "stopped",
  uploading:    "stopped",
  uploaded:     "uploaded",
  upload_failed: "error",
  error:        "error",
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
  // Enable Capture Screen when a session is active (recording or stopped, before upload).
  btnCaptureScreen.disabled =
    state.status === "idle" ||
    state.status === "uploading" ||
    state.status === "uploaded"
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

btnStop.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "STOP_RECORDING" }, () => refreshState())
})

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

// ── ImageCapture type shim ─────────────────────────────────────────────────
// The TypeScript DOM lib does not include ImageCapture.grabFrame().
// Define a minimal interface so we can call it without a cast error.
interface ImageCaptureShim {
  grabFrame(): Promise<ImageBitmap>
}
declare const ImageCapture: {
  new (track: MediaStreamTrack): ImageCaptureShim
} | undefined

// ── Screen / window capture (getDisplayMedia) ──────────────────────────────
// Uses the browser's built-in screen-share picker (getDisplayMedia) to capture
// a single JPEG frame from the user's screen/window/tab.  This bypasses the
// hardware-overlay limitation that causes captureVisibleTab to return a black
// frame during native fullscreen video playback.
//
// Workflow:
//   1. User exits fullscreen (or uses any point in recording).
//   2. Clicks "Capture Screen Now" in the popup.
//   3. Browser shows screen-share picker → user selects screen/window.
//   4. Popup grabs one frame from the video track, draws to canvas, exports JPEG.
//   5. Sends base64 frame to background via CAPTURE_SCREEN_FRAME.
//   6. Background adds it to state.visualFrames alongside normal screenshots.

btnCaptureScreen.addEventListener("click", () => {
  void captureScreenNow()
})

async function captureScreenNow(): Promise<void> {
  btnCaptureScreen.disabled = true
  captureScreenStatus.textContent = "Opening screen picker…"

  let stream: MediaStream | null = null
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 1 },  // one frame is enough
      audio: false,
    })

    captureScreenStatus.textContent = "Capturing frame…"

    const track = stream.getVideoTracks()[0]
    if (!track) throw new Error("No video track")

    // Grab one frame via ImageCapture API (available in Chrome 60+)
    // Fall back to drawing a video element to canvas if ImageCapture is absent.
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
      { type: "CAPTURE_SCREEN_FRAME", payload: { frame_base64: base64, frame_type: "screen_capture_manual" } },
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
    // "Permission denied" (user cancelled picker) → silent feedback.
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
