// Content script — injected into every page; only captures events while recording is active.
// Never collects cookies, localStorage, sessionStorage, or password values.

const SENSITIVE_RE =
  /password|pass\b|token|secret|api_key|apikey|card|cvv|ssn|otp|2fa|mfa|authorization|bearer/i

interface WorkflowEvent {
  type: "page_visit" | "click" | "input_change"
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
}

// ── Module-level state ────────────────────────────────────────────────────────

let capturing = false
let barHost: HTMLElement | null = null

// Set to true if the extension is reloaded while this content script is running.
// All chrome.runtime calls are gated on this flag to prevent uncaught exceptions.
let contextInvalidated = false

// Timer reference for auto-dismissing the bar after a successful upload.
let autoDismissTimer: ReturnType<typeof setTimeout> | null = null

// ── Utility ───────────────────────────────────────────────────────────────────

function nowIso(): string {
  return new Date().toISOString()
}

function isSensitive(el: HTMLInputElement): boolean {
  return (
    el.type === "password" ||
    SENSITIVE_RE.test(el.name ?? "") ||
    SENSITIVE_RE.test(el.id ?? "") ||
    SENSITIVE_RE.test(el.getAttribute("autocomplete") ?? "")
  )
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
// Wraps every chrome.runtime.sendMessage call so that extension reloads
// (which invalidate the extension context) never produce uncaught errors.

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
      contextInvalidated = true
      handleContextInvalidated()
    }
    // "The message port closed before a response was received" is harmless for
    // fire-and-forget messages (e.g. WORKFLOW_EVENT) — just return null.
    return null
  }
}

function handleContextInvalidated(): void {
  // Stop the polling interval so we don't keep trying to reach the dead background.
  if (barPoll) {
    clearInterval(barPoll)
    barPoll = null
  }
  if (autoDismissTimer) {
    clearTimeout(autoDismissTimer)
    autoDismissTimer = null
  }
  stopCapture()
  // Replace bar contents with a reload notice — do not hide it so the user sees the message.
  if (barShadow) {
    barShadow.innerHTML = `<style>${BAR_CSS}</style>
      <div class="bar">
        <div class="logo">VB</div>
        <div class="info">
          <span class="msg er">Extension reloaded — refresh this page to continue.</span>
        </div>
      </div>`
  }
}

// ── Event capture ─────────────────────────────────────────────────────────────

function emit(event: WorkflowEvent): void {
  void safeSendMessage({ type: "WORKFLOW_EVENT", payload: event })
}

function handleClick(e: Event): void {
  const target = e.target as Element
  // Shadow DOM re-targets clicks inside the bar host to the host element at capture phase.
  if (!target || target === barHost) return
  emit({
    type: "click",
    timestamp: nowIso(),
    page_url: location.href,
    page_title: document.title,
    ...safeMeta(target),
  })
}

function handleChange(e: Event): void {
  const target = e.target as HTMLInputElement
  if (!target) return
  emit({
    type: "input_change",
    timestamp: nowIso(),
    page_url: location.href,
    page_title: document.title,
    ...safeMeta(target),
    value: isSensitive(target) ? "[REDACTED]" : undefined,
  })
}

function startCapture(): void {
  if (capturing) return
  capturing = true
  emit({ type: "page_visit", timestamp: nowIso(), page_url: location.href, page_title: document.title })
  document.addEventListener("click", handleClick, { capture: true, passive: true })
  document.addEventListener("change", handleChange, { capture: true, passive: true })
}

function stopCapture(): void {
  if (!capturing) return
  capturing = false
  document.removeEventListener("click", handleClick, true)
  document.removeEventListener("change", handleChange, true)
}

chrome.runtime.onMessage.addListener((msg: { type: string }) => {
  if (msg.type === "START_CAPTURING") {
    startCapture()
    showFloatingBar()
  } else if (msg.type === "STOP_CAPTURING") {
    stopCapture()
    // Keep bar visible in stopped state so user can still send proof.
    refreshBar()
  }
})

// ── Session detection ──────────────────────────────────────────────────────────
// Reads veribridge_session_id from the URL once at document_idle and notifies
// the background service worker so it can pre-fill the popup.

function detectSessionFromUrl(): void {
  const params = new URLSearchParams(location.search)
  const sessionId = params.get("veribridge_session_id")
  if (!sessionId) return
  void safeSendMessage({
    type: "SESSION_DETECTED_FROM_PAGE",
    payload: {
      session_id: sessionId,
      page_url: location.href,
      page_title: document.title,
      detected_at: nowIso(),
    },
  })
}

detectSessionFromUrl()

// On init, check if recording is already active (handles page navigation during a session).
void safeSendMessage<StateSnapshot>({ type: "GET_STATE" }).then((s) => {
  if (s?.isRecording) {
    startCapture()
    showFloatingBar()
  }
})

// ── Floating recorder bar ──────────────────────────────────────────────────────

