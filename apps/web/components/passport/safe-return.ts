/**
 * Safe internal "return to" path validation for proof-studio flows.
 *
 * A Project Defense student can be sent to the Document Proof or Website Proof
 * page with a `returnTo` query param so we can bring them back after they add a
 * new proof. We must never honor an attacker-controlled open redirect: only
 * same-origin internal paths under `/student/` are allowed. External URLs,
 * protocol-relative `//host` paths, and anything with a scheme are rejected.
 */
export function safeReturnTo(value: string | null | undefined): string | null {
  if (!value) return null
  const path = value.trim()
  // Protocol-relative (`//evil.com`) and scheme URLs (`https://…`, `javascript:`)
  // are external — never redirect to them.
  if (path.startsWith("//")) return null
  if (path.includes("://") || path.includes("\\")) return null
  // Only allow internal student proof-studio paths.
  if (!path.startsWith("/student/")) return null
  return path
}

/** Read a validated internal returnTo from the current URL, browser-side only. */
export function readReturnToFromLocation(): string | null {
  if (typeof window === "undefined") return null
  try {
    const params = new URLSearchParams(window.location.search)
    return safeReturnTo(params.get("returnTo"))
  } catch {
    return null
  }
}
