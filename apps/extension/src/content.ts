// Content script — injected into every page; only captures events while recording is active.
// Never collects cookies, localStorage, sessionStorage, or password values.

import type { VisibleEvidenceEvent, FileUploadMeta } from "./types"

// ── Debug flag — set to false to silence visible evidence logs in production ──
const DEBUG_VISIBLE_EVIDENCE = true

function dbgVE(...args: unknown[]): void {
  if (DEBUG_VISIBLE_EVIDENCE) console.log("[VisibleEvidence]", ...args)
}

dbgVE("content script loaded on", location.href)

// ── Sensitive field detection ──────────────────────────────────────────────────

/**
 * Matches field names / labels / placeholders that indicate sensitive inputs.
 * The check is project-agnostic — it covers passwords, API keys, tokens, PII,
 * payment card data, and bank account fields across any website or app type.
 */
const SENSITIVE_RE =
  /password|passcode|pass\b|token|secret|api[\s_\-]?key|apikey|access[\s_\-]?key|private[\s_\-]?key|bearer|auth(?:entication|orization|token)?|credential|ssn|social[\s_\-]?security|credit[\s_\-]?card|card[\s_\-]?number|cvv|cvc|expir|bank|routing|account[\s_\-]?number|otp|2fa|mfa/i

// ── Sensitive URL query parameters ────────────────────────────────────────────

/**
 * Query parameter names that often carry secret values.
 * Any URL with one of these parameters will have the value replaced with
 * [REDACTED] before it is stored in the workflow timeline.
 */
