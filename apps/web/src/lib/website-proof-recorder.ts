"use client"

import { createSupabaseBrowserClient } from "@/lib/supabase/client"
import { PUBLIC_API_BASE } from "@/lib/api-base"
import {
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_AUTH_REFRESH_ACK,
  RECORDER_BRIDGE_PING,
  RECORDER_BRIDGE_PONG,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_INIT_REQUEST,
  RECORDER_KNOWN_EXTENSION_MESSAGE_TYPES,
  RECORDER_START_ACK,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_ACK,
  RECORDER_TARGET_OPEN_REQUEST,
  RECORDER_TARGET_READY,
  WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  isRecorderBuildAtLeast,
  normalizeWebsiteProofRecorderConfig,
  normalizeWebsiteProofApiBase,
  safeRecorderDiagnostic,
  type RecorderBridgePong,
  type RecorderInitAck,
  type RecorderInitRequest,
  type RecorderProtocolErrorCode,
  type RecorderProtocolNack,
  type RecorderStartAck,
  type RecorderStartRequest,
  type RecorderTargetReadyAck,
  type WebsiteProofRecorderConfig,
} from "../../../../packages/shared/websiteProofRecorderContract"

const APP_MESSAGE_SOURCE = "veribridge-app"
const EXTENSION_MESSAGE_SOURCE = "veribridge-extension"
const INIT_RETRY_MS = [0, 250, 750, 1500, 3000, 5000] as const
const BRIDGE_PING_RETRY_MS = [0, 400, 1200, 2500, 4500] as const
const INIT_TIMEOUT_MS = 10_000
// The bridge PONG is answered synchronously by the content script (no MV3
// worker involved), so several unanswered pings mean the extension is not
// installed — fail fast to the install screen instead of burning the full
// initialization deadline.
const INIT_ABSENT_FAST_FAIL_MS = 3_000
// A response observed shortly before the deadline earns one extension: the
// bridge is alive and the worker may still be waking, so a late ACK remains
// relevant and must not be discarded because a timer fired first.
const INIT_LATE_SIGNAL_WINDOW_MS = 2_500
const INIT_DEADLINE_EXTENSION_MS = 4_000
const TARGET_TIMEOUT_MS = 12_000
const START_TIMEOUT_MS = 6_000

export type RecorderSessionInput = {
  config_revision: number
  session_id: string
  owner_user_id: string
  project_id: string | null
  website_url: string
  repository_url: string | null
  claimed_skills: string[]
  proof_objective: string
  created_at: string
}

export type RecorderHandshakeSuccess = {
  ok: true
  config: WebsiteProofRecorderConfig
  acknowledgement: RecorderInitAck
}

export type RecorderHandshakeFailure = {
  ok: false
  error_code: RecorderProtocolErrorCode
  message: string
  diagnostic_code: string
}

export type RecorderHandshakeResult = RecorderHandshakeSuccess | RecorderHandshakeFailure

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function diagnostic(
  event: string,
  config: WebsiteProofRecorderConfig | null,
  errorCode?: RecorderProtocolErrorCode,
): void {
  console.info("[WebsiteProofRecorder]", {
    event,
    ...(config ? safeRecorderDiagnostic(config) : {}),
    timestamp: new Date().toISOString(),
    ...(errorCode ? { error_code: errorCode } : {}),
  })
}

function failure(errorCode: RecorderProtocolErrorCode, message: string): RecorderHandshakeFailure {
  return {
    ok: false,
    error_code: errorCode,
    message,
    diagnostic_code: `WPR-${errorCode.replaceAll("_", "-").toUpperCase()}`,
  }
}

function postToExtension(type: string, payload: unknown): void {
  window.postMessage({ source: APP_MESSAGE_SOURCE, type, payload }, window.location.origin)
}

