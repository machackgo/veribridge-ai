/**
 * Website Proof recorder protocol shared by the authenticated web app and the
 * Chrome extension. This is the only session configuration shape allowed at
 * the page/content-script/background boundary.
 *
 * The full config is extension-private because it contains a short-lived auth
 * credential. ACKs, diagnostics, URLs, and browser messages outside the
 * trusted VeriBridge app origin must use the safe fields only.
 */

export const WEBSITE_PROOF_RECORDER_SCHEMA_VERSION = 1 as const
export const WEBSITE_PROOF_RECORDER_BUILD_VERSION = "1.0.1" as const

/**
 * Oldest extension build the web app accepts. Store-distributed extensions
 * auto-update on Chrome's schedule, so the page compares builds as
 * "at least this version" — never as an exact match, which would break every
 * user mid-rollout. Pre-1.0 dev builds compare exact-match on their side and
 * therefore NACK themselves against this value, which routes them to the
 * update-required screen.
 */
export const WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION = "1.0.0" as const

/**
 * Parse a "major.minor.patch" build version. Extra label suffixes (e.g.
 * "1.0.0 (recorder schema 1)") are rejected — manifest versions never carry
 * them. Returns null for anything non-conforming.
 */
export function parseRecorderBuildVersion(value: unknown): [number, number, number] | null {
  if (typeof value !== "string") return null
  const match = /^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$/.exec(value.trim())
  if (!match) return null
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

/** True when `actual` is a valid build version >= `minimum`. Fails closed. */
export function isRecorderBuildAtLeast(actual: unknown, minimum: string): boolean {
  const a = parseRecorderBuildVersion(actual)
  const m = parseRecorderBuildVersion(minimum)
  if (!a || !m) return false
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== m[i]) return a[i] > m[i]
  }
  return true
}

export const RECORDER_BRIDGE_PING = "VERIBRIDGE_RECORDER_BRIDGE_PING" as const
export const RECORDER_BRIDGE_PONG = "VERIBRIDGE_RECORDER_BRIDGE_PONG" as const
export const RECORDER_INIT_REQUEST = "VERIBRIDGE_RECORDER_INIT_REQUEST" as const
export const RECORDER_INIT_ACK = "VERIBRIDGE_RECORDER_INIT_ACK" as const
export const RECORDER_INIT_NACK = "VERIBRIDGE_RECORDER_INIT_NACK" as const
export const RECORDER_AUTH_REFRESH_REQUEST = "VERIBRIDGE_RECORDER_AUTH_REFRESH_REQUEST" as const
export const RECORDER_AUTH_REFRESH_ACK = "VERIBRIDGE_RECORDER_AUTH_REFRESH_ACK" as const
export const RECORDER_TARGET_OPEN_REQUEST = "VERIBRIDGE_RECORDER_TARGET_OPEN_REQUEST" as const
export const RECORDER_TARGET_OPEN_ACK = "VERIBRIDGE_RECORDER_TARGET_OPEN_ACK" as const
export const RECORDER_TARGET_READY = "VERIBRIDGE_RECORDER_TARGET_READY" as const
export const RECORDER_START_REQUEST = "VERIBRIDGE_RECORDER_START_REQUEST" as const
export const RECORDER_START_ACK = "VERIBRIDGE_RECORDER_START_ACK" as const

export type RecorderAuthAccess = {
  mechanism: "bearer"
  access_token: string
  expires_at: string | null
}

export type WebsiteProofRecorderConfig = {
  schema_version: typeof WEBSITE_PROOF_RECORDER_SCHEMA_VERSION
  config_revision: number
  session_id: string
  owner_user_id: string
  api_base_url: string
  auth: RecorderAuthAccess
  project_id: string | null
  website_url: string
  repository_url: string | null
  claimed_skills: string[]
  proof_objective: string
  created_at: string
  expires_at: string | null
}

export type RecorderProtocolErrorCode =
  | "extension_not_detected"
  | "extension_version_incompatible"
  | "extension_worker_unreachable"
  | "initialization_timeout"
  | "invalid_config"
  | "invalid_api_base"
  | "authentication_unavailable"
  | "session_mismatch"
  | "revision_mismatch"
  | "stale_config"
  | "different_session_active"
  | "storage_write_failed"
  | "target_open_failed"
  | "target_ready_timeout"
  | "target_session_mismatch"
  | "target_url_mismatch"
  | "recording_not_ready"
  | "recording_start_failed"
  | "replay_not_retained"
  | "extension_context_invalidated"
  | "unknown_error"