const SENSITIVE_QUERY_PARAMS = new Set([
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
 * Redact sensitive query parameters from a URL string.
 * Operates on any URL (deployed, localhost, local network, etc.).
 * Returns the original string unchanged if it cannot be parsed or has no sensitive params.
 */
function redactSensitiveQueryParams(url: string): string {
  if (!url || url.startsWith("chrome://") || url.startsWith("about:")) return url
  try {
    const parsed = new URL(url)
    let changed = false
    parsed.searchParams.forEach((_, k) => {
      if (SENSITIVE_QUERY_PARAMS.has(k.toLowerCase())) {
        parsed.searchParams.set(k, "[REDACTED]")
        changed = true
      }
    })
    return changed ? parsed.toString() : url
  } catch {
    // Non-standard URL — use regex-based fallback (handles data: URLs, etc.)
    return url.replace(
      /([?&])(token|access_token|id_token|refresh_token|api_key|key|secret|password|code|auth|session|jwt)(=[^&]*)/gi,
      "$1$2=[REDACTED]",
    )
  }
}

// ── Visible Evidence — constants & helpers ────────────────────────────────────

/**
 * Keywords that flag a text block as a likely AI/ML result or output.
 * This list intentionally covers many demo domains (object detection, dashboards,
 * chatbots, routing apps, finance, document analysis, etc.).
 */
const RESULT_KWDS = [
  "prediction", "result", "output", "score", "confidence", "probability",
  "risk", "detected", "label", "class", "summary", "answer", "response",
  "route", "recommendation", "chart", "table", "generated", "analysis",
]
// Build once — avoids re-compiling the regex on every DOM snapshot.
const RESULT_KWD_RE = new RegExp(`\\b(${RESULT_KWDS.join("|")})\\b`, "i")

/**
 * Privacy scrubbing patterns applied client-side to every text block
 * before the event is emitted to the background service worker.
 * The backend applies the same patterns again as defense-in-depth.
 */
const SCRUB_PATTERNS: Array<[RegExp, string]> = [
  // JWT-shaped strings first (avoids overlapping with hex pattern below)
  [/ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*/g, "[JWT]"],
  // password / token / key = value pairs in any format
  [/\b(password|passwd|api[_-]?key|secret|token|bearer|auth)\s*[:=]\s*\S+/gi, "$1=[REDACTED]"],
  // Windows and Unix local file paths
  [/([A-Za-z]:\\[^\s,;"'<>]+|\/(?:home|Users|root|tmp|var|etc)\/[^\s,;"'<>]+)/g, "[LOCAL_PATH]"],
  // Supabase project URLs
  [/https?:\/\/[a-z0-9]+\.supabase\.(?:co|com|io)[^\s]*/gi, "[SUPABASE_URL]"],
  // VeriBridge internal pages on localhost
  [/https?:\/\/localhost(?::\d+)?\/(?:dashboard|admin|passport)[^\s]*/gi, "[INTERNAL_URL]"],
  // Credit card numbers (13–16 digits, optional space/dash separators)
  [/\b(?:\d[ -]?){13,16}\b/g, "[CARD]"],
  // Social Security Numbers
  [/\b\d{3}[-\s]\d{2}[-\s]\d{4}\b/g, "[SSN]"],
  // Long hex strings 32+ chars (hashes, tokens, API keys)
  [/\b[0-9a-f]{32,}\b/gi, "[HEX]"],
]

/** Apply all SCRUB_PATTERNS to a single text block. */
function scrubBlock(text: string): string {
  let s = text
  for (const [re, repl] of SCRUB_PATTERNS) s = s.replace(re, repl)
  return s.trim()
}

/**
 * Returns true when the current page is an internal VeriBridge page.
 * We skip evidence capture there to avoid leaking session metadata or auth tokens.
 */
function isVeriBridgeInternal(): boolean {
  const { hostname, pathname } = location
  if (hostname === "localhost") {
    return (
      pathname.startsWith("/dashboard") ||
      pathname.startsWith("/passport") ||
      pathname.startsWith("/admin")
    )
  }
  return hostname.endsWith("veribridge.ai")
}

/** Collect a safe snapshot of current non-sensitive form input values. */
function getInputSnapshot(): Record<string, string> {
  const out: Record<string, string> = {}
  try {
    document.querySelectorAll<HTMLInputElement>("input, select, textarea").forEach((el) => {
      if (isSensitive(el)) return
      const key = (el.name || el.id || el.getAttribute("aria-label") || "").slice(0, 50)
      if (!key || key.startsWith("vb-")) return
      const val =
        el.type === "checkbox" || el.type === "radio"
          ? String((el as HTMLInputElement).checked)
          : (el.value ?? "").trim().slice(0, 200)
      if (val) out[key] = val
    })
  } catch { /* best-effort */ }
  return out
}

const MAX_VE_BLOCKS = 120
const MIN_VE_LEN = 3
const MAX_VE_LEN = 300

/**
 * Walk the live DOM via TreeWalker and return up to MAX_VE_BLOCKS sanitized
 * visible text blocks.  Skips the recorder bar, hidden nodes, and non-content tags.
 */
function getVisibleBlocks(): string[] {
  const blocks: string[] = []
  try {
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const p = node.parentElement
          if (!p) return NodeFilter.FILTER_REJECT
          // Skip recorder bar shadow host and everything inside it
          if (p.closest("#veribridge-recorder-host") !== null) return NodeFilter.FILTER_REJECT
          const tag = p.tagName.toUpperCase()
          if (["SCRIPT", "STYLE", "NOSCRIPT", "META", "HEAD", "TITLE"].includes(tag)) {
            return NodeFilter.FILTER_REJECT
          }
          if ((p as HTMLElement).hidden) return NodeFilter.FILTER_REJECT
          return NodeFilter.FILTER_ACCEPT
        },
      }
    )
    let node: Node | null
    while ((node = walker.nextNode()) !== null && blocks.length < MAX_VE_BLOCKS) {
      const text = (node.textContent ?? "").trim()
      if (text.length >= MIN_VE_LEN && text.length <= MAX_VE_LEN) {
        const scrubbed = scrubBlock(text)
        if (scrubbed.length >= MIN_VE_LEN) blocks.push(scrubbed)
      }
    }
  } catch { /* DOM may be partially constructed */ }
  return blocks
}

/** Filter visible blocks to those containing at least one result keyword. */
function getResultBlocks(blocks: string[]): string[] {
  return blocks.filter((b) => RESULT_KWD_RE.test(b)).slice(0, 30)
}

/**
 * Count graphical rendering elements on the current page.
 * Canvas and SVG elements are used for charts, plots, and data visualizations
 * whose output values may not be readable from DOM text alone.
 */
function getGraphicalElementCounts(): { canvas_count: number; svg_count: number } {
  try {
    const canvas_count = document.querySelectorAll("canvas").length
    const svg_count = document.querySelectorAll("svg").length
    return { canvas_count, svg_count }
  } catch {
    return { canvas_count: 0, svg_count: 0 }
  }
}

/** FNV-1a non-reversible hash — used to mask filenames before sending to the backend. */
function hashName(name: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, "0")
}

/** Categorise a file by its extension for the file_upload_meta payload. */
function fileExtCategory(ext: string): FileUploadMeta["file_category"] {
  const e = ext.toLowerCase()
  if (["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff", "ico"].includes(e)) return "image"
  if (["mp4", "webm", "mov", "avi", "mkv", "flv"].includes(e)) return "video"
  if (["mp3", "wav", "ogg", "aac", "flac", "m4a"].includes(e)) return "audio"
  if (["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "txt", "json", "xml", "md"].includes(e)) {
    return "document"
  }
  return "other"
}

interface WorkflowEvent {
  type: "page_visit" | "click" | "input_change" | "tab_opened" | "navigation"
  timestamp: string
  page_url: string
  page_title: string
  element_tag?: string
  element_id?: string
  element_class?: string
  element_text?: string
  element_name?: string
  element_type?: string
  value?: string
}

interface StateSnapshot {
  isRecording: boolean
  eventCount: number
  startedAt: string | null
  stoppedAt: string | null
  status: string
  lastUploadError: string | null
  sessionId: string
  dismissedForSessionId: string
}

// ── Module-level state ────────────────────────────────────────────────────────

let capturing = false
let barHost: HTMLElement | null = null
let barShadow: ShadowRoot | null = null

// Set to true if the extension is reloaded while this content script is running.
// All chrome.runtime calls are gated on this flag to prevent uncaught exceptions.
let contextInvalidated = false

let autoDismissTimer: ReturnType<typeof setTimeout> | null = null
let barPoll: ReturnType<typeof setInterval> | null = null
let barMinimized = false
let lastState: StateSnapshot | null = null

// ── Fullscreen state tracking ─────────────────────────────────────────────────
/**
 * True when the document (or any element) is in fullscreen.
 * Used to show a warning in the floating bar and handle stop safely.
 */
let isFullscreen = false

// ── Visible Evidence — module state ──────────────────────────────────────────
/** Epoch-ms at which the current recording started; offset basis for timestamp_ms. */
let recordingStartMs = 0
/** Debounce timer for post-action DOM snapshots (click / input_change). */
let postActionSnapTimer: ReturnType<typeof setTimeout> | null = null
/** Debounce timer for MutationObserver-triggered snapshots. */
let mutDebounceTimer: ReturnType<typeof setTimeout> | null = null
/** Active MutationObserver — null when not recording. */
let mutObs: MutationObserver | null = null

// ── Local dismiss storage ─────────────────────────────────────────────────────
// Persists dismissed state in sessionStorage so it survives polling restarts and
// extension context loss without depending on the background service worker.

function dismissedStorageKey(sessionId: string): string {
  return `veribridge:dismissed-upload-success:${sessionId}`
}

function isLocallyDismissed(sessionId: string): boolean {
  try {
    return sessionStorage.getItem(dismissedStorageKey(sessionId)) === "true"
  } catch {
    return false
  }
}

function setLocallyDismissed(sessionId: string): void {
  try {
    sessionStorage.setItem(dismissedStorageKey(sessionId), "true")
  } catch { /* storage unavailable — best effort */ }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function nowIso(): string {
  return new Date().toISOString()
}

/**
 * Returns the current page URL with sensitive query parameters already redacted.
 * Use this everywhere instead of `location.href` when storing events.
 */
function safePageUrl(): string {
  return redactSensitiveQueryParams(location.href)
}

/**
 * Returns true if the input element should never have its value stored.
 * Checks: input type, name, id, placeholder, aria-label, label text, autocomplete.
 */
function isSensitive(el: HTMLInputElement): boolean {
  if (el.type === "password") return true
  const attrs = [
    el.name ?? "",
    el.id ?? "",
    el.getAttribute("placeholder") ?? "",
    el.getAttribute("aria-label") ?? "",
    el.getAttribute("autocomplete") ?? "",
    el.getAttribute("data-field") ?? "",
  ]
  return attrs.some((a) => SENSITIVE_RE.test(a))
}

function safeMeta(el: Element): Partial<WorkflowEvent> {
  const input = el as HTMLInputElement
  return {
    element_tag: el.tagName.toLowerCase(),
    element_id: el.id || undefined,
    element_class: (el.className as string) || undefined,
    element_text: el.textContent?.trim().slice(0, 80) || undefined,
    element_name: input.name || undefined,
    element_type: input.type || undefined,
  }
}

// ── Extension context safety ──────────────────────────────────────────────────

async function safeSendMessage<T = unknown>(message: unknown): Promise<T | null> {
  if (contextInvalidated) return null
  try {
    const result = (await chrome.runtime.sendMessage(message)) as T
    return result
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (
      msg.includes("Extension context invalidated") ||
      msg.includes("Receiving end does not exist")
    ) {
      handleContextInvalidated()
    }
    return null
  }
}

/**
 * Handle extension context invalidation (extension reloaded/disabled).
 *
 * Idempotent — safe to call multiple times; only the first call takes effect.
 * Stops all timers, removes event listeners, hides the bar, and sets the
 * contextInvalidated flag so all subsequent safeSendMessage calls short-circuit
 * without attempting any chrome.runtime calls.
 *
 * Only logs one console warning so the extension error log stays clean.
 */
function handleContextInvalidated(): void {
  if (contextInvalidated) return   // already handled — do not log again
  contextInvalidated = true
  console.warn(
    "VeriBridge extension was reloaded. " +
    "Refresh this page before continuing recording.",
  )
  stopCapture()
  hideFloatingBar()
}

// ── Visible Evidence — emit & capture ────────────────────────────────────────

/** Forward a VisibleEvidenceEvent to the background service worker. */
function emitVisibleEvidence(event: VisibleEvidenceEvent): void {
  dbgVE("message sent to background", event.event_type,
    "| visible_text_blocks:", event.visible_text_blocks.length,
    "| result_like_blocks:", event.result_like_blocks.length)
  void safeSendMessage({ type: "VISIBLE_EVIDENCE_EVENT", payload: event })
}

/**
 * Take a DOM snapshot and emit a VisibleEvidenceEvent.
 * Silently skips when not recording or on a VeriBridge-internal page.
 */
function captureSnapshot(
  eventType: VisibleEvidenceEvent["event_type"],
  actionMeta?: Record<string, string>,
  fileUploadMeta?: FileUploadMeta | null,
): void {
  if (!capturing || isVeriBridgeInternal()) return
  const visibleBlocks = getVisibleBlocks()
  const resultBlocks = getResultBlocks(visibleBlocks)
  const { canvas_count, svg_count } = getGraphicalElementCounts()
  dbgVE("snapshot created", eventType,
    "| visible_text_blocks:", visibleBlocks.length,
    "| result_like_blocks:", resultBlocks.length,
    "| canvas:", canvas_count, "| svg:", svg_count)
  emitVisibleEvidence({
    event_type: eventType,
    timestamp_ms: Date.now() - recordingStartMs,
    url: safePageUrl(),
    page_title: document.title,
    target_domain: location.hostname,
    visible_text_blocks: visibleBlocks,
    result_like_blocks: resultBlocks,
    input_snapshot: getInputSnapshot(),
    action_snapshot: { ...(actionMeta ?? {}), canvas_count: String(canvas_count), svg_count: String(svg_count) },
    file_upload_meta: fileUploadMeta ?? null,
    canvas_count,
    svg_count,
  })
}

/**
 * Debounced post-action snapshot: waits 1.5 s after the triggering event so
 * the page has time to render any result or status change.
 * A subsequent call within the window resets the timer.
 */
function schedulePostActionSnapshot(
  eventType: VisibleEvidenceEvent["event_type"],
  actionMeta?: Record<string, string>,
): void {
  if (postActionSnapTimer) clearTimeout(postActionSnapTimer)
  postActionSnapTimer = setTimeout(() => {
    postActionSnapTimer = null
    captureSnapshot(eventType, actionMeta)
  }, 1500)
}

// ── Event capture ─────────────────────────────────────────────────────────────

function emit(event: WorkflowEvent): void {
  void safeSendMessage({ type: "WORKFLOW_EVENT", payload: event })
}

function handleFormSubmit(e: Event): void {
  const form = e.target as HTMLFormElement
  const actionMeta: Record<string, string> = {}
  if (form.action) actionMeta["form_action"] = form.action.slice(0, 200)
  if (form.method) actionMeta["form_method"] = form.method
  captureSnapshot("form_submit", actionMeta)
}

function handleClick(e: Event): void {
  const target = e.target as Element
  // Shadow DOM re-targets clicks inside the bar host to the host element at capture phase.
  if (!target || target === barHost) return
  const meta = safeMeta(target)
  emit({
    type: "click",
    timestamp: nowIso(),
    page_url: safePageUrl(),
    page_title: document.title,
    ...meta,
  })
  // Schedule a DOM snapshot 1.5 s after the click to capture any resulting page update.
  const actionMeta: Record<string, string> = {}
  if (meta.element_tag) actionMeta["tag"] = meta.element_tag
  if (meta.element_text) actionMeta["text"] = meta.element_text.slice(0, 100)
  if (meta.element_id) actionMeta["id"] = meta.element_id
  schedulePostActionSnapshot("click", actionMeta)
}

function handleChange(e: Event): void {
  const target = e.target as HTMLInputElement
  if (!target) return
  const meta = safeMeta(target)
  emit({
    type: "input_change",
    timestamp: nowIso(),
    page_url: safePageUrl(),
    page_title: document.title,
    ...meta,
    // Sensitive inputs: store a redaction marker instead of any value.
    // The marker [REDACTED_SENSITIVE_FIELD] lets the backend privacy scan
    // count how many fields the extension already masked.
    value: isSensitive(target) ? "[REDACTED_SENSITIVE_FIELD]" : undefined,
  })

  if (target.type === "file" && target.files && target.files.length > 0) {
    // File input: capture safe metadata only — never the local path or raw filename.
    const file = target.files[0]
    const nameParts = file.name.split(".")
    const ext = nameParts.length > 1 ? nameParts[nameParts.length - 1] : ""
    const uploadMeta: FileUploadMeta = {
      file_category: fileExtCategory(ext),
      file_extension: ext.toLowerCase(),
      file_name_masked: hashName(file.name),
    }
    const actionMeta: Record<string, string> = {}
    if (meta.element_tag) actionMeta["tag"] = meta.element_tag
    if (meta.element_name) actionMeta["name"] = meta.element_name ?? ""
    captureSnapshot("file_upload", actionMeta, uploadMeta)
  } else {
    // Regular input change — snapshot after the debounce window in case the page reacts.
    const inputMeta: Record<string, string> = {}
    if (meta.element_tag) inputMeta["tag"] = meta.element_tag
    if (meta.element_name) inputMeta["name"] = meta.element_name ?? ""
    if (meta.element_type) inputMeta["input_type"] = meta.element_type
    if (!isSensitive(target) && target.value?.trim()) {
      inputMeta["value_preview"] = target.value.trim().slice(0, 50)
    }
    schedulePostActionSnapshot("input_change", inputMeta)
  }
}

// ── Fullscreen change handlers ─────────────────────────────────────────────────

/**
 * Returns true if the document has an active fullscreen element,
 * checking both the standard and WebKit-prefixed APIs.
 */
function detectFullscreen(): boolean {
  return (
    !!document.fullscreenElement ||
    !!(document as unknown as { webkitFullscreenElement: Element | null })
      .webkitFullscreenElement
  )
}

/**
 * Handle fullscreen enter/exit events.
 * Updates the isFullscreen flag and re-renders the bar with a warning when fullscreen
 * is active. Recording state and event capture are NOT interrupted — only the UI
 * warning changes.
 *
 * Chrome limitation: `captureVisibleTab` (used in background.ts for screenshots)
 * may return a blank/black frame for native video content in hardware-accelerated
 * fullscreen. DOM event capture continues normally. A warning is shown in the bar.
 */
function handleFullscreenChange(): void {
  const nowFullscreen = detectFullscreen()
  if (nowFullscreen === isFullscreen) return  // no change, skip re-render
  isFullscreen = nowFullscreen
  dbgVE("[Fullscreen] changed — fullscreen:", isFullscreen)
  // Re-render bar so the warning badge appears/disappears without polling delay.
  if (barHost) {
    fetchAndRender()
  }
}

function startCapture(): void {
  if (capturing) return
  capturing = true
  recordingStartMs = Date.now()

  dbgVE("recording active", true, "| session_id (from URL):", new URLSearchParams(location.search).get("veribridge_session_id") ?? "(not in URL)")
  dbgVE("starting capture on", location.href)

  emit({ type: "page_visit", timestamp: nowIso(), page_url: safePageUrl(), page_title: document.title })
  document.addEventListener("click", handleClick, { capture: true, passive: true })
  document.addEventListener("change", handleChange, { capture: true, passive: true })
  document.addEventListener("submit", handleFormSubmit, { capture: true, passive: true })

  // ── Fullscreen detection ────────────────────────────────────────────────────
  // Detect initial fullscreen state on capture start (e.g. if already fullscreen).
  isFullscreen = detectFullscreen()
  // Standard API (Chrome 61+)
  document.addEventListener("fullscreenchange", handleFullscreenChange, { passive: true })
  // WebKit prefix — needed for older Safari and some embedded webviews.
  document.addEventListener("webkitfullscreenchange", handleFullscreenChange, { passive: true })

  // Capture the page's current visible state on load.
  captureSnapshot("page_load")

  // Watch for DOM mutations (debounced 1.5 s) — emits result_detected if result
  // keywords appear in the updated content, otherwise dom_snapshot.
  mutObs = new MutationObserver(() => {
    if (mutDebounceTimer) clearTimeout(mutDebounceTimer)
    mutDebounceTimer = setTimeout(() => {
      mutDebounceTimer = null
      if (!capturing || isVeriBridgeInternal()) return
      const visibleBlocks = getVisibleBlocks()
      const resultBlocks = getResultBlocks(visibleBlocks)
      emitVisibleEvidence({
        event_type: resultBlocks.length > 0 ? "result_detected" : "dom_snapshot",
        timestamp_ms: Date.now() - recordingStartMs,
        url: safePageUrl(),
        page_title: document.title,
        target_domain: location.hostname,
        visible_text_blocks: visibleBlocks,
        result_like_blocks: resultBlocks,
        input_snapshot: getInputSnapshot(),
        action_snapshot: {},
        file_upload_meta: null,
      })
    }, 1500)
  })
  mutObs.observe(document.body, { childList: true, subtree: true, characterData: true })
}

function stopCapture(): void {
  if (!capturing) return
  // Snapshot the final page state BEFORE flipping the flag (captureSnapshot checks it).
  captureSnapshot("recording_end")
  capturing = false

  document.removeEventListener("click", handleClick, true)
  document.removeEventListener("change", handleChange, true)
  document.removeEventListener("submit", handleFormSubmit, true)

  // Remove fullscreen listeners to avoid memory leaks.
  document.removeEventListener("fullscreenchange", handleFullscreenChange)
  document.removeEventListener("webkitfullscreenchange", handleFullscreenChange)
  isFullscreen = false

  if (postActionSnapTimer) { clearTimeout(postActionSnapTimer); postActionSnapTimer = null }
  if (mutDebounceTimer) { clearTimeout(mutDebounceTimer); mutDebounceTimer = null }
  if (mutObs) { mutObs.disconnect(); mutObs = null }
}

chrome.runtime.onMessage.addListener((msg: { type: string }) => {
  if (msg.type === "START_CAPTURING") {
    startCapture()
    showFloatingBar()
  } else if (msg.type === "STOP_CAPTURING") {
    stopCapture()
    refreshBar()
  }
})

// ── Session detection ──────────────────────────────────────────────────────────

function detectSessionFromUrl(): void {
  const params = new URLSearchParams(location.search)
  const sessionId = params.get("veribridge_session_id")
  if (!sessionId) return
  void safeSendMessage({
    type: "SESSION_DETECTED_FROM_PAGE",
    payload: {
      session_id: sessionId,
      page_url: safePageUrl(),
      page_title: document.title,
      detected_at: nowIso(),
    },
  })
}

detectSessionFromUrl()

// On init, check if recording is already active (handles page navigation during a session).
void safeSendMessage<StateSnapshot>({ type: "GET_STATE" }).then((s) => {
  dbgVE("recording active", s?.isRecording ?? false, "| session_id:", s?.sessionId ?? "(none)")
  if (s?.isRecording) {
    startCapture()
    showFloatingBar()
  }
})

// ── Manual test hook ──────────────────────────────────────────────────────────
// Call window.__VERIBRIDGE_CAPTURE_VISIBLE_EVIDENCE_TEST__() from DevTools to
// force one DOM snapshot from the current page and send it to the background.
// This lets you verify the pipeline (content → background → backend) without
// going through a full recording session.
;(window as unknown as Record<string, unknown>).__VERIBRIDGE_CAPTURE_VISIBLE_EVIDENCE_TEST__ =
  function (): void {
    dbgVE("manual test hook triggered on", location.href)
    if (!capturing) {
      // Temporarily enable capturing so captureSnapshot proceeds
      capturing = true
      recordingStartMs = Date.now()
      captureSnapshot("dom_snapshot", { source: "manual_test" })
      capturing = false
    } else {
      captureSnapshot("dom_snapshot", { source: "manual_test" })
    }
    dbgVE("manual test hook: snapshot sent to background (check console + Network tab)")
  }

// ── Floating recorder bar ──────────────────────────────────────────────────────

const BAR_HOST_ID = "veribridge-recorder-host"

function fmtTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0")
  const s = (totalSeconds % 60).toString().padStart(2, "0")
  return `${m}:${s}`
}

function elapsedSecs(startedAt: string | null, stoppedAt: string | null): number {
  if (!startedAt) return 0
  const end = stoppedAt ? new Date(stoppedAt).getTime() : Date.now()
  return Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000))
}