let barShadow: ShadowRoot | null = null
let barPoll: ReturnType<typeof setInterval> | null = null
let barMinimized = false
let lastState: StateSnapshot | null = null

function fmtTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0")
  const s = (totalSeconds % 60).toString().padStart(2, "0")
  return `${m}:${s}`
}

// Bug 1 fix: use stoppedAt as the end time when the recording is not active,
// so the timer freezes the moment Stop is clicked.
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
`

// Bug 2/4 fix: bar is driven entirely by background status — no local barUploadPhase.
// Any state change (whether triggered by popup or floating bar) is reflected here
// within one poll cycle (≤1 second).
function buildBarHTML(s: StateSnapshot | null): string {
  const status = s?.status ?? "idle"
  const rec    = s?.isRecording ?? false
  const count  = s?.eventCount ?? 0
  // Bug 1 fix: pass stoppedAt so timer freezes after Stop.
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
    // No buttons during upload to prevent duplicate sends.
    info = `<span class="msg up">Uploading proof…</span>`

  } else if (status === "uploaded") {
    info = `<span class="msg ok">✓ Proof uploaded successfully</span>`
    acts = `<button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>`

  } else if (status === "upload_failed" || status === "error") {
    // Bug 3 fix: show actual error reason from background state.
    const reason = (s?.lastUploadError ?? "Unknown error").slice(0, 55)
    info = `<span class="msg er">Upload failed: ${reason}</span>`
    acts = `
      <button class="btn b-send" id="vb-send">Retry</button>
      <button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>
    `

  } else if (status === "recording" || rec) {
    // Active recording: pulsing red dot, live timer, Stop + Stop & Send.
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
    // Bug 6 fix: stopped state with frozen timer, amber dot, clear Send Proof CTA.
    info = `
      <div class="dot stp"></div>
      <span class="lbl">Stopped</span>
      <span class="tmr">${fmtTime(secs)}</span>
      <span class="sep">·</span>
      <span class="cnt">${count} event${count !== 1 ? "s" : ""}</span>
    `
    acts = `<button class="btn b-send" id="vb-send">Send Proof</button>`
  }

  return `<div class="bar">
    <div class="logo">VB</div>
    <div class="info">${info}</div>
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
  barShadow.getElementById("vb-dismiss")?.addEventListener("click", hideFloatingBar)
}

async function onBarStop(): Promise<void> {
  stopCapture()
  await safeSendMessage({ type: "STOP_RECORDING" })
  // Force immediate bar refresh — don't wait for the next poll tick.
  const s = await safeSendMessage<StateSnapshot>({ type: "GET_STATE" })
  if (s) renderBar(s)
}

// "Stop & Send" and "Send Proof" (after stop) and "Retry" all call this.
async function onBarStopAndSend(): Promise<void> {
  if (capturing) {
    // Stop first and wait briefly for background to process STOP_RECORDING.
    await onBarStop()
    await new Promise<void>((r) => setTimeout(r, 200))
  }

  // SEND_PROOF is async in the background (return true keeps channel open).
  // This await resolves only after the upload completes (success or failure).
  // During the upload the 1-second poll keeps the bar updated to "Uploading…".
  await safeSendMessage({ type: "SEND_PROOF", payload: { finalNote: null } })

  // Force an immediate refresh so the bar shows the final state without waiting
  // for the next poll cycle.
  const s = await safeSendMessage<StateSnapshot>({ type: "GET_STATE" })
  if (s) renderBar(s)
}

function fetchAndRender(): void {
  void safeSendMessage<StateSnapshot>({ type: "GET_STATE" }).then((s) => {
    if (!s) return
    renderBar(s)
    // Auto-dismiss bar 5 seconds after a successful upload.
    if (s.status === "uploaded" && !autoDismissTimer) {
      autoDismissTimer = setTimeout(() => {
        hideFloatingBar()
        autoDismissTimer = null
      }, 5000)
    }
  })
}

function showFloatingBar(): void {
  if (!barHost) {
    const host = document.createElement("div")
    host.id = "veribridge-recorder-host"
    // Use setAttribute so !important flags prevent page CSS from overriding position:fixed.
    host.setAttribute(
      "style",
      "all:initial!important;position:fixed!important;bottom:20px!important;" +
      "right:20px!important;z-index:2147483647!important;pointer-events:auto!important;"
    )
    ;(document.body ?? document.documentElement).appendChild(host)
    barHost = host
    barShadow = host.attachShadow({ mode: "open" })
  }

  barHost.style.display = ""
  barMinimized = false
  fetchAndRender()

  if (!barPoll) {
    barPoll = setInterval(fetchAndRender, 1000)
  }
}

function hideFloatingBar(): void {
  if (barPoll) { clearInterval(barPoll); barPoll = null }
  if (autoDismissTimer) { clearTimeout(autoDismissTimer); autoDismissTimer = null }
  if (barHost) barHost.style.display = "none"
}

function refreshBar(): void {
  if (barHost && barHost.style.display !== "none") {
    fetchAndRender()
  }
}
