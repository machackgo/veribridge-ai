/**
 * Strict parser for recruiter-pasted / QR-scanned Verified Build Report input.
 *
 * Accepts exactly two shapes:
 *   1. a raw public report token (URL-safe base64, as minted by the backend)
 *   2. a VeriBridge public report URL on a trusted app origin —
 *      `/vbr/report/{token}` (canonical) or `/r/{token}` (legacy)
 *
 * The parser NEVER returns a destination taken from the input: on success it
 * returns only the extracted token plus an internally constructed same-app
 * path, so open redirects are structurally impossible. Everything else —
 * foreign origins, `javascript:`/`data:` schemes, protocol-relative URLs,
 * malformed percent-encoding, oversized input — is rejected with a typed
 * reason the UI can explain.
 */

import { publicAppUrl } from "@/lib/app-url"

/** Matches backend minting (`secrets.token_urlsafe(24)` → 32 chars) with loose bounds. */
const TOKEN_RE = /^[A-Za-z0-9_-]{16,64}$/

/** Hard cap well above any legitimate report URL; blocks pathological input. */
const MAX_INPUT_LENGTH = 2048

const CANONICAL_PATH_PREFIX = "/vbr/report/"
const LEGACY_PATH_PREFIX = "/r/"

export type ReportLinkRejection =
  | "empty"
  | "too_long"
  | "unsupported_scheme"
  | "foreign_origin"
  | "not_a_report_link"
  | "invalid_token"

export type ReportLinkParse =
  | { ok: true; token: string; path: string; kind: "token" | "url"; legacy: boolean }
  | { ok: false; reason: ReportLinkRejection }

/** Human guidance for each rejection, shared by paste UI and scanner. */
export const REPORT_LINK_REJECTION_MESSAGES: Record<ReportLinkRejection, string> = {
  empty: "Paste a report link or token first.",
  too_long: "That input is too long to be a report link.",
  unsupported_scheme:
    "Only https VeriBridge report links are accepted — this input uses an unsupported address type.",
  foreign_origin:
    "That link does not point to this VeriBridge app, so it was not opened. Paste the report token itself if you have one.",
  not_a_report_link:
    "That looks like a VeriBridge address, but not a Verified Build Report link.",
  invalid_token: "That is not a valid report link or token.",
}

/** Origins a pasted/scanned report URL may use (normalized, lowercase, no trailing slash). */
export function trustedReportOrigins(): string[] {
  const origins = new Set<string>()
  const configured = publicAppUrl()
  if (configured) origins.add(normalizeOrigin(configured))
  if (typeof window !== "undefined" && window.location?.origin) {
    origins.add(normalizeOrigin(window.location.origin))
  }
  return [...origins].filter(Boolean)
}

function normalizeOrigin(value: string): string {
  return value.trim().toLowerCase().replace(/\/+$/, "")
}

function tokenFromPath(pathname: string): { token: string; legacy: boolean } | null {
  // Reject any extra path segments; only the exact report routes count.
  for (const [prefix, legacy] of [
    [CANONICAL_PATH_PREFIX, false],
    [LEGACY_PATH_PREFIX, true],
  ] as const) {
    if (!pathname.startsWith(prefix)) continue
    const segment = pathname.slice(prefix.length)
    if (!segment || segment.includes("/")) return null
    let decoded: string
    try {
      decoded = decodeURIComponent(segment)
    } catch {
      // Malformed percent-encoding can't hide a valid token.
      return null
    }
    return { token: decoded, legacy }
  }
  return null
}

export function parseReportLink(rawInput: string): ReportLinkParse {
  const input = (rawInput ?? "").trim()
  if (!input) return { ok: false, reason: "empty" }
  if (input.length > MAX_INPUT_LENGTH) return { ok: false, reason: "too_long" }

  // Raw token paste — the recruiter-friendly cross-environment path.
  if (TOKEN_RE.test(input)) {
    return {
      ok: true,
      token: input,
      path: `${CANONICAL_PATH_PREFIX}${input}`,
      kind: "token",
      legacy: false,
    }
  }

  // Protocol-relative URLs inherit whatever scheme the page has — never trust them.
  if (input.startsWith("//")) return { ok: false, reason: "unsupported_scheme" }

  // URL paste. Tolerate a missing scheme ("veribridgeai.com/vbr/report/x") by
  // retrying with https:// — the origin allow-list below still has to pass.
  let url: URL | null = null
  try {
    url = new URL(input)
  } catch {
    if (input.includes("/") && !input.includes(":")) {
      try {
        url = new URL(`https://${input}`)
      } catch {
        url = null
      }
    }
  }
  if (!url) return { ok: false, reason: "invalid_token" }

  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { ok: false, reason: "unsupported_scheme" }
  }

  if (!trustedReportOrigins().includes(normalizeOrigin(url.origin))) {
    return { ok: false, reason: "foreign_origin" }
  }

  const fromPath = tokenFromPath(url.pathname)
  if (!fromPath) return { ok: false, reason: "not_a_report_link" }
  if (!TOKEN_RE.test(fromPath.token)) return { ok: false, reason: "invalid_token" }

  // Destination is rebuilt from the validated token alone — query/hash and the
  // pasted host are deliberately discarded.
  const path = fromPath.legacy
    ? `${LEGACY_PATH_PREFIX}${fromPath.token}`
    : `${CANONICAL_PATH_PREFIX}${fromPath.token}`
  return { ok: true, token: fromPath.token, path, kind: "url", legacy: fromPath.legacy }
}
