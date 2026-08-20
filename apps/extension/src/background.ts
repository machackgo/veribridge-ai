// Background service worker — manages recording state and uploads proof to the backend.

import type { WorkflowEvent, ExtensionState, RecorderPrivateState, RecordingStatus, VisibleEvidenceEvent } from "./types"
import { computeLiveCoach } from "./liveFeedback"
import type { LiveCoachState } from "./liveFeedback"
import {
  normalizeRecorderSessionConfig,
  recorderApiUrlForSession,
  selectRecorderSessionConfig,
  type RecorderSessionConfig,
} from "./recorderSessionConfig"
import {
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_INIT_REQUEST,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_REQUEST,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  isAllowedRecorderApiBase,
  isRecorderBuildAtLeast,
  isVeriBridgeInternalAppLocation,
  refreshWebsiteProofRecorderAuth,
  safeRecorderDiagnostic,
  type RecorderInitRequest,
  type RecorderProtocolErrorCode,
  type RecorderStartRequest,
  type RecorderTargetOpenRequest,
} from "../../../packages/shared/websiteProofRecorderContract"
import { IS_DEV_BUILD } from "./buildChannel"

// ── Debug flag ────────────────────────────────────────────────────────────────
const DEBUG_VISIBLE_EVIDENCE = false

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
  /** Atomic app-provided config for the fresh Website Proof session. */
  recorderSessionConfig: RecorderSessionConfig | null
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
  /** Exact tab opened by the background for this config revision. */
  targetTabId: number | null
  /** Correlates the target-content readiness acknowledgement to the web request. */
  targetOpenRequestId: string | null
  targetOpenPending: boolean
  targetReadyRevision: number | null
  // Recorder tab — auto-opened on START_RECORDING.
  // Tracks the tab so we can focus it if it already exists.
  recorderTabId: number | null
  // ── Video upload state (reported by recorder tab) ──────────────────────────
  videoUploadStatus: "none" | "uploading" | "uploaded" | "failed"
  videoUploadError: string | null
  videoKeyframeCount: number
  /** Detected getDisplayMedia surface: "tab" | "window" | "screen" | null. */
  captureSurface: string | null
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
}

const state: InternalState = {
  sessionId: "",
  apiUrl: "",
  authToken: "",
  recorderSessionConfig: null,
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
  targetTabId: null,
  targetOpenRequestId: null,
  targetOpenPending: false,
  targetReadyRevision: null,
  recorderTabId: null,
  videoUploadStatus: "none",
  videoUploadError: null,
  videoKeyframeCount: 0,
  captureSurface: null,
  recorderTabStreamActive: false,
  claimedSkills: [],
  liveCoach: null,
  sensitiveWarningSeen: false,
  lastSnapshotEventCount: 0,
}

// ── Persisted recording state key ────────────────────────────────────────────
// Written while RECORDING or STOPPED; cleared only after successful upload.
// Lets the service worker restore recording context after Chrome kills it.
const _SW_STATE_KEY = "vb_sw_recording"
const _SW_EVIDENCE_BUFFER_KEY = "vb_sw_evidence_buffer"
const WEBSITE_PROOF_UPLOAD_STATE_KEY = "websiteProofUploadState"
export const RECORDER_SESSION_CONFIG_KEY = "vb_recorder_session_config"
const MISSING_RECORDER_AUTH_MESSAGE =
  "Recording isn't signed in. Open the VeriBridge Website Proof page while signed in, then restart the recording from there."

interface PersistedRecordingState {
  sessionId: string
  configRevision: number
  startedAt: string
  phase: "recording" | "stopped"
  stoppedAt?: string | null
  originalTabId?: number | null
  proofBuilderTabId?: number | null
  videoUploadStatus?: "none" | "uploading" | "uploaded" | "failed"
  videoUploadError?: string | null
  videoKeyframeCount?: number
  captureSurface?: string | null
  recorderTabId?: number | null
}

interface PersistedEvidenceBuffer {
  sessionId: string
  configRevision: number
  workflowEvents: WorkflowEvent[]
  visibleEvidenceEvents: VisibleEvidenceEvent[]
  /** True when oldest visible-evidence snapshots were dropped to fit the quota. */
  truncated?: boolean
}

interface WebsiteProofUploadState {
  status: "uploading" | "uploaded" | "upload_failed"
  sessionId: string
  startedAt: string
  lastEvent: "upload_started" | "upload_succeeded" | "upload_failed"
  statusMessage?: string
  lastUploadError?: string | null
}

let recordingStateWriteQueue: Promise<void> = Promise.resolve()
let evidenceBufferWriteQueue: Promise<void> = Promise.resolve()
let uploadStateWriteQueue: Promise<void> = Promise.resolve()

/**
 * Persist the minimal recording context that must survive a service-worker restart.
 * MV3 service workers are killed when idle; without this, module-level state resets
 * to `isRecording = false` and all subsequent VISIBLE_EVIDENCE_EVENT messages are
 * silently dropped, causing 0 DOM rows for the session.
 */
function persistRecordingState(): void {
  const config = state.recorderSessionConfig
  if (!config) return
  const payload: PersistedRecordingState = {
    sessionId: config.session_id,
    configRevision: config.config_revision,
    startedAt: state.startedAt ?? new Date().toISOString(),
    phase: state.isRecording ? "recording" : "stopped",
    stoppedAt: state.stoppedAt,
    originalTabId: state.originalTabId,
    proofBuilderTabId: state.proofBuilderTabId,
    videoUploadStatus: state.videoUploadStatus,
    videoUploadError: state.videoUploadError,
    videoKeyframeCount: state.videoKeyframeCount,
    captureSurface: state.captureSurface,
    recorderTabId: state.recorderTabId,
  }
  const write = recordingStateWriteQueue.then(() =>
    chrome.storage.local.set({ [_SW_STATE_KEY]: payload }),
  )
  recordingStateWriteQueue = write.catch(() => undefined)
  dbgVE("persistRecordingState: saved session", state.sessionId)
}

// chrome.storage.session holds up to 10MB (Chrome 112+). Keep the serialized
// recovery buffer well under that so a long recording never fails its write
// wholesale. Workflow events are small and structurally essential (kept in
// full); bulky visible-evidence snapshots are trimmed oldest-first to fit.
const _SW_EVIDENCE_BUDGET_BYTES = 6_000_000
// Coalesce bursts of per-event persistence into a single trailing write so a
// streaming recording does not re-serialize the whole buffer on every event.
const _SW_EVIDENCE_COALESCE_MS = 400

