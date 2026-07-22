// Background service worker — manages recording state and uploads proof to the backend.

import type { WorkflowEvent, ExtensionState, RecordingStatus, VisibleEvidenceEvent } from "./types"
import { computeLiveCoach } from "./liveFeedback"
import type { LiveCoachState } from "./liveFeedback"
import {
  authorizedJsonHeaders,
  buildRecorderAuthAck,
  buildRecorderAuthDebugState,
  MISSING_RECORDER_AUTH_MESSAGE,
  normalizeApiUrl,
  persistRecorderAuthAndVerify,
  RECORDER_AUTH_BUILD_FINGERPRINT,
  RECORDER_AUTH_STORAGE_KEY,
  recorderTokenMetadata,
  resolveStartRecordingAuth,
  restoreRecorderAuth,
  uploadEndpointUrl,
  validateRecorderAuthPayload,
  type RecorderAuthFailureCategory,
  type RecorderAuthPersistenceResult,
  type RecorderAuthStorageArea,
  type RecorderAuthSource,
} from "./recorderAuth"

const VB_BUILD_ID = RECORDER_AUTH_BUILD_FINGERPRINT

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
  proofBuilderTabId: number | null
  // Recorder tab — auto-opened on START_RECORDING.
  // Tracks the tab so we can focus it if it already exists.
  recorderTabId: number | null
  // ── Video upload state (reported by recorder tab) ──────────────────────────
  videoUploadStatus: "none" | "uploading" | "uploaded" | "failed"
  videoUploadError: string | null
  videoKeyframeCount: number
  // ── Recorder tab stream state ───────────────────────────────────────────────
  // True while recorder tab has an active getDisplayMedia MediaRecorder stream.
  // Set via RECORDER_STREAM_STARTED / RECORDER_STREAM_STOPPED messages.
  // Lets the popup show ONE status ("screen recording active in recorder tab")
  // instead of two conflicting indicators.
  recorderTabStreamActive: boolean
  // ── Live Coach ─────────────────────────────────────────────────────────────
  /** Claimed skills passed to START_RECORDING (optional — set by popup/content). */
  claimedSkills: string[]
  /** Recomputed on each VISIBLE_EVIDENCE_EVENT. Null before first event. */
  liveCoach: LiveCoachState | null
  /** Set when SENSITIVE_WARNING message is received (from content script pattern match). */
  sensitiveWarningSeen: boolean
  /** Event count at which the last snapshot was pushed to the backend. */
  lastSnapshotEventCount: number
  // ── Recorder auth lifecycle (debug metadata only — token lives in authToken) ──
  /** Where the current authToken came from — for GET_RECORDER_AUTH_DEBUG_STATE. */
  authTokenSource: RecorderAuthSource
  /** When the app last handed us a token (SET_RECORDER_AUTH). Never the token. */
  lastAuthHandoffAt: string | null
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
  proofBuilderTabId: null,
  recorderTabId: null,
  videoUploadStatus: "none",
  videoUploadError: null,
  videoKeyframeCount: 0,
  recorderTabStreamActive: false,
  claimedSkills: [],
  liveCoach: null,
  sensitiveWarningSeen: false,
  lastSnapshotEventCount: 0,
  authTokenSource: "none",
  lastAuthHandoffAt: null,
}

let lastAuthPersistence: RecorderAuthPersistenceResult = {
  ok: false,
  persistenceAttempted: false,
  persistenceSucceeded: false,
  readBackSucceeded: false,
  storedSessionMatches: false,
  failureCategory: "none",
}
let lastAuthFailureCategory: RecorderAuthFailureCategory = "none"

// ── Persisted recording state key ────────────────────────────────────────────
// Written on START_RECORDING; cleared on STOP_RECORDING and successful upload.
// Lets the service worker restore recording context after Chrome kills it.
const _SW_STATE_KEY = "vb_sw_recording"
const WEBSITE_PROOF_UPLOAD_STATE_KEY = "websiteProofUploadState"

