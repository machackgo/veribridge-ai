// Background service worker — manages recording state and uploads proof to the backend.

import type { WorkflowEvent, ExtensionState, RecordingStatus, VisibleEvidenceEvent } from "./types"

// ── URL privacy redaction ─────────────────────────────────────────────────────
// Mirrors the same set used in content.ts. Defined here independently because
// the background service worker and content scripts run in separate V8 contexts.

const _SENSITIVE_QUERY_PARAMS = new Set([
  "token",
  "access_token",
  "id_token",
  "refresh_token",
  "api_key",
  "key",
  "secret",
  "password",
  "code",
  "auth",
  "session",
  "jwt",
])

/**
 * Redact sensitive query parameters from a URL string before storing it in
 * workflow events or tracked-URL lists.  Returns the original string unchanged
 * if it cannot be parsed or contains no sensitive parameters.
 */
function redactUrl(url: string): string {
  if (!url || url.startsWith("chrome://") || url.startsWith("about:")) return url
  try {
    const parsed = new URL(url)
    let changed = false
    parsed.searchParams.forEach((_, k) => {
      if (_SENSITIVE_QUERY_PARAMS.has(k.toLowerCase())) {
        parsed.searchParams.set(k, "[REDACTED]")
        changed = true
      }
    })
    return changed ? parsed.toString() : url
  } catch {
    return url.replace(
      /([?&])(token|access_token|id_token|refresh_token|api_key|key|secret|password|code|auth|session|jwt)(=[^&]*)/gi,
      "$1$2=[REDACTED]",
    )
  }
}

interface InternalState {
  sessionId: string
  apiUrl: string
  authToken: string
  isRecording: boolean
  events: WorkflowEvent[]
  /** Visible evidence DOM snapshots accumulated during the recording. */
  visibleEvidenceEvents: VisibleEvidenceEvent[]
  startedAt: string | null
  stoppedAt: string | null
  status: RecordingStatus
  statusMessage: string
  lastUploadError: string | null
  dismissedForSessionId: string
  // Tab tracking — maintained across the lifetime of one recording session.
  trackedTabIds: Set<number>
  originalTabId: number | null
  trackedTabUrls: Map<number, string>  // last known URL per tracked tab (for navigation detection)
}

const state: InternalState = {
  sessionId: "",
  apiUrl: "http://localhost:8000",
  authToken: "",
  isRecording: false,
  events: [],
  visibleEvidenceEvents: [],
  startedAt: null,
  stoppedAt: null,
  status: "idle",
  statusMessage: "Ready",
  lastUploadError: null,
  dismissedForSessionId: "",
  trackedTabIds: new Set(),
  originalTabId: null,
  trackedTabUrls: new Map(),
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
    lastUploadError: state.lastUploadError,
    dismissedForSessionId: state.dismissedForSessionId,
    trackedTabIds: [...state.trackedTabIds],
    originalTabId: state.originalTabId,
  }
}

chrome.runtime.onMessage.addListener(
  (msg: { type: string; payload?: unknown }, sender: chrome.runtime.MessageSender, sendResponse) => {
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
        state.visibleEvidenceEvents = []
        state.startedAt = new Date().toISOString()
        state.stoppedAt = null
        state.status = "recording"
        state.statusMessage = "Recording…"
        state.lastUploadError = null
        state.dismissedForSessionId = ""  // new session clears any prior dismiss
        // Reset tab tracking — seed with the original tab detected from the page URL.
        state.trackedTabIds = new Set()
        state.trackedTabUrls = new Map()
        if (state.originalTabId !== null) {
          state.trackedTabIds.add(state.originalTabId)
        }
        void broadcastToAllTabs({ type: "START_CAPTURING" })
        sendResponse({ ok: true })
        break
      }

      case "STOP_RECORDING":
        state.isRecording = false
        state.stoppedAt = new Date().toISOString()
        state.status = "stopped"
        state.statusMessage = `Stopped — ${state.events.length} event(s) captured. Click Send Proof to upload.`
        void broadcastToAllTabs({ type: "STOP_CAPTURING" })
        sendResponse({ ok: true })
        break

      case "SEND_PROOF": {
        // Guard against duplicate simultaneous uploads
        if (state.status === "uploading") {
          sendResponse({ ok: false, error: "Upload already in progress." })
          break
        }
        const { finalNote } = (msg.payload ?? {}) as { finalNote: string | null }
        void sendProof(finalNote).then((result) => sendResponse(result))
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
        // Remember which tab holds the VeriBridge proof URL so we can seed
        // trackedTabIds when recording starts.
        if (sender.tab?.id !== undefined) {
          state.originalTabId = sender.tab.id
        }
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

      case "DISMISS_UPLOAD_SUCCESS": {
        // Accept an explicit sessionId from the content script payload so the
        // target page's session ID is always used, even if background state has
        // drifted (e.g. a second tab detected a different session).
        const providedId = (msg.payload as { sessionId?: string } | undefined)?.sessionId
        const sid = providedId ?? state.sessionId
        console.log(`Background stored dismissed session: ${sid}`)
        state.dismissedForSessionId = sid
        sendResponse({ ok: true })
        break
      }

      case "WORKFLOW_EVENT":
        if (state.isRecording) {
          state.events.push(msg.payload as WorkflowEvent)
        }
        break

      case "VISIBLE_EVIDENCE_EVENT":
        if (state.isRecording) {
          state.visibleEvidenceEvents.push(msg.payload as VisibleEvidenceEvent)
        }
        break
    }
  }
)