let evidenceBufferDirty = false
let evidenceBufferFlushTimer: ReturnType<typeof setTimeout> | null = null

function buildEvidenceBufferPayload(): PersistedEvidenceBuffer | null {
  const config = state.recorderSessionConfig
  if (!config) return null
  const workflowEvents = [...state.events]
  const baseBytes = JSON.stringify({
    sessionId: config.session_id,
    configRevision: config.config_revision,
    workflowEvents,
  }).length
  // Newest-first cumulative fit: measure each visible-evidence event once, then
  // keep the most recent that fit the remaining budget (O(n), no re-serialize).
  const visibleBudget = _SW_EVIDENCE_BUDGET_BYTES - baseBytes
  const source = state.visibleEvidenceEvents
  const kept: VisibleEvidenceEvent[] = []
  let used = 2 // "[]" brackets
  let truncated = false
  for (let i = source.length - 1; i >= 0; i -= 1) {
    const cost = JSON.stringify(source[i]).length + 1 // + comma separator
    if (used + cost > visibleBudget) { truncated = true; break }
    used += cost
    kept.push(source[i])
  }
  const visibleEvidenceEvents = kept.reverse()
  return {
    sessionId: config.session_id,
    configRevision: config.config_revision,
    workflowEvents,
    visibleEvidenceEvents,
    ...(truncated ? { truncated: true } : {}),
  }
}

/** Immediately enqueue a full recovery-buffer write (used at start/stop). */
function flushEvidenceBuffer(): void {
  evidenceBufferDirty = false
  if (evidenceBufferFlushTimer !== null) {
    clearTimeout(evidenceBufferFlushTimer)
    evidenceBufferFlushTimer = null
  }
  const payload = buildEvidenceBufferPayload()
  if (!payload) return
  const write = evidenceBufferWriteQueue.then(() =>
    chrome.storage.session.set({ [_SW_EVIDENCE_BUFFER_KEY]: payload }),
  )
  evidenceBufferWriteQueue = write.catch(() => undefined)
}

/** Debounced per-event persistence — coalesces streaming events into one write. */
function persistEvidenceBuffer(): void {
  if (!state.recorderSessionConfig) return
  evidenceBufferDirty = true
  if (evidenceBufferFlushTimer !== null) return
  evidenceBufferFlushTimer = setTimeout(() => {
    evidenceBufferFlushTimer = null
    if (evidenceBufferDirty) flushEvidenceBuffer()
  }, _SW_EVIDENCE_COALESCE_MS)
}

function clearPersistedEvidenceBuffer(): void {
  evidenceBufferDirty = false
  if (evidenceBufferFlushTimer !== null) {
    clearTimeout(evidenceBufferFlushTimer)
    evidenceBufferFlushTimer = null
  }
  const write = evidenceBufferWriteQueue.then(() =>
    chrome.storage.session.remove(_SW_EVIDENCE_BUFFER_KEY),
  )
  evidenceBufferWriteQueue = write.catch(() => undefined)
}

/** Remove the persisted recording state (recording stopped or proof uploaded). */
function clearPersistedRecordingState(): void {
  const write = recordingStateWriteQueue.then(() => chrome.storage.local.remove(_SW_STATE_KEY))
  recordingStateWriteQueue = write.catch(() => undefined)
  dbgVE("clearPersistedRecordingState: cleared")
}

function persistWebsiteProofUploadState(uploadState: WebsiteProofUploadState): void {
  const write = uploadStateWriteQueue.then(() =>
    chrome.storage.local.set({ [WEBSITE_PROOF_UPLOAD_STATE_KEY]: uploadState }),
  )
  uploadStateWriteQueue = write.catch(() => undefined)
}

// Runtime-only write epoch used solely to prevent an asynchronous startup read
// from overwriting a config already acknowledged in this worker instance.
let recorderSessionConfigWriteEpoch = 0
let recorderSessionConfigWriteQueue: Promise<void> = Promise.resolve()

function applyRecorderSessionConfig(config: RecorderSessionConfig): void {
  state.recorderSessionConfig = config
  state.sessionId = config.session_id
  state.apiUrl = config.api_base_url
  state.authToken = config.auth.access_token
  state.claimedSkills = [...config.claimed_skills]
}

async function persistRecorderSessionConfig(config: RecorderSessionConfig): Promise<void> {
  // One atomic object is the only durable recorder configuration. Popup and
  // recorder views consume the public in-memory projection through GET_STATE.
  const write = recorderSessionConfigWriteQueue.then(() =>
    chrome.storage.local.set({ [RECORDER_SESSION_CONFIG_KEY]: config }),
  )
  recorderSessionConfigWriteQueue = write.catch(() => undefined)
  await write
}

