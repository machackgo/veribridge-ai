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
  status: string
}

let capturing = false
let barHost: HTMLElement | null = null

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

function emit(event: WorkflowEvent): void {
  chrome.runtime
    .sendMessage({ type: "WORKFLOW_EVENT", payload: event })
    .catch(() => undefined)
}

function handleClick(e: Event): void {
  const target = e.target as Element
  // Shadow DOM re-targets clicks inside the bar to the host element at capture phase
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
    // Mask value for sensitive fields; never include password values
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
    // Keep bar visible in stopped state so user can send proof from the page
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

  chrome.runtime
    .sendMessage({
      type: "SESSION_DETECTED_FROM_PAGE",
      payload: {
        session_id: sessionId,
        page_url: location.href,
        page_title: document.title,
        detected_at: nowIso(),
      },
    })
    .catch(() => undefined)
}

detectSessionFromUrl()

// On init, check if recording is already active (handles page navigation during a session).
chrome.runtime
  .sendMessage({ type: "GET_STATE" })
  .then((s: StateSnapshot) => {
    if (s?.isRecording) {
      startCapture()
      showFloatingBar()
    }
  })
  .catch(() => undefined)

// ── Floating recorder bar ──────────────────────────────────────────────────────

let barShadow: ShadowRoot | null = null
let barPoll: ReturnType<typeof setInterval> | null = null
let barMinimized = false
let barUploadPhase: "idle" | "uploading" | "success" | "error" = "idle"
let lastState: StateSnapshot | null = null

function fmtTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0")
  const s = (totalSeconds % 60).toString().padStart(2, "0")
  return `${m}:${s}`
}

function elapsedSecs(startedAt: string | null): number {
  if (!startedAt) return 0
  return Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000))
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
  const rec    = s?.isRecording ?? false
  const status = s?.status ?? "idle"
  const count  = s?.eventCount ?? 0
  const secs   = elapsedSecs(s?.startedAt ?? null)

  if (barMinimized) {
    return `<div class="bar mini">
      <div class="logo">VB</div>
      <div class="dot${rec ? " rec" : ""}"></div>
      <button class="b-icon" id="vb-expand" title="Expand">＋</button>
    </div>`
  }

  let info = ""
  let acts = ""

  if (barUploadPhase === "uploading") {
    info = `<span class="msg up">Uploading proof…</span>`
  } else if (barUploadPhase === "success") {
    info = `<span class="msg ok">✓ Proof uploaded successfully</span>`
    acts = `<button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>`
  } else if (barUploadPhase === "error") {
    info = `<span class="msg er">Upload failed. Open extension to retry.</span>`
    acts = `<button class="btn b-dismiss" id="vb-dismiss">Dismiss</button>`
  } else {
    const dotClass = rec ? " rec" : (status === "stopped" || status === "error" ? " stp" : "")
    const lbl      = rec ? "Recording" : (status === "stopped" || status === "error" ? "Stopped" : "")
    info = `
      <div class="dot${dotClass}"></div>
      <span class="lbl">${lbl}</span>
      <span class="tmr">${fmtTime(secs)}</span>
      <span class="sep">·</span>
      <span class="cnt">${count} event${count !== 1 ? "s" : ""}</span>
    `
    if (rec) {
      acts = `
        <button class="btn b-stop" id="vb-stop">Stop</button>
        <button class="btn b-send" id="vb-send">Stop &amp; Send</button>
      `
    } else if (status === "stopped" || status === "error") {
      acts = `<button class="btn b-send" id="vb-send">Send Proof</button>`
    }
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
  barShadow.getElementById("vb-stop")?.addEventListener("click", onBarStop)
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

function onBarStop(): void {
  stopCapture()
  chrome.runtime.sendMessage({ type: "STOP_RECORDING" }).catch(() => undefined)
}

async function onBarStopAndSend(): Promise<void> {
  if (capturing) {
    onBarStop()
    // Brief pause so background processes STOP_RECORDING before SEND_PROOF
    await new Promise<void>((r) => setTimeout(r, 200))
  }
  barUploadPhase = "uploading"
  renderBar(null)

  try {
    const resp = await chrome.runtime.sendMessage({
      type: "SEND_PROOF",
      payload: { finalNote: null },
    }) as { ok: boolean; error?: string }
    barUploadPhase = resp?.ok ? "success" : "error"
  } catch {
    barUploadPhase = "error"
  }

  renderBar(null)
  if (barUploadPhase === "success") {
    // Auto-dismiss the bar after showing success for 5 seconds
    setTimeout(hideFloatingBar, 5000)
  }
}

function fetchAndRender(): void {
  chrome.runtime
    .sendMessage({ type: "GET_STATE" })
    .then((s: StateSnapshot) => renderBar(s))
    .catch(() => undefined)
}

function showFloatingBar(): void {
  if (!barHost) {
    const host = document.createElement("div")
    host.id = "veribridge-recorder-host"
    // Use setAttribute so !important flags prevent page CSS from overriding position:fixed
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
  barUploadPhase = "idle"
  fetchAndRender()

  if (!barPoll) {
    barPoll = setInterval(fetchAndRender, 1000)
  }
}

function hideFloatingBar(): void {
  if (barPoll) { clearInterval(barPoll); barPoll = null }
  if (barHost) barHost.style.display = "none"
  barUploadPhase = "idle"
}

function refreshBar(): void {
  if (barHost && barHost.style.display !== "none") {
    fetchAndRender()
  }
}