export function recorderFailureMessage(result: RecorderHandshakeFailure): string {
  const messages: Record<RecorderProtocolErrorCode, string> = {
    extension_not_detected: "The VeriBridge Recorder extension is not installed in this browser (or is disabled).",
    extension_version_incompatible: "Your VeriBridge Recorder extension is out of date. Update it, then retry.",
    extension_worker_unreachable: "The recorder's background worker did not answer. Retry — if it keeps failing, reload the extension and refresh this page.",
    initialization_timeout: "Recorder initialization timed out. Keep this page open and retry.",
    invalid_config: "The recorder rejected this session configuration.",
    invalid_api_base: "The Website Proof API address is invalid.",
    authentication_unavailable: "Your signed-in session is unavailable. Sign in again, then retry.",
    session_mismatch: "The recorder acknowledged a different session. Retry this fresh session.",
    revision_mismatch: "The recorder acknowledged an outdated session revision. Retry initialization.",
    stale_config: "An older recorder configuration was rejected. Retry this fresh session.",
    different_session_active: "Another Website Proof is actively recording. Stop it before starting this session.",
    storage_write_failed: "The recorder could not save this session configuration. Reload the extension and retry.",
    target_open_failed: "The recorder could not open the target website.",
    target_ready_timeout: "The target website opened, but the recorder did not become ready. Refresh the target or reload the extension and retry.",
    target_session_mismatch: "The opened target attached to a different recorder session.",
    target_url_mismatch: "The recorder attached to a different target website.",
    recording_not_ready: "The recorder is not attached to the target website yet.",
    recording_start_failed: "The recorder could not start this Website Proof session.",
    replay_not_retained: "The screen recording has not been retained yet. Finish its upload, then send the proof.",
    extension_context_invalidated: "The extension was reloaded. Refresh this proof page and retry the same session.",
    unknown_error: "The recorder could not initialize this session.",
  }
  return `${messages[result.error_code]} (${result.diagnostic_code})`
}

export type RecorderExtensionProbe = {
  /** True when any recorder bridge answered the ping. */
  installed: boolean
  /** True when installed AND schema/min-build compatible AND context valid. */
  ready: boolean
  /** Build version the bridge reported, when installed. */
  build_version: string | null
  /** False when the extension was updated/reloaded and needs a page refresh. */
  context_valid: boolean
  /** True when installed but older than the supported minimum. */
  outdated: boolean
}

const PROBE_PING_RETRY_MS = [0, 300, 900] as const
const PROBE_TIMEOUT_MS = 2_000

/**
 * Lightweight installed/compatible check for the install and returning-user
 * screens. Uses only the synchronous content-script bridge ping — it never
 * wakes the service worker, never sends a token, and resolves fast.
 */
export async function probeRecorderExtension(): Promise<RecorderExtensionProbe> {
  const absent: RecorderExtensionProbe = {
    installed: false,
    ready: false,
    build_version: null,
    context_valid: true,
    outdated: false,
  }
  if (typeof window === "undefined") return absent
  const correlationId = requestId()
  return await new Promise<RecorderExtensionProbe>((resolve) => {
    let settled = false
    const timers: number[] = []
    const finish = (result: RecorderExtensionProbe) => {
      if (settled) return
      settled = true
      window.removeEventListener("message", onMessage)
      timers.forEach(timer => window.clearTimeout(timer))
      resolve(result)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const data = event.data as { source?: unknown; type?: unknown; payload?: unknown } | null
      if (data?.source !== EXTENSION_MESSAGE_SOURCE) return
      if (data.type !== RECORDER_BRIDGE_PONG) return
      const pong = data.payload as Partial<RecorderBridgePong>
      if (pong.request_id !== correlationId) return
      const buildVersion = typeof pong.build_version === "string" ? pong.build_version : null
      const compatible =
        pong.schema_version === WEBSITE_PROOF_RECORDER_SCHEMA_VERSION &&
        isRecorderBuildAtLeast(pong.build_version, WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION)
      const contextValid = pong.context_valid !== false
      finish({
        installed: true,
        ready: compatible && contextValid,
        build_version: buildVersion,
        context_valid: contextValid,
        outdated: !compatible,
      })
    }
    window.addEventListener("message", onMessage)
    for (const delayMs of PROBE_PING_RETRY_MS) {
      timers.push(window.setTimeout(
        () => postToExtension(RECORDER_BRIDGE_PING, { request_id: correlationId }),
        delayMs,
      ))
    }
    timers.push(window.setTimeout(() => finish(absent), PROBE_TIMEOUT_MS))
  })
}

