// Popup — VeriBridge extension recording controls.
//
// Unified Phase-0 flow:
//   1. Paste session ID → Start Recording
//   2. Recorder tab opens automatically (getDisplayMedia requires user gesture there)
//   3. In recorder tab: Start Screen Capture → go fullscreen → Stop Screen Capture → video uploads
//   4. Back to popup: Stop Recording → Send Proof
//
// captureVisibleTab is used ONLY as a background helper for DOM-event correlated
// screenshots — it is NOT the primary visual recorder and NOT surfaced in the UI.

import type { ExtensionState, RecordingStatus } from "./types"

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T
}

const sessionIdInput    = el<HTMLInputElement>("sessionId")
const apiUrlInput       = el<HTMLInputElement>("apiUrl")
const authTokenInput    = el<HTMLInputElement>("authToken")
const claimedSkillsInput = el<HTMLInputElement>("claimedSkills")
const finalNoteInput    = el<HTMLTextAreaElement>("finalNote")
const btnStart          = el<HTMLButtonElement>("btnStart")
const btnStop           = el<HTMLButtonElement>("btnStop")
const btnSend           = el<HTMLButtonElement>("btnSend")
const btnReopenRecorder = el<HTMLButtonElement>("btnReopenRecorder")
const statusDot         = el("statusDot")
const statusText        = el("statusText")
const eventCountEl      = el("eventCount")
const detectedBanner    = el("detectedBanner")
const videoStatusEl     = el("videoStatus")
const liveCoachEl       = el("liveCoach")

// Session/API/skills are read-only projections of the single background config.
// The popup never maintains a second editable launch configuration.
sessionIdInput.readOnly = true
apiUrlInput.readOnly = true
authTokenInput.readOnly = true
claimedSkillsInput.readOnly = true

// ── Status dot class mapping ───────────────────────────────────────────────────
const DOT_CLASS: Record<RecordingStatus, string> = {
  idle:          "",
  ready:         "ready",
  recording:     "recording",
  stopped:       "stopped",
  uploading:     "stopped",
  uploaded:      "uploaded",
  upload_failed: "error",
  error:         "error",
}

function applyState(state: ExtensionState): void {
  const streamActive = !!state.recorderTabStreamActive

  // Status dot — always reflects background recording session state
  statusDot.className = `status-dot ${DOT_CLASS[state.status] ?? ""}`.trim()

  // Status text — when stream is active, defer to recorder tab to avoid two timers
  if (streamActive && state.isRecording) {
    statusText.textContent = "Screen recording active — open recorder tab to stop & upload"
  } else if (state.videoUploadStatus === "uploaded" && state.isRecording) {
    const kf = state.videoKeyframeCount ?? 0
    statusText.textContent = kf > 0
      ? `✓ Video uploaded (${kf} keyframe${kf !== 1 ? "s" : ""}) — Stop Recording → Send Proof`
      : "✓ Video uploaded — Stop Recording → Send Proof"
  } else {
    statusText.textContent = state.statusMessage
  }

  eventCountEl.textContent =
    state.eventCount > 0 ? `${state.eventCount} event(s) captured` : ""

  sessionIdInput.value = state.sessionId ?? ""
  apiUrlInput.value = state.apiUrl || ""
  authTokenInput.value = state.authConfigured ? "configured" : ""
  claimedSkillsInput.value = (state.claimedSkills ?? []).join(", ")

  detectedBanner.style.display = state.status === "ready" ? "" : "none"

  btnStart.disabled = state.isRecording || state.status === "uploading"
  // Lock Stop Recording while screen capture is active — prevents orphaned sessions
  btnStop.disabled = !state.isRecording || streamActive
  btnSend.disabled =
    state.isRecording ||
    state.status === "uploading" ||
    state.videoUploadStatus === "uploading" ||
    !["stopped", "upload_failed", "error"].includes(state.status)

  // "Recorder Tab" button — primary action when stream active, fallback when not
  btnReopenRecorder.style.display = state.isRecording ? "" : "none"
  btnReopenRecorder.disabled = false   // always clickable when visible
  if (streamActive) {
    btnReopenRecorder.textContent = "📺 Open Recorder Tab (Recording Active)"
    btnReopenRecorder.classList.add("active")
  } else {
    btnReopenRecorder.textContent = "📺 Re-open Recorder Tab"
    btnReopenRecorder.classList.remove("active")
  }

  // ── Video upload status bar ────────────────────────────────────────────────
  const vs = state.videoUploadStatus
  if (vs === "none" || !vs) {
    videoStatusEl.style.display = "none"
    videoStatusEl.textContent = ""
  } else if (vs === "uploading") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status uploading"
    videoStatusEl.textContent = "⏳ Uploading screen recording…"
  } else if (vs === "uploaded") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status uploaded"
    const kf = state.videoKeyframeCount ?? 0
    videoStatusEl.textContent =
      kf > 0
        ? `✓ Recording uploaded — ${kf} keyframe(s) extracted`
        : "✓ Screen recording uploaded"
  } else if (vs === "failed") {
    videoStatusEl.style.display = ""
    videoStatusEl.className = "video-status failed"
    videoStatusEl.textContent = `✗ Video upload failed: ${state.videoUploadError ?? "unknown error"}`
  }

  // ── Live Proof Coach ───────────────────────────────────────────────────────
  renderLiveCoach(state)
}

