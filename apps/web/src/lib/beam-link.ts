/**
 * Beam Link resolution — the client side of the dynamic revocable short QR.
 *
 * A Beam Card QR encodes `{app}/b/{code}`. The `/b/[code]` route calls
 * {@link resolveBeamCode}, which asks the backend resolver — the ONLY authority
 * on where a scanned code goes — and either redirects to the returned public
 * Passport path or shows the safe inactive page.
 *
 * This module is intentionally NOT marked "use client": the `/b/[code]` route
 * is a server component, so resolution runs on the Next server (works for any
 * scanner, no JS required) and the redirect is a real HTTP redirect.
 *
 * Fail-closed rules:
 *  - a code that doesn't look like a minted code is `inactive` without a fetch;
 *  - only a literal `/p/{slug}` relative path from the backend is followed —
 *    anything else (absolute URL, private route, malformed) is treated as
 *    `inactive`, so a compromised payload can never become an open redirect;
 *  - backend 404/410 → `inactive` (revoked/expired/unknown are one state);
 *  - network / 5xx → `unavailable` (a transient blip must NOT tell a recruiter
 *    the link was killed).
 */

// Prefer NEXT_PUBLIC_API_URL (production domain, e.g. https://api.veribridgeai.com);
// fall back to the legacy NEXT_PUBLIC_API_BASE_URL, then to local dev.
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000"

/** Shape of a minted beam code: URL-safe base64, 12–64 chars, nothing else. */
export const BEAM_CODE_PATTERN = /^[A-Za-z0-9_-]{12,64}$/

/** The only redirect target the resolver result is allowed to name. */
const PUBLIC_PASSPORT_PATH_PATTERN = /^\/p\/[A-Za-z0-9_-]+$/

export type BeamResolution =
  | { kind: "active"; publicPassportPath: string }
  /** Unknown / revoked / expired / target unpublished — one indistinct state. */
  | { kind: "inactive" }
  /** Resolver unreachable or erroring — retryable, NOT a dead link. */
  | { kind: "unavailable" }

/** Resolve a scanned code against the backend resolver. Never throws. */
export async function resolveBeamCode(code: string): Promise<BeamResolution> {
  if (!BEAM_CODE_PATTERN.test(code)) return { kind: "inactive" }
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/beam/${encodeURIComponent(code)}`,
      { cache: "no-store" },
    )
    if (res.ok) {
      const data: unknown = await res.json()
      const record = (typeof data === "object" && data !== null ? data : {}) as Record<
        string,
        unknown
      >
      const path = typeof record.public_passport_path === "string" ? record.public_passport_path : ""
      if (record.status === "active" && PUBLIC_PASSPORT_PATH_PATTERN.test(path)) {
        return { kind: "active", publicPassportPath: path }
      }
      // A 200 that isn't a clean active `/p/{slug}` answer fails closed.
      return { kind: "inactive" }
    }
    if (res.status === 404 || res.status === 410) return { kind: "inactive" }
    return { kind: "unavailable" }
  } catch {
    return { kind: "unavailable" }
  }
}
