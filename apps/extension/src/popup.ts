import type { ExtensionState, RecordingStatus } from "./types"

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const sessionIdInput  = el<HTMLInputElement>("sessionId")
const apiUrlInput     = el<HTMLInputElement>("apiUrl")
const authTokenInput  = el<HTMLInputElement>("authToken")
const finalNoteInput  = el<HTMLTextAreaElement>("finalNote")
const btnStart        = el<HTMLButtonElement>("btnStart")
const btnStop         = el<HTMLButtonElement>("btnStop")
const btnSend         = el<HTMLButtonElement>("btnSend")
const statusDot       = el("statusDot")
const statusText      = el("statusText")
const eventCountEl    = el("eventCount")
const detectedBanner  = el("detectedBanner")

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