export async function initializeWebsiteProofRecorder(
  input: RecorderSessionInput,
): Promise<RecorderHandshakeResult> {
  if (typeof window === "undefined") {
    return failure("extension_not_detected", "Recorder bridge is unavailable outside the browser.")
  }
  const supabase = createSupabaseBrowserClient()
  const { data: { session } } = await supabase.auth.getSession()
  if (!session?.access_token || !session.user?.id || session.user.id !== input.owner_user_id) {
    return failure("authentication_unavailable", "No matching signed-in session is available.")
  }
  const expiresAt = session.expires_at ? new Date(session.expires_at * 1000).toISOString() : null
  const config = normalizeWebsiteProofRecorderConfig({
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: input.config_revision,
    session_id: input.session_id,
    owner_user_id: input.owner_user_id,
    api_base_url: PUBLIC_API_BASE,
    auth: {
      mechanism: "bearer",
      access_token: session.access_token,
      expires_at: expiresAt,
    },
    project_id: input.project_id,
    website_url: input.website_url,
    repository_url: input.repository_url,
    claimed_skills: input.claimed_skills,
    proof_objective: input.proof_objective,
    created_at: input.created_at,
    expires_at: expiresAt,
  })
  if (!config) {
    const apiValid = normalizeWebsiteProofApiBase(PUBLIC_API_BASE) !== null
    return failure(apiValid ? "invalid_config" : "invalid_api_base", "Recorder config validation failed.")
  }
  const correlationId = requestId()
  const request: RecorderInitRequest = {
    request_id: correlationId,
    expected_schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    // MINIMUM supported build. Store-distributed extensions update on
    // Chrome's schedule, so any build >= this version must be accepted.
    expected_build_version: WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION,
    config,
  }
  diagnostic("extension_init_requested", config)

  return await new Promise<RecorderHandshakeResult>((resolve) => {
    let settled = false
    let sawExtensionMessage = false
    let bridgePongSeen = false
    let workerUnreachableSeen = false
    let lastSignalAtMs = 0
    let deadlineExtended = false
    const timers: number[] = []
    const finish = (result: RecorderHandshakeResult) => {
      if (settled) return
      settled = true
      window.removeEventListener("message", onMessage)
      timers.forEach(timer => window.clearTimeout(timer))
      resolve(result)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const data = event.data as { source?: unknown; type?: unknown; payload?: unknown } | null
      if (data?.source !== EXTENSION_MESSAGE_SOURCE) return
      sawExtensionMessage = true
      lastSignalAtMs = Date.now()
      if (data.type === "VERIBRIDGE_RECORDER_AUTH_APPLIED") {
        diagnostic("extension_init_rejected", config, "extension_version_incompatible")
        finish(failure("extension_version_incompatible", "A legacy recorder build answered the compatibility probe."))
        return
      }
      if (typeof data.type === "string" && !RECORDER_KNOWN_EXTENSION_MESSAGE_TYPES.has(data.type)) {
        // Any extension-sourced message type the current protocol does not
        // emit means a stale/foreign build is loaded. Waiting longer can never
        // succeed — fail fast with the actionable diagnostic.
        diagnostic("extension_init_rejected", config, "extension_version_incompatible")
        finish(failure("extension_version_incompatible", "An unrecognized recorder build is loaded in this browser."))
        return
      }
      if (data.type === RECORDER_BRIDGE_PONG) {
        const pong = data.payload as Partial<RecorderBridgePong>
        if (pong.request_id !== correlationId) return
        if (
          pong.schema_version !== WEBSITE_PROOF_RECORDER_SCHEMA_VERSION ||
          !isRecorderBuildAtLeast(pong.build_version, WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION)
        ) {
          diagnostic("extension_init_rejected", config, "extension_version_incompatible")
          finish(failure("extension_version_incompatible", "The recorder bridge reported an incompatible build."))
          return
        }
        if (pong.context_valid === false) {
          diagnostic("extension_init_rejected", config, "extension_context_invalidated")
          finish(failure("extension_context_invalidated", "The recorder bridge belongs to a reloaded extension."))
          return
        }
        bridgePongSeen = true
        return
      }
      if (data.type === RECORDER_INIT_NACK) {
        const nack = data.payload as Partial<RecorderProtocolNack>
        if (nack.request_id !== correlationId) return
        const code = nack.error_code ?? "unknown_error"
        if (code === "extension_worker_unreachable") {
          // The bridge exists but the MV3 worker didn't answer this attempt.
          // Retries are already scheduled — record the signal and keep waiting
          // instead of failing while the worker may still be waking up.
          workerUnreachableSeen = true
          return
        }
        diagnostic("extension_init_rejected", config, code)
        finish(failure(code, nack.message ?? "The extension rejected initialization."))
        return
      }
      if (data.type !== RECORDER_INIT_ACK) return
      const ack = data.payload as Partial<RecorderInitAck>
      if (ack.request_id !== correlationId) return
      if (ack.session_id !== config.session_id) {
        finish(failure("session_mismatch", "The acknowledgement session did not match."))
        return
      }
      if (ack.config_revision !== config.config_revision) {
        finish(failure("revision_mismatch", "The acknowledgement revision did not match."))
        return
      }
      if (
        ack.api_base_url !== config.api_base_url ||
        ack.schema_version !== WEBSITE_PROOF_RECORDER_SCHEMA_VERSION ||
        !isRecorderBuildAtLeast(ack.build_version, WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION) ||
        ack.ready !== true
      ) {
        finish(failure("extension_version_incompatible", "The recorder compatibility acknowledgement did not match."))
        return
      }
      diagnostic("extension_init_acknowledged", config)
      finish({ ok: true, config, acknowledgement: ack as RecorderInitAck })
    }
    const onDeadline = () => {
      // A signal that arrived moments ago means an ACK may still be in flight
      // (SW cold start). Extend once rather than discarding a viable handshake.
      if (!deadlineExtended && Date.now() - lastSignalAtMs <= INIT_LATE_SIGNAL_WINDOW_MS) {
        deadlineExtended = true
        timers.push(window.setTimeout(onDeadline, INIT_DEADLINE_EXTENSION_MS))
        timers.push(window.setTimeout(() => postToExtension(RECORDER_INIT_REQUEST, request), 0))
        return
      }
      const code: RecorderProtocolErrorCode = !sawExtensionMessage
        ? "extension_not_detected"
        : workerUnreachableSeen || bridgePongSeen
          ? "extension_worker_unreachable"
          : "initialization_timeout"
      diagnostic("extension_init_failed", config, code)
      finish(failure(code, "No matching recorder acknowledgement arrived before the deadline."))
    }
    window.addEventListener("message", onMessage)
    timers.push(window.setTimeout(() => {
      if (sawExtensionMessage) return
      diagnostic("extension_init_failed", config, "extension_not_detected")
      finish(failure("extension_not_detected", "No recorder bridge answered any ping."))
    }, INIT_ABSENT_FAST_FAIL_MS))
    for (const delayMs of INIT_RETRY_MS) {
      timers.push(window.setTimeout(() => postToExtension(RECORDER_INIT_REQUEST, request), delayMs))
    }
    // Bridge liveness probe — answered synchronously by the content script.
    for (const delayMs of BRIDGE_PING_RETRY_MS) {
      timers.push(window.setTimeout(
        () => postToExtension(RECORDER_BRIDGE_PING, { request_id: correlationId }),
        delayMs,
      ))
    }
    // NOTE: the former legacy compatibility probe (VERIBRIDGE_SET_RECORDER_AUTH)
    // was removed deliberately: it posted the bearer token in a legacy field
    // shape before build compatibility was established. A pre-schema build now
    // classifies as extension_not_detected, which routes the user to the
    // install/update screen — the correct outcome for a build that old.
    timers.push(window.setTimeout(onDeadline, INIT_TIMEOUT_MS))
  })
}

