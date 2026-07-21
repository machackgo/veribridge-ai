/**
 * Fire-and-forget view beacon for the public Verified Build Report.
 *
 * Sends one privacy-conscious event per (report, browser session) to
 * `POST /api/v1/public/vbr/reports/{token}/view`. Strictly best-effort: every
 * failure path is swallowed, so analytics can never block, delay, or break
 * the recruiter's page load. Nothing identifying is sent — only the arrival
 * source ("direct" / "recruiter_open" / "recruiter_scan") and an opaque
 * random dedupe key so same-session rerenders and tab refreshes don't
 * inflate counts.
 */

import { PUBLIC_API_BASE } from "@/lib/api-base"

export type ReportOpenSource = "direct" | "recruiter_open" | "recruiter_scan"

const SOURCE_STORAGE_KEY = "vb-report-open-source"
const DEDUPE_STORAGE_PREFIX = "vb-report-view-key:"

function safeSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null
    return window.sessionStorage
  } catch {
    return null // storage blocked (private mode / permissions) — beacon degrades
  }
}

/**
 * Called by the recruiter open/scan page just before internal navigation so
 * the report page can attribute the arrival. The tag is single-use.
 */
export function markReportOpenSource(source: ReportOpenSource): void {
  safeSessionStorage()?.setItem(SOURCE_STORAGE_KEY, source)
}

function consumeReportOpenSource(): ReportOpenSource {
  const storage = safeSessionStorage()
  const value = storage?.getItem(SOURCE_STORAGE_KEY)
  if (storage && value) storage.removeItem(SOURCE_STORAGE_KEY)
  return value === "recruiter_open" || value === "recruiter_scan" ? value : "direct"
}

/** Stable per-(session, report) opaque key; never derived from user identity. */
function dedupeKeyFor(token: string): string | null {
  const storage = safeSessionStorage()
  if (!storage) return null
  const storageKey = `${DEDUPE_STORAGE_PREFIX}${token}`
  const existing = storage.getItem(storageKey)
  if (existing) return existing
  const generated =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
  storage.setItem(storageKey, generated)
  return generated
}

/**
 * Record one view for a successfully loaded public report. Never throws and
 * never blocks — callers may fire this without awaiting.
 */
export async function recordPublicReportView(token: string): Promise<void> {
  if (!token) return
  try {
    const body: Record<string, string> = { source: consumeReportOpenSource() }
    const dedupeKey = dedupeKeyFor(token)
    if (dedupeKey) body.dedupe_key = dedupeKey
    await fetch(
      `${PUBLIC_API_BASE}/api/v1/public/vbr/reports/${encodeURIComponent(token)}/view`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
        keepalive: true,
      },
    )
  } catch {
    // Analytics must never surface to the recruiter.
  }
}
