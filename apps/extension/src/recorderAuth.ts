// Recorder auth lifecycle — pure, chrome-API-free helpers shared by the
// background service worker, the recorder tab, and unit tests.
//
// The recorder uploads proof artifacts (visible evidence, visual frames, video,
// final upload) straight to the backend with `Authorization: Bearer <token>`.
// The token comes from the signed-in VeriBridge app via a same-origin
// postMessage handoff, so its lifecycle must survive: content-script load
// timing, MV3 service-worker restarts, a freshly opened recorder tab, and the
// Stop & Send upload burst. Everything here fails CLOSED: a missing token means
// "don't send the request", never "send it anonymously".
//
// SECURITY: no function in this module accepts-and-returns a token inside any
// payload that leaves the extension (ACK, debug state). Those payloads carry
// only booleans/metadata so the token can never reach a page DOM or log.

export const MISSING_RECORDER_AUTH_MESSAGE =
  "Recording isn't signed in. Open the VeriBridge Website Proof page while signed in, then restart the recording from there."

/** Message shown by the app when the extension never ACKed the token handoff. */
export const RECORDER_AUTH_NOT_ESTABLISHED_MESSAGE =
  "Recorder authentication was not established. Reload the extension and start again."

/** chrome.storage.local key for the structured recorder-auth record. */
export const RECORDER_AUTH_STORAGE_KEY = "vb_recorder_auth"

/** Bump whenever the page/content/background recorder-auth contract changes. */
export const RECORDER_AUTH_BUILD_FINGERPRINT = "recorder-auth-5.6-debug-28284748"

export type RecorderAuthSource = "memory" | "storage" | "none"

/** Structured storage record — replaces the loose top-level authToken/apiUrl keys. */
export interface PersistedRecorderAuth {
  authToken: string
  apiUrl?: string
  /** Proof session the app most recently associated with this token ("" if none yet). */
  sessionId?: string
  updatedAt: string
}

export interface RecorderTokenMetadata {
  tokenPresent: boolean
  tokenLength: number
  jwtSegmentCount: number
  startsWithEy: boolean
  expiresAt: number | null
  expired: boolean
}

function decodeJwtExpiry(token: string): number | null {
  const payload = token.split(".")[1]
  if (!payload) return null
  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/")
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=")
    const parsed = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof parsed.exp === "number" && Number.isFinite(parsed.exp) ? parsed.exp : null
  } catch {
    return null
  }
}

/** Safe token facts for validation/diagnostics. Never includes token contents. */
export function recorderTokenMetadata(
  token: string | null | undefined,
  nowMs = Date.now(),
): RecorderTokenMetadata {
  const value = typeof token === "string" ? token.trim() : ""
  const expiresAt = value ? decodeJwtExpiry(value) : null
  return {
    tokenPresent: !!value,
    tokenLength: value.length,
    jwtSegmentCount: value ? value.split(".").length : 0,
    startsWithEy: value.startsWith("ey"),
    expiresAt,
    expired: expiresAt !== null && expiresAt * 1000 <= nowMs,
  }
}

export type RecorderAuthFailureCategory =
  | "none"
  | "missing_token"
  | "invalid_token_shape"
  | "expired_token"
  | "missing_session_id"
  | "invalid_api_url"
  | "session_mismatch"
  | "storage_write_failed"
  | "storage_read_failed"
  | "storage_readback_mismatch"

export type RecorderAuthPayloadValidation =
  | {
      ok: true
      value: { authToken: string; apiUrl: string; sessionId: string }
      tokenMetadata: RecorderTokenMetadata
    }
  | {
      ok: false
      failureCategory: RecorderAuthFailureCategory
      tokenMetadata: RecorderTokenMetadata
    }

/** Validate the privileged page-to-background payload without logging secrets. */
export function validateRecorderAuthPayload(
  input: { authToken?: unknown; apiUrl?: unknown; sessionId?: unknown },
  nowMs = Date.now(),
): RecorderAuthPayloadValidation {
  const authToken = typeof input.authToken === "string" ? input.authToken.trim() : ""
  const tokenMetadata = recorderTokenMetadata(authToken, nowMs)
  if (!tokenMetadata.tokenPresent) {
    return { ok: false, failureCategory: "missing_token", tokenMetadata }
  }
  if (tokenMetadata.jwtSegmentCount !== 3 || !tokenMetadata.startsWithEy) {
    return { ok: false, failureCategory: "invalid_token_shape", tokenMetadata }
  }
  if (tokenMetadata.expired) {
    return { ok: false, failureCategory: "expired_token", tokenMetadata }
  }

  const sessionId = typeof input.sessionId === "string" ? input.sessionId.trim() : ""
  if (!sessionId) {
    return { ok: false, failureCategory: "missing_session_id", tokenMetadata }
  }

  const rawApiUrl = typeof input.apiUrl === "string" ? input.apiUrl.trim() : ""
  try {
    const parsed = new URL(rawApiUrl)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("protocol")
  } catch {
    return { ok: false, failureCategory: "invalid_api_url", tokenMetadata }
  }

  return {
    ok: true,
    value: { authToken, apiUrl: normalizeApiUrl(rawApiUrl, rawApiUrl), sessionId },
    tokenMetadata,
  }
}