// ── Tab tracking ──────────────────────────────────────────────────────────────
// When a tab is opened from a tracked tab during recording, automatically add it
// to the tracked set and tell its content script to start capturing once loaded.

chrome.tabs.onCreated.addListener((tab) => {
  if (!state.isRecording || tab.id === undefined) return
  const opener = tab.openerTabId
  if (opener !== undefined && state.trackedTabIds.has(opener)) {
    state.trackedTabIds.add(tab.id)
    state.events.push({
      type: "tab_opened",
      timestamp: new Date().toISOString(),
      page_url: redactUrl(tab.url ?? tab.pendingUrl ?? ""),
      page_title: tab.title ?? "",
    })
  }
})

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!state.isRecording || !state.trackedTabIds.has(tabId)) return
  if (changeInfo.status !== "complete") return
  const url = tab.url
  if (!url || url.startsWith("chrome://") || url === "about:blank" || url === "about:newtab") return

  // Record navigation when a tracked tab moves to a different URL.
  const safeUrl = redactUrl(url)
  const lastUrl = state.trackedTabUrls.get(tabId)
  if (lastUrl !== undefined && lastUrl !== safeUrl) {
    state.events.push({
      type: "navigation",
      timestamp: new Date().toISOString(),
      page_url: safeUrl,
      page_title: tab.title ?? "",
    })
  }
  state.trackedTabUrls.set(tabId, safeUrl)

  // Proactively ask the content script in this tab to start capturing.
  // Complements the init-check in content.ts for cases where the service
  // worker was idle when the tab first loaded.
  chrome.tabs.sendMessage(tabId, { type: "START_CAPTURING" }).catch(() => undefined)
})

/**
 * Fire-and-forget upload of accumulated visible evidence events.
 * Never throws; never retries more than once.  A failure here must not block
 * or affect the main proof upload.
 */
async function sendVisibleEvidence(): Promise<void> {
  if (!state.sessionId || state.visibleEvidenceEvents.length === 0) return
  const events = [...state.visibleEvidenceEvents]          // snapshot — don't hold the reference
  const url = `${state.apiUrl}/api/v1/student/extension-proof/sessions/${state.sessionId}/workflow/visible-evidence`
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`
  const body = JSON.stringify({ events })

  const attemptFetch = (): Promise<Response> =>
    fetch(url, { method: "POST", headers, body })

  try {
    let resp = await attemptFetch()
    if (!resp.ok && resp.status >= 500) {
      // One retry after a brief pause for transient 5xx errors.
      await new Promise<void>((r) => setTimeout(r, 800))
      resp = await attemptFetch()
    }
    if (!resp.ok) {
      console.warn(`VeriBridge: visible evidence upload returned HTTP ${resp.status}`)
    }
  } catch (err) {
    // Network failure — log and swallow so the main upload is not affected.
    console.warn("VeriBridge: visible evidence upload failed:", err)
  }
}

async function sendProof(finalNote: string | null): Promise<{ ok: boolean; error?: string }> {
  if (!state.sessionId) {
    const err = "No session ID. Enter a session ID in the extension popup."
    return { ok: false, error: err }
  }

  state.status = "uploading"
  state.statusMessage = "Uploading proof…"
  state.lastUploadError = null

  // Fire-and-forget: send visible evidence events to the backend.
  // This must not block or affect the main proof upload.
  void sendVisibleEvidence()

  const trackedUrls = [
    ...new Set(
      state.events
        .filter((e) => e.type === "page_visit" || e.type === "navigation")
        .map((e) => redactUrl(e.page_url))
        .filter(Boolean)
    ),
  ]

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
    // Multi-tab tracking metadata — stored in the proof upload for later review.
    tracked_tab_count: state.trackedTabIds.size,
    tracked_urls: trackedUrls,
    external_tabs_opened: state.events.filter((e) => e.type === "tab_opened").length,
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`

  try {
    const resp = await fetch(
      `${state.apiUrl}/api/v1/student/extension-proof/sessions/${state.sessionId}/upload`,
      { method: "POST", headers, body: JSON.stringify(payload) }
    )

    if (!resp.ok) {
      let errorMsg = `HTTP ${resp.status}`
      try {
        const rawBody = await resp.text()
        const parsed = JSON.parse(rawBody) as { detail?: { message?: string } | string }
        const detail = parsed?.detail
        errorMsg =
          (typeof detail === "object" ? detail?.message : detail)
          ?? rawBody.slice(0, 120)
          ?? errorMsg
      } catch { /* keep HTTP status string */ }

      state.status = "upload_failed"
      state.statusMessage = `Upload failed: ${errorMsg}`
      state.lastUploadError = errorMsg
      return { ok: false, error: errorMsg }
    }

    state.status = "uploaded"
    state.statusMessage = "Proof uploaded successfully ✓"
    state.lastUploadError = null
    return { ok: true }

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : "Network error — check your connection."
    state.status = "upload_failed"
    state.statusMessage = `Upload failed: ${errorMsg}`
    state.lastUploadError = errorMsg
    return { ok: false, error: errorMsg }
  }
}