export type RecorderBridgePing = {
  request_id: string
}

/**
 * Answered synchronously by the content-script bridge WITHOUT involving the
 * background service worker. Lets the page distinguish "no content script at
 * all" from "bridge present but the worker is unreachable" and detect a stale
 * extension build before any timeout elapses.
 */
export type RecorderBridgePong = {
  request_id: string
  schema_version: number
  build_version: string
  /** False when the extension was reloaded and this content script is orphaned. */
  context_valid: boolean
  /** True when the current page qualifies as a trusted VeriBridge app origin. */
  bridge_trusted: boolean
}

/**
 * Every window-message type the CURRENT extension build may post with
 * source "veribridge-extension". The page uses this to classify any other
 * extension-sourced message type as a stale/incompatible build instead of
 * silently waiting for a timeout that can never succeed.
 */
export const RECORDER_KNOWN_EXTENSION_MESSAGE_TYPES: ReadonlySet<string> = new Set([
  RECORDER_BRIDGE_PONG,
  RECORDER_INIT_ACK,
  RECORDER_INIT_NACK,
  RECORDER_AUTH_REFRESH_ACK,
  RECORDER_TARGET_OPEN_ACK,
  RECORDER_TARGET_READY,
  RECORDER_START_ACK,
  "VERIBRIDGE_EXTENSION_STATE",
  "VERIBRIDGE_PROOF_UPLOAD_STARTED",
])

export type RecorderInitRequest = {
  request_id: string
  expected_schema_version: typeof WEBSITE_PROOF_RECORDER_SCHEMA_VERSION
  /** MINIMUM build the page accepts — the extension passes when its own
   *  manifest version is >= this value (same schema). */
  expected_build_version: string
  config: WebsiteProofRecorderConfig
}

export type RecorderInitAck = {
  request_id: string
  session_id: string
  config_revision: number
  api_base_url: string
  schema_version: number
  build_version: string
  extension_id: string
  ready: true
}

export type RecorderProtocolNack = {
  request_id: string
  session_id: string | null
  config_revision: number | null
  schema_version: number
  build_version: string
  extension_id: string
  ready: false
  error_code: RecorderProtocolErrorCode
  message: string
}

export type RecorderTargetOpenRequest = {
  request_id: string
  session_id: string
  config_revision: number
}

export type RecorderTargetReadyAck = {
  request_id: string
  session_id: string
  config_revision: number
  api_base_url: string
  claimed_skills: string[]
  target_tab_id: number
  target_url: string
  ready: true
}

export type RecorderStartRequest = {
  request_id: string
  session_id: string
  config_revision: number
}

export type RecorderStartAck = RecorderStartRequest & {
  started_at: string
  idempotent: boolean
  ready: true
}