export interface RecorderAuthStorageArea {
  set(items: Record<string, unknown>): Promise<void>
  get(keys: string | string[]): Promise<Record<string, unknown>>
}

export interface RecorderAuthPersistenceResult {
  ok: boolean
  persistenceAttempted: boolean
  persistenceSucceeded: boolean
  readBackSucceeded: boolean
  storedSessionMatches: boolean
  failureCategory: RecorderAuthFailureCategory
}

/** Persist auth and prove the exact session/token record is readable before ACK. */
export async function persistRecorderAuthAndVerify(
  storage: RecorderAuthStorageArea,
  value: { authToken: string; apiUrl: string; sessionId: string },
  updatedAt = new Date().toISOString(),
): Promise<RecorderAuthPersistenceResult> {
  const record: PersistedRecorderAuth = { ...value, updatedAt }
  try {
    await storage.set({
      [RECORDER_AUTH_STORAGE_KEY]: record,
      authToken: value.authToken,
      apiUrl: value.apiUrl,
    })
  } catch {
    return {
      ok: false,
      persistenceAttempted: true,
      persistenceSucceeded: false,
      readBackSucceeded: false,
      storedSessionMatches: false,
      failureCategory: "storage_write_failed",
    }
  }

  let stored: Record<string, unknown>
  try {
    stored = await storage.get([RECORDER_AUTH_STORAGE_KEY])
  } catch {
    return {
      ok: false,
      persistenceAttempted: true,
      persistenceSucceeded: true,
      readBackSucceeded: false,
      storedSessionMatches: false,
      failureCategory: "storage_read_failed",
    }
  }

  const readRecord = stored[RECORDER_AUTH_STORAGE_KEY] as Partial<PersistedRecorderAuth> | undefined
  const storedSessionMatches = readRecord?.sessionId === value.sessionId
  const tokenMatches =
    typeof readRecord?.authToken === "string" &&
    readRecord.authToken.length === value.authToken.length &&
    readRecord.authToken === value.authToken
  const apiMatches = readRecord?.apiUrl === value.apiUrl
  const updatedAtExists = typeof readRecord?.updatedAt === "string" && !!readRecord.updatedAt
  const ok = storedSessionMatches && tokenMatches && apiMatches && updatedAtExists
  return {
    ok,
    persistenceAttempted: true,
    persistenceSucceeded: true,
    readBackSucceeded: true,
    storedSessionMatches,
    failureCategory: ok ? "none" : "storage_readback_mismatch",
  }
}

/** Trusted app pages that are allowed to hand auth to the extension. */
export function isTrustedVeriBridgeAppUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl)
    const hostname = url.hostname.toLowerCase()
    if (hostname === "veribridge.ai" || hostname.endsWith(".veribridge.ai")) return true
    if (hostname === "veribridgeai.com" || hostname.endsWith(".veribridgeai.com")) return true
    if (hostname !== "localhost" && hostname !== "127.0.0.1") return false
    return ["/student", "/dashboard", "/passport", "/admin", "/vbr"].some(
      (prefix) => url.pathname.startsWith(prefix),
    )
  } catch {
    return false
  }
}

export function normalizeApiUrl(url: string | null | undefined, fallback: string): string {
  const candidate = typeof url === "string" && url.trim() ? url.trim() : fallback
  return candidate.replace(/\/$/, "")
}

/**
 * Decide whether a START_RECORDING request may proceed.
 * An explicit token (popup manual field) wins; otherwise fall back to the
 * app-handed token already in state/storage. With neither, recording must NOT
 * start — failing later on upload wastes an entire recording session.
 */
export function resolveStartRecordingAuth(
  explicitToken: string | null | undefined,
  storedToken: string | null | undefined,
): { ok: true; authToken: string } | { ok: false; error: string } {
  const token = (explicitToken ?? "").trim() || (storedToken ?? "").trim()
  if (!token) return { ok: false, error: MISSING_RECORDER_AUTH_MESSAGE }
  return { ok: true, authToken: token }
}

export interface RestoredRecorderAuth {
  authToken: string
  apiUrl: string
  sessionId: string
  source: RecorderAuthSource
}

/**
 * Rebuild recorder auth from a chrome.storage.local snapshot after an MV3
 * service-worker restart. Prefers the structured record, falls back to the
 * legacy top-level `authToken` / `apiUrl` keys (older builds + popup manual
 * field persist those).
 */
export function restoreRecorderAuth(
  stored: Record<string, unknown>,
  fallbackApiUrl: string,
): RestoredRecorderAuth {
  const record = stored[RECORDER_AUTH_STORAGE_KEY] as Partial<PersistedRecorderAuth> | undefined
  if (record && typeof record.authToken === "string" && record.authToken) {
    return {
      authToken: record.authToken,
      apiUrl: normalizeApiUrl(typeof record.apiUrl === "string" ? record.apiUrl : undefined, fallbackApiUrl),
      sessionId: typeof record.sessionId === "string" ? record.sessionId : "",
      source: "storage",
    }
  }
  const legacyToken = stored["authToken"]
  if (typeof legacyToken === "string" && legacyToken) {
    return {
      authToken: legacyToken,
      apiUrl: normalizeApiUrl(typeof stored["apiUrl"] === "string" ? (stored["apiUrl"] as string) : undefined, fallbackApiUrl),
      sessionId: "",
      source: "storage",
    }
  }
  return { authToken: "", apiUrl: fallbackApiUrl, sessionId: "", source: "none" }
}