const BAR_CSS = `
:host{all:initial}
.bar{
  display:flex;align-items:center;gap:10px;
  background:#111;color:#fff;border-radius:12px;
  padding:10px 14px;font-size:13px;line-height:1;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  box-shadow:0 4px 24px rgba(0,0,0,.5),0 1px 4px rgba(0,0,0,.3);
  border:1px solid rgba(255,255,255,.1);user-select:none;white-space:nowrap;
}
.bar.mini{padding:8px 10px;gap:8px}
.logo{
  background:#fff;color:#111;font-weight:900;font-size:11px;
  border-radius:5px;padding:2px 6px;letter-spacing:-.5px;flex-shrink:0;
}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:#6b7280}
.dot.rec{background:#ef4444;animation:vbpulse 1.1s ease-in-out infinite}
.dot.stp{background:#f59e0b}
@keyframes vbpulse{0%,100%{opacity:1}50%{opacity:.3}}
.info{display:flex;align-items:center;gap:8px;flex:1;min-width:0}
.lbl{font-weight:600;color:#f9fafb}
.tmr{font-variant-numeric:tabular-nums;color:#d1d5db}
.sep{color:#4b5563}
.cnt{color:#9ca3af;font-size:12px}
.msg{font-size:12px}
.msg.up{color:#93c5fd}
.msg.ok{color:#86efac;font-weight:600}
.msg.er{color:#fca5a5}
.acts{display:flex;gap:6px;align-items:center}
.btn{
  border:none;border-radius:7px;padding:5px 10px;
  font-size:12px;font-weight:600;cursor:pointer;
  font-family:inherit;transition:opacity .1s;
}
.btn:hover{opacity:.82}
.b-stop{background:#dc2626;color:#fff}
.b-send{background:#fff;color:#111}
.b-dismiss{background:#374151;color:#d1d5db}
.b-icon{
  background:none;border:none;color:#6b7280;
  font-size:18px;line-height:1;cursor:pointer;
  padding:0 2px;font-family:inherit;flex-shrink:0;
}
.b-icon:hover{color:#d1d5db}
.fs-warn{
  font-size:10px;font-weight:600;color:#fbbf24;
  background:rgba(251,191,36,.12);border:1px solid rgba(251,191,36,.3);
  border-radius:5px;padding:2px 7px;white-space:normal;max-width:220px;line-height:1.3;
}
`