export type RecorderConfigSelection = {
  accepted: boolean
  config: WebsiteProofRecorderConfig | null
  idempotent: boolean
  error_code?: Extract<
    RecorderProtocolErrorCode,
    "invalid_config" | "stale_config" | "revision_mismatch" | "different_session_active"
  >
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"])

/**
 * Canonical production domain. Matches the apex host exactly and any true
 * subdomain (`www.`, `api.`, …) via a dot-boundary suffix so lookalike hosts
 * like `evilveribridgeai.com` or the stale `veribridge.ai` never qualify.
 */
const PRODUCTION_APP_DOMAIN = "veribridgeai.com"

export function isProductionVeriBridgeHostname(hostname: string): boolean {
  return (
    hostname === PRODUCTION_APP_DOMAIN ||
    hostname.endsWith(`.${PRODUCTION_APP_DOMAIN}`)
  )
}

const TRUSTED_APP_PATH_PREFIXES = [
  "/student",
  "/dashboard",
  "/passport",
  "/admin",
  "/vbr",
] as const

/**
 * True when a page location is an authenticated/internal VeriBridge APP
 * surface (student dashboard, passport, admin, report studio). The recorder
 * must never capture DOM evidence or screenshots from these pages, because
 * they can expose session metadata, private reports, and account state.
 *
 * This is deliberately PATH-scoped on the production domain: public
 * veribridgeai.com pages (landing, /privacy, marketing) are ordinary
 * recordable web pages when the student explicitly targets them, while the
 * app routes below stay excluded. On localhost the same app paths are
 * excluded so local development mirrors production behavior.
 */
export function isVeriBridgeInternalAppLocation(
  location: { hostname: string; pathname: string },
): boolean {
  const onVeriBridgeHost =
    isProductionVeriBridgeHostname(location.hostname) ||
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1"
  if (!onVeriBridgeHost) return false
  return TRUSTED_APP_PATH_PREFIXES.some(prefix => location.pathname.startsWith(prefix))
}

/**
 * True when a page location belongs to the trusted VeriBridge app surface that
 * may exchange recorder messages (including the auth handoff) with the
 * extension. Shared by the page and the content script so both sides agree.
 *
 * `allowLocalDev` extends trust to localhost app routes. Store-distributed
 * (production-channel) extension builds pass false so a page served from an
 * arbitrary local port can never reach the recorder bridge; dev builds and the
 * web app keep the default.
 *
 * IMPORTANT: single-page navigations change the pathname without re-running
 * the content script, so callers MUST evaluate this per message — never cache
 * the result from script-load time.
 */
export function isTrustedVeriBridgeAppLocation(
  location: { hostname: string; pathname: string },
  allowLocalDev = true,
): boolean {
  if (isProductionVeriBridgeHostname(location.hostname)) return true
  if (allowLocalDev && (location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    return TRUSTED_APP_PATH_PREFIXES.some(prefix => location.pathname.startsWith(prefix))
  }
  return false
}

/**
 * Production API origins the recorder may upload to. The onrender.com host is
 * the live deployment today; any true veribridgeai.com subdomain covers the
 * planned api.veribridgeai.com custom domain without another release.
 */
const PRODUCTION_API_HOSTNAMES = new Set(["veribridge-api.onrender.com"])

/**
 * True when a normalized recorder API base may receive session evidence.
 * Production-channel extension builds pass allowLocalDev=false, pinning
 * uploads to the production API; dev builds also accept loopback bases.
 * The input must already be normalized via normalizeWebsiteProofApiBase.
 */
export function isAllowedRecorderApiBase(apiBase: string, allowLocalDev = true): boolean {
  const normalized = normalizeWebsiteProofApiBase(apiBase)
  if (!normalized) return false
  const { protocol, hostname } = new URL(normalized)
  if (protocol === "https:") {
    // Any other https origin is rejected in every channel — evidence must
    // never be uploadable to an arbitrary server.
    return PRODUCTION_API_HOSTNAMES.has(hostname) || isProductionVeriBridgeHostname(hostname)
  }
  // normalizeWebsiteProofApiBase only lets HTTP through for loopback hosts.
  return allowLocalDev
}
const SENSITIVE_URL_PARAMS = new Set([
  "token", "access_token", "id_token", "refresh_token", "api_key", "key",
  "secret", "password", "code", "auth", "authorization", "session", "jwt",
])

/**
 * Require one explicit absolute API origin. HTTP is accepted only for local
 * development; credentials, query strings, fragments, and path prefixes are
 * rejected so every endpoint is derived from the same base.
 */
export function normalizeWebsiteProofApiBase(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null
  try {
    const parsed = new URL(value.trim())
    const localHttp = parsed.protocol === "http:" && LOOPBACK_HOSTS.has(parsed.hostname)
    if (parsed.protocol !== "https:" && !localHttp) return null
    if (parsed.username || parsed.password || parsed.search || parsed.hash) return null
    if (parsed.pathname !== "/" && parsed.pathname !== "") return null
    return `${parsed.protocol}//${parsed.host}`
  } catch {
    return null
  }
}

export function normalizeWebsiteProofTargetUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null
  try {
    const parsed = new URL(value.trim())
    const localHttp = parsed.protocol === "http:" && LOOPBACK_HOSTS.has(parsed.hostname)
    if (parsed.protocol !== "https:" && !localHttp) return null
    if (parsed.username || parsed.password) return null
    let hasSensitiveParam = false
    parsed.searchParams.forEach((_, key) => {
      if (SENSITIVE_URL_PARAMS.has(key.toLowerCase())) hasSensitiveParam = true
    })
    if (hasSensitiveParam) return null
    return parsed.toString()
  } catch {
    return null
  }
}

function normalizedSkills(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(
    value
      .filter((skill): skill is string => typeof skill === "string")
      .map(skill => skill.trim())
      .filter(Boolean),
  )]
}

function validIso(value: unknown, nullable = false): string | null {
  if (nullable && (value === null || value === undefined || value === "")) return null
  if (typeof value !== "string" || !value.trim() || Number.isNaN(Date.parse(value))) return null
  return new Date(value).toISOString()
}

