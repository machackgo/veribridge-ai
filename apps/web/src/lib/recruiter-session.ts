/**
 * Recruiter session token management.
 *
 * Flow:
 *   1. Call createRecruiterSession(email) — POST /public/recruiter/sessions
 *   2. Token is stored in sessionStorage (cleared when the browser tab closes).
 *   3. Add X-Recruiter-Token header to all private recruiter API calls via
 *      withRecruiterTokenHeader().
 *   4. On 401, call clearRecruiterSession() and prompt the user to re-enter
 *      their email.
 *
 * Security invariants:
 *   - Token is stored in sessionStorage (NOT localStorage).
 *   - Token is NEVER logged.
 *   - Token is NEVER placed in URL query params.
 *   - Email is kept only for display/context — identity comes from the token.
 */

"use client"

// Prefer NEXT_PUBLIC_API_URL (production domain, e.g. https://api.veribridgeai.com);
// fall back to the legacy NEXT_PUBLIC_API_BASE_URL, then to local dev.
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000"

/** sessionStorage keys — only this module reads/writes them. */
const TOKEN_KEY = "vb_recruiter_token"
const EMAIL_KEY = "vb_recruiter_email"

// ─── Session creation ──────────────────────────────────────────────────────

/**
 * Create (or refresh) a recruiter session via the backend.
 *
 * Calls POST /api/v1/public/recruiter/sessions and stores the returned
 * session_token in sessionStorage.  Returns the plaintext token.
 *
 * Throws a user-facing Error if the backend rejects the request.
 */
export async function createRecruiterSession(email: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/public/recruiter/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requester_email: email }),
  })

  if (!res.ok) {
    const raw = await res.text().catch(() => "")
    let msg = `Failed to create recruiter session (HTTP ${res.status}).`
    try {
      const parsed = JSON.parse(raw) as { detail?: { message?: string } | string }
      const d = parsed.detail
      if (d && typeof d === "object" && typeof d.message === "string") {
        msg = d.message
      } else if (typeof d === "string") {
        msg = d
      }
    } catch { /* not JSON — keep generic message */ }
    throw new Error(msg)
  }

  const data = (await res.json()) as { session_token: string; requester_email: string }

  // Store the token safely — sessionStorage is scoped to the tab session.
  try {
    sessionStorage.setItem(TOKEN_KEY, data.session_token)
    sessionStorage.setItem(EMAIL_KEY, data.requester_email)
  } catch {
    /* sessionStorage may be unavailable in some contexts — degrade gracefully */
  }

  // Return token (used internally; must NOT be shown in the UI or logs).
  return data.session_token
}

// ─── Session accessors ─────────────────────────────────────────────────────

/** Returns the stored token, or null if no session exists. */
export function getStoredRecruiterToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

/**
 * Returns the recruiter email from the current session (display/context only).
 * Identity is always established via the token, not this value.
 */
export function getStoredRecruiterEmail(): string | null {
  try {
    return sessionStorage.getItem(EMAIL_KEY)
  } catch {
    return null
  }
}

/**
 * Clear the recruiter session.
 * Call this when a 401 is received or when the user explicitly signs out.
 */
export function clearRecruiterSession(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(EMAIL_KEY)
  } catch { /* ignore */ }
}

// ─── Header helper ─────────────────────────────────────────────────────────

/**
 * Return a copy of the provided headers object with X-Recruiter-Token injected.
 * If no token is currently stored the header is omitted (the backend will 401).
 *
 * The token value is NEVER logged or exposed to the UI.
 */
export function withRecruiterTokenHeader(
  headers: Record<string, string> = {},
): Record<string, string> {
  const token = getStoredRecruiterToken()
  if (!token) return { ...headers }
  return { ...headers, "X-Recruiter-Token": token }
}
