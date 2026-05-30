// Background service worker — manages recording state and uploads proof to the backend.

import type { WorkflowEvent, ExtensionState, RecordingStatus, VisibleEvidenceEvent } from "./types"

// ── Debug flag ────────────────────────────────────────────────────────────────
const DEBUG_VISIBLE_EVIDENCE = true

function dbgVE(...args: unknown[]): void {
  if (DEBUG_VISIBLE_EVIDENCE) console.log("[VisibleEvidence]", ...args)
}

// ── Visual frame capture constants ────────────────────────────────────────────
/**
 * Maximum number of visual frames captured per recording session.
 * Set to 40 to support the Fullscreen Recorder Tab mode which captures one
 * frame every 2 seconds — 40 frames ≈ 80 seconds of fullscreen coverage.
 * Standard tab capture (captureVisibleTab) uses a subset of this budget.
 */
const MAX_VISUAL_FRAMES = 40

/**
 * Minimum milliseconds between consecutive frame captures.
 * Prevents flooding the backend with duplicate frames.
 */
const MIN_FRAME_INTERVAL_MS = 2000

/**
 * Minimum base64 string length for a valid (non-black) JPEG frame.
 *
 * A nearly-all-black JPEG captured from a hardware-decoded fullscreen video
 * compresses extremely well and comes back as ~400–900 base64 chars.
 * A real screenshot (even a simple page) is typically 5 000+ chars.
 * Threshold set at 1 200 to safely skip blank/black frames without discarding
 * legitimate low-complexity pages.
 */
const MIN_VALID_FRAME_BASE64_LEN = 1200

/** Internal representation of one captured visual frame. */
interface VisualFrameData {
  frame_base64: string          // base64-encoded JPEG (no data: prefix)
  frame_type: string            // recording_start | page_load | after_result_detected | …
  timestamp_ms: number          // ms since recording started
  visible_evidence_event_id?: string
}

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
  /** Visual frame screenshots captured during the recording (captureVisibleTab helper). */
  visualFrames: VisualFrameData[]
  /** Epoch-ms when the last visual frame was captured (for throttling). */
  lastFrameCaptureMs: number
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
  // Recorder tab — auto-opened on START_RECORDING.
  // Tracks the tab so we can focus it if it already exists.
  recorderTabId: number | null
  // ── Video upload state (reported by recorder tab) ──────────────────────────
  videoUploadStatus: "none" | "uploading" | "uploaded" | "failed"
  videoUploadError: string | null
  videoKeyframeCount: number
}

const state: InternalState = {
  sessionId: "",
  apiUrl: "http://localhost:8000",
  authToken: "",
  isRecording: false,
  events: [],
  visibleEvidenceEvents: [],
  visualFrames: [],
  lastFrameCaptureMs: 0,
  startedAt: null,
  stoppedAt: null,
  status: "idle",
  statusMessage: "Ready",
  lastUploadError: null,
  dismissedForSessionId: "",
  trackedTabIds: new Set(),
  originalTabId: null,
  trackedTabUrls: new Map(),
  recorderTabId: null,
  videoUploadStatus: "none",
  videoUploadError: null,
  videoKeyframeCount: 0,
}

// ── Persisted recording state key ────────────────────────────────────────────
// Written on START_RECORDING; cleared on STOP_RECORDING and successful upload.
// Lets the service worker restore recording context after Chrome kills it.
const _SW_STATE_KEY = "vb_sw_recording"

interface PersistedRecordingState {
  sessionId: string
  apiUrl: string
  authToken: string
  startedAt: string
}

/**
 * Persist the minimal recording context that must survive a service-worker restart.
 * MV3 service workers are killed when idle; without this, module-level state resets
 * to `isRecording = false` and all subsequent VISIBLE_EVIDENCE_EVENT messages are
 * silently dropped, causing 0 DOM rows for the session.
 */
function persistRecordingState(): void {
  const payload: PersistedRecordingState = {
    sessionId: state.sessionId,
    apiUrl: state.apiUrl,
    authToken: state.authToken,
    startedAt: state.startedAt ?? new Date().toISOString(),
  }
  void chrome.storage.local.set({ [_SW_STATE_KEY]: payload })
  dbgVE("persistRecordingState: saved session", state.sessionId)
}

/** Remove the persisted recording state (recording stopped or proof uploaded). */
function clearPersistedRecordingState(): void {
  void chrome.storage.local.remove(_SW_STATE_KEY)
  dbgVE("clearPersistedRecordingState: cleared")
}