export function normalizeWebsiteProofRecorderConfig(
  value: unknown,
): WebsiteProofRecorderConfig | null {
  if (!value || typeof value !== "object") return null
  const input = value as Partial<WebsiteProofRecorderConfig>
  const apiBase = normalizeWebsiteProofApiBase(input.api_base_url)
  const websiteUrl = normalizeWebsiteProofTargetUrl(input.website_url)
  const repositoryUrl = input.repository_url == null || input.repository_url === ""
    ? null
    : normalizeWebsiteProofTargetUrl(input.repository_url)
  const createdAt = validIso(input.created_at)
  const expiresAt = validIso(input.expires_at, true)
  const auth = input.auth
  if (
    input.schema_version !== WEBSITE_PROOF_RECORDER_SCHEMA_VERSION ||
    !Number.isSafeInteger(input.config_revision) ||
    Number(input.config_revision) < 1 ||
    typeof input.session_id !== "string" || !input.session_id.trim() ||
    typeof input.owner_user_id !== "string" || !input.owner_user_id.trim() ||
    !apiBase || !websiteUrl || (input.repository_url && !repositoryUrl) ||
    !createdAt || (input.expires_at && !expiresAt) ||
    !auth || auth.mechanism !== "bearer" ||
    typeof auth.access_token !== "string" || !auth.access_token.trim() ||
    typeof input.proof_objective !== "string" || !input.proof_objective.trim()
  ) {
    return null
  }
  return {
    schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
    config_revision: Number(input.config_revision),
    session_id: input.session_id.trim(),
    owner_user_id: input.owner_user_id.trim(),
    api_base_url: apiBase,
    auth: {
      mechanism: "bearer",
      access_token: auth.access_token.trim(),
      expires_at: validIso(auth.expires_at, true),
    },
    project_id: typeof input.project_id === "string" && input.project_id.trim()
      ? input.project_id.trim()
      : null,
    website_url: websiteUrl,
    repository_url: repositoryUrl,
    claimed_skills: normalizedSkills(input.claimed_skills),
    proof_objective: input.proof_objective.trim(),
    created_at: createdAt,
    expires_at: expiresAt,
  }
}

function configsEqual(left: WebsiteProofRecorderConfig, right: WebsiteProofRecorderConfig): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

/**
 * Durable revision ordering. Duplicate delivery of the exact same revision is
 * idempotent; lower revisions and same-revision/different-payload writes fail
 * closed. An active recording can never be redirected to another session.
 */
export function selectWebsiteProofRecorderConfig(
  current: WebsiteProofRecorderConfig | null,
  incoming: unknown,
  isRecording: boolean,
): RecorderConfigSelection {
  const next = normalizeWebsiteProofRecorderConfig(incoming)
  if (!next) return { accepted: false, config: current, idempotent: false, error_code: "invalid_config" }
  if (isRecording && current && current.session_id !== next.session_id) {
    return { accepted: false, config: current, idempotent: false, error_code: "different_session_active" }
  }
  if (!current || current.session_id !== next.session_id) {
    return { accepted: true, config: next, idempotent: false }
  }
  if (next.config_revision < current.config_revision) {
    return { accepted: false, config: current, idempotent: false, error_code: "stale_config" }
  }
  if (next.config_revision === current.config_revision) {
    if (configsEqual(current, next)) {
      return { accepted: true, config: current, idempotent: true }
    }
    return { accepted: false, config: current, idempotent: false, error_code: "revision_mismatch" }
  }
  return { accepted: true, config: next, idempotent: false }
}

/** Auth renewal is explicitly bound and cannot alter any non-auth field. */
export function refreshWebsiteProofRecorderAuth(
  current: WebsiteProofRecorderConfig | null,
  input: {
    session_id: unknown
    config_revision: unknown
    access_token: unknown
    expires_at?: unknown
  },
): WebsiteProofRecorderConfig | null {
  if (
    !current || input.session_id !== current.session_id ||
    input.config_revision !== current.config_revision ||
    typeof input.access_token !== "string" || !input.access_token.trim()
  ) return null
  return {
    ...current,
    auth: {
      mechanism: "bearer",
      access_token: input.access_token.trim(),
      expires_at: validIso(input.expires_at, true),
    },
  }
}

export function safeRecorderDiagnostic(config: WebsiteProofRecorderConfig): Record<string, unknown> {
  return {
    session_id: config.session_id,
    config_revision: config.config_revision,
    api_base_url: config.api_base_url,
    schema_version: config.schema_version,
  }
}