export async function openWebsiteProofTarget(
  config: WebsiteProofRecorderConfig,
): Promise<RecorderTargetReadyAck | RecorderHandshakeFailure> {
  const correlationId = requestId()
  diagnostic("target_open_requested", config)
  return await new Promise((resolve) => {
    let settled = false
    const timers: number[] = []
    const finish = (result: RecorderTargetReadyAck | RecorderHandshakeFailure) => {
      if (settled) return
      settled = true
      window.removeEventListener("message", onMessage)
      timers.forEach(timer => window.clearTimeout(timer))
      resolve(result)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const data = event.data as { source?: unknown; type?: unknown; payload?: unknown } | null
      if (data?.source !== EXTENSION_MESSAGE_SOURCE) return
      if (data.type === RECORDER_INIT_NACK) {
        const nack = data.payload as Partial<RecorderProtocolNack>
        if (nack.request_id !== correlationId) return
        finish(failure(nack.error_code ?? "target_open_failed", nack.message ?? "Target open failed."))
        return
      }
      if (data.type !== RECORDER_TARGET_READY) return
      const ack = data.payload as Partial<RecorderTargetReadyAck>
      if (ack.request_id !== correlationId) return
      if (ack.session_id !== config.session_id) {
        finish(failure("target_session_mismatch", "The target attached to another session."))
        return
      }
      if (ack.config_revision !== config.config_revision) {
        finish(failure("revision_mismatch", "The target attached to another revision."))
        return
      }
      if (ack.api_base_url !== config.api_base_url || ack.ready !== true) {
        finish(failure("target_session_mismatch", "The target acknowledgement did not match the recorder config."))
        return
      }
      let expectedOrigin = ""
      let actualOrigin = ""
      try {
        expectedOrigin = new URL(config.website_url).origin
        actualOrigin = new URL(String(ack.target_url ?? "")).origin
      } catch {
        finish(failure("target_url_mismatch", "The target acknowledgement contained an invalid URL."))
        return
      }
      if (expectedOrigin !== actualOrigin) {
        finish(failure("target_url_mismatch", "The target acknowledgement came from another website."))
        return
      }
      if (JSON.stringify(ack.claimed_skills ?? []) !== JSON.stringify(config.claimed_skills)) {
        finish(failure("target_session_mismatch", "The target acknowledgement did not preserve claimed skills."))
        return
      }
      diagnostic("target_content_script_ready", config)
      finish(ack as RecorderTargetReadyAck)
    }
    window.addEventListener("message", onMessage)
    const request = {
      request_id: correlationId,
      session_id: config.session_id,
      config_revision: config.config_revision,
    }
    for (const delayMs of [0, 500, 1500] as const) {
      timers.push(window.setTimeout(() => postToExtension(RECORDER_TARGET_OPEN_REQUEST, request), delayMs))
    }
    timers.push(window.setTimeout(() => {
      diagnostic("target_ready_failed", config, "target_ready_timeout")
      finish(failure("target_ready_timeout", "Target content-script readiness was not acknowledged."))
    }, TARGET_TIMEOUT_MS))
  })
}