function buildBarHTML(s: StateSnapshot | null): string {
  const status = s?.status ?? "idle"
  const rec    = s?.isRecording ?? false
  const count  = s?.eventCount ?? 0
  const secs   = elapsedSecs(s?.startedAt ?? null, s?.stoppedAt ?? null)

  if (barMinimized) {
    return `<div class="bar mini">
      <div class="logo">VB</div>
      <div class="dot${rec ? " rec" : ""}"></div>
      <button class="b-icon" id="vb-expand" title="Expand">＋</button>
    </div>`
  }

  let info = ""
  let acts = ""

  if (status === "uploading") {
    info = `<span class="msg up">Uploading proof…</span>`

  } else if (status === "uploaded") {
    info = `<span class="msg ok">✓ Proof uploaded successfully</span>`
    acts = `<button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>`

  } else if (status === "upload_failed" || status === "error") {
    const reason = (s?.lastUploadError ?? "Unknown error").slice(0, 55)
    info = `<span class="msg er">Upload failed: ${reason}</span>`
    acts = `
      <button class="btn b-send" id="vb-send">Retry</button>
      <button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>
    `

  } else if (status === "recording" || rec) {
    info = `
      <div class="dot rec"></div>
      <span class="lbl">Recording</span>
      <span class="tmr">${fmtTime(secs)}</span>
      <span class="sep">·</span>
      <span class="cnt">${count} event${count !== 1 ? "s" : ""}</span>
    `
    acts = `
      <button class="btn b-stop" id="vb-stop">Stop</button>
      <button class="btn b-send" id="vb-send">Stop &amp; Send</button>
    `

  } else if (status === "stopped") {
    info = `
      <div class="dot stp"></div>
      <span class="lbl">Stopped</span>
      <span class="tmr">${fmtTime(secs)}</span>
      <span class="sep">·</span>
      <span class="cnt">${count} event${count !== 1 ? "s" : ""}</span>
    `
    acts = `<button class="btn b-send" id="vb-send">Send Proof</button>`
  }

  // ── Fullscreen warning (shown when isFullscreen and recording) ────────────
  // The floating bar is hidden by the browser's fullscreen compositor layer,
  // so we can't show it while fullscreen is active. After the user exits
  // fullscreen, the bar reappears and shows this contextual note.
  const fullscreenWarn = (!isFullscreen && rec && capturing)
    ? ""   // not in fullscreen — no warning needed
    : isFullscreen
    ? `<span class="fs-warn">Fullscreen recording may be limited by browser restrictions. Exit fullscreen if capture appears paused.</span>`
    : ""

  return `<div class="bar">
    <div class="logo">VB</div>
    <div class="info">${info}${fullscreenWarn}</div>
    <div class="acts">${acts}</div>
    <button class="b-icon" id="vb-minimize" title="Minimize">−</button>
  </div>`
}