// On service-worker startup, check whether a recording was active before the SW
// was killed.  If so, restore the core fields so VISIBLE_EVIDENCE_EVENT messages
// are accepted again and re-broadcast START_CAPTURING to all open tabs.
const startupConfigWriteEpoch = recorderSessionConfigWriteEpoch
void chrome.storage.local.get([
  _SW_STATE_KEY,
  RECORDER_SESSION_CONFIG_KEY,
]).then(async (data) => {
  const stored = data as Record<string, unknown>
  // Restore the app-handed recorder auth (SET_RECORDER_AUTH persists these
  // top-level keys) so a session started AFTER an MV3 service-worker restart
  // still uploads with Authorization: Bearer instead of anonymously 401ing.
  // The in-recording snapshot below takes precedence when one exists.
  // A fresh runtime handoff may arrive while this async storage read is in
  // flight. Never let the older stored config overwrite the acknowledged one.
  if (recorderSessionConfigWriteEpoch === startupConfigWriteEpoch) {
    const storedConfig = normalizeRecorderSessionConfig(
      (stored[RECORDER_SESSION_CONFIG_KEY] ?? {}) as RecorderSessionConfig,
    )
    if (storedConfig) {
      applyRecorderSessionConfig(storedConfig)
    }
  }
  const rs = stored[_SW_STATE_KEY] as PersistedRecordingState | undefined
  if (!rs?.sessionId) return
  if (
    recorderSessionConfigWriteEpoch !== startupConfigWriteEpoch &&
    state.sessionId &&
    state.sessionId !== rs.sessionId
  ) {
    return
  }
  dbgVE("service-worker restarted — restoring recording state for session:", rs.sessionId)
  // A recording snapshot is valid only alongside the exact persisted config;
  // it never reconstructs a second, partial session shape.
  if (
    !state.recorderSessionConfig ||
    state.recorderSessionConfig.session_id !== rs.sessionId ||
    state.recorderSessionConfig.config_revision !== rs.configRevision
  ) {
    clearPersistedRecordingState()
    clearPersistedEvidenceBuffer()
    return
  }
  const evidenceStored = await chrome.storage.session.get(_SW_EVIDENCE_BUFFER_KEY)
  const evidence = evidenceStored[_SW_EVIDENCE_BUFFER_KEY] as PersistedEvidenceBuffer | undefined
  if (
    evidence?.sessionId === rs.sessionId &&
    evidence.configRevision === rs.configRevision
  ) {
    state.events = Array.isArray(evidence.workflowEvents) ? evidence.workflowEvents : []
    state.visibleEvidenceEvents = Array.isArray(evidence.visibleEvidenceEvents)
      ? evidence.visibleEvidenceEvents
      : []
  } else {
    state.events = []
    state.visibleEvidenceEvents = []
    clearPersistedEvidenceBuffer()
  }
  state.isRecording  = rs.phase !== "stopped"
  state.startedAt    = rs.startedAt
  state.stoppedAt    = rs.stoppedAt ?? null
  state.originalTabId = rs.originalTabId ?? null
  state.proofBuilderTabId = rs.proofBuilderTabId ?? null
  state.trackedTabIds = new Set()
  if (state.originalTabId !== null) state.trackedTabIds.add(state.originalTabId)
  state.videoUploadStatus = rs.videoUploadStatus ?? "none"
  state.videoUploadError = rs.videoUploadError ?? null
  state.videoKeyframeCount = rs.videoKeyframeCount ?? 0
  state.captureSurface = rs.captureSurface ?? null
  state.recorderTabId = rs.recorderTabId ?? null
  state.status       = state.isRecording ? "recording" : "stopped"
  state.targetReadyRevision = state.recorderSessionConfig.config_revision
  state.statusMessage = state.isRecording
    ? "Recording resumed after extension restart…"
    : `Stopped — ${state.events.length} event(s) recovered. Click Send Proof to upload.`
  // Re-send START_CAPTURING to the session's own tabs so content scripts that
  // missed the original signal (because the SW was dead) begin capturing again.
  if (state.isRecording) {
    broadcastStartCapturingToSessionTabs()
    // An extension reload destroys the recorder page's JavaScript context and
    // its in-memory MediaRecorder even when the proof session itself restores
    // successfully. Reconnect (or recreate) that recorder tab as part of the
    // same persisted session so its Start button observes the restored worker
    // state; do not wait for a second START_RECORDING request that the already-
    // recording Website Proof page will correctly never send.
    openOrRefreshRecorderTab({ active: true })
  }
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

    // Skip VeriBridge-internal app pages and chrome:// pages — no evidence
    // may ever be captured there (same path-scoped rule the content script
    // applies for DOM snapshots).
    const tabUrl = tab.url ?? tab.pendingUrl ?? ""
    if (isCaptureExcludedUrl(tabUrl)) {
      dbgVE("[VisualFrame] skip — internal/excluded page:", tabUrl.slice(0, 60))
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

type EvidenceUploadResult = { ok: true } | { ok: false; error: string }

/** POST visual frames before the canonical proof upload can advance. */
async function sendVisualFrames(): Promise<EvidenceUploadResult> {
  if (!state.sessionId || state.visualFrames.length === 0) {
    dbgVE(
      "[VisualFrame] sendVisualFrames skip — session=%s frames=%d",
      state.sessionId || "(none)", state.visualFrames.length,
    )
    return { ok: true }
  }
  if (!state.authToken) {
    dbgVE("[VisualFrame] upload skipped — missing recorder auth token")
    console.warn("VeriBridge: visual frame upload skipped because recorder auth is missing. Restart from the VeriBridge app.")
    return { ok: false, error: "Visual frame upload is missing recorder authentication." }
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
    let resp = await fetch(url, { method: "POST", headers, body })
    if (!resp.ok && resp.status >= 500) {
      await new Promise<void>(resolve => setTimeout(resolve, 800))
      resp = await fetch(url, { method: "POST", headers, body })
    }
    if (!resp.ok) {
      dbgVE("[VisualFrame] POST error — HTTP %d", resp.status)
      return { ok: false, error: `Visual frame upload returned HTTP ${resp.status}.` }
    } else {
      dbgVE("[VisualFrame] POST success — HTTP %d", resp.status)
      return { ok: true }
    }
  } catch (err) {
    dbgVE("[VisualFrame] POST network error:", err)
    return { ok: false, error: "Visual frame upload failed because the backend was unreachable." }
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

/** True when a tab belongs to the active recording session's tab set. */
function isSessionTabId(tabId: number | undefined): boolean {
  if (tabId === undefined) return false
  return state.trackedTabIds.has(tabId) || tabId === state.proofBuilderTabId
}

/**
 * Send START_CAPTURING only to the session's own tabs (target tab, tabs opened
 * from it, and the proof-builder tab for its silent modal sync). Unrelated
 * open tabs must never be told to start capturing — that both leaked the
 * recorder HUD into unrelated tabs and recorded browsing activity outside the
 * proof session.
 */
function broadcastStartCapturingToSessionTabs(): void {
  const targets = new Set<number>(state.trackedTabIds)
  if (state.proofBuilderTabId !== null) targets.add(state.proofBuilderTabId)
  for (const tabId of targets) {
    chrome.tabs.sendMessage(tabId, { type: "START_CAPTURING" }).catch(() => undefined)
  }
}

/** True when a URL is a VeriBridge-internal app page or a browser page that
 *  must never be captured as evidence. */
function isCaptureExcludedUrl(url: string): boolean {
  if (!url) return true
  if (url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("about:")) {
    return true
  }
  try {
    const parsed = new URL(url)
    return isVeriBridgeInternalAppLocation(parsed)
  } catch {
    return true
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

function publicState(): ExtensionState {
  return {
    sessionId: state.sessionId,
    apiUrl: state.apiUrl,
    authConfigured: Boolean(state.authToken),
    configRevision: state.recorderSessionConfig?.config_revision ?? null,
    claimedSkills: [...(state.recorderSessionConfig?.claimed_skills ?? [])],
    targetWebsiteUrl: state.recorderSessionConfig?.website_url ?? null,
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
    captureSurface: state.captureSurface,
    recorderTabStreamActive: state.recorderTabStreamActive,
    liveCoach: state.liveCoach,
  }
}

function privateRecorderState(): RecorderPrivateState {
  return { ...publicState(), authToken: state.authToken }
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

function recorderDiagnostic(
  event: string,
  config: RecorderSessionConfig | null,
  errorCode?: RecorderProtocolErrorCode,
): void {
  console.info("[WebsiteProofRecorder]", {
    event,
    ...(config ? safeRecorderDiagnostic(config) : {}),
    state: state.status,
    timestamp: new Date().toISOString(),
    ...(errorCode ? { error_code: errorCode } : {}),
  })
}

function protocolNack(
  requestId: string,
  errorCode: RecorderProtocolErrorCode,
  message: string,
): Record<string, unknown> {
  const config = state.recorderSessionConfig
  recorderDiagnostic("extension_init_rejected", config, errorCode)
  return {
    ok: false,
    request_id: requestId,
    session_id: config?.session_id ?? null,
    config_revision: config?.config_revision ?? null,
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    build_version: chrome.runtime.getManifest().version,
    extension_id: chrome.runtime.id,
    ready: false,
    error_code: errorCode,
    message,
  }
}

function sameTargetOrigin(expectedUrl: string, actualUrl: string): boolean {
  try {
    return new URL(expectedUrl).origin === new URL(actualUrl).origin
  } catch {
    return false
  }
}

function startRecordingForConfiguredTarget(
  sessionId: string,
  configRevision?: number,
): Record<string, unknown> {
  const config = state.recorderSessionConfig
  if (!config || config.session_id !== sessionId) {
    return {
      ok: false,
      error_code: "session_mismatch",
      error: "This session has not completed the Website Proof recorder handshake. Retry from the proof page.",
    }
  }
  if (configRevision !== undefined && configRevision !== config.config_revision) {
    return {
      ok: false,
      error_code: "revision_mismatch",
      error: "This start request uses a stale recorder configuration revision.",
    }
  }
  if (state.isRecording) {
    const sameSession = state.sessionId === sessionId
    if (sameSession) {
      // A same-session retry is also the recovery signal for a recorder page
      // whose MediaRecorder was lost during an extension reload. Reconnect the
      // page even though the logical proof start is idempotent.
      openOrRefreshRecorderTab({ active: true })
    }
    return {
      ok: sameSession,
      idempotent: sameSession,
      session_id: config.session_id,
      config_revision: config.config_revision,
      started_at: state.startedAt,
      ready: sameSession,
      ...(!sameSession ? { error_code: "different_session_active" } : {}),
    }
  }
  if (
    state.targetTabId === null ||
    state.targetReadyRevision !== config.config_revision
  ) {
    return {
      ok: false,
      error_code: "recording_not_ready",
      error: "The configured target content script has not acknowledged readiness.",
    }
  }

  applyRecorderSessionConfig(config)
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
  state.dismissedForSessionId = ""
  state.videoUploadStatus = "none"
  state.videoUploadError = null
  state.videoKeyframeCount = 0
  state.captureSurface = null
  state.recorderTabStreamActive = false
  state.claimedSkills = [...config.claimed_skills]
  state.liveCoach = null
  state.sensitiveWarningSeen = false
  state.lastSnapshotEventCount = 0
  state.trackedTabIds = new Set([state.targetTabId])
  state.trackedTabUrls = new Map()
  state.originalTabId = state.targetTabId
  persistRecordingState()
  flushEvidenceBuffer()
  void rememberProofBuilderTab()
  broadcastStartCapturingToSessionTabs()

  // A recorder tab can survive an unpacked-extension reload while its JS
  // context is invalidated. Merely focusing that stale tab leaves
  // "Start Screen Recording" disabled even though the new worker and target
  // tab are recording. Refresh a non-capturing recorder tab before reuse so it
  // polls the current worker/session; never refresh an active MediaRecorder
  // stream because that would destroy the only in-memory video bytes.
  openOrRefreshRecorderTab({ active: true })
  setTimeout(() => { void captureVisualFrame("recording_start") }, 1200)
  recorderDiagnostic("recording_started", config)
  return {
    ok: true,
    idempotent: false,
    session_id: config.session_id,
    config_revision: config.config_revision,
    started_at: state.startedAt,
    ready: true,
  }
}

function openOrRefreshRecorderTab(
  options: { active: boolean; onReady?: (tabId: number | null) => void },
): void {
  const recorderUrl = chrome.runtime.getURL("recorder.html")
  const focusWindow = (windowId: number | undefined): void => {
    if (options.active && windowId !== undefined) {
      void chrome.windows.update(windowId, { focused: true })
    }
  }
  const createTab = (): void => {
    chrome.tabs.create({ url: recorderUrl, active: options.active }, (tab) => {
      state.recorderTabId = tab?.id ?? null
      persistRecordingState()
      focusWindow(tab?.windowId)
      options.onReady?.(tab?.id ?? null)
    })
  }
  const existingTabId = state.recorderTabId
  if (existingTabId === null) {
    createTab()
    return
  }
  chrome.tabs.get(existingTabId, (existingTab) => {
    if (chrome.runtime.lastError || !existingTab) {
      createTab()
      return
    }
    const activate = (): void => {
      void chrome.tabs.update(existingTabId, { active: options.active })
      focusWindow(existingTab.windowId)
      options.onReady?.(existingTabId)
    }
    if (state.recorderTabStreamActive) {
      activate()
      return
    }
    chrome.tabs.reload(existingTabId, {}, () => {
      if (chrome.runtime.lastError) {
        // A tab retained from an invalidated extension context may reject
        // reload. Re-navigating it to the current extension URL recreates the
        // recorder page without allocating a duplicate tab.
        void chrome.tabs.update(existingTabId, { url: recorderUrl, active: options.active })
        focusWindow(existingTab.windowId)
        options.onReady?.(existingTabId)
        return
      }
      activate()
    })
  })
}

chrome.runtime.onMessage.addListener(
  (msg: { type: string; payload?: unknown }, sender: chrome.runtime.MessageSender, sendResponse) => {
    switch (msg.type) {
      case "GET_STATE":
        // isTrackedTab is per-sender: content scripts use it to decide whether
        // THIS tab is part of the recording session (HUD + capture eligibility).
        // Extension pages (popup, recorder tab) have no sender.tab and get false.
        sendResponse({
          ...publicState(),
          isTrackedTab: sender.tab?.id !== undefined && state.trackedTabIds.has(sender.tab.id),
        })
        break

      case "GET_RECORDER_PRIVATE_STATE": {
        const recorderPage = chrome.runtime.getURL("recorder.html")
        if (typeof sender.url !== "string" || !sender.url.startsWith(recorderPage)) {
          sendResponse({ ok: false, error_code: "authentication_unavailable" })
          break
        }
        sendResponse(privateRecorderState())
        break
      }

      case RECORDER_INIT_REQUEST: {
        const request = (msg.payload ?? {}) as Partial<RecorderInitRequest>
        const requestId = typeof request.request_id === "string" ? request.request_id : "unknown"
        // Schema must match exactly; the build only has to be AT LEAST the
        // page's declared minimum. Store updates roll out on Chrome's
        // schedule, so a newer installed build must keep working against a
        // page that has not been redeployed yet.
        if (
          request.expected_schema_version !== WEBSITE_PROOF_RECORDER_SCHEMA_VERSION ||
          !isRecorderBuildAtLeast(chrome.runtime.getManifest().version, String(request.expected_build_version ?? ""))
        ) {
          sendResponse(protocolNack(
            requestId,
            "extension_version_incompatible",
            "The installed recorder build is older than this Website Proof page requires. Update the extension.",
          ))
          break
        }
        const selection = selectRecorderSessionConfig(
          state.recorderSessionConfig,
          request.config,
          state.isRecording,
        )
        if (!selection.accepted || !selection.config) {
          sendResponse(protocolNack(
            requestId,
            selection.error_code ?? "invalid_config",
            "The recorder session configuration was rejected.",
          ))
          break
        }
        // Channel gate: evidence may only ever be uploaded to an approved
        // VeriBridge API origin (store builds: production only).
        if (!isAllowedRecorderApiBase(selection.config.api_base_url, IS_DEV_BUILD)) {
          sendResponse(protocolNack(
            requestId,
            "invalid_api_base",
            "This recorder build does not accept the configured API address.",
          ))
          break
        }
        recorderSessionConfigWriteEpoch += 1
        applyRecorderSessionConfig(selection.config)
        state.targetTabId = null
        state.targetOpenRequestId = null
        state.targetOpenPending = false
        state.targetReadyRevision = null
        if (!state.isRecording) {
          state.status = "ready"
          state.statusMessage = "Website Proof session configured."
        }
        void persistRecorderSessionConfig(selection.config).then(() => {
          if (state.isRecording) persistRecordingState()
          recorderDiagnostic("extension_init_acknowledged", selection.config)
          sendResponse({
            ok: true,
            request_id: requestId,
            session_id: selection.config?.session_id,
            config_revision: selection.config?.config_revision,
            api_base_url: selection.config?.api_base_url,
            schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
            build_version: chrome.runtime.getManifest().version,
            extension_id: chrome.runtime.id,
            ready: true,
          })
        }).catch(() => sendResponse(protocolNack(
          requestId,
          "storage_write_failed",
          "The recorder could not persist the session configuration.",
        )))
        return true
      }

      case RECORDER_AUTH_REFRESH_REQUEST: {
        const payload = (msg.payload ?? {}) as {
          request_id?: unknown
          session_id: unknown
          config_revision: unknown
          access_token: unknown
          expires_at?: unknown
        }
        const refreshed = refreshWebsiteProofRecorderAuth(state.recorderSessionConfig, payload)
        if (!refreshed) {
          sendResponse({
            ...protocolNack(
              typeof payload.request_id === "string" ? payload.request_id : "unknown",
              "session_mismatch",
              "The auth refresh does not match the active recorder config.",
            ),
          })
          break
        }
        recorderSessionConfigWriteEpoch += 1
        applyRecorderSessionConfig(refreshed)
        void persistRecorderSessionConfig(refreshed).then(() => {
          if (state.isRecording) persistRecordingState()
          sendResponse({
            ok: true,
            request_id: payload.request_id,
            session_id: refreshed.session_id,
            config_revision: refreshed.config_revision,
          })
        }).catch(() => sendResponse(protocolNack(
          typeof payload.request_id === "string" ? payload.request_id : "unknown",
          "storage_write_failed",
          "The recorder could not persist refreshed authentication.",
        )))
        return true
      }

      case RECORDER_TARGET_OPEN_REQUEST: {
        const request = (msg.payload ?? {}) as Partial<RecorderTargetOpenRequest>
        const config = state.recorderSessionConfig
        if (!config || request.session_id !== config.session_id) {
          sendResponse(protocolNack(
            typeof request.request_id === "string" ? request.request_id : "unknown",
            "session_mismatch",
            "The target request does not match the configured session.",
          ))
          break
        }
        if (request.config_revision !== config.config_revision) {
          sendResponse(protocolNack(
            typeof request.request_id === "string" ? request.request_id : "unknown",
            "revision_mismatch",
            "The target request uses a stale recorder revision.",
          ))
          break
        }
        if (sender.tab?.id === undefined) {
          sendResponse(protocolNack(
            typeof request.request_id === "string" ? request.request_id : "unknown",
            "target_open_failed",
            "The recorder could not identify the Website Proof tab.",
          ))
          break
        }
        if (state.targetOpenRequestId === request.request_id) {
          sendResponse({
            ok: true,
            pending: state.targetOpenPending,
            request_id: request.request_id,
            session_id: config.session_id,
            config_revision: config.config_revision,
            target_tab_id: state.targetTabId,
          })
          break
        }
        state.proofBuilderTabId = sender.tab.id
        state.targetOpenRequestId = String(request.request_id)
        state.targetOpenPending = true
        state.targetReadyRevision = null
        recorderDiagnostic("target_open_requested", config)
        chrome.tabs.create({ url: config.website_url, active: true, openerTabId: sender.tab.id }, (tab) => {
          if (chrome.runtime.lastError || tab?.id === undefined) {
            state.targetOpenPending = false
            sendResponse(protocolNack(
              String(request.request_id),
              "target_open_failed",
              "Chrome could not open the configured target page.",
            ))
            return
          }
          state.targetTabId = tab.id
          state.targetOpenPending = false
          state.originalTabId = tab.id
          state.statusMessage = "Target opened. Waiting for the recorder content script…"
          recorderDiagnostic("target_opened", config)
          sendResponse({
            ok: true,
            request_id: request.request_id,
            session_id: config.session_id,
            config_revision: config.config_revision,
            target_tab_id: tab.id,
          })
        })
        return true
      }

      case "RECORDER_TARGET_CONTENT_READY": {
        const config = state.recorderSessionConfig
        const pageUrl = String((msg.payload as { page_url?: unknown } | undefined)?.page_url ?? "")
        if (!config || sender.tab?.id === undefined || sender.tab.id !== state.targetTabId) {
          sendResponse({ ok: false, error_code: "target_session_mismatch" })
          break
        }
        if (!sameTargetOrigin(config.website_url, pageUrl)) {
          sendResponse({ ok: false, error_code: "target_url_mismatch" })
          break
        }
        state.originalTabId = sender.tab.id
        state.targetReadyRevision = config.config_revision
        state.status = "ready"
        state.statusMessage = "Recorder ready"
        const payload = {
          request_id: state.targetOpenRequestId,
          session_id: config.session_id,
          config_revision: config.config_revision,
          api_base_url: config.api_base_url,
          claimed_skills: config.claimed_skills,
          target_tab_id: sender.tab.id,
          target_url: pageUrl,
          ready: true,
        }
        recorderDiagnostic("target_content_script_ready", config)
        if (state.proofBuilderTabId !== null) {
          void chrome.tabs.sendMessage(state.proofBuilderTabId, {
            type: "RECORDER_TARGET_READY",
            payload,
          }).catch(() => undefined)
        }
        sendResponse({ ok: true, ...payload })
        break
      }

      case RECORDER_START_REQUEST: {
        const request = (msg.payload ?? {}) as Partial<RecorderStartRequest>
        const requestId = typeof request.request_id === "string" ? request.request_id : "unknown"
        const result = startRecordingForConfiguredTarget(
          typeof request.session_id === "string" ? request.session_id : "",
          typeof request.config_revision === "number" ? request.config_revision : undefined,
        )
        if (!result.ok) {
          sendResponse(protocolNack(
            requestId,
            (result.error_code as RecorderProtocolErrorCode | undefined) ?? "recording_start_failed",
            String(result.error ?? "The recorder could not start capture."),
          ))
          break
        }
        sendResponse({ ...result, request_id: requestId })
        break
      }

      // Legacy pages receive an explicit incompatibility response. New pages
      // never use this partial shape; it exists only to make stale builds
      // diagnosable during local development.
      case "SET_RECORDER_AUTH":
        sendResponse({
          ok: false,
          error_code: "extension_version_incompatible",
          schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
          build_version: chrome.runtime.getManifest().version,
        })
        break

      case "START_RECORDING": {
        const { sessionId } = msg.payload as {
          sessionId: string
        }
        sendResponse(startRecordingForConfiguredTarget(sessionId))
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
        // A stopped session remains recoverable until the canonical upload ACK.
        // Flush synchronously so the full buffer is durable the instant capture
        // ends — a service-worker death before Send Proof must not lose events.
        persistRecordingState()
        flushEvidenceBuffer()
        void broadcastToAllTabs({ type: "STOP_CAPTURING" })
        recorderDiagnostic("recording_stopped", state.recorderSessionConfig)
        // Kick off screen-recording finalization immediately: a Stop from the
        // floating bar or popup must never leave the recorder tab capturing
        // (previously the video upload silently never started, so Send Proof
        // failed with "Finish uploading the screen recording…").
        if (state.videoUploadStatus !== "uploaded") {
          void sendFinalizeRequestToRecorder()
        }
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
        const configuredApiUrl = recorderApiUrlForSession(state.recorderSessionConfig, session_id)
        if (!configuredApiUrl && state.recorderSessionConfig) {
          // A target/historical URL must never retarget a fresh config.
          sendResponse({ ok: false, reason: "session config mismatch" })
          break
        }
        if (!configuredApiUrl) {
          sendResponse({ ok: false, reason: "missing API base for session" })
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
        if (!state.isRecording) {
          state.status = "ready"
          state.statusMessage =
            "Proof session detected from VeriBridge. You can start recording."
        }
        sendResponse({ ok: true, sessionId: session_id, apiUrl: configuredApiUrl })
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
      case "RECORDER_VIDEO_UPLOAD_STARTED": {
        const startedSession = ((msg.payload ?? {}) as { session_id?: string | null }).session_id
        if (startedSession && state.sessionId && startedSession !== state.sessionId) {
          dbgVE(
            "[Video] ignoring upload-started for stale session %s (active %s)",
            startedSession, state.sessionId,
          )
          sendResponse({ ok: false, ignored: true })
          break
        }
        state.videoUploadStatus = "uploading"
        state.videoUploadError = null
        persistRecordingState()
        broadcastStateUpdate()
        sendResponse({ ok: true })
        break
      }

      case "RECORDER_VIDEO_UPLOADED": {
        const { ok, error, keyframe_count, session_id } = (msg.payload ?? {}) as {
          ok?: boolean
          error?: string | null
          keyframe_count?: number
          session_id?: string | null
        }
        // An upload result belongs to the session that was recorded, not to
        // whichever session is active now — never credit a different session.
        if (session_id && state.sessionId && session_id !== state.sessionId) {
          dbgVE(
            "[Video] ignoring upload result for stale session %s (active %s)",
            session_id, state.sessionId,
          )
          sendResponse({ ok: false, ignored: true })
          break
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
        persistRecordingState()
        broadcastStateUpdate()
        sendResponse({ ok: true })
        break
      }

      // ── Recorder tab stream state (sent by recorder.ts) ─────────────────────
      // Lets the popup show ONE status line instead of duplicating the recorder
      // tab's "Screen capture active" indicator.
      case "RECORDER_STREAM_STARTED": {
        state.recorderTabStreamActive = true
        const surface = (msg.payload as { display_surface?: unknown } | undefined)?.display_surface
        state.captureSurface = typeof surface === "string" && surface ? surface : null
        persistRecordingState()
        dbgVE("[RecorderStream] stream started — recorderTabStreamActive=true session=%s", state.sessionId)
        // Broadcast to all tracked content scripts so they hide the floating bar
        // (prevents the VeriBridge overlay from appearing inside the screen recording).
        void broadcastToAllTabs({ type: "RECORDER_STREAM_STARTED" })
        sendResponse({ ok: true })
        break
      }

      // Keepalive ping from the recorder tab during an upload — resets the MV3
      // idle timer so the service worker survives long uploads.
      case "RECORDER_VIDEO_UPLOAD_PROGRESS":
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
        openOrRefreshRecorderTab({
          active: true,
          onReady: (tabId) => sendResponse({ ok: true, tabId }),
        })
        return true  // async sendResponse
      }

      case "DISMISS_UPLOAD_SUCCESS": {
        // Accept an explicit sessionId from the content script payload so the
        // target page's session ID is always used, even if background state has
        // drifted (e.g. a second tab detected a different session).
        const providedId = (msg.payload as { sessionId?: string } | undefined)?.sessionId
        const sid = providedId ?? state.sessionId
        dbgVE("stored dismissed session:", sid)
        state.dismissedForSessionId = sid
        sendResponse({ ok: true })
        break
      }

      case "WORKFLOW_EVENT":
        // Only the session's tracked tabs may contribute workflow events —
        // browsing activity from unrelated tabs is never recorded or uploaded.
        // (Extension-internal senders have no sender.tab and pass through.)
        if (sender.tab?.id !== undefined && !state.trackedTabIds.has(sender.tab.id)) {
          break
        }
        if (state.isRecording) {
          state.events.push(msg.payload as WorkflowEvent)
          persistEvidenceBuffer()
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
        // Same tracked-tab requirement as WORKFLOW_EVENT: DOM snapshots may
        // only come from tabs that belong to this recording session.
        if (
          sender.tab?.id !== undefined &&
          !state.trackedTabIds.has(sender.tab.id)
        ) {
          dbgVE("VISIBLE_EVIDENCE_EVENT from untracked tab — event dropped")
          break
        }
        if (state.isRecording) {
          const veEvent = msg.payload as VisibleEvidenceEvent
          state.visibleEvidenceEvents.push(veEvent)
          persistEvidenceBuffer()
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
    persistEvidenceBuffer()
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
      persistEvidenceBuffer()
    }
    state.trackedTabUrls.set(tabId, safeUrl)
  }

  // Send START_CAPTURING only to the session's own tabs (tracked tabs and the
  // proof-builder tab). This is what re-attaches the HUD after a full-document
  // navigation — the fresh content script receives the signal, asks GET_STATE,
  // and rehydrates capture + HUD exactly once. Unrelated tabs are never told
  // to capture.
  if (isSessionTabId(tabId)) {
    chrome.tabs.sendMessage(tabId, { type: "START_CAPTURING" }).catch(() => undefined)
  }
})

// Re-inject overlay when the user switches to a tab during recording.
// Handles the case where the user activates a tab that already loaded but
// missed the initial broadcast (e.g. the recorder tab was focused at that time).
chrome.tabs.onActivated.addListener((activeInfo) => {
  if (!state.isRecording) return
  if (!isSessionTabId(activeInfo.tabId)) return
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (chrome.runtime.lastError) return
    const url = tab.url ?? ""
    if (url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url === "about:blank") return
    chrome.tabs.sendMessage(activeInfo.tabId, { type: "START_CAPTURING" }).catch(() => undefined)
  })
})

/**
 * Upload accumulated visible evidence before advancing the session upload.
 * Duplicate delivery is harmless because the backend keys events by the
 * extension-generated event_id.
 */
async function sendVisibleEvidence(): Promise<EvidenceUploadResult> {
  if (!state.sessionId || state.visibleEvidenceEvents.length === 0) {
    dbgVE("sendVisibleEvidence: skipping — sessionId:", state.sessionId || "(none)",
      "events:", state.visibleEvidenceEvents.length)
    return { ok: true }
  }
  if (!state.authToken) {
    dbgVE("sendVisibleEvidence: upload skipped — missing recorder auth token")
    console.warn("VeriBridge: visible evidence upload skipped because recorder auth is missing. Restart from the VeriBridge app.")
    return { ok: false, error: "Visible evidence upload is missing recorder authentication." }
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
      dbgVE("sendVisibleEvidence: POST error — HTTP", resp.status)
      console.warn(`VeriBridge: visible evidence upload returned HTTP ${resp.status}`)
      return { ok: false, error: `Visible evidence upload returned HTTP ${resp.status}.` }
    } else {
      dbgVE("sendVisibleEvidence: POST success — HTTP", resp.status)
      return { ok: true }
    }
  } catch (err) {
    // Network failure — log and swallow so the main upload is not affected.
    dbgVE("sendVisibleEvidence: network error:", err)
    console.warn("VeriBridge: visible evidence upload failed:", err)
    return { ok: false, error: "Visible evidence upload failed because the backend was unreachable." }
  }
}

// ── Screen-recording finalization orchestration ───────────────────────────────
// The recorder tab owns the only copy of the screen recording. When the user
// stops or sends the proof from the floating bar / popup, the background must
// ask the recorder tab to finalize (flush final chunks → persist → upload) and
// wait for the backend acknowledgment — never hard-fail with an instruction the
// user cannot act on. Runtime messages reach extension pages (the recorder tab)
// but not content scripts, so this broadcast targets exactly the recorder.

/** Upper bound for one finalize-and-upload round trip (large blob + slow net). */
const VIDEO_FINALIZE_WAIT_MS = 150_000

interface RecorderFinalizeResponse {
  ok?: boolean
  has_media?: boolean
  keyframe_count?: number
  code?: string
  message?: string
  no_listener?: boolean
  timed_out?: boolean
}

function sendFinalizeRequestToRecorder(): Promise<RecorderFinalizeResponse> {
  return new Promise((resolve) => {
    try {
      // The target session travels with the request so a recorder tab left
      // over from a PREVIOUS session stays silent instead of answering with
      // its own (already-completed) upload state — a stale tab answering
      // first is how a missing recording got reported as uploaded.
      chrome.runtime.sendMessage({
        type: "RECORDER_FINALIZE_REQUEST",
        payload: { session_id: state.sessionId },
      }, (resp) => {
        if (chrome.runtime.lastError || resp === undefined || resp === null) {
          resolve({ no_listener: true })
          return
        }
        resolve(resp as RecorderFinalizeResponse)
      })
    } catch {
      resolve({ no_listener: true })
    }
  })
}

// The status mutates concurrently (RECORDER_VIDEO_UPLOADED runs during awaits),
// so reads go through this helper to avoid stale control-flow narrowing.
function videoUploadStatusNow(): InternalState["videoUploadStatus"] {
  return state.videoUploadStatus
}

/** Poll the video-upload status (updated by RECORDER_VIDEO_UPLOADED) until settled. */
async function waitForVideoUploaded(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (videoUploadStatusNow() === "uploaded") return true
    if (videoUploadStatusNow() === "failed") return false
    await new Promise<void>((r) => setTimeout(r, 1000))
  }
  return videoUploadStatusNow() === "uploaded"
}

/** Open (or keep) a recorder tab so its load-time recovery can resume a persisted upload. */
function openRecorderTabForRecovery(): void {
  const recorderUrl = chrome.runtime.getURL("recorder.html")
  const createTab = (): void => {
    chrome.tabs.create({ url: recorderUrl, active: false }, (tab) => {
      if (tab?.id !== undefined) {
        state.recorderTabId = tab.id
        persistRecordingState()
      }
    })
  }
  const existingTabId = state.recorderTabId
  if (existingTabId !== null) {
    chrome.tabs.get(existingTabId, (existingTab) => {
      if (chrome.runtime.lastError || !existingTab) createTab()
    })
  } else {
    createTab()
  }
}

async function ensureVideoUploaded(): Promise<{ ok: true } | { ok: false; error: string }> {
  if (state.videoUploadStatus === "uploaded") return { ok: true }
  recorderDiagnostic("video_finalize_requested", state.recorderSessionConfig)
  const overallDeadline = Date.now() + VIDEO_FINALIZE_WAIT_MS

  // The recorder answers only after its upload settles; cap the wait (and
  // clear the cap timer on settle so it never lingers).
  const resp = await new Promise<RecorderFinalizeResponse>((resolve) => {
    let settled = false
    const timer = setTimeout(() => {
      if (!settled) { settled = true; resolve({ timed_out: true }) }
    }, VIDEO_FINALIZE_WAIT_MS)
    void sendFinalizeRequestToRecorder().then((r) => {
      if (!settled) { settled = true; clearTimeout(timer); resolve(r) }
    })
  })

  if (resp.ok === true) {
    if (videoUploadStatusNow() !== "uploaded") {
      state.videoUploadStatus = "uploaded"
      state.videoUploadError = null
      const kf = Number(resp.keyframe_count ?? 0)
      state.videoKeyframeCount = Number.isFinite(kf) ? kf : 0
      persistRecordingState()
    }
    return { ok: true }
  }

  if (resp.no_listener === true) {
    // Recorder tab is closed. Re-open it: on load it recovers any persisted
    // recording from IndexedDB, resumes the upload, and reports back via
    // RECORDER_VIDEO_UPLOADED — which the poll below observes.
    openRecorderTabForRecovery()
    const remaining = overallDeadline - Date.now()
    if (remaining > 0 && await waitForVideoUploaded(remaining)) return { ok: true }
    const error =
      state.videoUploadError ??
      "The screen recording has not been uploaded yet. Open the VeriBridge recorder tab, " +
      "finish or retry the recording upload, then send proof again. [WPR-UPLOAD-ACK-LOST]"
    return { ok: false, error }
  }

  if (resp.timed_out === true) {
    if (videoUploadStatusNow() === "uploaded") return { ok: true }
    return {
      ok: false,
      error:
        "The screen recording upload did not finish in time. Keep the recorder tab open " +
        "until the upload completes, then retry. [WPR-UPLOAD-ACK-LOST]",
    }
  }

  const message = String(resp.message ?? "The screen recording could not be uploaded.")
  return { ok: false, error: resp.code ? `${message} [${resp.code}]` : message }
}

async function sendProof(finalNote: string | null): Promise<{ ok: boolean; error?: string }> {
  if (!state.sessionId) {
    const err = "No session ID. Enter a session ID in the extension popup."
    return { ok: false, error: err }
  }
  if (!state.authToken) {
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
  if (state.videoUploadStatus !== "uploaded") {
    // The recorder tab still holds the capture, an in-flight upload, or a
    // failed-but-recoverable recording. Finalize it (stop → flush final
    // chunks → persist → upload with the same idempotency key) and wait for
    // the backend acknowledgment instead of hard-failing with an instruction
    // the user cannot act on from the floating bar.
    state.status = "uploading"
    state.statusMessage = "Finishing screen recording upload…"
    state.lastUploadError = null
    broadcastProofUploadStarted()
    broadcastStateUpdate()
    const ensured = await ensureVideoUploaded()
    if (!ensured.ok) {
      const replayError = ensured.error
      state.status = "upload_failed"
      state.statusMessage = `Upload failed: ${replayError}`
      state.lastUploadError = replayError
      persistWebsiteProofUploadState({
        status: "upload_failed",
        sessionId: state.sessionId,
        startedAt: new Date().toISOString(),
        lastEvent: "upload_failed",
        statusMessage: state.statusMessage,
        lastUploadError: replayError,
      })
      recorderDiagnostic("proof_upload_blocked", state.recorderSessionConfig, "replay_not_retained")
      broadcastStateUpdate()
      return { ok: false, error: replayError }
    }
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

  // Analysis may not begin until both side-evidence contracts have either
  // persisted their batch or explicitly reported that the batch is empty.
  const [visibleEvidenceResult, visualFrameResult] = await Promise.all([
    sendVisibleEvidence(),
    sendVisualFrames(),
  ])
  const failedSideEvidence = [visibleEvidenceResult, visualFrameResult]
    .find((result): result is { ok: false; error: string } => !result.ok)
  if (failedSideEvidence) {
    const errorMsg = failedSideEvidence.error
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
  recorderDiagnostic("evidence_uploaded", state.recorderSessionConfig)

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
    recorderDiagnostic("proof_uploaded", state.recorderSessionConfig)
    // Proof uploaded — clear persisted recording state so a future SW restart
    // doesn't incorrectly resume a completed recording.
    clearPersistedRecordingState()
    clearPersistedEvidenceBuffer()
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