/** Start capture only after the exact target tab has acknowledged attachment. */
export async function startWebsiteProofRecording(
  config: WebsiteProofRecorderConfig,
): Promise<RecorderStartAck | RecorderHandshakeFailure> {
  const correlationId = requestId()
  const request: RecorderStartRequest = {
    request_id: correlationId,
    session_id: config.session_id,
    config_revision: config.config_revision,
  }
  diagnostic("recording_start_requested", config)
  return await new Promise((resolve) => {
    let settled = false
    const timers: number[] = []
    const finish = (result: RecorderStartAck | RecorderHandshakeFailure) => {
      if (settled) return
      settled = true
      window.removeEventListener("message", onMessage)
      timers.forEach(timer => window.clearTimeout(timer))
      resolve(result)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const data = event.data as { source?: unknown; type?: unknown; payload?: unknown } | null
      if (data?.source !== EXTENSION_MESSAGE_SOURCE) return
      if (data.type === RECORDER_INIT_NACK) {
        const nack = data.payload as Partial<RecorderProtocolNack>
        if (nack.request_id !== correlationId) return
        finish(failure(nack.error_code ?? "recording_start_failed", nack.message ?? "Recording start failed."))
        return
      }
      if (data.type !== RECORDER_START_ACK) return
      const ack = data.payload as Partial<RecorderStartAck>
      if (ack.request_id !== correlationId) return
      if (ack.session_id !== config.session_id) {
        finish(failure("session_mismatch", "The recorder started another session."))
        return
      }
      if (ack.config_revision !== config.config_revision) {
        finish(failure("revision_mismatch", "The recorder started another config revision."))
        return
      }
      if (ack.ready !== true || typeof ack.started_at !== "string") {
        finish(failure("recording_start_failed", "The recorder returned an incomplete start acknowledgement."))
        return
      }
      diagnostic("recording_started", config)
      finish(ack as RecorderStartAck)
    }
    window.addEventListener("message", onMessage)
    for (const delayMs of [0, 500, 1500] as const) {
      timers.push(window.setTimeout(() => postToExtension(RECORDER_START_REQUEST, request), delayMs))
    }
    timers.push(window.setTimeout(() => {
      diagnostic("recording_start_failed", config, "recording_start_failed")
      finish(failure("recording_start_failed", "No matching recording acknowledgement arrived."))
    }, START_TIMEOUT_MS))
  })
}