function renderBar(s: StateSnapshot | null): void {
  if (!barShadow) return
  if (s) lastState = s
  barShadow.innerHTML = `<style>${BAR_CSS}</style>${buildBarHTML(lastState)}`
  wireBarButtons()
}

function wireBarButtons(): void {
  if (!barShadow) return
  barShadow.getElementById("vb-stop")?.addEventListener("click", () => { void onBarStop() })
  barShadow.getElementById("vb-send")?.addEventListener("click", () => { void onBarStopAndSend() })
  barShadow.getElementById("vb-minimize")?.addEventListener("click", () => {
    barMinimized = true
    renderBar(null)
  })
  barShadow.getElementById("vb-expand")?.addEventListener("click", () => {
    barMinimized = false
    renderBar(null)
  })
  barShadow.getElementById("vb-dismiss")?.addEventListener("click", () => {
    const sessionId = lastState?.sessionId ?? ""
    console.log("Dismiss clicked on target page")

    // Store local flag and remove DOM immediately — do NOT wait for the background
    // message. This is the real guard; background message is best-effort.
    if (sessionId) {
      setLocallyDismissed(sessionId)
      console.log(`Stored local dismissed flag for session: ${sessionId}`)
    }
    hideFloatingBar()

    // Notify background so other tabs and future poll cycles also skip the bar.
    void safeSendMessage({
      type: "DISMISS_UPLOAD_SUCCESS",
      payload: { sessionId },
    }).then((r) => {
      if (r !== null) {
        console.log("Sent DISMISS_UPLOAD_SUCCESS to background")
      } else {
        console.log("Background dismiss failed, using local fallback")
      }
    })
  })
}