/**
 * Headers for an authorized recorder JSON POST — or `null` when there is no
 * token, in which case the caller MUST skip the request entirely (fail closed,
 * never POST anonymously).
 */
export function authorizedJsonHeaders(
  authToken: string | null | undefined,
): Record<string, string> | null {
  if (!authToken) return null
  return { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` }
}

/** Headers for the multipart video POST (browser sets Content-Type) — null = don't send. */
export function authorizedUploadHeaders(
  authToken: string | null | undefined,
): Record<string, string> | null {
  if (!authToken) return null
  return { Authorization: `Bearer ${authToken}` }
}

export type RecorderUploadEndpoint =
  | "visible-evidence"
  | "visual-frames"
  | "video"
  | "upload"
  | "live-feedback"

export function uploadEndpointUrl(
  apiUrl: string,
  sessionId: string,
  endpoint: RecorderUploadEndpoint,
): string {
  const base = `${normalizeApiUrl(apiUrl, "http://localhost:8000")}/api/v1/student/extension-proof/sessions/${sessionId}`
  return endpoint === "upload" ? `${base}/upload` : endpoint === "live-feedback" ? `${base}/live-feedback` : `${base}/workflow/${endpoint}`
}

// ── Safe (token-free) handoff ACK + debug state ────────────────────────────────

/** postMessage type the content script sends back to the app after relaying auth. */
export const RECORDER_AUTH_ACK_MESSAGE_TYPE = "VERIBRIDGE_RECORDER_AUTH_ACK"
/** postMessage type the content script sends to ask the app to (re)publish auth. */
export const RECORDER_AUTH_REQUEST_MESSAGE_TYPE = "VERIBRIDGE_RECORDER_AUTH_REQUEST"

export interface RecorderAuthAck {
  ok: boolean
  hasAuthToken: boolean
  buildId: string
  extensionId: string
  sessionId: string
  ackAt: string
  persistenceAttempted: boolean
  persistenceSucceeded: boolean
  readBackSucceeded: boolean
  storedSessionMatches: boolean
  failureCategory: RecorderAuthFailureCategory
}

export function buildRecorderAuthAck(input: {
  ok: boolean
  hasAuthToken: boolean
  buildId: string
  extensionId?: string
  sessionId?: string | null
  persistenceAttempted?: boolean
  persistenceSucceeded?: boolean
  readBackSucceeded?: boolean
  storedSessionMatches?: boolean
  failureCategory?: RecorderAuthFailureCategory
  now?: Date
}): RecorderAuthAck {
  return {
    ok: input.ok,
    hasAuthToken: input.hasAuthToken,
    buildId: input.buildId,
    extensionId: input.extensionId ?? "",
    sessionId: input.sessionId ?? "",
    ackAt: (input.now ?? new Date()).toISOString(),
    persistenceAttempted: input.persistenceAttempted ?? false,
    persistenceSucceeded: input.persistenceSucceeded ?? false,
    readBackSucceeded: input.readBackSucceeded ?? false,
    storedSessionMatches: input.storedSessionMatches ?? false,
    failureCategory: input.failureCategory ?? "none",
  }
}

export interface RecorderAuthDebugState {
  sessionId: string
  hasAuthToken: boolean
  authTokenSource: RecorderAuthSource
  apiUrl: string
  buildId: string
  lastAuthHandoffAt: string | null
  isRecording: boolean
  pendingUploadEndpoints: RecorderUploadEndpoint[]
}

/**
 * Build the safe debug snapshot returned by GET_RECORDER_AUTH_DEBUG_STATE.
 * Intentionally has no field that could hold the token value.
 */
export function buildRecorderAuthDebugState(input: {
  sessionId: string
  hasAuthToken: boolean
  authTokenSource: RecorderAuthSource
  apiUrl: string
  buildId: string
  lastAuthHandoffAt: string | null
  isRecording: boolean
  visibleEvidenceCount: number
  visualFrameCount: number
  recordingStoppedPendingSend: boolean
}): RecorderAuthDebugState {
  const pending: RecorderUploadEndpoint[] = []
  if (input.visibleEvidenceCount > 0) pending.push("visible-evidence")
  if (input.visualFrameCount > 0) pending.push("visual-frames")
  if (input.recordingStoppedPendingSend) pending.push("upload")
  return {
    sessionId: input.sessionId,
    hasAuthToken: input.hasAuthToken,
    authTokenSource: input.authTokenSource,
    apiUrl: input.apiUrl,
    buildId: input.buildId,
    lastAuthHandoffAt: input.lastAuthHandoffAt,
    isRecording: input.isRecording,
    pendingUploadEndpoints: pending,
  }
}
