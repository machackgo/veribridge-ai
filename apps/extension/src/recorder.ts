// Recorder tab — persistent screen capture for fullscreen / media recording sessions.
//
// This is a dedicated Chrome extension page (NOT the popup).  It opens as a real
// browser tab so it survives popup close and continues running while the user
// watches fullscreen video on another tab.
//
// Flow:
//   1. User clicks "Open Fullscreen Recorder" in the extension popup.
//   2. This tab opens.  Background recording must already be active.
//   3. User clicks "Start Screen Capture" → user gesture → getDisplayMedia() succeeds.
//   4. Browser screen-share picker appears → user selects Entire Screen or Window.
//   5. This tab captures one JPEG frame every 2 s via canvas / ImageCapture API.
//   6. Each frame is sent to the background service worker (CAPTURE_SCREEN_FRAME).
//   7. User minimises this tab, enters fullscreen on another tab.
//   8. Frame capture CONTINUES (this tab's JS keeps running in the background).
//   9. User exits fullscreen, returns here, clicks "Stop Screen Capture".
//  10. User then uses extension popup → Stop Recording → Send Proof.
//
// Chrome note: getDisplayMedia at OS level bypasses the hardware-decoded video
// compositor limitation that makes captureVisibleTab return black frames during
// native fullscreen playback.  Selecting "Entire Screen" in the picker is the
// recommended choice for fullscreen video proof.

import type { ExtensionState } from "./types"

// ── ImageCapture type shim ─────────────────────────────────────────────────
// TypeScript DOM lib does not include ImageCapture.grabFrame().
interface ImageCaptureShim {
  grabFrame(): Promise<ImageBitmap>
}
declare const ImageCapture:
  | { new (track: MediaStreamTrack): ImageCaptureShim }
  | undefined

// ── Constants ─────────────────────────────────────────────────────────────────
/** Milliseconds between consecutive frame captures. */
const CAPTURE_INTERVAL_MS = 2000
/** Hard cap per session — prevents unbounded memory growth. */
const MAX_FRAMES_PER_SESSION = 40

// ── Module state ──────────────────────────────────────────────────────────────
let displayStream: MediaStream | null = null
let captureInterval: ReturnType<typeof setInterval> | null = null
let framesSent = 0
let isRecordingActive = false
let currentSessionId = ""
let statePoll: ReturnType<typeof setInterval> | null = null
let contextInvalidated = false

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
const frameBadgeEl  = el("frameBadge")
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
    streamIndEl.textContent = "🟢"
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

function updateFrameBadge(): void {
  frameBadgeEl.textContent = `${framesSent} frame${framesSent !== 1 ? "s" : ""}`
  frameBadgeEl.className = `frame-badge${framesSent > 0 ? " has-frames" : ""}`
}

function applyRecordingState(state: ExtensionState): void {
  const wasRecording = isRecordingActive
  isRecordingActive  = state.isRecording
  currentSessionId   = state.sessionId ?? ""

  // Update recording status dot and label
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

  // Enable Start only when recording is active and no stream yet
  btnStart.disabled = !isRecordingActive || displayStream !== null
  // Stop enabled only when stream is active
  btnStop.disabled = displayStream === null

  // If recording just stopped while stream is active, notify user
  if (wasRecording && !isRecordingActive && displayStream) {
    setMsg(
      "Recording stopped from the extension popup. Stop screen capture here too, then send proof.",
      "warn",
    )
  }

  // Initial message when no recording is active
  if (!isRecordingActive && !displayStream) {
    setMsg(
      'Start a recording session in the extension popup first, then click "Start Screen Capture" here.',
    )
  }
}

// ── Frame capture ──────────────────────────────────────────────────────────────

/**
 * Grab one JPEG frame from the display stream.
 * Prefers ImageCapture.grabFrame() (Chrome 60+) and falls back to a <video> element.
 * Returns null on any error so capture keeps running.
 */
async function grabFrame(track: MediaStreamTrack): Promise<string | null> {
  try {
    if (typeof ImageCapture !== "undefined" && ImageCapture !== undefined) {
      const ic     = new ImageCapture(track)
      const bitmap = await ic.grabFrame()
      const canvas = document.createElement("canvas")
      canvas.width  = bitmap.width
      canvas.height = bitmap.height
      const ctx = canvas.getContext("2d")
      if (!ctx) { bitmap.close(); return null }
      ctx.drawImage(bitmap, 0, 0)
      bitmap.close()
      const dataUrl = canvas.toDataURL("image/jpeg", 0.5)
      return dataUrl.slice(dataUrl.indexOf(",") + 1)
    }

    // Fallback: draw through a <video> element.
    // We create a temporary stream wrapping the single track so the video element
    // can display it without affecting the module-level displayStream reference.
    const tmpStream = new MediaStream([track])
    const video = document.createElement("video")
    video.srcObject = tmpStream
    video.muted = true
    await new Promise<void>((resolve, reject) => {
      video.onloadedmetadata = () => {
        video.play().then(resolve).catch(reject)
      }
      video.onerror = () => reject(new Error("video error"))
      setTimeout(() => reject(new Error("video timeout")), 3000)
    })
    const canvas = document.createElement("canvas")
    canvas.width  = video.videoWidth  || 1280
    canvas.height = video.videoHeight || 720
    const ctx = canvas.getContext("2d")
    if (!ctx) { video.pause(); video.srcObject = null; return null }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    video.pause()
    video.srcObject = null
    const dataUrl = canvas.toDataURL("image/jpeg", 0.5)
    return dataUrl.slice(dataUrl.indexOf(",") + 1)
  } catch (err) {
    console.warn("[VB Recorder] grabFrame error:", err)
    return null
  }
}