async function onBarStop(): Promise<void> {
  // Best-effort: exit fullscreen before stopping so the bar reappears
  // and the final screenshot is not a black frame.
  if (isFullscreen && document.fullscreenElement) {
    try {
      await document.exitFullscreen()
    } catch {
      // exitFullscreen() throws if there is no fullscreen element or if not
      // allowed from this context — silently ignore and stop anyway.
    }
  }
  stopCapture()
  await safeSendMessage({ type: "STOP_RECORDING" })
  const s = await safeSendMessage<StateSnapshot>({ type: "GET_STATE" })
  if (s) renderBar(s)
}

async function onBarStopAndSend(): Promise<void> {
  if (capturing) {
    await onBarStop()
    await new Promise<void>((r) => setTimeout(r, 200))
  }
  await safeSendMessage({ type: "SEND_PROOF", payload: { finalNote: null } })
  const s = await safeSendMessage<StateSnapshot>({ type: "GET_STATE" })
  if (s) renderBar(s)
}

function shouldSkipRender(s: StateSnapshot): boolean {
  if (s.status !== "uploaded") return false
  const sid = s.sessionId
  if (!sid) return false
  // Local flag: works even when background messaging is unavailable.
  if (isLocallyDismissed(sid)) {
    console.log("Skip render because local dismissed flag exists")
    return true
  }
  // Background flag: set by DISMISS_UPLOAD_SUCCESS handler.
  if (s.dismissedForSessionId === sid) {
    return true
  }
  return false
}

