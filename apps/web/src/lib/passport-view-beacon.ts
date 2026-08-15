/**
 * Fire-and-forget view beacon for the public Work Passport.
 *
 * Sends one privacy-conscious event per (passport, browser session) to
 * `POST /api/v1/public/p/{slug}/view` (migration 065). Strictly best-effort:
 * every failure path is swallowed, so analytics can never block, delay, or
 * break the passport page load. Nothing identifying is sent — only the
 * arrival source ("qr_scan" / "shared_link" / "direct") and an opaque random
 * dedupe key so same-session rerenders and tab refreshes don't inflate
 * counts. Mirrors `report-view-beacon.ts`.
 */

import { PUBLIC_API_BASE } from "@/lib/api-base"

export type PassportViewSource = "direct" | "qr_scan" | "shared_link"

const DEDUPE_STORAGE_PREFIX = "vb-passport-view-key:"

function safeSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null
    return window.sessionStorage
  } catch {
    return null // storage blocked (private mode / permissions) — beacon degrades
  }
}

/** Stable per-(session, passport) opaque key; never derived from user identity. */
function dedupeKeyFor(slug: string): string | null {
  const storage = safeSessionStorage()
  if (!storage) return null
  const storageKey = `${DEDUPE_STORAGE_PREFIX}${slug}`
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
 * Record one view for a successfully loaded public passport. Never throws
 * and never blocks — callers may fire this without awaiting.
 */
export async function recordPublicPassportView(
  slug: string,
  source: PassportViewSource,
): Promise<void> {
  if (!slug) return
  try {
    const body: Record<string, string> = { source }
    const dedupeKey = dedupeKeyFor(slug)
    if (dedupeKey) body.dedupe_key = dedupeKey
    await fetch(`${PUBLIC_API_BASE}/api/v1/public/p/${encodeURIComponent(slug)}/view`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      keepalive: true,
    })
  } catch {
    // Analytics must never surface to the viewer.
  }
}