/** Send one captured frame to the background service worker. */
function sendFrame(base64: string): void {
  if (contextInvalidated) return
  chrome.runtime.sendMessage(
    {
      type: "CAPTURE_SCREEN_FRAME",
      payload: { frame_base64: base64, frame_type: "fullscreen_recorder" },
    },
    (resp: { ok: boolean; error?: string; total?: number }) => {
      if (chrome.runtime.lastError) {
        const msg = chrome.runtime.lastError.message ?? "unknown"
        if (msg.includes("Extension context invalidated")) {
          contextInvalidated = true
          setMsg("Extension was reloaded. Refresh this tab.", "err")
        }
        return
      }
      if (!resp?.ok) {
        if (resp?.error === "Frame cap reached") {
          // Background has hit its frame limit — stop capturing
          stopCapture()
          setMsg(
            `Frame cap reached (${MAX_FRAMES_PER_SESSION} max). Stop recording and send proof.`,
            "warn",
          )
        } else if (resp?.error === "Not recording") {
          setMsg("Recording is not active. Start recording in the popup first.", "warn")
        }
      }
    },
  )
}

/** Capture one frame and send it. Called by the capture interval. */
async function captureOneTick(): Promise<void> {
  if (!displayStream || framesSent >= MAX_FRAMES_PER_SESSION) {
    stopCapture()
    return
  }
  const track = displayStream.getVideoTracks()[0]
  if (!track) { stopCapture(); return }

  const base64 = await grabFrame(track)
  if (!base64) return  // silently skip failed captures

  framesSent++
  updateFrameBadge()
  sendFrame(base64)
}

// ── Start / stop capture ───────────────────────────────────────────────────────

async function startCapture(): Promise<void> {
  if (displayStream) return   // already capturing
  btnStart.disabled = true
  setMsg("Opening screen picker… select Entire Screen or your Window.", "default")

  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 2, max: 5 } },
      audio: false,
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (msg.includes("Permission denied") || msg.includes("NotAllowedError")) {
      setMsg("Screen selection cancelled. Click Start to try again.")
    } else {
      setMsg(`Could not open screen picker: ${msg.slice(0, 80)}`, "err")
    }
    btnStart.disabled = !isRecordingActive
    return
  }

  displayStream = stream
  framesSent    = 0
  updateStreamUI(true)
  updateFrameBadge()
  setMsg(
    "✓ Screen capture started! Minimise this tab and enter fullscreen on your video page.",
    "ok",
  )
  btnStart.disabled = true
  btnStop.disabled  = false

  // Capture the first frame immediately, then on interval
  await captureOneTick()
  captureInterval = setInterval(() => { void captureOneTick() }, CAPTURE_INTERVAL_MS)

  // Handle stream ending via browser UI (user clicks the "Stop sharing" button)
  stream.getVideoTracks().forEach((track) => {
    track.addEventListener("ended", () => {
      cleanupStream()
      setMsg(
        `Screen sharing ended by browser. ${framesSent} frame(s) captured and saved to proof.`,
        "warn",
      )
    })
  })
}

/** Stop and clean up the display stream and interval. Does NOT modify framesSent. */
function cleanupStream(): void {
  if (captureInterval) { clearInterval(captureInterval); captureInterval = null }
  if (displayStream) {
    displayStream.getTracks().forEach((t) => t.stop())
    displayStream = null
  }
  updateStreamUI(false)
  btnStart.disabled = !isRecordingActive
  btnStop.disabled  = true
}

function stopCapture(): void {
  const captured = framesSent
  cleanupStream()
  if (captured > 0) {
    setMsg(
      `✓ Capture stopped. ${captured} frame(s) saved to the proof session. ` +
      `Return to the extension popup → Stop Recording → Send Proof.`,
      "ok",
    )
  } else {
    setMsg("Capture stopped. No frames were captured.")
  }
}

// ── Button handlers ────────────────────────────────────────────────────────────

btnStart.addEventListener("click", () => { void startCapture() })
btnStop.addEventListener("click",  () => { stopCapture() })

// ── State polling ──────────────────────────────────────────────────────────────

function safeSendGet(): void {
  if (contextInvalidated) return
  try {
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp: ExtensionState) => {
      if (chrome.runtime.lastError) {
        const msg = chrome.runtime.lastError.message ?? ""
        if (msg.includes("Extension context invalidated")) {
          contextInvalidated = true
        }
        return
      }
      if (resp) applyRecordingState(resp)
    })
  } catch { /* context may be gone */ }
}

// Initial state check
safeSendGet()
// Poll every 1.5 s to keep status in sync with recording / upload progress
statePoll = setInterval(safeSendGet, 1500)

// Cleanup on page unload
window.addEventListener("unload", () => {
  if (statePoll) clearInterval(statePoll)
  cleanupStream()
})