function fetchAndRender(): void {
  void safeSendMessage<StateSnapshot>({ type: "GET_STATE" }).then((s) => {
    if (!s) return

    if (shouldSkipRender(s)) {
      hideFloatingBar()
      return
    }

    renderBar(s)

    // Auto-dismiss bar 5 seconds after a successful upload.
    if (s.status === "uploaded" && !autoDismissTimer) {
      const sessionId = s.sessionId ?? ""
      autoDismissTimer = setTimeout(() => {
        console.log("Auto-dismissing success bar")
        if (sessionId) setLocallyDismissed(sessionId)
        hideFloatingBar()
        autoDismissTimer = null
        // Notify background best-effort.
        void safeSendMessage({ type: "DISMISS_UPLOAD_SUCCESS", payload: { sessionId } })
      }, 5000)
    }
  })
}

function showFloatingBar(): void {
  if (!barHost) {
    // Reuse a leftover host from a previous content script execution in this tab
    // rather than creating a duplicate element.
    const existing = document.getElementById(BAR_HOST_ID) as HTMLElement | null
    if (existing) {
      barHost = existing
      barShadow = existing.shadowRoot
    } else {
      const host = document.createElement("div")
      host.id = BAR_HOST_ID
      host.setAttribute(
        "style",
        "all:initial!important;position:fixed!important;bottom:20px!important;" +
        "right:20px!important;z-index:2147483647!important;pointer-events:auto!important;"
      )
      ;(document.body ?? document.documentElement).appendChild(host)
      barHost = host
      barShadow = host.attachShadow({ mode: "open" })
    }
  }

  barMinimized = false
  fetchAndRender()

  if (!barPoll) {
    barPoll = setInterval(fetchAndRender, 1000)
  }
}

function hideFloatingBar(): void {
  if (barPoll) { clearInterval(barPoll); barPoll = null }
  if (autoDismissTimer) { clearTimeout(autoDismissTimer); autoDismissTimer = null }
  // Remove the DOM node entirely rather than setting display:none.
  // This prevents any stale poll response from re-rendering the bar through
  // the still-attached shadow root.
  if (barHost) {
    barHost.remove()
    barHost = null
    barShadow = null
    lastState = null
    console.log("Removed floating bar DOM")
  }
}

function refreshBar(): void {
  if (barHost) {
    fetchAndRender()
  }
}