interface PersistedRecordingState {
  sessionId: string
  apiUrl: string
  authToken: string
  startedAt: string
  originalTabId?: number | null
  proofBuilderTabId?: number | null
}

interface WebsiteProofUploadState {
  status: "uploading" | "uploaded" | "upload_failed"
  sessionId: string
  startedAt: string
  lastEvent: "upload_started" | "upload_succeeded" | "upload_failed"
  statusMessage?: string
  lastUploadError?: string | null
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
    originalTabId: state.originalTabId,
    proofBuilderTabId: state.proofBuilderTabId,
  }
  void chrome.storage.local.set({ [_SW_STATE_KEY]: payload })
  dbgVE("persistRecordingState: saved session", state.sessionId)
}

/** Remove the persisted recording state (recording stopped or proof uploaded). */
function clearPersistedRecordingState(): void {
  void chrome.storage.local.remove(_SW_STATE_KEY)
  dbgVE("clearPersistedRecordingState: cleared")
}

/** Clear the privileged recorder auth handoff after the proof is fully uploaded. */
function clearStoredRecorderAuth(): void {
  state.authToken = ""
  state.authTokenSource = "none"
  state.lastAuthHandoffAt = null
  void chrome.storage.local.remove([RECORDER_AUTH_STORAGE_KEY, "authToken"])
  dbgVE("[RecorderAuth] cleared stored token after upload")
}

function persistWebsiteProofUploadState(uploadState: WebsiteProofUploadState): void {
  void chrome.storage.local.set({ [WEBSITE_PROOF_UPLOAD_STATE_KEY]: uploadState })
}

// On service-worker startup, check whether a recording was active before the SW
// was killed.  If so, restore the core fields so VISIBLE_EVIDENCE_EVENT messages
// are accepted again and re-broadcast START_CAPTURING to all open tabs.
//
// The promise is retained so message handlers and upload paths can AWAIT the
// restore instead of racing it — an upload that fires right after an MV3
// service-worker wake must never observe the pre-restore empty authToken and
// either skip or (worse) attempt an anonymous POST.
const recorderAuthRestored: Promise<void> = chrome.storage.local
  .get([_SW_STATE_KEY, RECORDER_AUTH_STORAGE_KEY, "authToken", "apiUrl"])
  .then((data) => {
    const stored = data as Record<string, unknown>
    // Restore the app-handed recorder auth (SET_RECORDER_AUTH persists the
    // structured record; older builds used loose top-level keys) so a session
    // started AFTER an MV3 service-worker restart still uploads with
    // Authorization: Bearer instead of anonymously 401ing.
    // The in-recording snapshot below takes precedence when one exists.
    const restored = restoreRecorderAuth(stored, state.apiUrl || "http://localhost:8000")
    if (restored.authToken) {
      state.authToken = restored.authToken
      state.authTokenSource = "storage"
      dbgVE(
        "[RecorderAuth] restored token from storage — length=%d build=%s",
        restored.authToken.length, VB_BUILD_ID,
      )
    }
    state.apiUrl = restored.apiUrl
    const rs = stored[_SW_STATE_KEY] as PersistedRecordingState | undefined
    if (!rs?.sessionId) return
    dbgVE("service-worker restarted — restoring recording state for session:", rs.sessionId)
    state.sessionId    = rs.sessionId
    state.apiUrl       = normalizeApiUrl(rs.apiUrl || state.apiUrl, "http://localhost:8000")
    state.authToken    = rs.authToken || state.authToken || ""
    if (rs.authToken) state.authTokenSource = "storage"
    state.isRecording  = true
    state.startedAt    = rs.startedAt
    state.originalTabId = rs.originalTabId ?? null
    state.proofBuilderTabId = rs.proofBuilderTabId ?? null
    state.trackedTabIds = new Set()
    if (state.originalTabId !== null) state.trackedTabIds.add(state.originalTabId)
    state.status       = "recording"
    state.statusMessage = "Recording resumed after extension restart…"
    // Re-broadcast START_CAPTURING so any content scripts that missed the original
    // broadcast (because the SW was dead) begin capturing immediately.
    void broadcastToAllTabs({ type: "START_CAPTURING" })
  })
  .catch(() => undefined)