// On service-worker startup, check whether a recording was active before the SW
// was killed.  If so, restore the core fields so VISIBLE_EVIDENCE_EVENT messages
// are accepted again and re-broadcast START_CAPTURING to all open tabs.
void chrome.storage.local.get(_SW_STATE_KEY).then((data) => {
  const rs = (data as Record<string, unknown>)[_SW_STATE_KEY] as PersistedRecordingState | undefined
  if (!rs?.sessionId) return
  dbgVE("service-worker restarted — restoring recording state for session:", rs.sessionId)
  state.sessionId    = rs.sessionId
  state.apiUrl       = (rs.apiUrl || "http://localhost:8000").replace(/\/$/, "")
  state.authToken    = rs.authToken || ""
  state.isRecording  = true
  state.startedAt    = rs.startedAt
  state.status       = "recording"
  state.statusMessage = "Recording resumed after extension restart…"
  // Re-broadcast START_CAPTURING so any content scripts that missed the original
  // broadcast (because the SW was dead) begin capturing immediately.
  void broadcastToAllTabs({ type: "START_CAPTURING" })
})

// ── Visual frame capture ──────────────────────────────────────────────────────

/**
 * Capture a JPEG screenshot of the current visible content of the recording
 * tab and append it to state.visualFrames.
 *
 * Silently no-ops when:
 *   - not recording
 *   - frame cap (MAX_VISUAL_FRAMES) already reached
 *   - throttle interval hasn't elapsed since the last capture
 *   - originalTabId is unknown
 *   - the tracked tab is not currently active (avoids capturing wrong content)
 *   - the visible URL is a VeriBridge-internal or chrome:// page
 *   - chrome.tabs.captureVisibleTab throws for any reason
 */
async function captureVisualFrame(
  frameType: string,
  visibleEvidenceEventId?: string,
): Promise<void> {
  if (!state.isRecording || !state.sessionId) return
  if (state.visualFrames.length >= MAX_VISUAL_FRAMES) return

  const now = Date.now()
  if (now - state.lastFrameCaptureMs < MIN_FRAME_INTERVAL_MS) return

  const tabId = state.originalTabId
  if (tabId === null) return

  try {
    const tab = await chrome.tabs.get(tabId)
    // Only capture when the tracked tab is the active tab in its window.
    // captureVisibleTab always captures the ACTIVE tab, so if the user has
    // switched away we'd capture the wrong content.
    if (!tab.active) {
      dbgVE("[VisualFrame] skip — tracked tab not active (tabId=%d)", tabId)
      return
    }
    if (!tab.windowId) return

    // Skip VeriBridge-internal and chrome:// pages — no useful evidence there.
    const tabUrl = tab.url ?? tab.pendingUrl ?? ""
    if (
      tabUrl.startsWith("chrome://") ||
      tabUrl.startsWith("about:") ||
      tabUrl.includes("veribridge.ai/dashboard") ||
      tabUrl.includes("veribridge.ai/admin") ||
      tabUrl.includes("localhost:3000/dashboard") ||
      tabUrl.includes("localhost:3000/admin")
    ) {
      dbgVE("[VisualFrame] skip — internal page:", tabUrl.slice(0, 60))
      return
    }

    // Update throttle timestamp BEFORE the async capture so concurrent calls
    // don't both pass the throttle check.
    state.lastFrameCaptureMs = now

    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: "jpeg",
      quality: 40,   // low quality → small payload
    })

    // Strip the "data:image/jpeg;base64," prefix
    const commaIdx = dataUrl.indexOf(",")
    if (commaIdx < 0) return
    const base64 = dataUrl.slice(commaIdx + 1)
    if (!base64) return

    // ── Black-frame detection ────────────────────────────────────────────────
    // captureVisibleTab returns a nearly-all-black JPEG when the tab is
    // displaying hardware-decoded video in native fullscreen (the video is
    // composited by the GPU overlay, bypassing the normal tab pixel pipeline).
    // Such frames are useless as evidence; skip them and log a debug note.
    if (base64.length < MIN_VALID_FRAME_BASE64_LEN) {
      dbgVE(
        "[VisualFrame] skipped likely-black/blank frame — base64 len=%d (threshold=%d) type=%s",
        base64.length, MIN_VALID_FRAME_BASE64_LEN, frameType,
      )
      // Reset the throttle timestamp so the NEXT call (e.g. after fullscreen exit)
      // is not blocked by this failed capture attempt.
      state.lastFrameCaptureMs = 0
      return
    }

    const timestampMs = state.startedAt
      ? now - new Date(state.startedAt).getTime()
      : now

    state.visualFrames.push({
      frame_base64: base64,
      frame_type: frameType,
      timestamp_ms: Math.max(0, timestampMs),
      visible_evidence_event_id: visibleEvidenceEventId,
    })

    dbgVE(
      "[VisualFrame] captured type=%s total=%d session=%s",
      frameType, state.visualFrames.length, state.sessionId,
    )
  } catch (err) {
    // captureVisibleTab throws if the tab is restricted (devtools, etc.) —
    // swallow silently so recording is not affected.
    dbgVE("[VisualFrame] capture failed:", err)
  }
}

