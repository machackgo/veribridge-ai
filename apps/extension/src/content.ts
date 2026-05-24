// Content script — injected into every page; only captures events while recording is active.
// Never collects cookies, localStorage, sessionStorage, or password values.

const SENSITIVE_RE =
  /password|pass\b|token|secret|api_key|apikey|card|cvv|ssn|otp|2fa|mfa|authorization|bearer/i

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
    return null
  }
}

function handleContextInvalidated(): void {
  // Stop all timers, then remove the bar entirely so users don't see a
  // broken "Extension reloaded" overlay. A console warning is enough.
  console.warn("VeriBridge: extension reloaded — refresh this page to continue.")
  stopCapture()
  hideFloatingBar()
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
