// Background service worker — manages recording state and uploads proof to the backend.

import type { WorkflowEvent, ExtensionState, RecordingStatus } from "./types"

interface InternalState {
  sessionId: string
  apiUrl: string
  authToken: string
  isRecording: boolean
  events: WorkflowEvent[]
  startedAt: string | null
  stoppedAt: string | null
  status: RecordingStatus
  statusMessage: string
}

const state: InternalState = {
  sessionId: "",
  apiUrl: "http://localhost:8000",
  authToken: "",
  isRecording: false,
  events: [],
  startedAt: null,
  stoppedAt: null,
  status: "idle",
  statusMessage: "Ready",
}

async function broadcastToAllTabs(message: unknown): Promise<void> {
  const tabs = await chrome.tabs.query({})
  for (const tab of tabs) {
    if (tab.id !== undefined) {
      chrome.tabs.sendMessage(tab.id, message).catch(() => undefined)
    }
  }
}

function publicState(): ExtensionState {
  return {
    sessionId: state.sessionId,
    apiUrl: state.apiUrl,
    authToken: state.authToken,
    isRecording: state.isRecording,
    eventCount: state.events.length,
    startedAt: state.startedAt,
    stoppedAt: state.stoppedAt,
    status: state.status,
    statusMessage: state.statusMessage,
  }
}

chrome.runtime.onMessage.addListener(
  (msg: { type: string; payload?: unknown }, _sender, sendResponse) => {
    switch (msg.type) {
      case "GET_STATE":
        sendResponse(publicState())
        break

      case "START_RECORDING": {
        const { sessionId, apiUrl, authToken } = msg.payload as {
          sessionId: string
          apiUrl: string
          authToken: string
        }
        state.sessionId = sessionId
        state.apiUrl = (apiUrl || "http://localhost:8000").replace(/\/$/, "")
        state.authToken = authToken
        state.isRecording = true
        state.events = []
        state.startedAt = new Date().toISOString()
        state.stoppedAt = null
        state.status = "recording"
        state.statusMessage = "Recording…"
        void broadcastToAllTabs({ type: "START_CAPTURING" })
        sendResponse({ ok: true })
        break
      }

      case "STOP_RECORDING":
        state.isRecording = false
        state.stoppedAt = new Date().toISOString()
        state.status = "stopped"
        state.statusMessage = `Stopped — ${state.events.length} event(s) captured.`
        void broadcastToAllTabs({ type: "STOP_CAPTURING" })
        sendResponse({ ok: true })
        break

      case "SEND_PROOF": {
        const { finalNote } = (msg.payload ?? {}) as { finalNote: string | null }
        void sendProof(finalNote).then(
          () => sendResponse({ ok: true }),
          (err: unknown) => sendResponse({ ok: false, error: String(err) })
        )
        return true // keep message channel open for async response
      }

      case "SESSION_DETECTED_FROM_PAGE": {
        const { session_id } = msg.payload as {
          session_id: string
          page_url: string
          page_title: string
          detected_at: string
        }
        // Never overwrite a different actively-recording session
        if (state.isRecording && state.sessionId !== session_id) {
          sendResponse({ ok: false, reason: "different session active" })
          break
        }
        // Persist for popup pre-fill across service-worker restarts
        void chrome.storage.local.set({ currentSessionId: session_id })
        if (!state.isRecording) {
          state.sessionId = session_id
          state.status = "ready"
          state.statusMessage =
            "Proof session detected from VeriBridge. You can start recording."
        }
        sendResponse({ ok: true })
        break
      }

      case "WORKFLOW_EVENT":
        if (state.isRecording) {
          state.events.push(msg.payload as WorkflowEvent)
        }
        break
    }
  }
)

async function sendProof(finalNote: string | null): Promise<void> {
  if (!state.sessionId) throw new Error("No session ID configured.")

  state.status = "uploading"
  state.statusMessage = "Uploading proof…"

  const payload = {
    workflow_events: state.events,
    screenshots: [] as unknown[],
    browser_metadata: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      platform: navigator.platform,
    },
    extension_version: chrome.runtime.getManifest().version,
    started_at: state.startedAt,
    stopped_at: state.stoppedAt ?? new Date().toISOString(),
    student_final_note: finalNote ?? null,
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`

  const resp = await fetch(
    `${state.apiUrl}/api/v1/student/extension-proof/sessions/${state.sessionId}/upload`,
    { method: "POST", headers, body: JSON.stringify(payload) }
  )

  if (!resp.ok) {
    const body = await resp.text().catch(() => "")
    state.status = "error"
    state.statusMessage = `Upload failed (${resp.status}): ${body.slice(0, 120)}`
    throw new Error(state.statusMessage)
  }

  state.status = "uploaded"
  state.statusMessage = "Proof uploaded successfully ✓"
}