export async function refreshWebsiteProofRecorderSessionAuth(
  sessionId: string,
  configRevision: number,
): Promise<boolean> {
  const supabase = createSupabaseBrowserClient()
  const { data: { session } } = await supabase.auth.getSession()
  if (!session?.access_token) return false
  const correlationId = requestId()
  const payload = {
    request_id: correlationId,
    session_id: sessionId,
    config_revision: configRevision,
    access_token: session.access_token,
    expires_at: session.expires_at ? new Date(session.expires_at * 1000).toISOString() : null,
  }
  return await new Promise<boolean>((resolve) => {
    let settled = false
    const finish = (ok: boolean) => {
      if (settled) return
      settled = true
      window.removeEventListener("message", onMessage)
      window.clearTimeout(retryTimer)
      window.clearTimeout(timeoutTimer)
      resolve(ok)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const data = event.data as { source?: unknown; type?: unknown; payload?: Record<string, unknown> } | null
      if (data?.source !== EXTENSION_MESSAGE_SOURCE) return
      if (data.payload?.request_id !== correlationId) return
      if (data.type === RECORDER_AUTH_REFRESH_ACK) {
        finish(
          data.payload.session_id === sessionId &&
          data.payload.config_revision === configRevision,
        )
      } else if (data.type === RECORDER_INIT_NACK) {
        finish(false)
      }
    }
    window.addEventListener("message", onMessage)
    postToExtension(RECORDER_AUTH_REFRESH_REQUEST, payload)
    const retryTimer = window.setTimeout(() => postToExtension(RECORDER_AUTH_REFRESH_REQUEST, payload), 500)
    const timeoutTimer = window.setTimeout(() => finish(false), 2_500)
  })
}