/**
 * POST accumulated visual frames to the backend visual-frames endpoint.
 * Fire-and-forget — never throws, never retries, never blocks proof upload.
 */
async function sendVisualFrames(): Promise<void> {
  if (!state.sessionId || state.visualFrames.length === 0) {
    dbgVE(
      "[VisualFrame] sendVisualFrames skip — session=%s frames=%d",
      state.sessionId || "(none)", state.visualFrames.length,
    )
    return
  }

  const frames = [...state.visualFrames]  // snapshot
  const url = `${state.apiUrl}/api/v1/student/extension-proof/sessions/${state.sessionId}/workflow/visual-frames`
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`

  const body = JSON.stringify({
    frames: frames.map((f) => ({
      frame_type: f.frame_type,
      frame_base64: f.frame_base64,
      timestamp_ms: f.timestamp_ms,
      visible_evidence_event_id: f.visible_evidence_event_id ?? null,
    })),
  })

  dbgVE("[VisualFrame] POSTing %d frames to backend session=%s", frames.length, state.sessionId)

  try {
    const resp = await fetch(url, { method: "POST", headers, body })
    if (!resp.ok) {
      let errBody = ""
      try { errBody = await resp.text() } catch { /* ignore */ }
      dbgVE("[VisualFrame] POST error — HTTP %d | %s", resp.status, errBody.slice(0, 200))
    } else {
      let respBody = ""
      try { respBody = await resp.text() } catch { /* ignore */ }
      dbgVE("[VisualFrame] POST success — HTTP %d | %s", resp.status, respBody.slice(0, 200))
    }
  } catch (err) {
    dbgVE("[VisualFrame] POST network error:", err)
  }
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
    videoUploadStatus: state.videoUploadStatus,
    videoUploadError: state.videoUploadError,
    videoKeyframeCount: state.videoKeyframeCount,
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
        state.visualFrames = []
        state.lastFrameCaptureMs = 0
        state.startedAt = new Date().toISOString()
        state.stoppedAt = null
        state.status = "recording"
        state.statusMessage = "Recording…"
        state.lastUploadError = null
        state.dismissedForSessionId = ""  // new session clears any prior dismiss
        // Reset video upload state for new session
        state.videoUploadStatus = "none"
        state.videoUploadError  = null
        state.videoKeyframeCount = 0
        // Reset tab tracking — seed with the original tab detected from the page URL.
        state.trackedTabIds = new Set()
        state.trackedTabUrls = new Map()
        if (state.originalTabId !== null) {
          state.trackedTabIds.add(state.originalTabId)
        }
        // Persist recording state so a service-worker restart can restore it.
        persistRecordingState()
        void broadcastToAllTabs({ type: "START_CAPTURING" })
        // Auto-open the recorder tab so the user can start screen capture immediately.
        // If the recorder tab is already open (recorderTabId set), focus it instead.
        const recorderUrl = chrome.runtime.getURL("recorder.html")
        const existingRecorderTabId = state.recorderTabId
        if (existingRecorderTabId !== null) {
          chrome.tabs.get(existingRecorderTabId, (existingTab) => {
            if (chrome.runtime.lastError || !existingTab) {
              // Tab was closed — open a fresh one
              chrome.tabs.create({ url: recorderUrl, active: true }, (tab) => {
                if (tab?.id !== undefined) state.recorderTabId = tab.id
              })
            } else {
              // Focus the existing recorder tab
              chrome.tabs.update(existingRecorderTabId, { active: true })
              if (existingTab.windowId) {
                chrome.windows.update(existingTab.windowId, { focused: true })
              }
            }
          })
        } else {
          chrome.tabs.create({ url: recorderUrl, active: true }, (tab) => {
            if (tab?.id !== undefined) state.recorderTabId = tab.id
          })
        }
        // DOM-event frame capture at recording start (background helper — not primary)
        setTimeout(() => { void captureVisualFrame("recording_start") }, 1200)
        sendResponse({ ok: true })
        break
      }

      case "STOP_RECORDING":
        // Capture a recording-end frame while isRecording is still true.
        // This covers the "Stop → Send" path (where sendProof runs after
        // isRecording is already false and would skip the capture there).
        state.lastFrameCaptureMs = 0  // override throttle for this final frame
        void captureVisualFrame("recording_end")
        state.isRecording = false
        state.stoppedAt = new Date().toISOString()
        state.status = "stopped"
        state.statusMessage = `Stopped — ${state.events.length} event(s) captured. Click Send Proof to upload.`
        // Clear persisted state — recording is explicitly stopped.
        clearPersistedRecordingState()
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

      // ── Immediate frame capture (fullscreen transitions) ─────────────────────
      // Sent by content.ts just before entering fullscreen and immediately after
      // exiting fullscreen.  overrideThrottle bypasses MIN_FRAME_INTERVAL_MS so
      // the transition frame is never silently skipped.
      case "CAPTURE_FRAME_NOW": {
        const { frameType, overrideThrottle } = (msg.payload ?? {}) as {
          frameType?: string
          overrideThrottle?: boolean
        }
        if (overrideThrottle) state.lastFrameCaptureMs = 0
        void captureVisualFrame(frameType ?? "manual")
        sendResponse({ ok: true })
        break
      }

      // ── Screen / window capture frame (from popup getDisplayMedia) ───────────
      // The popup uses navigator.mediaDevices.getDisplayMedia, captures one JPEG
      // frame from the stream, and posts it here.  This bypasses the hardware-
      // overlay limitation that makes captureVisibleTab return black frames during
      // native fullscreen video.
      case "CAPTURE_SCREEN_FRAME": {
        const { frame_base64, frame_type } = (msg.payload ?? {}) as {
          frame_base64?: string
          frame_type?: string
        }
        if (!frame_base64) {
          sendResponse({ ok: false, error: "No frame data" })
          break
        }
        if (!state.isRecording && state.status !== "stopped") {
          sendResponse({ ok: false, error: "Not recording" })
          break
        }
        if (state.visualFrames.length >= MAX_VISUAL_FRAMES) {
          sendResponse({ ok: false, error: "Frame cap reached" })
          break
        }
        const now = Date.now()
        const timestampMs = state.startedAt
          ? now - new Date(state.startedAt).getTime()
          : now
        state.visualFrames.push({
          frame_base64,
          frame_type: frame_type ?? "screen_capture",
          timestamp_ms: Math.max(0, timestampMs),
        })
        dbgVE(
          "[VisualFrame] screen-capture frame added type=%s total=%d session=%s",
          frame_type ?? "screen_capture", state.visualFrames.length, state.sessionId,
        )
        sendResponse({ ok: true, total: state.visualFrames.length })
        break
      }

      // ── Video upload result from recorder tab ────────────────────────────────
      // Sent by recorder.ts after the WebM video is POSTed to /workflow/video.
      case "RECORDER_VIDEO_UPLOADED": {
        const { ok, error, keyframe_count } = (msg.payload ?? {}) as {
          ok?: boolean
          error?: string | null
          keyframe_count?: number
        }
        if (ok) {
          state.videoUploadStatus   = "uploaded"
          state.videoUploadError    = null
          state.videoKeyframeCount  = keyframe_count ?? 0
          dbgVE(
            "[Video] upload succeeded — keyframes=%d session=%s",
            state.videoKeyframeCount, state.sessionId,
          )
        } else {
          state.videoUploadStatus   = "failed"
          state.videoUploadError    = error ?? "Unknown error"
          state.videoKeyframeCount  = 0
          dbgVE("[Video] upload failed — %s session=%s", state.videoUploadError, state.sessionId)
        }
        sendResponse({ ok: true })
        break
      }

      // ── Open / focus the Recorder Tab (manual fallback) ──────────────────────
      // Auto-opened by START_RECORDING above.  This handler is kept so the popup
      // can re-open the tab if the user accidentally closed it.
      case "OPEN_RECORDER_TAB": {
        const recorderUrl = chrome.runtime.getURL("recorder.html")
        const existingTabId = state.recorderTabId
        if (existingTabId !== null) {
          chrome.tabs.get(existingTabId, (existingTab) => {
            if (chrome.runtime.lastError || !existingTab) {
              chrome.tabs.create({ url: recorderUrl, active: true }, (tab) => {
                if (tab?.id !== undefined) state.recorderTabId = tab.id
                sendResponse({ ok: true, tabId: tab?.id ?? null })
              })
            } else {
              chrome.tabs.update(existingTabId, { active: true })
              sendResponse({ ok: true, tabId: existingTabId })
            }
          })
        } else {
          chrome.tabs.create({ url: recorderUrl, active: true }, (tab) => {
            if (tab?.id !== undefined) state.recorderTabId = tab.id
            sendResponse({ ok: true, tabId: tab?.id ?? null })
          })
        }
        return true  // async sendResponse
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
          const veEvent = msg.payload as VisibleEvidenceEvent
          state.visibleEvidenceEvents.push(veEvent)
          dbgVE("background received event batch",
            "| event_type:", veEvent.event_type,
            "| session_id:", state.sessionId,
            "| total accumulated:", state.visibleEvidenceEvents.length)
          // Trigger visual frame capture for the most evidence-rich event types.
          // Each call respects MAX_VISUAL_FRAMES and MIN_FRAME_INTERVAL_MS.
          switch (veEvent.event_type) {
            case "result_detected":
              void captureVisualFrame("after_result_detected", veEvent.event_id)
              break
            case "page_load":
              void captureVisualFrame("page_load", veEvent.event_id)
              break
            case "form_submit":
              void captureVisualFrame("after_form_submit", veEvent.event_id)
              break
            case "file_upload":
              void captureVisualFrame("after_upload", veEvent.event_id)
              break
            case "dom_snapshot":
              // Only capture dom_snapshot frames if we haven't hit the cap yet
              // and it looks like a result-rich page (result_like_blocks present)
              if (
                veEvent.result_like_blocks &&
                veEvent.result_like_blocks.length > 0 &&
                state.visualFrames.length < MAX_VISUAL_FRAMES - 2
              ) {
                void captureVisualFrame("after_dom_mutation", veEvent.event_id)
              }
              break
          }
        } else {
          dbgVE("VISIBLE_EVIDENCE_EVENT received but isRecording=false — event dropped")
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
  if (!state.sessionId || state.visibleEvidenceEvents.length === 0) {
    dbgVE("sendVisibleEvidence: skipping — sessionId:", state.sessionId || "(none)",
      "events:", state.visibleEvidenceEvents.length)
    return
  }
  const events = [...state.visibleEvidenceEvents]          // snapshot — don't hold the reference
  const url = `${state.apiUrl}/api/v1/student/extension-proof/sessions/${state.sessionId}/workflow/visible-evidence`
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (state.authToken) headers["Authorization"] = `Bearer ${state.authToken}`
  const body = JSON.stringify({ events })

  dbgVE("sendVisibleEvidence: POSTing", events.length, "events")
  dbgVE("sendVisibleEvidence: session_id:", state.sessionId)
  dbgVE("sendVisibleEvidence: backend URL:", url)
  dbgVE("sendVisibleEvidence: auth token present:", !!state.authToken)

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
      let errorBody = ""
      try { errorBody = await resp.text() } catch { /* ignore */ }
      dbgVE("sendVisibleEvidence: POST error — HTTP", resp.status, "|", errorBody.slice(0, 200))
      console.warn(`VeriBridge: visible evidence upload returned HTTP ${resp.status}`)
    } else {
      let responseBody = ""
      try { responseBody = await resp.text() } catch { /* ignore */ }
      dbgVE("sendVisibleEvidence: POST success — HTTP", resp.status, "|", responseBody.slice(0, 200))
    }
  } catch (err) {
    // Network failure — log and swallow so the main upload is not affected.
    dbgVE("sendVisibleEvidence: network error:", err)
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

  // Capture a final recording-end frame before uploading (best-effort).
  // Only fires when still recording (i.e. "Stop & Send" without a prior STOP_RECORDING).
  // When the user did "Stop" then "Send", STOP_RECORDING already captured this frame.
  if (state.isRecording) {
    state.lastFrameCaptureMs = 0  // override throttle
    await captureVisualFrame("recording_end")
  }

  // Fire-and-forget: send visible evidence events to the backend.
  // This must not block or affect the main proof upload.
  void sendVisibleEvidence()

  // Fire-and-forget: send visual frames to the backend.
  // This must not block or affect the main proof upload.
  void sendVisualFrames()

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
    // Proof uploaded — clear persisted recording state so a future SW restart
    // doesn't incorrectly resume a completed recording.
    clearPersistedRecordingState()
    return { ok: true }

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : "Network error — check your connection."
    state.status = "upload_failed"
    state.statusMessage = `Upload failed: ${errorMsg}`
    state.lastUploadError = errorMsg
    return { ok: false, error: errorMsg }
  }
}
