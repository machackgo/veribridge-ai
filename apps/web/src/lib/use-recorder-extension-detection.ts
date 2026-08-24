"use client"

/**
 * Shared recorder-extension detection state for every install/discovery
 * surface (student dashboard card, Website Proof install gate, connection
 * recovery panel).
 *
 * Detection is REAL: it resolves only from `probeRecorderExtension()`, which
 * requires a correlated PONG from the extension's content-script bridge. A
 * student clicking through to the Chrome Web Store never moves this state —
 * "detected" always means the browser actually answered.
 *
 * Recovery model (no aggressive polling): probe once on mount, then re-probe
 * when the tab regains focus/visibility — which is exactly the moment a
 * student returns from the Web Store tab — plus on explicit "check again".
 * Automatic probes are throttled, and callers may opt into a slow interval
 * only while a blocking gate is on screen.
 */

import { useCallback, useEffect, useRef, useState } from "react"

import {
  probeRecorderExtension,
  type RecorderExtensionProbe,
} from "@/lib/website-proof-recorder"
import {
  emitRecorderExtensionEvent,
  type RecorderExtensionSurface,
} from "@/lib/recorder-extension-telemetry"

/**
 * Detection outcome, deliberately distinct from recorder RUNTIME failures.
 * Only `absent` and `outdated` are installation problems; `reload_needed`
 * means the extension is installed but its bridge was orphaned by an
 * update/reload, which a page refresh fixes.
 */
export type RecorderDetectionStatus =
  | "checking"
  | "detected"
  | "outdated"
  | "reload_needed"
  | "absent"

/** Minimum gap between AUTOMATIC probes (focus/visibility/interval). */
const AUTO_PROBE_THROTTLE_MS = 1_500

export function statusFromProbe(probe: RecorderExtensionProbe | null): RecorderDetectionStatus {
  if (!probe) return "checking"
  if (!probe.installed) return "absent"
  if (!probe.context_valid) return "reload_needed"
  if (probe.outdated) return "outdated"
  return probe.ready ? "detected" : "reload_needed"
}

export type RecorderExtensionDetection = {
  status: RecorderDetectionStatus
  probe: RecorderExtensionProbe | null
  /** True while a probe is in flight. */
  checking: boolean
  /** Manual "I've installed it — check again". Emits a retry event. */
  recheck: () => void
  /** Records that the student opened the store listing, arming the
   *  detected-after-install event for the next successful probe. */
  markInstallClicked: () => void
}

export function useRecorderExtensionDetection(options: {
  surface: RecorderExtensionSurface
  /** Slow background re-probe, for blocking gates only. Off by default. */
  pollIntervalMs?: number
  /**
   * Set false for browsers that cannot run the recorder at all — no probe, no
   * listeners, and `status` stays "checking" so no caller renders an
   * installed/not-installed verdict it has not earned.
   */
  enabled?: boolean
}): RecorderExtensionDetection {
  const { surface, pollIntervalMs, enabled = true } = options
  const [probe, setProbe] = useState<RecorderExtensionProbe | null>(null)
  const [probing, setProbing] = useState(true)
  const inFlight = useRef(false)
  const lastAutoProbeAtMs = useRef(0)
  const installClicked = useRef(false)
  const announcedDetection = useRef(false)

  // No setState before the first await: automatic re-probes are silent by
  // design (the UI must not flicker "Checking…" on every tab focus), and
  // keeping this asynchronous also avoids cascading renders from the mount
  // effect. The explicit `recheck` handler owns the visible checking state.
  const runProbe = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const result = await probeRecorderExtension()
      setProbe(result)
      // "Detected after install" fires once, and only when a real probe
      // succeeded after the student went to the store from this surface.
      if (result.ready && installClicked.current && !announcedDetection.current) {
        announcedDetection.current = true
        emitRecorderExtensionEvent("extension_detected_after_install", surface, {
          build_version: result.build_version,
        })
      }
    } catch {
      // Probe never rejects in practice; treat any throw as "unknown yet".
    } finally {
      inFlight.current = false
      setProbing(false)
    }
  }, [surface])

  const autoProbe = useCallback(() => {
    const now = Date.now()
    if (now - lastAutoProbeAtMs.current < AUTO_PROBE_THROTTLE_MS) return
    lastAutoProbeAtMs.current = now
    void runProbe()
  }, [runProbe])

  useEffect(() => {
    if (!enabled) return
    // The first probe is dispatched from a timer rather than the effect body:
    // it is a subscription kickoff to an external system (the extension
    // bridge), and running it synchronously here would cascade renders.
    const mountProbe = window.setTimeout(() => {
      lastAutoProbeAtMs.current = Date.now()
      void runProbe()
    }, 0)

    // Returning from the Chrome Web Store tab lands here. Installing the
    // extension injects the content script into already-open tabs, so this
    // usually detects without any page reload.
    const onVisibility = () => {
      if (document.visibilityState === "visible") autoProbe()
    }
    const onFocus = () => autoProbe()
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("focus", onFocus)

    let interval: number | undefined
    if (pollIntervalMs && pollIntervalMs > 0) {
      interval = window.setInterval(autoProbe, pollIntervalMs)
    }
    return () => {
      window.clearTimeout(mountProbe)
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("focus", onFocus)
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [runProbe, autoProbe, pollIntervalMs, enabled])

  const recheck = useCallback(() => {
    if (!enabled) return
    emitRecorderExtensionEvent("extension_detection_retry", surface)
    lastAutoProbeAtMs.current = Date.now()
    setProbing(true)
    void runProbe()
  }, [runProbe, surface, enabled])

  const markInstallClicked = useCallback(() => {
    installClicked.current = true
  }, [])

  // Derived, not stored: a disabled hook never probes, so it is never
  // "checking" — computing it avoids a setState inside the effect body.
  const checking = enabled && probing

  return { status: statusFromProbe(probe), probe, checking, recheck, markInstallClicked }
}