function renderLiveCoach(state: ExtensionState): void {
  if (!state.isRecording || !state.liveCoach) {
    liveCoachEl.style.display = "none"
    return
  }
  liveCoachEl.style.display = ""

  const coach = state.liveCoach
  const score = coach.live_score
  const scoreColor = score >= 70 ? "#166534" : score >= 40 ? "#92400e" : "#991b1b"
  const scoreBg    = score >= 70 ? "#f0fdf4"  : score >= 40 ? "#fefce8"  : "#fef2f2"
  const scoreBorder = score >= 70 ? "#bbf7d0" : score >= 40 ? "#fde68a"  : "#fecaca"

  const chk = coach.checklist

  const chips: Array<{ label: string; captured: boolean }> = [
    { label: "Website loaded",    captured: chk.website_loaded },
    { label: "Page content",      captured: chk.dom_text_seen },
    { label: "Interaction",       captured: chk.interaction_seen },
    { label: "Form/input",        captured: chk.form_input_seen },
    { label: "Output/result",     captured: chk.output_or_result_seen },
    { label: "Chart/visual",      captured: chk.chart_or_visual_seen },
    { label: "Code/repo",         captured: chk.code_or_repo_seen },
    { label: "GitHub",            captured: chk.github_seen },
  ]

  const privacyWarning = coach.sensitive_warning
    ? `<div class="coach-warning">⚠ Sensitive content detected — avoid showing tokens, passwords, or keys.</div>`
    : ""

  const chipsHtml = chips
    .map(c => {
      const cls = c.captured ? "chip captured" : "chip missing"
      const icon = c.captured ? "✓" : "○"
      return `<span class="${cls}">${icon} ${c.label}</span>`
    })
    .join("")

  const suggestionsHtml = coach.suggestions.length > 0
    ? `<div class="coach-suggestions">${coach.suggestions
        .map(s => `<div class="coach-tip">→ ${s}</div>`)
        .join("")
      }</div>`
    : ""

  liveCoachEl.innerHTML = `
    <div class="coach-header">
      <span class="coach-title">Live Proof Coach</span>
      <span class="coach-score" style="background:${scoreBg};color:${scoreColor};border-color:${scoreBorder}">
        ${score}/100
      </span>
    </div>
    ${privacyWarning}
    <div class="coach-chips">${chipsHtml}</div>
    ${suggestionsHtml}
  `
}

function refreshState(): void {
  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp: ExtensionState) => {
    if (chrome.runtime.lastError) return
    applyState(resp)
  })
}

refreshState()
const poll = setInterval(refreshState, 1000)
window.addEventListener("unload", () => clearInterval(poll))

// ── Start recording ────────────────────────────────────────────────────────────
// The background service worker auto-opens the recorder tab on START_RECORDING.

btnStart.addEventListener("click", () => {
  const sessionId = sessionIdInput.value.trim()

  if (!sessionId) {
    statusText.textContent = "Open this proof from the VeriBridge Website Proof page first."
    return
  }

  chrome.runtime.sendMessage(
    { type: "START_RECORDING", payload: { sessionId } },
    (response: { ok?: boolean; error?: string }) => {
      if (!response?.ok && response?.error) statusText.textContent = response.error
      refreshState()
    }
  )
})

// ── Stop recording ─────────────────────────────────────────────────────────────

btnStop.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "STOP_RECORDING" }, () => refreshState())
})

// ── Send proof ─────────────────────────────────────────────────────────────────

btnSend.addEventListener("click", () => {
  const finalNote = finalNoteInput.value.trim() || null
  btnSend.disabled = true
  statusText.textContent = "Uploading…"

  chrome.runtime.sendMessage(
    { type: "SEND_PROOF", payload: { finalNote } },
    (resp: { ok: boolean; error?: string }) => {
      if (chrome.runtime.lastError) {
        statusText.textContent = `Error: ${chrome.runtime.lastError.message ?? "unknown"}`
        btnSend.disabled = false
        return
      }
      if (!resp?.ok && resp?.error) {
        statusText.textContent = `Upload failed: ${resp.error}`
      }
      refreshState()
    }
  )
})

// ── Re-open Recorder Tab (fallback if user closed it) ─────────────────────────

btnReopenRecorder.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "OPEN_RECORDER_TAB" }, () => { /* tab opens */ })
})
