/**
 * First-party landing-page event instrumentation.
 *
 * VeriBridge AI ships NO third-party analytics — the public privacy policy
 * states plainly that "we use no third-party advertising or analytics
 * trackers on our pages", so this module must never grow a vendor SDK. It
 * follows the same conventions as the existing report/passport view beacons
 * (see report-view-beacon.ts): fire-and-forget, every failure swallowed, and
 * nothing identifying in the payload.
 *
 * Delivery has two layers:
 *   1. A DOM CustomEvent (`veribridge:landing-analytics`) dispatched on
 *      `window` — always. Tests observe this, and it is the seam any future
 *      first-party collector plugs into without touching call sites.
 *   2. An optional `navigator.sendBeacon` POST to a FIRST-PARTY collector at
 *      NEXT_PUBLIC_LANDING_ANALYTICS_ENDPOINT. No endpoint configured (the
 *      current production state) ⇒ no network request is ever made.
 *
 * Every event is deduped per browser session, so a rerender, a replay, or a
 * scrub backwards over an already-crossed progress threshold cannot inflate
 * counts.
 */

export type LandingAnalyticsEvent =
  | "landing_launch_video_impression"
  | "landing_launch_video_play"
  | "landing_launch_video_25"
  | "landing_launch_video_50"
  | "landing_launch_video_75"
  | "landing_launch_video_complete"
  | "landing_launch_cta_click"
  | "career_fair_cta_click"

export const LANDING_ANALYTICS_DOM_EVENT = "veribridge:landing-analytics"

const DEDUPE_STORAGE_PREFIX = "vb-landing-evt:"

function safeSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null
    return window.sessionStorage
  } catch {
    return null // storage blocked (private mode / permissions) — degrade quietly
  }
}

/**
 * True the first time `event` is seen this browser session. When storage is
 * unavailable we fall back to an in-memory set so dedupe still holds for the
 * life of the page — a private-mode visitor must not emit 40 progress events
 * while dragging the scrubber.
 */
const seenInMemory = new Set<string>()

function claimOnce(event: LandingAnalyticsEvent): boolean {
  const storage = safeSessionStorage()
  if (!storage) {
    if (seenInMemory.has(event)) return false
    seenInMemory.add(event)
    return true
  }
  const key = `${DEDUPE_STORAGE_PREFIX}${event}`
  try {
    if (storage.getItem(key)) return false
    storage.setItem(key, "1")
    return true
  } catch {
    if (seenInMemory.has(event)) return false
    seenInMemory.add(event)
    return true
  }
}

/**
 * Record one landing-page event. Never throws, never awaited, never blocks
 * rendering or navigation. Returns true when the event was actually emitted
 * (i.e. it had not already fired this session).
 */
export function trackLandingEvent(
  event: LandingAnalyticsEvent,
  detail?: Record<string, string | number | boolean>,
): boolean {
  if (typeof window === "undefined") return false
  if (!claimOnce(event)) return false

  try {
    window.dispatchEvent(
      new CustomEvent(LANDING_ANALYTICS_DOM_EVENT, { detail: { event, ...detail } }),
    )
  } catch {
    // Observability must never break the page.
  }

  const endpoint = process.env.NEXT_PUBLIC_LANDING_ANALYTICS_ENDPOINT
  if (!endpoint) return true

  try {
    const body = JSON.stringify({ event, ...detail })
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      navigator.sendBeacon(endpoint, new Blob([body], { type: "application/json" }))
    } else {
      void fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        cache: "no-store",
        keepalive: true,
      }).catch(() => {})
    }
  } catch {
    // Analytics must never surface to the visitor.
  }
  return true
}

/** Test-only reset so specs can assert first-fire behaviour in isolation. */
export function __resetLandingAnalyticsForTests(): void {
  seenInMemory.clear()
  const storage = safeSessionStorage()
  if (!storage) return
  try {
    for (let i = storage.length - 1; i >= 0; i -= 1) {
      const key = storage.key(i)
      if (key?.startsWith(DEDUPE_STORAGE_PREFIX)) storage.removeItem(key)
    }
  } catch {
    // ignore
  }
}