dbgVE("[RecorderAuth] background loaded — build", VB_BUILD_ID)

/**
 * Resolve the auth token for a recorder upload, waiting out the storage
 * restore first. Returns "" when no token exists — the caller MUST then skip
 * the request (fail closed). Never returns a token to any page context.
 */
async function ensureUploadAuth(): Promise<string> {
  await recorderAuthRestored
  if (state.authToken) return state.authToken
  // Last-resort re-read: SET_RECORDER_AUTH may have persisted a token from a
  // different SW lifetime after our startup snapshot was taken.
  try {
    const stored = (await chrome.storage.local.get([RECORDER_AUTH_STORAGE_KEY, "authToken", "apiUrl"])) as Record<string, unknown>
    const restored = restoreRecorderAuth(stored, state.apiUrl || "http://localhost:8000")
    if (restored.authToken) {
      state.authToken = restored.authToken
      state.apiUrl = restored.apiUrl
      state.authTokenSource = "storage"
      dbgVE("[RecorderAuth] late-restored token from storage — length=%d", restored.authToken.length)
    }
  } catch { /* fail closed below */ }
  return state.authToken
}

/** Safe (token-free) debug snapshot — GET_RECORDER_AUTH_DEBUG_STATE + SW console. */
function recorderAuthDebugState() {
  const tokenMetadata = recorderTokenMetadata(state.authToken)
  return {
    ...buildRecorderAuthDebugState({
      sessionId: state.sessionId,
      hasAuthToken: !!state.authToken,
      authTokenSource: state.authToken ? state.authTokenSource : "none",
    apiUrl: state.apiUrl,
    buildId: VB_BUILD_ID,
    lastAuthHandoffAt: state.lastAuthHandoffAt,
    isRecording: state.isRecording,
    visibleEvidenceCount: state.visibleEvidenceEvents.length,
      visualFrameCount: state.visualFrames.length,
      recordingStoppedPendingSend: state.status === "stopped",
    }),
    component: "background-service-worker",
    buildFingerprint: VB_BUILD_ID,
    extensionId: chrome.runtime.id,
    tokenPresent: tokenMetadata.tokenPresent,
    tokenLength: tokenMetadata.tokenLength,
    jwtSegmentCount: tokenMetadata.jwtSegmentCount,
    startsWithEy: tokenMetadata.startsWithEy,
    expiresAt: tokenMetadata.expiresAt,
    expired: tokenMetadata.expired,
    ...lastAuthPersistence,
    failureCategory: lastAuthFailureCategory,
  }
}

// Inspectable from the service-worker DevTools console:
//   __VB_RECORDER_AUTH_DEBUG__()
;(globalThis as Record<string, unknown>).__VB_RECORDER_AUTH_DEBUG__ = recorderAuthDebugState

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
  // Fail closed: restore-aware token lookup; a missing token means NO request.
  const headers = authorizedJsonHeaders(await ensureUploadAuth())
  if (!headers) {
    dbgVE("[VisualFrame] upload skipped — missing recorder auth token")
    console.warn("VeriBridge: visual frame upload skipped because recorder auth is missing. Restart from the VeriBridge app.")
    return
  }

  const frames = [...state.visualFrames]  // snapshot
  const url = uploadEndpointUrl(state.apiUrl, state.sessionId, "visual-frames")

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

async function rememberProofBuilderTab(): Promise<void> {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
    const activeTab = tabs[0]
    if (activeTab?.id === undefined) return
    state.proofBuilderTabId =
      activeTab.openerTabId ?? state.proofBuilderTabId ?? activeTab.id
    persistRecordingState()
  } catch {
    // Best-effort only; upload should still proceed if Chrome cannot report the tab.
  }
}

