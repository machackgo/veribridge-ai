/**
 * Lightweight product events for recorder-extension discovery and install.
 *
 * VeriBridge has NO general-purpose client analytics provider — the only
 * existing event sinks are two purpose-built backend view beacons (public
 * passport / public report), each backed by its own table and endpoint. This
 * task must not introduce a third-party analytics vendor, and adding a new
 * backend table for UI funnel events is out of its scope, so these events use
 * the pattern the recorder already uses for its own observability: one
 * structured `console.info` line (visible in browser consoles and in support
 * sessions), plus a DOM CustomEvent so a real analytics layer can subscribe
 * later without touching any of these call sites.
 *
 * Payloads are deliberately non-identifying: an event name, the surface that
 * produced it, and coarse detection facts. No user id, email, session id,
 * project id, URL, or token is ever included.
 */

export type RecorderExtensionEventName =
  | "extension_install_clicked"
  | "extension_detected_after_install"
  | "extension_detection_retry"
  | "extension_listing_viewed"

/** Which UI surface produced the event. */
export type RecorderExtensionSurface = "dashboard" | "website_proof"

export const RECORDER_EXTENSION_EVENT_CHANNEL = "veribridge:recorder-extension-event"

export type RecorderExtensionEvent = {
  name: RecorderExtensionEventName
  surface: RecorderExtensionSurface
  /** Coarse, non-identifying context (gate reason, detected build, …). */
  detail?: Record<string, string | number | boolean | null>
}

/**
 * Emit one discovery/install event. Fire-and-forget and fully swallowed —
 * product measurement must never break, block, or delay an install flow.
 */
export function emitRecorderExtensionEvent(
  name: RecorderExtensionEventName,
  surface: RecorderExtensionSurface,
  detail?: RecorderExtensionEvent["detail"],
): void {
  const event: RecorderExtensionEvent = { name, surface, ...(detail ? { detail } : {}) }
  try {
    console.info("[RecorderExtension]", { ...event, timestamp: new Date().toISOString() })
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(
        new CustomEvent<RecorderExtensionEvent>(RECORDER_EXTENSION_EVENT_CHANNEL, { detail: event }),
      )
    }
  } catch {
    // Never surface telemetry failures to the student.
  }
}

/**
 * Convenience name for a surface-suffixed install click, matching the agreed
 * event vocabulary (`extension_install_clicked_dashboard`, …). Emitted as the
 * base name plus a `surface` field so the funnel can be sliced either way.
 */
export function emitInstallClicked(
  surface: RecorderExtensionSurface,
  detail?: RecorderExtensionEvent["detail"],
): void {
  emitRecorderExtensionEvent("extension_install_clicked", surface, detail)
}
