"use client"

import { createSupabaseBrowserClient } from "@/lib/supabase/client"
import { PUBLIC_API_BASE } from "@/lib/api-base"
import {
  RECORDER_AUTH_REFRESH_REQUEST,
  RECORDER_AUTH_REFRESH_ACK,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_INIT_REQUEST,
  RECORDER_START_ACK,
  RECORDER_START_REQUEST,
  RECORDER_TARGET_OPEN_ACK,
  RECORDER_TARGET_OPEN_REQUEST,
  RECORDER_TARGET_READY,
  WEBSITE_PROOF_RECORDER_BUILD_VERSION,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  normalizeWebsiteProofRecorderConfig,
  normalizeWebsiteProofApiBase,
  safeRecorderDiagnostic,
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
const INIT_RETRY_MS = [0, 250, 750, 1500, 3000] as const
const INIT_TIMEOUT_MS = 7_000
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
    extension_not_detected: "VeriBridge Recorder was not detected. Reload the unpacked extension and refresh this proof page.",
    extension_version_incompatible: "The loaded VeriBridge Recorder is out of date. Reload the extension from this worktree, then retry.",
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
    expected_build_version: WEBSITE_PROOF_RECORDER_BUILD_VERSION,
    config,
  }
  diagnostic("extension_init_requested", config)

  return await new Promise<RecorderHandshakeResult>((resolve) => {
    let settled = false
    let sawExtensionMessage = false
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
      if (data.type === "VERIBRIDGE_RECORDER_AUTH_APPLIED") {
        diagnostic("extension_init_rejected", config, "extension_version_incompatible")
        finish(failure("extension_version_incompatible", "A legacy recorder build answered the compatibility probe."))
        return
      }
      if (data.type === RECORDER_INIT_NACK) {
        const nack = data.payload as Partial<RecorderProtocolNack>
        if (nack.request_id !== correlationId) return
        const code = nack.error_code ?? "unknown_error"
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
        ack.build_version !== WEBSITE_PROOF_RECORDER_BUILD_VERSION ||
        ack.ready !== true
      ) {
        finish(failure("extension_version_incompatible", "The recorder compatibility acknowledgement did not match."))
        return
      }
      diagnostic("extension_init_acknowledged", config)
      finish({ ok: true, config, acknowledgement: ack as RecorderInitAck })
    }
    window.addEventListener("message", onMessage)
    for (const delayMs of INIT_RETRY_MS) {
      timers.push(window.setTimeout(() => postToExtension(RECORDER_INIT_REQUEST, request), delayMs))
    }
    // Compatibility probe: a pre-schema extension responds to this legacy
    // shape, allowing a stale build to be distinguished from a missing one.
    timers.push(window.setTimeout(() => postToExtension("VERIBRIDGE_SET_RECORDER_AUTH", {
      requestId: correlationId,
      sessionId: config.session_id,
      apiUrl: config.api_base_url,
      authToken: config.auth.access_token,
      claimedSkills: config.claimed_skills,
    }), 2_000))
    timers.push(window.setTimeout(() => {
      const code = sawExtensionMessage ? "initialization_timeout" : "extension_not_detected"
      diagnostic("extension_init_failed", config, code)
      finish(failure(code, "No matching recorder acknowledgement arrived before the deadline."))
    }, INIT_TIMEOUT_MS))
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