async function focusProofBuilderTab(): Promise<void> {
  const tabId = state.proofBuilderTabId
  if (tabId === null) return
  try {
    const tab = await chrome.tabs.get(tabId)
    await chrome.tabs.update(tabId, { active: true })
    if (tab.windowId !== undefined) {
      await chrome.windows.update(tab.windowId, { focused: true })
    }
  } catch {
    // The user may have closed the proof-builder tab; nothing to restore.
  }
}

/**
 * State snapshot for GET_STATE consumers.
 *
 * @param includeAuthToken only true for the extension's own pages (popup /
 * recorder tab, which attaches Authorization to the video POST itself).
 * Content scripts run inside the external target website and never need the
 * token, so they always receive a redacted snapshot.
 */
function publicState(includeAuthToken = false): ExtensionState {
  return {
    sessionId: state.sessionId,
    apiUrl: state.apiUrl,
    authToken: includeAuthToken ? state.authToken : "",
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
    recorderTabStreamActive: state.recorderTabStreamActive,
    liveCoach: state.liveCoach,
  }
}

function broadcastStateUpdate(): void {
  void broadcastToAllTabs({ type: "EXTENSION_STATE_UPDATED" })
}

function broadcastProofUploadStarted(): void {
  const startedAt = new Date().toISOString()
  persistWebsiteProofUploadState({
    status: "uploading",
    sessionId: state.sessionId,
    startedAt,
    lastEvent: "upload_started",
    statusMessage: "Uploading proof…",
    lastUploadError: null,
  })
  void broadcastToAllTabs({
    type: "PROOF_UPLOAD_STARTED",
    payload: {
      sessionId: state.sessionId,
      status: "uploading",
      statusMessage: "Uploading proof…",
      lastUploadError: null,
      isRecording: state.isRecording,
      startedAt,
      lastEvent: "upload_started",
    },
  })
}

/**
 * Begin a recording session. Only called once START_RECORDING has resolved a
 * non-empty auth token — recording must never start in a state where its
 * uploads are guaranteed to 401.
 */
function startRecording(
  sessionId: string,
  apiUrl: string,
  authToken: string,
  claimedSkills?: string[],
): void {
  state.sessionId = sessionId
  state.apiUrl = normalizeApiUrl(apiUrl || state.apiUrl, "http://localhost:8000")
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
  state.recorderTabStreamActive = false
  // Reset live coach state for new session
  state.claimedSkills = claimedSkills ?? []
  state.liveCoach = null
  state.sensitiveWarningSeen = false
  state.lastSnapshotEventCount = 0
  // Reset tab tracking — seed with the original tab detected from the page URL.
  state.trackedTabIds = new Set()
  state.trackedTabUrls = new Map()
  if (state.originalTabId !== null) {
    state.trackedTabIds.add(state.originalTabId)
  }
  // Persist recording state (including the token, keyed by this sessionId) so
  // a service-worker restart can restore it mid-recording.
  persistRecordingState()
  void rememberProofBuilderTab()
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
}

