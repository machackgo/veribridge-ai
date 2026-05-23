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

let capturing = false

function now(): string {
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
  // Silently ignore if background service worker is inactive (e.g. first install)
  chrome.runtime
    .sendMessage({ type: "WORKFLOW_EVENT", payload: event })
    .catch(() => undefined)
}

function handleClick(e: Event): void {
  const target = e.target as Element
  if (!target) return
  emit({
    type: "click",
    timestamp: now(),
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
    timestamp: now(),
    page_url: location.href,
    page_title: document.title,
    ...safeMeta(target),
    // Mask value for sensitive fields; never include password values
    value: isSensitive(target) ? "[REDACTED]" : undefined,
  })
}

function start(): void {
  if (capturing) return
  capturing = true
  emit({ type: "page_visit", timestamp: now(), page_url: location.href, page_title: document.title })
  document.addEventListener("click", handleClick, { capture: true, passive: true })
  document.addEventListener("change", handleChange, { capture: true, passive: true })
}

function stop(): void {
  if (!capturing) return
  capturing = false
  document.removeEventListener("click", handleClick, true)
  document.removeEventListener("change", handleChange, true)
}

chrome.runtime.onMessage.addListener((msg: { type: string }) => {
  if (msg.type === "START_CAPTURING") start()
  else if (msg.type === "STOP_CAPTURING") stop()
})

// ── Session detection ──────────────────────────────────────────────────────────
// Runs once at document_idle. Reads veribridge_session_id from the URL and
// notifies the background service worker so it can pre-fill the popup.

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
        detected_at: new Date().toISOString(),
      },
    })
    .catch(() => undefined)
}

detectSessionFromUrl()
