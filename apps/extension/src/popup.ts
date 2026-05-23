import type { ExtensionState, RecordingStatus } from "./types"

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const sessionIdInput = el<HTMLInputElement>("sessionId")
const apiUrlInput = el<HTMLInputElement>("apiUrl")
const authTokenInput = el<HTMLInputElement>("authToken")
const finalNoteInput = el<HTMLTextAreaElement>("finalNote")
const btnStart = el<HTMLButtonElement>("btnStart")
const btnStop = el<HTMLButtonElement>("btnStop")
const btnSend = el<HTMLButtonElement>("btnSend")
const statusDot = el("statusDot")
const statusText = el("statusText")
const eventCountEl = el("eventCount")

// Restore persisted inputs
chrome.storage.local.get(["sessionId", "apiUrl", "authToken"], (data) => {
  if (data.sessionId) sessionIdInput.value = data.sessionId as string
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
  idle: "",
  recording: "recording",
  stopped: "stopped",
  uploading: "stopped",
  uploaded: "uploaded",
  error: "error",
}

function applyState(state: ExtensionState): void {
  statusDot.className = `status-dot ${DOT_CLASS[state.status] ?? ""}`.trim()
  statusText.textContent = state.statusMessage
  eventCountEl.textContent =
    state.eventCount > 0 ? `${state.eventCount} event(s) captured` : ""

  btnStart.disabled = state.isRecording
  btnStop.disabled = !state.isRecording
  btnSend.disabled =
    state.isRecording || !["stopped", "error"].includes(state.status)
}

function refreshState(): void {
  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp: ExtensionState) => {
    if (chrome.runtime.lastError) return
    applyState(resp)
  })
}

refreshState()
const poll = setInterval(refreshState, 1000)

// Clean up poll when popup is closed
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
        return
      }
      if (!resp.ok) {
        statusText.textContent = resp.error ?? "Upload failed."
      }
      refreshState()
    }
  )
})