chrome.runtime.onMessage.addListener(
  (msg: { type: string; payload?: unknown }, sender: chrome.runtime.MessageSender, sendResponse) => {
    switch (msg.type) {
      case "GET_STATE": {
        // Await the storage restore so a recorder tab / popup polling right
        // after an MV3 service-worker wake never sees a transiently-empty
        // authToken and caches it for the video upload.
        // SECURITY: the raw token is only included for the extension's own
        // pages (popup / recorder tab). Content scripts — which also run on
        // the external target website — get a redacted snapshot; they never
        // need the token (the background attaches Authorization itself).
        const senderIsExtensionPage =
          typeof sender.url === "string" && sender.url.startsWith(chrome.runtime.getURL(""))
        void recorderAuthRestored.then(() => {
          sendResponse(publicState(senderIsExtensionPage))
        })
        return true // async sendResponse
      }

      case "GET_RECORDER_AUTH_DEBUG_STATE": {
        // Safe diagnostics for QA: has-token booleans, source, build id — never
        // the token value.
        void ensureUploadAuth().then(() => {
          sendResponse(recorderAuthDebugState())
        })
        return true // async sendResponse
      }

      case "SET_RECORDER_AUTH": {
        // The authenticated VeriBridge app (relayed by the content script on its
        // own origin) hands us the signed-in user's Supabase access token so the
        // recorder's direct-to-backend uploads carry Authorization: Bearer. We
        // keep it in privileged state/storage; it never reaches the target site.
        // TODO(security): replace the raw Supabase access token with a
        // short-lived, recorder-scoped upload token minted by the backend
        // (audience-limited to the session's upload endpoints).
        void (async () => {
          // Startup restoration must finish first; otherwise its stale snapshot
          // can overwrite the fresh token immediately after this handoff.
          await recorderAuthRestored
          const validation = validateRecorderAuthPayload(
            (msg.payload ?? {}) as { authToken?: unknown; apiUrl?: unknown; sessionId?: unknown },
          )
          const requestedSessionId =
            typeof (msg.payload as { sessionId?: unknown } | undefined)?.sessionId === "string"
              ? ((msg.payload as { sessionId: string }).sessionId)
              : ""

          if (!validation.ok) {
            lastAuthFailureCategory = validation.failureCategory
            console.warn("[RecorderAuth] background rejected handoff", {
              component: "background-service-worker",
              buildFingerprint: VB_BUILD_ID,
              extensionId: chrome.runtime.id,
              sessionId: requestedSessionId,
              ...validation.tokenMetadata,
              failureCategory: validation.failureCategory,
            })
            sendResponse(buildRecorderAuthAck({
              ok: false,
              hasAuthToken: false,
              buildId: VB_BUILD_ID,
              extensionId: chrome.runtime.id,
              sessionId: requestedSessionId,
              failureCategory: validation.failureCategory,
            }))
            return
          }

          if (state.isRecording && state.sessionId && state.sessionId !== validation.value.sessionId) {
            lastAuthFailureCategory = "session_mismatch"
            sendResponse(buildRecorderAuthAck({
              ok: false,
              hasAuthToken: !!state.authToken,
              buildId: VB_BUILD_ID,
              extensionId: chrome.runtime.id,
              sessionId: validation.value.sessionId,
              failureCategory: "session_mismatch",
            }))
            return
          }

          const handoffAt = new Date().toISOString()
          lastAuthPersistence = await persistRecorderAuthAndVerify(
            chrome.storage.local as unknown as RecorderAuthStorageArea,
            validation.value,
            handoffAt,
          )
          lastAuthFailureCategory = lastAuthPersistence.failureCategory
          if (!lastAuthPersistence.ok) {
            console.warn("[RecorderAuth] background persistence failed", {
              component: "background-service-worker",
              buildFingerprint: VB_BUILD_ID,
              extensionId: chrome.runtime.id,
              sessionId: validation.value.sessionId,
              ...validation.tokenMetadata,
              ...lastAuthPersistence,
            })
            sendResponse(buildRecorderAuthAck({
              ...lastAuthPersistence,
              ok: false,
              hasAuthToken: false,
              buildId: VB_BUILD_ID,
              extensionId: chrome.runtime.id,
              sessionId: validation.value.sessionId,
            }))
            return
          }

          state.authToken = validation.value.authToken
          state.authTokenSource = "storage"
          state.lastAuthHandoffAt = handoffAt
          state.sessionId = validation.value.sessionId
          state.apiUrl = validation.value.apiUrl
          if (state.isRecording) persistRecordingState()
          console.info("[RecorderAuth] background persisted handoff", {
            component: "background-service-worker",
            buildFingerprint: VB_BUILD_ID,
            extensionId: chrome.runtime.id,
            sessionId: state.sessionId,
            apiUrl: state.apiUrl,
            ...validation.tokenMetadata,
            ...lastAuthPersistence,
            ackEmitted: true,
          })
          sendResponse(buildRecorderAuthAck({
            ...lastAuthPersistence,
            ok: true,
            hasAuthToken: true,
            buildId: VB_BUILD_ID,
            extensionId: chrome.runtime.id,
            sessionId: state.sessionId,
          }))
        })().catch(() => {
          lastAuthFailureCategory = "storage_write_failed"
          sendResponse(buildRecorderAuthAck({
            ok: false,
            hasAuthToken: false,
            buildId: VB_BUILD_ID,
            extensionId: chrome.runtime.id,
            sessionId: "",
            failureCategory: "storage_write_failed",
          }))
        })
        return true // async sendResponse after validated persistence + read-back
      }

      case "START_RECORDING": {
        const { sessionId, apiUrl, authToken, claimedSkills } = msg.payload as {
          sessionId: string
          apiUrl: string
          authToken: string
          claimedSkills?: string[]
        }
        // Wait out the storage restore, then require a token BEFORE anything
        // starts: recording an entire session whose uploads can only 401 is the
        // exact failure this guards against. Prefer an explicit token from the
        // popup, falling back to the app-handed SET_RECORDER_AUTH token.
        void ensureUploadAuth().then((restoredToken) => {
          const auth = resolveStartRecordingAuth(authToken, restoredToken)
          if (!auth.ok) {
            state.status = "error"
            state.statusMessage = auth.error
            dbgVE("[RecorderAuth] START_RECORDING rejected — no auth token (build=%s)", VB_BUILD_ID)
            sendResponse({ ok: false, error: auth.error })
            return
          }
          startRecording(sessionId, apiUrl, auth.authToken, claimedSkills)
          sendResponse({ ok: true })
        })
        return true // async sendResponse
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
          if (sender.tab.openerTabId !== undefined) {
            state.proofBuilderTabId = sender.tab.openerTabId
          }
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

      // ── Recorder tab stream state (sent by recorder.ts) ─────────────────────
      // Lets the popup show ONE status line instead of duplicating the recorder
      // tab's "Screen capture active" indicator.
      case "RECORDER_STREAM_STARTED":
        state.recorderTabStreamActive = true
        dbgVE("[RecorderStream] stream started — recorderTabStreamActive=true session=%s", state.sessionId)
        // Broadcast to all tracked content scripts so they hide the floating bar
        // (prevents the VeriBridge overlay from appearing inside the screen recording).
        void broadcastToAllTabs({ type: "RECORDER_STREAM_STARTED" })
        sendResponse({ ok: true })
        break

      case "RECORDER_STREAM_STOPPED":
        state.recorderTabStreamActive = false
        dbgVE("[RecorderStream] stream stopped — recorderTabStreamActive=false session=%s", state.sessionId)
        // Broadcast so content scripts can re-show the floating bar
        void broadcastToAllTabs({ type: "RECORDER_STREAM_STOPPED" })
        sendResponse({ ok: true })
        break

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

      // ── Live Coach: claimed skills update ────────────────────────────────────
      // Sent by popup when the user updates the session's claimed skill list.
      case "SET_CLAIMED_SKILLS": {
        const { skills } = (msg.payload ?? {}) as { skills?: string[] }
        state.claimedSkills = skills ?? []
        if (state.liveCoach !== null) {
          // Recompute with updated skills immediately
          state.liveCoach = computeLiveCoach(
            state.claimedSkills,
            state.visibleEvidenceEvents,
            state.sensitiveWarningSeen,
          )
        }
        sendResponse({ ok: true })
        break
      }

      // ── Live Coach: sensitive content detected by content script ─────────────
      case "SENSITIVE_WARNING":
        state.sensitiveWarningSeen = true
        if (state.liveCoach !== null) {
          state.liveCoach = computeLiveCoach(
            state.claimedSkills,
            state.visibleEvidenceEvents,
            true,
          )
        }
        sendResponse({ ok: true })
        break

      case "VISIBLE_EVIDENCE_EVENT":
        if (state.isRecording) {
          const veEvent = msg.payload as VisibleEvidenceEvent
          state.visibleEvidenceEvents.push(veEvent)
          dbgVE("background received event batch",
            "| event_type:", veEvent.event_type,
            "| session_id:", state.sessionId,
            "| total accumulated:", state.visibleEvidenceEvents.length)

          // ── Live Coach: recompute on each event ────────────────────────────
          state.liveCoach = computeLiveCoach(
            state.claimedSkills,
            state.visibleEvidenceEvents,
            state.sensitiveWarningSeen,
          )
          // Live-feedback network push removed — live coach runs locally only.

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
  if (!state.isRecording) return
  if (changeInfo.status !== "complete") return
  const url = tab.url
  if (!url || url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url === "about:blank" || url === "about:newtab") return

  // Record navigation events for tracked tabs only.
  if (state.trackedTabIds.has(tabId)) {
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
  }

  // Send START_CAPTURING to ALL tabs during recording (not just tracked ones).
  // This ensures the overlay re-appears after any page navigation in any tab,
  // including the target website opened from the recorder tab or a new window.
  chrome.tabs.sendMessage(tabId, { type: "START_CAPTURING" }).catch(() => undefined)
})

// Re-inject overlay when the user switches to a tab during recording.
// Handles the case where the user activates a tab that already loaded but
// missed the initial broadcast (e.g. the recorder tab was focused at that time).
chrome.tabs.onActivated.addListener((activeInfo) => {
  if (!state.isRecording) return
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (chrome.runtime.lastError) return
    const url = tab.url ?? ""
    if (url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url === "about:blank") return
    chrome.tabs.sendMessage(activeInfo.tabId, { type: "START_CAPTURING" }).catch(() => undefined)
  })
})

/**
 * Push a lightweight live feedback snapshot to the backend during recording.
 * Fire-and-forget — never throws, never blocks proof upload.
 * Called every 5 VISIBLE_EVIDENCE_EVENTs during active recording.
 */
async function pushLiveSnapshot(): Promise<void> {
  if (!state.sessionId || !state.isRecording) return
  // Fail closed: no token → no request (restore-aware lookup).
  const authHeaders = authorizedJsonHeaders(await ensureUploadAuth())
  if (!authHeaders) return

  const events = state.visibleEvidenceEvents
  const allText = events.flatMap(e => e.visible_text_blocks).join(" ")
  const allUrls = events.map(e => e.url).join(" ")
  const lastEvent = events[events.length - 1]

  const payload = {
    claimed_skills: state.claimedSkills,
    current_url: lastEvent?.url ?? "",
    page_title: lastEvent?.page_title ?? "",
    dom_text_snippets: events.flatMap(e => e.visible_text_blocks).slice(-20),  // last 20 blocks
    click_count: events.filter(e => e.event_type === "click").length,
    input_count: events.filter(e => e.event_type === "input_change").length,
    form_submit_count: events.filter(e => e.event_type === "form_submit").length,
    output_block_count: events.filter(e => e.result_like_blocks.length > 0).length,
    canvas_count: Math.max(0, ...events.map(e => e.canvas_count ?? 0)),
    svg_count: Math.max(0, ...events.map(e => e.svg_count ?? 0)),
    github_url_seen: events.some(e => /github\.com\/[\w\-]+\/[\w\-]/i.test(e.url)),
    recording_duration_s: state.startedAt
      ? (Date.now() - new Date(state.startedAt).getTime()) / 1000
      : 0,
    sensitive_warning_seen: state.sensitiveWarningSeen,
  }

  const url = uploadEndpointUrl(state.apiUrl, state.sessionId, "live-feedback")
  const headers = authHeaders

  dbgVE("[LiveCoach] pushing snapshot — events=%d score=%d", events.length, state.liveCoach?.live_score ?? 0)

  try {
    await fetch(url, { method: "POST", headers, body: JSON.stringify(payload) })
  } catch {
    // Silent — live snapshot push failure must never affect proof upload
  }
}

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
  // Fail closed: restore-aware token lookup; a missing token means NO request.
  const headers = authorizedJsonHeaders(await ensureUploadAuth())
  if (!headers) {
    dbgVE("sendVisibleEvidence: upload skipped — missing recorder auth token")
    console.warn("VeriBridge: visible evidence upload skipped because recorder auth is missing. Restart from the VeriBridge app.")
    return
  }
  const events = [...state.visibleEvidenceEvents]          // snapshot — don't hold the reference
  const url = uploadEndpointUrl(state.apiUrl, state.sessionId, "visible-evidence")
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
  // Fail closed: restore-aware token lookup (covers Stop & Send right after an
  // MV3 service-worker restart). No token → surface the restart message, never
  // POST anonymously.
  const authHeaders = authorizedJsonHeaders(await ensureUploadAuth())
  if (!authHeaders) {
    state.status = "upload_failed"
    state.statusMessage = `Upload failed: ${MISSING_RECORDER_AUTH_MESSAGE}`
    state.lastUploadError = MISSING_RECORDER_AUTH_MESSAGE
    persistWebsiteProofUploadState({
      status: "upload_failed",
      sessionId: state.sessionId,
      startedAt: new Date().toISOString(),
      lastEvent: "upload_failed",
      statusMessage: state.statusMessage,
      lastUploadError: MISSING_RECORDER_AUTH_MESSAGE,
    })
    broadcastStateUpdate()
    return { ok: false, error: MISSING_RECORDER_AUTH_MESSAGE }
  }

  state.status = "uploading"
  state.statusMessage = "Uploading proof…"
  state.lastUploadError = null
  broadcastProofUploadStarted()
  broadcastStateUpdate()

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

  const headers = authHeaders

  try {
    const resp = await fetch(
      uploadEndpointUrl(state.apiUrl, state.sessionId, "upload"),
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

      if (resp.status === 401) {
        // The backend correctly failed closed: the recorder had an expired or
        // invalid token. Give the user the actionable recovery path instead of
        // the raw backend auth message.
        errorMsg = MISSING_RECORDER_AUTH_MESSAGE
      }

      state.status = "upload_failed"
      state.statusMessage = `Upload failed: ${errorMsg}`
      state.lastUploadError = errorMsg
      persistWebsiteProofUploadState({
        status: "upload_failed",
        sessionId: state.sessionId,
        startedAt: new Date().toISOString(),
        lastEvent: "upload_failed",
        statusMessage: state.statusMessage,
        lastUploadError: errorMsg,
      })
      broadcastStateUpdate()
      return { ok: false, error: errorMsg }
    }

    state.status = "uploaded"
    state.statusMessage = "Proof uploaded successfully ✓"
    state.lastUploadError = null
    persistWebsiteProofUploadState({
      status: "uploaded",
      sessionId: state.sessionId,
      startedAt: new Date().toISOString(),
      lastEvent: "upload_succeeded",
      statusMessage: state.statusMessage,
      lastUploadError: null,
    })
    broadcastStateUpdate()
    // Proof uploaded — clear persisted recording state so a future SW restart
    // doesn't incorrectly resume a completed recording, and clear the
    // extension-private auth handoff so it must be refreshed for the next proof.
    clearPersistedRecordingState()
    clearStoredRecorderAuth()
    void chrome.storage.local.set({
      currentSessionId: state.sessionId,
      lastUploadedSessionId: state.sessionId,
    })
    void focusProofBuilderTab()
    return { ok: true }

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : "Network error — check your connection."
    state.status = "upload_failed"
    state.statusMessage = `Upload failed: ${errorMsg}`
    state.lastUploadError = errorMsg
    persistWebsiteProofUploadState({
      status: "upload_failed",
      sessionId: state.sessionId,
      startedAt: new Date().toISOString(),
      lastEvent: "upload_failed",
      statusMessage: state.statusMessage,
      lastUploadError: errorMsg,
    })
    broadcastStateUpdate()
    return { ok: false, error: errorMsg }
  }
}
